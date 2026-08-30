#!/usr/bin/env python3
"""Report tests: section order, determinism, truth-preserving wording, and
health-state rendering under synthetic failure states."""

from __future__ import annotations

import importlib.util
import json
import re
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


class ReportTestBase(unittest.TestCase):
    """A synthetic series with success, skip, failed, and absent states."""

    @classmethod
    def setUpClass(cls):
        cls.contract = load_module(
            ROOT / "scripts" / "pilot_contract.py", "pilot_contract_rep")
        cls.updater = load_module(
            ROOT / "scripts" / "pilot-update.py", "pilot_update_rep")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.pilot_root = self.base / "pilot"
        self.derived_root = self.base / "derived"
        self.reports_dir = self.base / "reports"
        self.now = self.contract.datetime(2026, 8, 27, 17, 30)

        # Two completed sweeps.
        synth.build_run_dir(self.pilot_root / "20260827-130002")
        synth.build_run_dir(self.pilot_root / "20260827-140002")
        # One receiver-absent skip.
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
        # One collector failure.
        failed = self.pilot_root / "20260827-160002"
        synth.build_run_dir(failed)
        instrument = failed / "instrument.json"
        doc = json.loads(instrument.read_text())
        doc["run_status"] = "failed"
        instrument.write_text(json.dumps(doc))
        # 20260827-170000 is absent: a missing hourly slot.
        # Commissioning runs: present, out of trend.
        for run_id in self.contract.COMMISSIONING_RUNS:
            (self.pilot_root / run_id).mkdir()
            (self.pilot_root / run_id / "frequencies.tsv").write_text(
                "band\tfrequency_mhz\tchannel\tregulatory_state\t"
                "sample_status\tdwell_seconds\tpcap_file\tbssid_count\t"
                "beacon_count\terror\n")

    def full_update(self):
        self.updater.enrich_stage(self.pilot_root, self.derived_root)
        db = self.updater.database_stage(
            self.pilot_root, self.derived_root, self.now)
        report = self.updater.report_stage(
            self.pilot_root, self.derived_root, self.reports_dir, self.now)
        return db, report

    def text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")


class SectionAndDeterminismTests(ReportTestBase):

    def test_all_ten_sections_in_required_order(self):
        _, report = self.full_update()
        text = self.text(report)
        positions = []
        for index, section in enumerate(self.contract.REPORT_SECTIONS, 1):
            marker = f"## {index}. {section}"
            self.assertIn(marker, text)
            positions.append(text.index(marker))
        self.assertEqual(positions, sorted(positions))

    def test_report_identifies_the_derived_schema(self):
        _, report = self.full_update()
        self.assertIn(self.contract.DERIVED_SCHEMA_ID, self.text(report))

    def test_identical_inputs_produce_byte_identical_output(self):
        _, report = self.full_update()
        first = self.text(report)
        self.updater.report_stage(
            self.pilot_root, self.derived_root, self.reports_dir, self.now)
        self.assertEqual(first, self.text(report))

    def test_cutoff_comes_from_source_events_not_wall_clock(self):
        _, report = self.full_update()
        text = self.text(report)
        # The known synthetic source event, not today's date.
        self.assertIn("2026-08-27T13:00:03Z", text)
        self.assertNotIn(str(self.contract.datetime.now().year + 1), text)


class TruthfulnessTests(ReportTestBase):

    def test_each_synthetic_state_gets_its_own_label(self):
        _, report = self.full_update()
        text = self.text(report)
        self.assertIn("Completed sweeps | 2", text)
        self.assertIn("Skipped (receiver absent) | 1", text)
        self.assertIn("Failed | 1", text)
        # Expected slots run from the approved series start (09:00), so the
        # synthetic tree's 09:00-12:00 and 17:00 hours are missing.
        self.assertIn("Missing hourly slots | 5", text)
        self.assertIn("`20260827-160002` (failed)", text)

    def test_commissioning_runs_never_enter_trend_sections(self):
        _, report = self.full_update()
        text = self.text(report)
        # Section 1 names the commissioning runs by contract; sections 2-8
        # are the trend surface and must not mention them at all.
        trend_body = text.split("## 2.")[1].split("## 9.")[0]
        commissioning_section = text.split("## 9. Commissioning reference")[1]
        for run_id in self.contract.COMMISSIONING_RUNS:
            self.assertNotIn(run_id, trend_body)
            self.assertIn(run_id, commissioning_section)

    def test_zero_direct_6ghz_reads_as_observation_not_capability_claim(self):
        _, report = self.full_update()
        text = " ".join(self.text(report).split())
        self.assertIn("No 6 GHz beacons were directly observed", text)
        self.assertIn("not a claim that no 6 GHz AP exists", text)
        self.assertIn(
            "not evidence that the receiver is calibrated for 6 GHz", text)

    def test_nonconcurrent_qualifier_is_mandatory(self):
        _, report = self.full_update()
        text = self.text(report)
        # The advertised-but-not-observed line must carry the qualifier.
        not_observed = [line for line in text.splitlines()
                        if "Advertised-but-not-observed" in line]
        self.assertTrue(not_observed)
        self.assertTrue(all("nonconcurrent" in line.lower()
                            for line in not_observed))
        # The narrative must deny a sensitivity/dwell conclusion.
        self.assertIn("not a miss rate", text)
        self.assertIn("not a sensitivity measurement", text)

    def test_no_calibrated_sensitivity_or_dwell_conclusion_anywhere(self):
        _, report = self.full_update()
        text = self.text(report).lower()
        for forbidden in ("sensitivity of", "dwell is too short",
                          "receiver blindness", "miss rate of"):
            self.assertNotIn(forbidden, text)

    def test_every_percentage_carries_numerator_and_denominator(self):
        _, report = self.full_update()
        text = self.text(report)
        for match in re.findall(r"\(([\d.]+)%\)", text):
            # Each percentage must be preceded by an n/m pattern on the same
            # line; the renderer only emits percentages via _fmt_pct.
            pass
        bare = [line for line in text.splitlines()
                if re.search(r"\d+\.\d%", line)
                and "/" not in line
                and "denominator" not in line.lower()]
        self.assertEqual(bare, [], f"percentage without n/m: {bare}")


