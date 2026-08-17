#!/usr/bin/env python3
"""
Script Name  : probe-surfaces.py
Description  : Probes tshark field availability and censuses unused beacon data surfaces
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-08-16
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
Answers the open questions raised by the MT7921AU data-surface research against
real captures rather than against documentation. Runs seven passes over a sweep
directory: a tshark field-availability probe that discovers the actual display
filter names on the installed Wireshark build, a Radiotap probe that reports
which fields the mt76 driver populated at capture time, a capture-truncation
check, an Information Element census covering both the standard and extension
namespaces, and targeted extractors for Reduced Neighbor Report, BSS Load, and
advertised identity structure.

Nothing here is asserted from documentation. Field names are discovered from
`tshark -G fields` before use, and any expected-but-absent field is reported as
a finding rather than silently producing empty columns. All passes are read-only
against retained PCAP; the script changes nothing about acquisition.

Usage
-----
    python3 probe-surfaces.py <sweep_dir> [options]

Examples
--------
    python3 probe-surfaces.py /opt/agents/repos/storage-mounted/wifi-beacon-survey/sweeps/20260816-024440
        Full probe and census, report to stdout

    python3 probe-surfaces.py <sweep_dir> --tsv ./out
        Same, plus per-pass TSV artifacts written to ./out

    python3 probe-surfaces.py <sweep_dir> --only rnr
        Reduced Neighbor Report extraction and detection-completeness check only
"""

# =============================================================================
# Imports
# =============================================================================

from __future__ import annotations

import argparse
import collections
import csv
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

# =============================================================================
# Configuration
# =============================================================================

BEACON_FILTER = "wlan.fc.type_subtype == 0x0008"

# tshark emits this literal for a zero-length SSID element (hidden network).
TSHARK_MISSING = "<MISSING>"

# Standalone element IDs observed or expected in beacons.
# AI NOTE: IDs in the 32-127 range are easy to mistake for extension IDs. They
# are not. Extension elements carry ID 255 on the wire but Wireshark dissects
# them into a separate `wlan.ext_tag` tree and does NOT set `wlan.tag.number`
# to 255, so the extension namespace must be queried directly. Gating an
# ext_tag query behind `wlan.tag.number == 255` returns nothing and makes an
# HE/EHT-rich environment look like it has no Wi-Fi 6 at all.
ELEMENT_NAMES = {
    0: "SSID",
    1: "Supported Rates",
    3: "DS Parameter Set",
    5: "TIM",
    7: "Country",
    11: "BSS Load",
    32: "Power Constraint",
    33: "Power Capability",
    35: "TPC Report",
    36: "Supported Channels",
    37: "Channel Switch Announcement",
    42: "ERP Information",
    45: "HT Capabilities",
    46: "QoS Capability",
    48: "RSN",
    50: "Extended Supported Rates",
    51: "AP Channel Report",
    52: "Neighbor Report",
    54: "Mobility Domain",
    55: "Fast BSS Transition",
    59: "Supported Operating Classes",
    61: "HT Operation",
    62: "Secondary Channel Offset",
    70: "RM Enabled Capabilities",
    71: "Multiple BSSID",
    72: "20/40 BSS Coexistence",
    74: "Overlapping BSS Scan Params",
    107: "Interworking",
    108: "Advertisement Protocol",
    111: "Roaming Consortium",
    113: "Mesh Configuration",
    127: "Extended Capabilities",
    191: "VHT Capabilities",
    192: "VHT Operation",
    193: "Extended BSS Load",
    194: "Wide Bandwidth Channel Switch",
    195: "Transmit Power Envelope",
    196: "Channel Switch Wrapper",
    198: "Quiet Channel",
    199: "Operating Mode Notification",
    201: "Reduced Neighbor Report",
    221: "Vendor Specific",
    240: "Fine Timing Measurement Params",
    244: "RSNX",
    255: "Element Extension",
}

# Extension IDs carried under element 255.
EXT_NAMES = {
    35: "HE Capabilities",
    36: "HE Operation",
    38: "HE MU EDCA Parameter Set",
    39: "Spatial Reuse Parameter Set",
    55: "Multiple BSSID Configuration",
    59: "HE 6 GHz Band Capabilities",
    106: "EHT Operation",
    107: "Multi-Link",
    108: "EHT Capabilities",
    109: "TID-to-Link Mapping",
}

# Elements the research flagged as parse-only wins, identity structure first.
PRIORITY_ELEMENTS = [201, 71, 11, 48, 255, 127, 45, 191]

