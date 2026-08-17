#!/usr/bin/env python3
"""Behavioral test for the collector's embedded PCAP summarizer."""

from __future__ import annotations

import csv
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "wifi-beacon-sample.sh"


def embedded_summarizer() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r'python3 - "\$band" "\$freq" "\$chan" "\$pcap" "\$summary" '
        r'"\$DWELL" <<\'PY\'\n(.*?)\nPY\n\}',
        text,
        re.DOTALL,
    )
    if not match:
        raise AssertionError("collector summarizer heredoc not found")
    return match.group(1)


def write_single_beacon_pcap(path: Path, source: bytes, bssid: bytes) -> None:
    radiotap = struct.pack("<BBHI", 0, 0, 8, 0)
    header = (
        b"\x80\x00"
        + b"\x00\x00"
        + b"\xff" * 6
        + source
        + bssid
        + b"\x00\x00"
    )
    fixed = b"\x00" * 8 + struct.pack("<H", 100) + b"\x00\x00"
    ssid = b"\x00\x04test"
    packet = radiotap + header + fixed + ssid
    global_header = (
        b"\xd4\xc3\xb2\xa1"
        + struct.pack("<HHIIII", 2, 4, 0, 0, 65535, 127)
    )
    packet_header = struct.pack("<IIII", 0, 0, len(packet), len(packet))
    path.write_bytes(global_header + packet_header + packet)


class CollectorParserTests(unittest.TestCase):
    def test_help_uses_storage_mounted_default(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "-h"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            "/opt/agents/repos/storage-mounted/wifi-beacon-survey/sweeps",
            result.stdout,
        )

    def test_summary_uses_address_3_bssid_and_utc_timestamp(self):
        source = bytes.fromhex("021122334455")
        bssid = bytes.fromhex("aabbccddeeff")

        with tempfile.TemporaryDirectory() as tmp:
            pcap = Path(tmp) / "sample.pcap"
            summary = Path(tmp) / "sample.tsv"
            write_single_beacon_pcap(pcap, source, bssid)
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    embedded_summarizer(),
                    "2.4GHz",
                    "2412",
                    "1",
                    str(pcap),
                    str(summary),
                    "10",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            with summary.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh, delimiter="\t"))

        self.assertEqual("aa:bb:cc:dd:ee:ff", rows[0]["bssid"])
        self.assertEqual("1970-01-01T00:00:00.000000Z", rows[0]["first_seen"])


if __name__ == "__main__":
    unittest.main()
