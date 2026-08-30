#!/usr/bin/env python3
"""Contract tests for pilot_contract.py: eligibility, states, slots, schemas.

The synthetic-series tests build throwaway pilot trees under a temp directory.
The live-inventory tests skip cleanly when the pilot tree is not mounted.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pilot_contract.py"
CONTRACT_DOC = ROOT / "docs" / "pilot-analysis-contract.md"
LIVE_PILOT = Path("/opt/agents/repos/storage-mounted/wifi-beacon-survey/pilot")


def load_module():
    spec = importlib.util.spec_from_file_location("pilot_contract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register before exec: dataclass field resolution looks the module up in
    # sys.modules while the module body is still executing.
    sys.modules["pilot_contract"] = module
    spec.loader.exec_module(module)
    return module


INSTRUMENT_HEADER = {
    "schema": "wifi-beacon-survey/instrument/1",
    "skip_reason": None,
    "interface_present": True,
}


def write_run(
    root: Path,
    run_id: str,
    run_status: str | None = "sweep",
    started_utc: str | None = "2026-08-27T13:00:03Z",
    with_tsvs: bool = True,
    instrument_raw: str | None = None,
) -> Path:
    """Write a synthetic run directory into root."""
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    if run_status is not None or instrument_raw is not None:
        doc = dict(INSTRUMENT_HEADER)
        doc["run_status"] = run_status
        doc["started_utc"] = started_utc
        (run_dir / "instrument.json").write_text(
            instrument_raw if instrument_raw is not None
            else json.dumps(doc),
            encoding="utf-8",
        )
    freq_header = (
        "band\tfrequency_mhz\tchannel\tregulatory_state\tsample_status\t"
        "dwell_seconds\tpcap_file\tbssid_count\tbeacon_count\terror\n"
    )
    agg_header = (
        "band\tfrequency_mhz\tchannel\tbssid\tssid\tbeacons\t"
        "beacon_interval_tu\trssi_min_dbm\trssi_mean_dbm\trssi_max_dbm\t"
        "first_seen\tlast_seen\tbeacon_reception_ratio\n"
    )
    if with_tsvs:
        (run_dir / "frequencies.tsv").write_text(freq_header, encoding="utf-8")
        (run_dir / "aggregate.tsv").write_text(agg_header, encoding="utf-8")
    return run_dir


class ModuleConstantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_frozen_series_boundary(self):
        self.assertEqual(self.m.PILOT_SERIES_START, "20260827-090003")
        self.assertEqual(
            self.m.COMMISSIONING_RUNS,
            ("20260827-054734", "20260827-060013"),
        )

    def test_derived_schema_identifier(self):
        self.assertEqual(self.m.DERIVED_SCHEMA_ID, "wifi-beacon-survey/pilot-derived/1")

    def test_view_names_are_the_twelve_required(self):
        self.assertEqual(len(self.m.VIEW_NAMES), 12)
        self.assertEqual(
            self.m.VIEW_NAMES[:7],
            (
                "pilot_runs", "pilot_frequencies", "pilot_observations",
                "pilot_ie_capabilities", "pilot_rnr", "pilot_bss_load",
                "pilot_field_resolution",
            ),
        )
        self.assertIn("pilot_6ghz_evidence", self.m.VIEW_NAMES)

    def test_report_sections_in_required_order(self):
        self.assertEqual(len(self.m.REPORT_SECTIONS), 10)
        self.assertEqual(self.m.REPORT_SECTIONS[0], "Scope and cutoff")
        self.assertEqual(self.m.REPORT_SECTIONS[-1], "Provenance")

    def test_shared_venv_duckdb_import(self):
        import duckdb  # noqa: F401  (declared dependency must resolve)


class ClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_commissioning_runs_classify_out_of_trend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for run_id in self.m.COMMISSIONING_RUNS:
                write_run(root, run_id, run_status=None, with_tsvs=True)
            inventory = self.m.inventory_pilot(root)
            self.assertEqual(len(inventory), 2)
            for cls_row in inventory:
                self.assertEqual(
                    cls_row.membership, self.m.Membership.COMMISSIONING
                )
                self.assertFalse(cls_row.eligible)
            health = self.m.build_run_health(inventory, [])
            for row in health:
                self.assertFalse(row.in_trend)

    def test_every_run_at_or_after_start_is_eligible_regardless_of_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, "20260827-090003", run_status="sweep")
            write_run(root, "20260827-100002", run_status="skipped_no_interface")
            write_run(root, "20260827-110002", run_status="failed")
            write_run(root, "20260827-120002", run_status="running")
            inventory = self.m.inventory_pilot(root)
            self.assertEqual(len(inventory), 4)
            for cls_row in inventory:
                self.assertEqual(cls_row.membership, self.m.Membership.PILOT)
                self.assertTrue(cls_row.eligible)
            states = {c.run_id: c.attempt_state for c in inventory}
            self.assertEqual(
                states["20260827-090003"], self.m.AttemptState.COMPLETED_SWEEP
            )
            self.assertEqual(
                states["20260827-100002"],
                self.m.AttemptState.SKIPPED_NO_INTERFACE,
            )
            self.assertEqual(states["20260827-110002"], self.m.AttemptState.FAILED)
            self.assertEqual(states["20260827-120002"], self.m.AttemptState.RUNNING)

    def test_malformed_variants_are_distinct_from_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, "20260827-090003", run_status=None)  # no instrument
            write_run(root, "20260827-100002", run_status="sweep", with_tsvs=False)
            write_run(
                root, "20260827-110002", instrument_raw="{not json",
            )
            write_run(root, "20260827-120002", run_status="mystery_status")
            inventory = self.m.inventory_pilot(root)
            for cls_row in inventory:
                self.assertEqual(cls_row.attempt_state, self.m.AttemptState.MALFORMED)
                self.assertTrue(cls_row.eligible)

    def test_outside_series_children_never_become_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "not-a-run").mkdir()
            (root / "notes.txt").write_text("stray file", encoding="utf-8")
            write_run(root, "20260827-080000", run_status="sweep")
            inventory = self.m.inventory_pilot(root)
            by_id = {c.run_id: c for c in inventory}
            self.assertEqual(len(inventory), 3)
            for run_id in ("not-a-run", "notes.txt", "20260827-080000"):
                self.assertEqual(
                    by_id[run_id].membership, self.m.Membership.OUTSIDE
                )
                self.assertFalse(by_id[run_id].eligible)
            # Health carries only eligible attempts and commissioning rows.
            health = self.m.build_run_health(inventory, [])
            self.assertEqual(health, [])

    def test_five_state_sequence_is_distinguishable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, "20260827-090003", run_status="sweep")
            write_run(root, "20260827-100002", run_status="skipped_no_interface")
            write_run(root, "20260827-110002", run_status="failed")
            write_run(root, "20260827-120002", instrument_raw="{broken")  # malformed
            # 20260827-130000 is absent: covered by slot reconciliation.
            slots = self.m.expected_slots(
                "20260827-090003",
                now=self.m.parse_run_hour("20260827-090003").replace(
                    hour=13
                ),
            )
            self.assertEqual(len(slots), 5)
            health = self.m.build_run_health(self.m.inventory_pilot(root), slots)
            by_id = {r.run_id: r.state for r in health}
            self.assertEqual(
                by_id["20260827-090003"], self.m.AttemptState.COMPLETED_SWEEP
            )
            self.assertEqual(
                by_id["20260827-100002"],
                self.m.AttemptState.SKIPPED_NO_INTERFACE,
            )
            self.assertEqual(by_id["20260827-110002"], self.m.AttemptState.FAILED)
            self.assertEqual(by_id["20260827-120002"], self.m.AttemptState.MALFORMED)
            self.assertEqual(
                by_id["20260827-130000"], self.m.AttemptState.MISSING_SLOT
            )
            counts = self.m.health_counts(health)
            self.assertEqual(counts["completed_sweep"], 1)
            self.assertEqual(counts["skipped_no_interface"], 1)
            self.assertEqual(counts["failed"], 1)
            self.assertEqual(counts["malformed"], 1)
            self.assertEqual(counts["missing_hourly_slot"], 1)

    def test_missing_hours_do_not_include_the_current_partial_hour(self):
        m = self.m
        start = m.parse_run_hour("20260827-090003")
        mid_hour = start.replace(hour=14, minute=30)
        slots = m.expected_slots("20260827-090003", now=mid_hour)
        self.assertEqual(slots[-1], "20260827-140000")
        self.assertEqual(len(slots), 6)  # 09:00..14:00 inclusive

    def test_slots_before_series_start_are_empty(self):
        m = self.m
        early = m.parse_run_hour("20260827-090003") - m.timedelta(hours=1)
        self.assertEqual(m.expected_slots("20260827-090003", now=early), [])

    def test_instrument_timestamp_authoritative_over_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(
                root,
                "20260827-090003",
                run_status="sweep",
                started_utc="2026-08-27T13:00:03Z",
            )
            cls_row = self.m.classify_pilot_child(root / "20260827-090003")
            self.assertEqual(cls_row.started_utc, "2026-08-27T13:00:03Z")


class MutationCheckTests(unittest.TestCase):
    """The classification must actually depend on the frozen constants: a
    changed exclusion or a shifted start must change the answer, or a stale
    constant could never be caught."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_removing_commissioning_exclusion_changes_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_run(
                root, "20260827-054734", run_status=None, with_tsvs=True
            )
            with_exclusion = self.m.classify_pilot_child(run_dir)
            without_exclusion = self.m.classify_pilot_child(
                run_dir, commissioning=()
            )
            self.assertEqual(
                with_exclusion.membership, self.m.Membership.COMMISSIONING
            )
            self.assertEqual(
                without_exclusion.membership, self.m.Membership.OUTSIDE
            )

    def test_shifting_series_start_by_one_hour_changes_eligibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_run(root, "20260827-090003", run_status="sweep")
            approved = self.m.classify_pilot_child(run_dir)
            shifted = self.m.classify_pilot_child(
                run_dir, series_start="20260827-100003"
            )
            self.assertTrue(approved.eligible)
            self.assertFalse(shifted.eligible)
            self.assertEqual(shifted.membership, self.m.Membership.OUTSIDE)