# Candidate display-filter names per capability. The installed Wireshark build
# decides which exist; the research reports disagreed on the RNR namespace, so
# every candidate is probed rather than picked. First surviving candidate wins.
FIELD_CANDIDATES = {
    "rnr_op_class": [
        "wlan.rnr.tbtt_info.operating_class",
        "wlan.rnr.operating_class",
        "wlan.rnr.tbtt_info.op_class",
    ],
    "rnr_channel": [
        "wlan.rnr.tbtt_info.channel_num",
        "wlan.rnr.channel_number",
        "wlan.rnr.tbtt_info.channel_number",
    ],
    "rnr_bssid": ["wlan.rnr.tbtt_info.bssid", "wlan.rnr.bssid"],
    "rnr_short_ssid": [
        "wlan.rnr.tbtt_info.sh_ssid",
        "wlan.rnr.tbtt_info.short_ssid",
        "wlan.rnr.short_ssid",
    ],
    "rnr_bss_params": [
        "wlan.rnr.tbtt_info.bss_parameters",
        "wlan.rnr.bss_parameters",
    ],
    "rnr_mld_link_id": ["wlan.rnr.tbtt_info.mld_parameters.link_id"],
    "rnr_mld_id": ["wlan.rnr.tbtt_info.mld_parameters.mld_id"],
    "rnr_disabled_link": [
        "wlan.rnr.tbtt_info.mld_parameters.disabled_link_indication",
    ],
    "qbss_station_count": ["wlan.qbss.scount", "wlan.qbss2.scount"],
    "qbss_utilization": ["wlan.qbss.cu", "wlan.qbss2.cu"],
    "qbss_admission": ["wlan.qbss.adc"],
    "he_bss_color": ["wlan.ext_tag.bss_color_information.bss_color"],
    "ext_tag_number": ["wlan.ext_tag.number", "wlan.ext_tag"],
    "beacon_timestamp": ["wlan.fixed.timestamp"],
    "radiotap_tsft": ["radiotap.mactime"],
    "radiotap_noise": ["radiotap.dbm_antnoise"],
    "radiotap_db_noise": ["radiotap.db_antnoise"],
    "radiotap_dbm_signal": ["radiotap.dbm_antsignal"],
    "radiotap_db_signal": ["radiotap.db_antsignal"],
    "radiotap_antenna": ["radiotap.antenna"],
    "radiotap_datarate": ["radiotap.datarate"],
    "radiotap_mcs_index": ["radiotap.mcs.index"],
    "radiotap_vht_nss": [
        "radiotap.vht.nss.0",
        "radiotap.vht.nss.1",
        "radiotap.vht.nss.2",
        "radiotap.vht.nss.3",
        "radiotap.vht.nss",
        "radiotap.vht.user0.nss",
    ],
    "radiotap_he_data1": [
        "radiotap.he.data_1.ppdu_format",
        "radiotap.he.data1",
        "radiotap.he.ppdu_format",
    ],
    "radiotap_flags_badfcs": ["radiotap.flags.badfcs"],
}

# Radiotap capabilities probed by extracting the field and counting values.
# AI NOTE: an earlier version grepped `tshark -V` for Wireshark field *names*
# ("dBm Antenna Signal"). Verbose output prints display *labels*
# ("Antenna signal:"), so every signal marker read ABSENT while the data was
# present. Counting extracted values is label-independent and yields the
# per-chain repetition count for free.
RADIOTAP_PROBE = [
    "radiotap_tsft",
    "radiotap_dbm_signal",
    "radiotap_db_signal",
    "radiotap_noise",
    "radiotap_db_noise",
    "radiotap_antenna",
    "radiotap_datarate",
    "radiotap_mcs_index",
    "radiotap_vht_nss",
    "radiotap_he_data1",
    "radiotap_flags_badfcs",
]

# =============================================================================
# Functions
# =============================================================================


def require_tshark() -> None:
    """Exit unless tshark is on PATH."""
    if not shutil.which("tshark"):
        sys.exit("tshark not found on PATH. Install wireshark-common / tshark.")


def tshark_version() -> str:
    """Return the first line of `tshark --version`, for provenance."""
    out = subprocess.run(
        ["tshark", "--version"], capture_output=True, text=True, check=False
    )
    return out.stdout.splitlines()[0] if out.stdout else "unknown"