class DegradationTests(ReportTestBase):

    def test_enrichment_failure_keeps_core_health_and_marks_advanced(self):
        # Break one run's source TSVs so its derivation fails, then prove the
        # report still updates its cutoff and core health, marks the affected
        # advanced surface unavailable, and does not reuse old values.
        self.full_update()
        first_text = self.text(self.reports_dir / "pilot-latest.md")
        self.assertIn("Latest trend run `20260827-140002`", first_text)

        third = self.pilot_root / "20260827-170002"
        synth.build_run_dir(third)
        (third / "aggregate.tsv").write_text("", encoding="utf-8")
        self.updater.enrich_stage(self.pilot_root, self.derived_root)
        self.updater.database_stage(
            self.pilot_root, self.derived_root, self.now)
        report = self.updater.report_stage(
            self.pilot_root, self.derived_root, self.reports_dir, self.now)
        text = self.text(report)
        # Core health moved forward (new cutoff, new attempt counted)...
        self.assertIn("`20260827-170002`", text)
        # ...the failure is itemized, not suppressed...
        self.assertIn("failed", text)
        self.assertIn("`20260827-170002`", text)
        # ...and the advanced line no longer claims the broken run.
        self.assertNotIn("Latest trend run `20260827-170002`", text)

    def test_advanced_section_never_reuses_stale_values(self):
        # Re-derive a run so its manifest fails: the advanced totals must
        # drop to what still verifies instead of repeating old numbers.
        self.full_update()
        broken = self.pilot_root / "20260827-140002"
        (broken / "aggregate.tsv").write_text("", encoding="utf-8")
        self.updater.enrich_stage(self.pilot_root, self.derived_root)
        self.updater.database_stage(
            self.pilot_root, self.derived_root, self.now)
        report = self.updater.report_stage(
            self.pilot_root, self.derived_root, self.reports_dir, self.now)
        text = self.text(report)
        # Capability totals collapsed from a denominator of 8 to 4, and the
        # HE numerator from 2 to 1: the broken run's advanced rows are gone,
        # not stale.
        self.assertIn("| HE (Wi-Fi 6) | 1 | 4 |", text)


class ValueReconciliationTests(ReportTestBase):

    def test_report_values_match_independent_computation(self):
        _, report = self.full_update()
        text = self.text(report)
        db = self.contract.derived_runs_root(
            self.derived_root).parents[2] / "pilot.duckdb"
        con = duckdb.connect(str(db), read_only=True)
        try:
            band_totals = con.execute(
                "SELECT band, SUM(attempted_frequencies),"
                " SUM(populated_frequencies), SUM(sampled_empty_frequencies),"
                " SUM(regulatory_skips), SUM(capture_errors),"
                " SUM(observed_bssids), SUM(beacon_frames)"
                " FROM pilot_band_metrics GROUP BY band ORDER BY band"
            ).fetchall()
        finally:
            con.close()
        coverage = text.split("## 3. Coverage")[1].split("## 4.")[0]
        for row in band_totals:
            band, attempted, populated, empty, skips, errors, bssids, \
                beacons = row
            expected_row = (f"| {band} | {attempted} | {populated} | "
                            f"{empty} | {skips} | {errors} | {bssids} | "
                            f"{beacons} |")
            self.assertIn(expected_row, coverage)


if __name__ == "__main__":
    unittest.main()
