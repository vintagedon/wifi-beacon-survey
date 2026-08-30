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
