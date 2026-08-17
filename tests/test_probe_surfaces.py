#!/usr/bin/env python3
"""Regression tests for probe-surfaces.py."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "probe-surfaces.py"


def load_module():
    spec = importlib.util.spec_from_file_location("probe_surfaces", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ProbeSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_installed_field_candidates_cover_verified_he_vht_and_disabled_link_names(self):
        fields = self.module.FIELD_CANDIDATES
        self.assertIn(
            "radiotap.he.data_1.ppdu_format",
            fields["radiotap_he_data1"],
        )
        for index in range(4):
            self.assertIn(
                f"radiotap.vht.nss.{index}",
                fields["radiotap_vht_nss"],
            )
        self.assertIn(
            "wlan.rnr.tbtt_info.mld_parameters.disabled_link_indication",
            fields["rnr_disabled_link"],
        )

    def test_nonconcurrent_rnr_miss_is_not_called_a_sensitivity_finding(self):
        records = [{
            "pcap": "freq-2412.pcap",
            "frame_number": "1",
            "frame_time_epoch": "1.0",
            "tx_bssid": "00:11:22:33:44:55",
            "tx_ssid": "example",
            "rnr_op_class": "81",
            "rnr_channel": "3",
            "rnr_bssid": "aabbccddeeff",
            "rnr_short_ssid": "",
            "rnr_bss_params": "0x00",
            "rnr_mld_link_id": "",
            "rnr_disabled_link": "",
            "structure_status": "single_occurrence",
        }]

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.module.report_rnr(records, {})

        text = output.getvalue()
        self.assertIn("advertised_but_not_observed_in_nonconcurrent_dwell", text)
        self.assertNotIn("sensitivity or dwell-length finding", text)

    def test_multi_occurrence_rnr_rows_are_not_positionally_interpreted(self):
        resolved = {
            "rnr_op_class": "op",
            "rnr_channel": "channel",
            "rnr_bssid": "bssid",
            "rnr_short_ssid": "short",
            "rnr_bss_params": "params",
            "rnr_mld_link_id": "link",
            "rnr_mld_id": "mld",
            "rnr_disabled_link": "disabled",
        }
        row = [
            "42", "1234.5", "00:11:22:33:44:55", "6578616d706c65",
            "81,81", "3,3", "aabbccddeeff,112233445566", "0x01,0x02",
            "0x00,0x00", "1,2", "1,1", "0,0",
        ]
        with mock.patch.object(self.module, "run_fields", return_value=[row]):
            records = self.module.pass_rnr([Path("freq-2412.pcap")], resolved)

        self.assertEqual("unpaired_multi_occurrence", records[0]["structure_status"])

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.module.report_rnr(records, {})

        text = output.getvalue()
        self.assertIn("skipped 1 unpaired multi-occurrence RNR row", text)
        self.assertNotIn("MISSED", text)


if __name__ == "__main__":
    unittest.main()
