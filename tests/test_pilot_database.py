#!/usr/bin/env python3
"""Database tests: DuckDB rebuilds from files, reconciles to Parquet, and
excludes commissioning runs from trend denominators."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import _synthetic_pcap as synth  # noqa: E402


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


import duckdb  # noqa: E402


class DatabaseTestBase(unittest.TestCase):
    """Shared setup: an enriched synthetic series and a built database."""

    @classmethod
    def setUpClass(cls):
        cls.contract = load_module(
            ROOT / "scripts" / "pilot_contract.py", "pilot_contract_db")
        cls.enrich = load_module(
            ROOT / "scripts" / "pilot_enrich.py", "pilot_enrich_db")
        cls.updater = load_module(
            ROOT / "scripts" / "pilot-update.py", "pilot_update_db")
        cls.database = load_module(
            ROOT / "scripts" / "pilot_database.py", "pilot_database_mod")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.pilot_root = self.base / "pilot"
        self.derived_root = self.base / "derived"
        # Two completed sweeps plus one skipped hour and one skipped
        # receiver: enough shape to exercise health and trends.
        synth.build_run_dir(self.pilot_root / "20260827-130002")
        synth.build_run_dir(self.pilot_root / "20260827-140002")
        skip = self.pilot_root / "20260827-150002"
        synth.build_run_dir(skip)
        instrument = skip / "instrument.json"
        doc = json.loads(instrument.read_text())
        doc["run_status"] = "skipped_no_interface"
        instrument.write_text(json.dumps(doc))
        for name in ("freq-2412.pcap", "freq-2437.pcap", "freq-5955.pcap"):
            (skip / name).unlink()
        for name in ("frequencies.tsv", "aggregate.tsv"):
            path = skip / name
            path.write_text(path.read_text().splitlines()[0] + "\n")
        # Commissioning runs are present but must stay outside every trend.
        for run_id in self.contract.COMMISSIONING_RUNS:
            (self.pilot_root / run_id).mkdir()
            (self.pilot_root / run_id / "frequencies.tsv").write_text(
                "band\tfrequency_mhz\tchannel\tregulatory_state\t"
                "sample_status\tdwell_seconds\tpcap_file\tbssid_count\t"
                "beacon_count\terror\n")
        self.now = self.contract.datetime(2026, 8, 27, 16, 30)
        self.updater.enrich_stage(self.pilot_root, self.derived_root)
        self.db = self.database.build_database(
            self.pilot_root, self.derived_root, now=self.now)

    def q(self, sql: str, params=None):
        con = duckdb.connect(str(self.db), read_only=True)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()


class ViewContractTests(DatabaseTestBase):

    def test_all_twelve_required_views_exist(self):
        present = {row[0] for row in self.q(
            "SELECT view_name FROM duckdb_views()")}
        for view in self.contract.VIEW_NAMES:
            self.assertIn(view, present)

    def test_views_have_documented_explicit_types(self):
        con = duckdb.connect(str(self.db), read_only=True)
        try:
            for view in self.contract.VIEW_NAMES[:7]:
                rows = con.execute(
                    "SELECT column_name, data_type FROM "
                    f"duckdb_columns() WHERE table_name = '{view}'"
                ).fetchall()
                self.assertTrue(rows, f"{view} has no columns")
                for _name, dtype in rows:
                    self.assertIn(dtype, (
                        "VARCHAR", "BIGINT", "DOUBLE", "BOOLEAN", "TIMESTAMP",
                    ), f"{view} column {_name} has type {dtype}")
        finally:
            con.close()


class ReconciliationTests(DatabaseTestBase):

    def test_base_views_reconcile_to_parquet_union(self):
        runs_root = self.contract.derived_runs_root(self.derived_root)
        for table in ("frequencies", "observations", "ie_capabilities",
                      "rnr", "bss_load"):
            expected = 0
            for run_dir in runs_root.iterdir():
                manifest = json.loads(
                    (run_dir / "manifest.json").read_text())
                if manifest["status"] not in ("succeeded", "partial"):
                    continue
                if table in ("ie_capabilities", "rnr", "bss_load") \
                        and manifest["status"] != "succeeded":
                    continue
                entry = next(o for o in manifest["outputs"]
                             if o["name"] == f"{table}.parquet")
                expected += entry["rows"]
            got = self.q(f"SELECT COUNT(*) FROM stg_{table}")[0][0]
            self.assertEqual(got, expected, f"{table} row reconciliation")

    def test_health_covers_attempts_and_missing_slots(self):
        rows = {r[0]: r for r in self.q(
            "SELECT run_id, state, in_trend FROM pilot_run_health")}
        # Two completed sweeps, one skipped receiver, one absent hour
        # (20260827-150002 is taken by the skip; 160000 is absent since
        # now is 16:30, so the 16:00 slot is expected and missing).
        self.assertEqual(rows["20260827-130002"][1], "completed_sweep")
        self.assertEqual(rows["20260827-150002"][1], "skipped_no_interface")
        self.assertEqual(rows["20260827-160000"][1], "missing_hourly_slot")
        self.assertFalse(rows["20260827-160000"][2])
        for run_id in self.contract.COMMISSIONING_RUNS:
            self.assertIn(run_id, rows)
            self.assertFalse(rows[run_id][2])

    def test_commissioning_runs_excluded_from_trend_denominators(self):
        trend_runs = {r[0] for r in self.q(
            "SELECT run_id FROM pilot_hourly_metrics")}
        for run_id in self.contract.COMMISSIONING_RUNS:
            self.assertNotIn(run_id, trend_runs)
        self.assertIn("20260827-130002", trend_runs)

    def test_fresh_scratch_rebuild_returns_identical_results(self):
        scratch_db = self.base / "scratch-rebuild" / "pilot.duckdb"
        scratch_db.parent.mkdir(parents=True)
        self.database.build_database(
            self.pilot_root, self.derived_root, target=scratch_db,
            now=self.now)
        for view in ("pilot_run_health", "pilot_hourly_metrics",
                     "pilot_band_metrics", "pilot_capability_metrics",
                     "pilot_6ghz_evidence"):
            ordered = (f"SELECT * FROM {view} ORDER BY ALL")
            persistent = self.q(ordered)
            con = duckdb.connect(str(scratch_db), read_only=True)
            try:
                fresh = con.execute(ordered).fetchall()
            finally:
                con.close()
            self.assertEqual(persistent, fresh, f"{view} differs on rebuild")

    def test_missing_manifest_is_a_reconciliation_error(self):
        # Simulate a silently absent derivation: drop a manifest for an
        # eligible, non-running attempt.
        shutil.rmtree(self.contract.derived_runs_root(self.derived_root)
                      / "20260827-140002")
        with self.assertRaises(self.database.ReconciliationError):
            self.database.build_database(
                self.pilot_root, self.derived_root, now=self.now)


class DegradedPathTests(DatabaseTestBase):
    """The projection remains queryable when no advanced artifact contributes."""

    def _mark_every_manifest_partial(self):
        runs_root = self.contract.derived_runs_root(self.derived_root)
        for run_dir in runs_root.iterdir():
            manifest_path = run_dir / self.contract.MANIFEST_NAME
            if not manifest_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "partial"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    @staticmethod
    def _query_path(path, sql):
        con = duckdb.connect(str(path), read_only=True)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_all_partial_manifests_keep_core_views_and_typed_empty_advanced(self):
        expected_health = self.q(
            "SELECT run_id, state, eligible, in_trend, reason, started_utc, "
            "input_complete FROM pilot_run_health ORDER BY ALL"
        )
        expected_hourly = self.q(
            "SELECT * FROM pilot_hourly_metrics ORDER BY ALL"
        )
        self._mark_every_manifest_partial()

        partial_db = self.base / "all-partial.duckdb"
        self.database.build_database(
            self.pilot_root,
            self.derived_root,
            target=partial_db,
            now=self.now,
        )

        present = {
            row[0]
            for row in self._query_path(
                partial_db, "SELECT view_name FROM duckdb_views()"
            )
        }
        self.assertEqual(present.intersection(self.contract.VIEW_NAMES),
                         set(self.contract.VIEW_NAMES))
        self.assertEqual(
            self._query_path(
                partial_db,
                "SELECT run_id, state, eligible, in_trend, reason, "
                "started_utc, input_complete FROM pilot_run_health "
                "ORDER BY ALL",
            ),
            expected_health,
        )
        self.assertEqual(
            self._query_path(
                partial_db, "SELECT * FROM pilot_hourly_metrics ORDER BY ALL"
            ),
            expected_hourly,
        )

        arrow_to_duckdb = {
            "string": "VARCHAR",
            "int64": "BIGINT",
            "double": "DOUBLE",
            "bool": "BOOLEAN",
        }
        for table_name in (
            "ie_capabilities", "rnr", "bss_load", "field_resolution"
        ):
            self.assertEqual(
                self._query_path(
                    partial_db, f"SELECT COUNT(*) FROM stg_{table_name}"
                ),
                [(0,)],
            )
            schema = self.database.pilot_enrich.table_schema(table_name)
            expected_columns = [
                (field.name, arrow_to_duckdb[str(field.type)])
                for field in schema
            ]
            actual_columns = self._query_path(
                partial_db,
                "SELECT column_name, data_type FROM duckdb_columns() "
                f"WHERE table_name = 'stg_{table_name}' ORDER BY column_index",
            )
            self.assertEqual(actual_columns, expected_columns)

    def test_empty_pilot_and_derived_trees_build_twelve_empty_views(self):
        empty_pilot = self.base / "empty-pilot"
        empty_pilot.mkdir()
        empty_derived = self.base / "empty-derived"
        empty_derived.mkdir()
        empty_db = self.base / "empty.duckdb"

        self.database.build_database(
            empty_pilot,
            empty_derived,
            target=empty_db,
            now=self.contract.datetime(2026, 8, 27, 8, 30),
        )

        for view_name in self.contract.VIEW_NAMES:
            self.assertEqual(
                self._query_path(empty_db, f"SELECT COUNT(*) FROM {view_name}"),
                [(0,)],
                view_name,
            )

    def test_missing_declared_type_fails_empty_path_loudly(self):
        self._mark_every_manifest_partial()
        type_columns = self.database.pilot_enrich._STRING_COLUMNS[
            "ie_capabilities"
        ]
        type_columns.remove("elements")
        try:
            with self.assertRaises(
                self.database.pilot_enrich.ExtractionError
            ):
                self.database.build_database(
                    self.pilot_root,
                    self.derived_root,
                    target=self.base / "missing-type.duckdb",
                    now=self.now,
                )
        finally:
            type_columns.add("elements")


class MutationCheckTests(DatabaseTestBase):

    def test_duplicated_parquet_observation_fails_reconciliation(self):
        # Duplicate one observation row in a scratch generation: the row
        # counts must stop matching the manifests instead of silently
        # accepting a plausible higher beacon/BSSID total.
        runs_root = self.contract.derived_runs_root(self.derived_root)
        run_dir = runs_root / "20260827-130002"
        import pyarrow.parquet as pq
        import pyarrow as pa
        table = pq.read_table(run_dir / "observations.parquet")
        doubled = pa.concat_tables([table, table.slice(0, 1)])
        pq.write_table(doubled, run_dir / "observations.parquet")
        with self.assertRaises(self.database.ReconciliationError):
            self.database.build_database(
                self.pilot_root, self.derived_root, now=self.now)

    def test_6ghz_evidence_distinguishes_observation_from_advertisement(self):
        # AP4 advertises a 6 GHz neighbor that no observation row contains:
        # the view must report it as nonconcurrent advertised-not-observed
        # while direct observations stay zero.
        rows = self.q(
            "SELECT direct_bssids, direct_beacons, sampled_empty_frequencies,"
            " advertised_6ghz_neighbors, advertised_6ghz_disabled_links,"
            " ambiguous_rnr_rows, advertised_not_observed_nonconcurrent"
            " FROM pilot_6ghz_evidence WHERE run_id = '20260827-130002'")
        self.assertEqual(len(rows), 1)
        (direct_bssids, direct_beacons, sampled_empty,
         advertised, disabled, ambiguous, not_observed) = rows[0]
        self.assertEqual(direct_bssids, 0)
        self.assertEqual(direct_beacons, 0)
        self.assertGreaterEqual(sampled_empty, 1)
        self.assertGreaterEqual(advertised, 2)   # AP2's + AP4's neighbors
        self.assertGreaterEqual(disabled, 1)
        self.assertGreaterEqual(ambiguous, 1)
        # Only enabled or unknown-state advertised neighbors count here;
        # the disabled link is reported separately, never as a miss.
        self.assertGreaterEqual(not_observed, 1)
        # The advertised neighbor spelling matches observation spelling.
        neighbors = {r[0] for r in self.q(
            "SELECT DISTINCT neighbor_bssid FROM pilot_rnr"
            " WHERE neighbor_bssid IS NOT NULL")}
        self.assertIn("00:00:00:60:70:80", neighbors)


if __name__ == "__main__":
    unittest.main()