class ContractDocumentTests(unittest.TestCase):
    def test_document_labels_the_surface_provisional_and_rebuildable(self):
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        self.assertIn("provisional", text.lower())
        self.assertIn("rebuildable", text.lower())

    def test_document_contains_no_ddl(self):
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        self.assertNotIn("CREATE TABLE", text)
        self.assertNotIn("CREATE VIEW", text)

    def test_document_names_the_single_source_module(self):
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        self.assertIn("pilot_contract.py", text)


@unittest.skipUnless(
    LIVE_PILOT.is_dir(), "live pilot tree not mounted on this host"
)
class LiveInventoryTests(unittest.TestCase):
    """Validation against the real pilot tree. Read-only."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.inventory = cls.m.inventory_pilot(LIVE_PILOT)

    def test_every_child_has_exactly_one_classification_and_reason(self):
        children = sorted(p.name for p in LIVE_PILOT.iterdir())
        self.assertEqual(sorted(c.run_id for c in self.inventory), children)
        for cls_row in self.inventory:
            self.assertIsInstance(cls_row.membership, self.m.Membership)
            self.assertTrue(cls_row.reason)

    def test_commissioning_runs_present_and_excluded(self):
        by_id = {c.run_id: c for c in self.inventory}
        for run_id in self.m.COMMISSIONING_RUNS:
            if run_id in by_id:  # absent commissioning runs are not re-created
                self.assertEqual(
                    by_id[run_id].membership, self.m.Membership.COMMISSIONING
                )
                self.assertFalse(by_id[run_id].eligible)
                self.assertFalse(
                    any(
                        r.in_trend for r in self.m.build_run_health(
                            self.inventory, []
                        ) if r.run_id == run_id
                    )
                )

    def test_series_start_run_is_eligible(self):
        by_id = {c.run_id: c for c in self.inventory}
        self.assertIn(self.m.PILOT_SERIES_START, by_id)
        self.assertTrue(by_id[self.m.PILOT_SERIES_START].eligible)

    def test_no_archive_children_enter_the_inventory(self):
        self.assertFalse(any("archive" in c.run_id for c in self.inventory))
        self.assertFalse(
            any("probe-out" in c.run_id for c in self.inventory)
        )

    def test_live_expected_slots_reconcile_without_future_gaps(self):
        slots = self.m.expected_slots()
        health = self.m.build_run_health(self.inventory, slots)
        missing = [
            r.run_id for r in health
            if r.state is self.m.AttemptState.MISSING_SLOT
        ]
        # The 2026-08-28 00:00-04:00 local outage is expected to appear as
        # missing hours; nothing after the last discovered attempt may be
        # missing unless its slot has fully elapsed.
        last_attempt = max(
            (c.run_id for c in self.inventory if c.eligible), default=None
        )
        if last_attempt:
            for slot in missing:
                self.assertLessEqual(slot[:10], last_attempt[:10])


if __name__ == "__main__":
    unittest.main()