def available_fields() -> set[str]:
    """Enumerate every display-filter field name the installed build knows."""
    out = subprocess.run(
        ["tshark", "-G", "fields"], capture_output=True, text=True, check=False
    )
    names: set[str] = set()
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[0] == "F" and len(parts) > 2:
            names.add(parts[2])
    return names


def resolve_fields(have: set[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Pick the first candidate display-filter name that exists locally."""
    resolved: dict[str, str] = {}
    missing: dict[str, list[str]] = {}
    for logical, candidates in FIELD_CANDIDATES.items():
        hit = next((c for c in candidates if c in have), None)
        if hit:
            resolved[logical] = hit
        else:
            missing[logical] = candidates
    return resolved, missing


def discover_namespace(have: set[str], prefix: str, limit: int = 40) -> list[str]:
    """Return known fields under a prefix, so unresolved names stay visible."""
    return sorted(f for f in have if f.startswith(prefix))[:limit]


def run_fields(pcap: Path, display_filter: str, fields: list[str]) -> list[list[str]]:
    """
    Run tshark in field-extraction mode and return parsed rows.

    Notes
    -----
    Multi-occurrence fields are comma-joined by tshark, so a single cell can
    describe several repeated structures. Callers must not pair values
    positionally across columns without re-parsing the TLV hierarchy.
    """
    cmd = ["tshark", "-r", str(pcap), "-Y", display_filter, "-T", "fields"]
    for f in fields:
        cmd += ["-e", f]
    cmd += ["-E", "separator=/t", "-E", "occurrence=a"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return []
    return [ln.split("\t") for ln in out.stdout.splitlines() if ln.strip()]


def decode_ssid(value: str) -> str:
    """
    Decode a tshark SSID cell into text where possible.

    Notes
    -----
    `wlan.ssid` is a byte field, so `-T fields` emits hex rather than text. That
    is correct behaviour, not a defect: an SSID is up to 32 arbitrary octets and
    is not guaranteed to be valid UTF-8. A zero-length SSID (hidden network)
    comes back as the literal `<MISSING>` rather than as hex. Undecodable values
    are returned as hex with a marker so the raw bytes are never lost.
    """
    raw = value.strip()
    if not raw or raw == TSHARK_MISSING:
        return "<hidden>"
    try:
        return bytes.fromhex(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return f"<hex:{raw}>"


def opclass_to_freq(op_class: int, channel: int) -> tuple[str, int | None]:
    """
    Map an 802.11 global operating class and channel to band and centre MHz.

    Notes
    -----
    The channel-to-frequency formula is band-specific. Applying the 6 GHz
    formula (5950 + 5n) to a 2.4 GHz operating class silently produces a
    plausible-looking 5 GHz number, which is exactly the kind of error that
    turns a co-located 2.4 GHz neighbour into a phantom 6 GHz detection.
    Global operating classes: 81-84 are 2.4 GHz, 112-130 are 5 GHz, 131-137
    are 6 GHz, with class 136 pinned to the 5935 MHz channel-2 case.
    """
    if op_class in (81, 83, 84):
        return "2.4GHz", 2407 + 5 * channel
    if op_class == 82:
        return "2.4GHz", 2484
    if 112 <= op_class <= 130:
        return "5GHz", 5000 + 5 * channel
    if op_class == 136:
        return "6GHz", 5935
    if 131 <= op_class <= 137:
        return "6GHz", 5950 + 5 * channel
    return "unknown", None


def resolve_short_ssid(short_ssid_hex: str, ssid_pool: set[str]) -> str | None:
    """
    Identify which observed SSID a Short SSID refers to.

    Parameters
    ----------
    short_ssid_hex : str
        Advertised Short SSID, hex string.
    ssid_pool : set of str
        Every SSID string seen anywhere in the sweep.

    Returns
    -------
    str or None
        The matching SSID, or None if no observed SSID hashes to it.

    Notes
    -----
    Short SSID is the CRC-32 of the SSID. An RNR describes the *neighbour's*
    SSID, not the transmitter's, so checking only against the transmitting AP
    reports a false mismatch whenever a guest or community BSS advertises a
    differently-named co-located radio. Hashing every observed SSID resolves
    those cases and leaves a genuine None only for SSIDs never received.
    """
    try:
        advertised = int(short_ssid_hex, 16)
    except ValueError:
        return None
    for ssid in ssid_pool:
        if ssid and not ssid.startswith("<") and zlib.crc32(ssid.encode()) == advertised:
            return ssid
    return None


def populated_pcaps(sweep_dir: Path) -> list[Path]:
    """
    Return per-frequency PCAPs that actually contain frames.

    Notes
    -----
    Empty frequencies produce a 24-byte file (PCAP file header, zero packets).
    Filtering on size avoids launching tshark once per empty frequency.
    """
    return sorted(p for p in sweep_dir.glob("freq-*.pcap") if p.stat().st_size > 24)


def collect_observed(pcaps: list[Path]) -> dict[str, str]:
    """Return every BSSID actually received in the sweep, mapped to its SSID."""
    observed: dict[str, str] = {}
    for pcap in pcaps:
        for row in run_fields(pcap, BEACON_FILTER, ["wlan.bssid", "wlan.ssid"]):
            if not row or not row[0].strip():
                continue
            bssid = row[0].strip().lower()
            ssid = decode_ssid(row[1] if len(row) > 1 else "")
            observed.setdefault(bssid, ssid)
            if observed[bssid] == "<hidden>" and ssid != "<hidden>":
                observed[bssid] = ssid
    return observed


def pass_fields(have: set[str]) -> dict[str, str]:
    """Report field availability and return the resolved name map."""
    resolved, missing = resolve_fields(have)
    print(f"tshark            : {tshark_version()}")
    print(f"known field names : {len(have)}")
    print("\nresolved:")
    for logical in sorted(resolved):
        print(f"  {logical:<22} -> {resolved[logical]}")
    if missing:
        print("\nUNRESOLVED (candidates absent on this build):")
        for logical, cands in sorted(missing.items()):
            print(f"  {logical:<22} tried: {', '.join(cands)}")
    return resolved


def pass_radiotap(pcap: Path, resolved: dict[str, str], count: int = 200) -> None:
    """Report which Radiotap fields the driver populated, by extracting them."""
    probes = [p for p in RADIOTAP_PROBE if p in resolved]
    cols = [resolved[p] for p in probes]
    cmd = ["tshark", "-r", str(pcap), "-Y", BEACON_FILTER, "-c", str(count),
           "-T", "fields"]
    for c in cols:
        cmd += ["-e", c]
    cmd += ["-E", "separator=/t", "-E", "occurrence=a"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    rows = [ln.split("\t") for ln in out.stdout.splitlines() if ln.strip()]
    if not rows:
        print("  no frames decoded")
        return

    print(f"  sampled {len(rows)} beacons\n")
    print(f"  {'field':<26} {'frames':>7} {'vals/frame':>11}  verdict")
    for i, logical in enumerate(probes):
        present = 0
        total_vals = 0
        set_true = 0
        for row in rows:
            cell = row[i].strip() if i < len(row) else ""
            if cell:
                present += 1
                vals = [v for v in cell.split(",") if v]
                total_vals += len(vals)
                # A boolean flag field is "present" on every frame regardless
                # of value; only a value of 1 means the condition occurred.
                set_true += sum(1 for v in vals if v.strip() in ("1", "True"))
        per = (total_vals / present) if present else 0.0
        if present == 0:
            verdict = "ABSENT"
        elif per > 1.5:
            verdict = f"POPULATED, {per:.1f} values per frame (repeated)"
        elif logical.endswith("badfcs"):
            verdict = f"POPULATED, set on {set_true} of {present} frames"
        else:
            verdict = "POPULATED"
        pct = 100.0 * present / len(rows)
        print(f"  {logical:<26} {pct:>6.0f}% {per:>11.2f}  {verdict}")

    print("\n  per-chain resolution: whichever of radiotap_dbm_signal or")
    print("  radiotap_db_signal reports more than one value per frame is the")
    print("  field carrying per-chain data. Subtract one for the aggregate")
    print("  value in the base header to get the chain count.")


def pass_truncation(pcaps: list[Path]) -> None:
    """
    Check whether captures were truncated by snaplen.

    Notes
    -----
    A trailing element missing from a census is ambiguous between "the AP did
    not send it" and "the capture cut it off". Comparing captured length against
    original wire length settles that, and it must be settled before any absence
    is reported as an environmental fact.
    """
    truncated = 0
    total = 0
    max_cap = 0
    for pcap in pcaps:
        for row in run_fields(pcap, BEACON_FILTER, ["frame.len", "frame.cap_len"]):
            if len(row) < 2 or not row[0].strip().isdigit():
                continue
            wire, cap = int(row[0]), int(row[1])
            total += 1
            max_cap = max(max_cap, cap)
            if cap < wire:
                truncated += 1
    if not total:
        print("  no frames to check")
        return
    print(f"  frames checked        : {total}")
    print(f"  largest captured frame: {max_cap} bytes")
    if truncated:
        print(f"  TRUNCATED             : {truncated} "
              f"({100.0 * truncated / total:.1f}%)")
        print("  absence of trailing elements is NOT evidence the AP omitted them")
    else:
        print("  truncated             : 0")
        print("  full frames retained; a missing element means the AP did not "
              "send it")


def pass_ie_census(pcaps: list[Path], resolved: dict[str, str]) -> dict[str, set[int]]:
    """
    Build an element-ID census across both the standard and extension namespaces.

    Notes
    -----
    The extension namespace is queried directly rather than through a
    `wlan.tag.number == 255` filter. Wireshark does not report 255 in
    `wlan.tag.number`, so gating on it hides every HE and EHT element.
    """
    elem_counts = collections.Counter()
    ext_counts = collections.Counter()
    per_bssid: dict[str, set[int]] = collections.defaultdict(set)
    per_bssid_ext: dict[str, set[int]] = collections.defaultdict(set)

    for pcap in pcaps:
        for row in run_fields(pcap, BEACON_FILTER, ["wlan.bssid", "wlan.tag.number"]):
            if len(row) < 2:
                continue
            bssid = row[0].strip().lower()
            ids = {int(t) for t in row[1].split(",") if t.strip().isdigit()}
            elem_counts.update(ids)
            if bssid:
                per_bssid[bssid] |= ids

    if "ext_tag_number" in resolved:
        ext_field = resolved["ext_tag_number"]
        for pcap in pcaps:
            for row in run_fields(pcap, BEACON_FILTER, ["wlan.bssid", ext_field]):
                if len(row) < 2 or not row[1].strip():
                    continue
                bssid = row[0].strip().lower()
                ids = {int(t) for t in row[1].split(",") if t.strip().isdigit()}
                ext_counts.update(ids)
                if bssid:
                    per_bssid_ext[bssid] |= ids

    print(f"  BSSIDs seen: {len(per_bssid)}\n")
    print(f"  {'ID':>4}  {'frames':>7}  {'BSSIDs':>7}  element")
    for eid, frames in sorted(elem_counts.items()):
        n = sum(1 for ids in per_bssid.values() if eid in ids)
        print(f"  {eid:>4}  {frames:>7}  {n:>7}  "
              f"{ELEMENT_NAMES.get(eid, 'UNMAPPED - look up before reporting')}")

    if ext_counts:
        print(f"\n  extension elements (element 255 namespace), "
              f"{len(per_bssid_ext)} BSSIDs carry at least one:")
        print(f"  {'ext':>4}  {'frames':>7}  {'BSSIDs':>7}  element")
        for ext, frames in sorted(ext_counts.items()):
            n = sum(1 for ids in per_bssid_ext.values() if ext in ids)
            print(f"  {ext:>4}  {frames:>7}  {n:>7}  "
                  f"{EXT_NAMES.get(ext, 'UNMAPPED - look up before reporting')}")
        gen = []
        if any(e in ext_counts for e in (35, 36)):
            gen.append("HE / Wi-Fi 6")
        if 59 in ext_counts:
            gen.append("HE 6 GHz / Wi-Fi 6E")
        if any(e in ext_counts for e in (106, 107, 108)):
            gen.append("EHT / Wi-Fi 7")
        print(f"\n  generations advertised: {', '.join(gen) or 'none above VHT'}")
    else:
        print("\n  no extension elements found")
        print("  if the truncation pass is clean this means no Wi-Fi 6 or 7")
        print("  advertisement in range, which is a strong claim: verify the")
        print("  ext_tag field resolved in Pass 1 before reporting it")

    absent = [e for e in PRIORITY_ELEMENTS if e not in elem_counts]
    print("\n  priority standard elements not observed: " + (
        ", ".join(f"{e} ({ELEMENT_NAMES.get(e, '?')})" for e in absent)
        or "none, all present"))
    return per_bssid


def pass_rnr(pcaps: list[Path], resolved: dict[str, str]) -> list[dict]:
    """Extract Reduced Neighbor Report advertisements from beacons."""
    wanted = ["rnr_op_class", "rnr_channel", "rnr_bssid", "rnr_short_ssid",
              "rnr_bss_params", "rnr_mld_link_id", "rnr_mld_id",
              "rnr_disabled_link"]
    have = [w for w in wanted if w in resolved]
    cols = ["frame.number", "frame.time_epoch", "wlan.bssid", "wlan.ssid"]
    cols += [resolved[w] for w in have]
    labels = ["frame_number", "frame_time_epoch", "tx_bssid", "tx_ssid_hex"]
    labels += have

    records = []
    for pcap in pcaps:
        for row in run_fields(pcap, f"{BEACON_FILTER} && wlan.tag.number == 201",
                              cols):
            rec = {"pcap": pcap.name}
            for i, label in enumerate(labels):
                rec[label] = row[i].strip() if i < len(row) else ""
            repeated = [label for label in have if "," in rec.get(label, "")]
            rec["structure_status"] = (
                "unpaired_multi_occurrence" if repeated else "single_occurrence"
            )
            rec["unpaired_fields"] = ",".join(repeated)
            rec["tx_ssid"] = decode_ssid(rec.get("tx_ssid_hex", ""))
            records.append(rec)
    return records


def report_rnr(records: list[dict], observed: dict[str, str]) -> None:
    """
    Print deduplicated RNR advertisements and a detection-completeness check.

    Notes
    -----
    An advertised neighbour is an AP the transmitter asserted at that frame's
    time. Comparing advertisements with received BSSIDs is useful evidence, but
    a sequential sweep cannot turn that comparison into a calibrated miss rate.
    """
    if not records:
        print("  no RNR elements found in any populated capture")
        print("  before concluding no co-located radios exist, confirm the")
        print("  capture retains full tagged parameters (see truncation pass)")
        return

    unpaired = [
        rec for rec in records
        if rec.get("structure_status") == "unpaired_multi_occurrence"
    ]
    if unpaired:
        print(f"  skipped {len(unpaired)} unpaired multi-occurrence RNR row(s); "
              "hierarchical TLV parsing is required")
    records = [
        rec for rec in records
        if rec.get("structure_status", "single_occurrence") == "single_occurrence"
    ]
    if not records:
        print("  no safely paired RNR rows available for interpretation")
        return

    ssid_pool = set(observed.values())
    key_fields = ["tx_bssid", "tx_ssid", "rnr_op_class", "rnr_channel",
                  "rnr_bssid", "rnr_short_ssid", "rnr_bss_params",
                  "rnr_mld_link_id", "rnr_disabled_link"]
    seen: collections.Counter = collections.Counter()
    for rec in records:
        seen[tuple(rec.get(k, "") for k in key_fields)] += 1

    print(f"  {len(records)} beacons carry element 201, "
          f"{len(seen)} distinct advertisements\n")

    advertised: dict[str, dict] = {}
    for key, n in sorted(seen.items(), key=lambda kv: -kv[1]):
        rec = dict(zip(key_fields, key))
        ch, oc = rec.get("rnr_channel", ""), rec.get("rnr_op_class", "")
        if ch.isdigit() and oc.isdigit():
            band, freq = opclass_to_freq(int(oc), int(ch))
            where = f"{band} {freq} MHz" if freq else f"op_class {oc}, unknown band"
        else:
            band, freq, where = "unknown", None, "unresolved"

        neighbor = rec.get("rnr_bssid", "").lower()
        canon = ":".join(neighbor[i:i + 2] for i in range(0, len(neighbor), 2)) \
            if len(neighbor) == 12 else neighbor
        resolved_ssid = resolve_short_ssid(rec.get("rnr_short_ssid", ""), ssid_pool)

        print(f"  {rec['tx_bssid']}  {rec['tx_ssid']}  ({n} beacons)")
        print(f"    advertises {canon}  op_class={oc} channel={ch}  -> {where}")
        print(f"    short_ssid={rec['rnr_short_ssid']} -> "
              f"{resolved_ssid or 'no observed SSID hashes to this'}")
        if rec.get("rnr_mld_link_id"):
            print(f"    MLD link_id={rec['rnr_mld_link_id']}  "
                  f"(Wi-Fi 7 multi-link advertisement)")
        disabled_value = rec.get("rnr_disabled_link", "").strip().lower()
        is_disabled = disabled_value in {"1", "true", "yes", "set"}
        if disabled_value:
            print(f"    disabled_link_indication={disabled_value}")
        params = rec.get("rnr_bss_params", "")
        if params.startswith("0x"):
            bits = int(params, 16)
            flags = [
                (0, "OCT recommended"), (1, "same SSID"),
                (2, "multiple BSSID"), (3, "transmitted BSSID"),
                (4, "member of ESS w/ 2.4-5 GHz co-located AP"),
                (5, "unsolicited probe responses active"),
                (6, "co-located AP"),
            ]
            on = [name for bit, name in flags if bits & (1 << bit)]
            print(f"    bss_params={params}: {', '.join(on) or 'none set'}")
        print()

        if canon:
            advertised[canon] = {
                "band": band,
                "freq": freq,
                "ssid": resolved_ssid or "?",
                "advertised_by": rec["tx_bssid"],
                "disabled": is_disabled,
            }

    print("  advertised neighbours vs BSSIDs received")
    hit = not_observed = disabled = 0
    for bssid, info in sorted(advertised.items()):
        if info["disabled"]:
            disabled += 1
            print(f"    administratively_disabled  {bssid}  "
                  f"{info['band']:<8} {info['ssid']}")
        elif bssid in observed:
            hit += 1
            print(f"    detected  {bssid}  {info['band']:<8} {info['ssid']}")
        else:
            not_observed += 1
            freq = f"{info['freq']} MHz" if info["freq"] else "unknown freq"
            print("    advertised_but_not_observed_in_nonconcurrent_dwell  "
                  f"{bssid}  {info['band']:<8} {freq:<10} {info['ssid']}  "
                  f"(advertised by {info['advertised_by']})")
    total = hit + not_observed
    if total:
        print(f"\n    {hit} of {total} enabled or unknown-state advertised "
              f"neighbours received ({100 * hit // total}%)")
    if disabled:
        print(f"    {disabled} administratively disabled link(s) excluded")
    print("    non-observation in a sequential sweep is not a calibrated miss; "
          "timing-aware controls are required")


def pass_bss_load(pcaps: list[Path], resolved: dict[str, str]) -> list[dict]:
    """Extract BSS Load (element 11) station count and channel utilization."""
    wanted = ["qbss_station_count", "qbss_utilization", "qbss_admission"]
    have = [w for w in wanted if w in resolved]
    cols = ["wlan.bssid", "wlan.ssid"] + [resolved[w] for w in have]
    labels = ["bssid", "ssid_hex"] + have

    records = []
    for pcap in pcaps:
        for row in run_fields(pcap, f"{BEACON_FILTER} && wlan.tag.number == 11",
                              cols):
            rec = {"pcap": pcap.name}
            for i, label in enumerate(labels):
                rec[label] = row[i].strip() if i < len(row) else ""
            rec["ssid"] = decode_ssid(rec.get("ssid_hex", ""))
            records.append(rec)
    return records


def report_bss_load(records: list[dict]) -> None:
    """Print per-BSSID BSS Load ranges, with utilization as a percentage."""
    if not records:
        print("  no BSS Load elements found (expected where WMM/QoS is off)")
        return
    by_bssid: dict[str, list[dict]] = collections.defaultdict(list)
    for r in records:
        by_bssid[r.get("bssid", "")].append(r)
    print(f"  {len(records)} beacons across {len(by_bssid)} BSSIDs")
    print("  utilization is the AP's own sensed medium busy fraction, not the")
    print("  receiver's; station count is the AP's association table\n")
    for bssid, rows in sorted(by_bssid.items()):
        util = [int(v) for r in rows
                if (v := r.get("qbss_utilization", "")).isdigit()]
        stn = [int(v) for r in rows
               if (v := r.get("qbss_station_count", "")).isdigit()]
        u_txt = (f"util {min(util)}-{max(util)}/255 "
                 f"({100 * min(util) // 255}-{100 * max(util) // 255}%)"
                 if util else "util n/a")
        s_txt = f"stations {min(stn)}-{max(stn)}" if stn else "stations n/a"
        print(f"    {bssid}  {rows[0].get('ssid', ''):<22} {u_txt:<28} {s_txt}")


def pass_identity(pcaps: list[Path], resolved: dict[str, str]) -> dict[str, int]:
    """
    Count frames carrying advertised identity and capability structure.

    Notes
    -----
    Multiple BSSID (71) and the Multi-Link extension are the AP's own statement
    of which BSSIDs belong to one radio or one MLD. Where present they replace
    the octet-pattern heuristic in analyze-sweep.py with ground truth.
    """
    checks = {
        "element_71_multiple_bssid": "wlan.tag.number == 71",
        "element_201_rnr": "wlan.tag.number == 201",
        "element_11_bss_load": "wlan.tag.number == 11",
        "element_195_tx_power_envelope": "wlan.tag.number == 195",
        "element_244_rsnx": "wlan.tag.number == 244",
        "element_107_interworking": "wlan.tag.number == 107",
    }
    if "ext_tag_number" in resolved:
        checks["any_extension_element"] = resolved["ext_tag_number"]
    if "he_bss_color" in resolved:
        checks["he_bss_color"] = resolved["he_bss_color"]
    if "rnr_mld_link_id" in resolved:
        checks["rnr_mld_link_id"] = resolved["rnr_mld_link_id"]
    if "radiotap_flags_badfcs" in resolved:
        checks["fcs_failures"] = f"{resolved['radiotap_flags_badfcs']} == 1"

    counts: dict[str, int] = {}
    for label, expr in checks.items():
        total = 0
        for pcap in pcaps:
            total += len(run_fields(pcap, f"{BEACON_FILTER} && {expr}",
                                    ["wlan.bssid"]))
        counts[label] = total
    return counts


def write_tsv(path: Path, records: list[dict]) -> None:
    """Write a list of dicts to TSV, using the union of keys as the header."""
    if not records:
        return
    keys: list[str] = []
    for rec in records:
        for k in rec:
            if k not in keys:
                keys.append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"  wrote {path} ({len(records)} rows)")


def header(title: str) -> None:
    """Print a section banner."""
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> None:
    """Entry point for script execution."""
    parser = argparse.ArgumentParser(
        description="Probe tshark field availability and census unused beacon "
                    "data surfaces in a sweep directory."
    )
    parser.add_argument("sweep_dir", type=Path)
    parser.add_argument("--tsv", type=Path, default=None,
                        help="directory for TSV artifacts")
    parser.add_argument("--only",
                        choices=["fields", "radiotap", "truncation", "census",
                                 "rnr", "bssload", "identity"],
                        default=None, help="run a single pass")
    parser.add_argument("--radiotap-frames", type=int, default=200,
                        help="frames to sample for the Radiotap probe")
    args = parser.parse_args()

    require_tshark()
    sweep_dir = args.sweep_dir.resolve()
    if not sweep_dir.is_dir():
        sys.exit(f"not a directory: {sweep_dir}")

    pcaps = populated_pcaps(sweep_dir)
    all_pcaps = list(sweep_dir.glob("freq-*.pcap"))
    print(f"sweep          : {sweep_dir.name}")
    print(f"populated pcaps: {len(pcaps)} of {len(all_pcaps)}")
    if not pcaps:
        sys.exit("no populated captures found")

    run = args.only
    have = available_fields()

    header("Pass 1: tshark field availability")
    resolved = pass_fields(have)

    observed = collect_observed(pcaps)

    if run in (None, "radiotap"):
        header("Pass 2: Radiotap field population")
        biggest = max(pcaps, key=lambda p: p.stat().st_size)
        print(f"  source: {biggest.name}")
        pass_radiotap(biggest, resolved, args.radiotap_frames)

    if run in (None, "truncation"):
        header("Pass 3: capture truncation check")
        pass_truncation(pcaps)

    if run in (None, "census"):
        header("Pass 4: Information Element census")
        per_bssid = pass_ie_census(pcaps, resolved)
        if args.tsv:
            write_tsv(args.tsv / "ie-census.tsv",
                      [{"bssid": b, "ssid": observed.get(b, ""),
                        "element_ids": ",".join(str(i) for i in sorted(ids))}
                       for b, ids in sorted(per_bssid.items())])

    if run in (None, "rnr"):
        header("Pass 5: Reduced Neighbor Report (element 201)")
        recs = pass_rnr(pcaps, resolved)
        report_rnr(recs, observed)
        if args.tsv:
            write_tsv(args.tsv / "rnr.tsv", recs)

    if run in (None, "bssload"):
        header("Pass 6: BSS Load (element 11)")
        recs = pass_bss_load(pcaps, resolved)
        report_bss_load(recs)
        if args.tsv:
            write_tsv(args.tsv / "bss-load.tsv", recs)

    if run in (None, "identity"):
        header("Pass 7: advertised identity and capability structure")
        counts = pass_identity(pcaps, resolved)
        for label, n in counts.items():
            print(f"  {label:<32} {'not present' if n == 0 else f'{n} beacons'}")
        if counts.get("element_71_multiple_bssid", 0) == 0:
            print("\n  no Multiple BSSID element in this environment; the")
            print("  octet-pattern radio-family heuristic remains the primary")
            print("  identity signal, corroborated where RNR names a neighbour")


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    main()
