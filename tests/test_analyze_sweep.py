#!/usr/bin/env python3
"""Regression tests for analyze-sweep.py."""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze-sweep.py"


def load_module():
    spec = importlib.util.spec_from_file_location("analyze_sweep", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AnalyzeSweepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_all_empty_sweep_is_a_valid_analysis_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            sweep = Path(tmp) / "empty-sweep"
            sweep.mkdir()
            with (sweep / "frequencies.tsv").open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=list(self.module.FREQ_DTYPES),
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerow({
                    "band": "6GHz",
                    "frequency_mhz": 5955,
                    "channel": 1,
                    "regulatory_state": "no-ir",
                    "sample_status": "sampled_empty",
                    "dwell_seconds": 10,
                    "pcap_file": "freq-5955.pcap",
                    "bssid_count": 0,
                    "beacon_count": 0,
                    "error": "",
                })
            agg_fields = [
                "band", "frequency_mhz", "channel", "bssid", "ssid", "beacons",
                "beacon_interval_tu", "rssi_min_dbm", "rssi_mean_dbm",
                "rssi_max_dbm", "first_seen", "last_seen",
                "beacon_reception_ratio",
            ]
            with (sweep / "aggregate.tsv").open("w", newline="", encoding="utf-8") as fh:
                csv.DictWriter(fh, fieldnames=agg_fields, delimiter="\t").writeheader()

            output = io.StringIO()
            with mock.patch.object(sys, "argv", [str(SCRIPT), str(sweep)]):
                with contextlib.redirect_stdout(output):
                    self.module.main()

            text = output.getvalue()
            self.assertIn("empty (negative observation)", text)
            self.assertIn("no BSSID observations", text)

    def test_single_sweep_maximum_is_reported_as_an_upper_bound(self):
        agg = pd.DataFrame({
            "beacon_interval_tu": pd.Series([100], dtype="Int64"),
            "beacons": pd.Series([90], dtype="Int64"),
            "beacon_reception_ratio": pd.Series([0.922], dtype="Float64"),
        })
        freq = pd.DataFrame({
            "dwell_seconds": pd.Series([10], dtype="Int64"),
        })

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.module.report_reception_calibration(agg, freq)

        text = output.getvalue()
        self.assertIn("observed ratio upper bound", text)
        self.assertNotIn("fixed offset", text)
        self.assertNotIn("instrumental loss", text)


if __name__ == "__main__":
    unittest.main()
