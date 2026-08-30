#!/usr/bin/env python3
"""
Script Name  : pilot_enrich.py
Description  : Version 1 per-run PCAP enrichment: replayable Parquet artifacts
               with hashed source identity and an atomic derivation manifest
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-08-28
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
Enriches one pilot run into the derived artifacts defined by
`docs/pilot-analysis-contract.md` and `pilot_contract.py`: core run,
frequency, and observation tables replayed from the source TSVs, plus
tshark-extracted IE capability, Reduced Neighbor Report, and BSS Load tables
at frame grain.

Design rules inherited from the repository contract:

- Evidence is opened read-only. Source identity (SHA-256 + size over the
  instrument JSON, both TSVs, and every per-frequency PCAP) is recorded in
  the manifest so a changed input can never be mistaken for a processed one.
- Field display-filter names are resolved against the installed tshark build
  before use, reusing the probe-surfaces resolver. A failed lookup is
  recorded as `unresolved`, never as an observed zero.
- Repeated tshark occurrences are never paired positionally. A beacon frame
  with several RNR neighbor blocks stays one ambiguous frame record.
- Every BSS Load row carries its source PCAP, frame number, and frame time;
  a row without packet identity is a validation failure, not a series.
- The manifest is written last via atomic rename. Only a complete success
  manifest makes a per-run output authoritative.

Usage
-----
    Imported by pilot-update.py; also usable directly:

    python3 pilot_enrich.py <run_dir> <out_dir>
"""

# =============================================================================
# Imports
# =============================================================================

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

# =============================================================================
# Module loading: the contract and the probe-surfaces resolver
# =============================================================================
# Both collaborators live in this directory under hyphenated or sibling names
# that the interpreter will not import directly, so they are loaded by path
# and registered in sys.modules (required while dataclass bodies execute).

_SCRIPTS_DIR = Path(__file__).resolve().parent


def _load_sibling(module_name: str, file_name: str):
    """Load a sibling script as a module without touching sys.path."""
    spec = importlib.util.spec_from_file_location(
        module_name, _SCRIPTS_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pilot = _load_sibling("pilot_contract", "pilot_contract.py")
probe = _load_sibling("probe_surfaces", "probe-surfaces.py")

# =============================================================================
# Configuration
# =============================================================================

# Core frame-identity fields, with single candidates verified like every other
# lookup so a renamed dissector field becomes an unresolved finding instead of
# a silent empty column.
CORE_FIELD_CANDIDATES: dict[str, list[str]] = {
    "frame_number": ["frame.number"],
    "frame_time_epoch": ["frame.time_epoch"],
    "wlan_bssid": ["wlan.bssid"],
    "wlan_ssid": ["wlan.ssid"],
    "tag_number": ["wlan.tag.number"],
}

# The full requested set: probe-surfaces candidates (RNR, BSS Load, extension
# namespace, Radiotap diagnostics) plus the core identity fields.
REQUESTED_FIELDS: dict[str, list[str]] = {
    **probe.FIELD_CANDIDATES,
    **CORE_FIELD_CANDIDATES,
}

# Logical fields whose resolved names this module actually extracts.
ENRICH_LOGICALS: tuple[str, ...] = (
    "frame_number", "frame_time_epoch", "wlan_bssid", "wlan_ssid",
    "tag_number", "ext_tag_number",
    "rnr_op_class", "rnr_channel", "rnr_bssid", "rnr_short_ssid",
    "rnr_bss_params", "rnr_mld_link_id", "rnr_mld_id", "rnr_disabled_link",
    "qbss_station_count", "qbss_utilization", "qbss_admission",
)

RNR_VALUE_FIELDS: tuple[str, ...] = (
    "rnr_op_class", "rnr_channel", "rnr_bssid", "rnr_short_ssid",
    "rnr_bss_params", "rnr_mld_link_id", "rnr_mld_id", "rnr_disabled_link",
)
QBSS_VALUE_FIELDS: tuple[str, ...] = (
    "qbss_station_count", "qbss_utilization", "qbss_admission",
)

# Artifact file names. The contract document maps logical artifacts to these.
ARTIFACT_NAMES: tuple[str, ...] = (
    "run.parquet", "frequencies.parquet", "observations.parquet",
    "ie_capabilities.parquet", "rnr.parquet", "bss_load.parquet",
    "field_resolution.parquet",
)


class ExtractionError(RuntimeError):
    """Raised when a derivation step fails; recorded in the manifest."""


# =============================================================================
# Source identity
# =============================================================================


def sha256_file(path: Path) -> str:
    """Stream a file through SHA-256."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(run_dir: Path) -> list[dict]:
    """The parsed-input set with SHA-256 and size, sorted by name.

    Notes
    -----
    This is the run's source identity. The manifest records it and the
    updater recomputes it on every invocation: any change to any listed file
    forces a reparse, while an unchanged run is never re-read by tshark.
    """
    names = ["frequencies.tsv", "aggregate.tsv", "instrument.json"]
    names += sorted(p.name for p in run_dir.glob("freq-*.pcap"))
    files = []
    for name in names:
        path = run_dir / name
        if not path.is_file():
            continue
        files.append({
            "name": name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return files


def identity_matches(manifest: dict, current_files: list[dict]) -> bool:
    """True when the recorded source identity equals the current one."""
    recorded = {
        f["name"]: (f["sha256"], f["size"])
        for f in manifest.get("source_files", [])
    }
    current = {f["name"]: (f["sha256"], f["size"]) for f in current_files}
    return recorded == current


# =============================================================================
# Core tables (no tshark required)
# =============================================================================


def _read_tsv_dicts(path: Path) -> list[dict[str, str]]:
    """Read a TSV into raw string dicts, preserving source order and cells."""
    import csv

    if not path.is_file():
        raise ExtractionError(f"missing source file: {path.name}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames is None:
            raise ExtractionError(f"unreadable TSV header: {path.name}")
        return [dict(row) for row in reader]


def _int_or_none(value: str | None) -> int | None:
    text = (value or "").strip()
    return int(text) if text else None


def _float_or_none(value: str | None) -> float | None:
    text = (value or "").strip()
    return float(text) if text else None


def frequencies_rows(run_id: str, run_dir: Path) -> list[dict]:
    """One row per source frequencies.tsv row, including empties and skips."""
    rows = []
    for src in _read_tsv_dicts(run_dir / "frequencies.tsv"):
        row = {"run_id": run_id}
        for col in ("band", "regulatory_state", "sample_status", "pcap_file",
                    "error"):
            row[col] = (src.get(col) or "").strip()
        for col in ("frequency_mhz", "channel", "dwell_seconds",
                    "bssid_count", "beacon_count"):
            row[col] = _int_or_none(src.get(col))
        rows.append(row)
    return rows


def observations_rows(run_id: str, run_dir: Path) -> list[dict]:
    """One row per source aggregate.tsv row; no entity consolidation."""
    rows = []
    for src in _read_tsv_dicts(run_dir / "aggregate.tsv"):
        row = {
            "run_id": run_id,
            "band": (src.get("band") or "").strip(),
            "bssid": (src.get("bssid") or "").strip().lower(),
            "ssid": (src.get("ssid") or "").strip(),
            "first_seen": (src.get("first_seen") or "").strip(),
            "last_seen": (src.get("last_seen") or "").strip(),
        }
        for col in ("frequency_mhz", "channel", "beacons",
                    "beacon_interval_tu", "rssi_min_dbm", "rssi_max_dbm"):
            row[col] = _int_or_none(src.get(col))
        for col in ("rssi_mean_dbm", "beacon_reception_ratio"):
            row[col] = _float_or_none(src.get(col))
        rows.append(row)
    return rows


# =============================================================================
# Field resolution
# =============================================================================


def resolve_requested_fields() -> tuple[dict[str, str], dict[str, list[str]]]:
    """Resolve every requested logical field against the installed build.

    Returns (resolved, unresolved) where unresolved maps a logical name to all
    of its failed candidates. Recording the candidates is the point: an
    unresolved name is an extraction-quality finding, not an absence.
    """
    try:
        have = probe.available_fields()
    except OSError:
        # tshark itself is unavailable: nothing resolves, and the manifest
        # records the advanced surfaces as failed rather than empty.
        have = set()
    resolved: dict[str, str] = {}
    unresolved: dict[str, list[str]] = {}
    for logical, candidates in REQUESTED_FIELDS.items():
        hit = next((c for c in candidates if c in have), None)
        if hit:
            resolved[logical] = hit
        else:
            unresolved[logical] = list(candidates)
    return resolved, unresolved


def field_resolution_rows(
    run_id: str,
    resolved: dict[str, str],
    unresolved: dict[str, list[str]],
) -> list[dict]:
    """One row per requested logical field with its resolution state."""
    rows = []
    for logical in sorted(REQUESTED_FIELDS):
        if logical in resolved:
            status, field = "resolved", resolved[logical]
        else:
            status, field = "unresolved", None
        rows.append({
            "run_id": run_id,
            "logical_name": logical,
            "status": status,
            "resolved_field": field,
            "candidates": ",".join(REQUESTED_FIELDS[logical]),
        })
    return rows


# =============================================================================
# tshark extraction: one pass per populated PCAP
# =============================================================================


def _tshark_beacons(
    pcap: Path,
    resolved: dict[str, str],
) -> list[dict[str, str]]:
    """Extract one row per beacon frame with identity and capability cells.

    Notes
    -----
    A single tshark invocation per PCAP carries every needed column. tshark
    joins repeated occurrences with commas, so any capability cell may be
    multi-valued; callers treat commas as "structure unknown", never as a
    positional pairing.
    """
    extracted = [name for name in ENRICH_LOGICALS if name in resolved]
    cmd = ["tshark", "-r", str(pcap), "-Y", probe.BEACON_FILTER,
           "-T", "fields"]
    for logical in extracted:
        cmd += ["-e", resolved[logical]]
    cmd += ["-E", "separator=/t", "-E", "occurrence=a"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise ExtractionError(
            f"tshark failed on {pcap.name}: {out.stderr.strip()[:300]}"
        )
    rows = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        cells = line.split("\t")
        rows.append({
            label: cells[i].strip() if i < len(cells) else ""
            for i, label in enumerate(extracted)
        })
    return rows


def advanced_rows(
    run_id: str,
    run_dir: Path,
    resolved: dict[str, str],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Derive the IE-capability, RNR, and BSS Load tables for one run.

    Returns (ie_rows, rnr_rows, bss_load_rows).
    """
    required = ("frame_number", "frame_time_epoch", "wlan_bssid")
    for logical in required:
        if logical not in resolved:
            raise ExtractionError(
                f"frame identity field {logical} unresolved; refusing to "
                "emit rows without packet identity"
            )

    elements_by_bssid: dict[str, set[int]] = {}
    ext_by_bssid: dict[str, set[int]] = {}
    rnr_rows: list[dict] = []
    bss_rows: list[dict] = []

    rnr_fields = [name for name in ENRICH_LOGICALS
                  if name in RNR_VALUE_FIELDS and name in resolved]
    qbss_fields = [name for name in ENRICH_LOGICALS
                   if name in QBSS_VALUE_FIELDS and name in resolved]

    for pcap in probe.populated_pcaps(run_dir):
        for row in _tshark_beacons(pcap, resolved):
            for logical in required:
                if not row.get(logical):
                    raise ExtractionError(
                        f"{pcap.name}: beacon row missing {logical}; "
                        "packet identity is mandatory"
                    )
            bssid = row["wlan_bssid"].lower()
            tags = _int_set(row.get("tag_number"))
            exts = _int_set(row.get("ext_tag_number"))
            elements_by_bssid.setdefault(bssid, set()).update(tags)
            ext_by_bssid.setdefault(bssid, set()).update(exts)

            if 201 in tags:
                rnr_rows.append(_rnr_record(
                    run_id, pcap.name, row, rnr_fields))
            if 11 in tags:
                bss_rows.append(_bss_load_record(
                    run_id, pcap.name, row, qbss_fields))

    ie_rows = [
        _ie_record(run_id, bssid, elements_by_bssid.get(bssid, set()),
                   ext_by_bssid.get(bssid, set()))
        for bssid in sorted(set(elements_by_bssid) | set(ext_by_bssid))
    ]
    return ie_rows, rnr_rows, bss_rows


def _int_set(cell: str | None) -> set[int]:
    """Parse a comma-joined multi-occurrence integer cell."""
    return {
        int(v) for v in (cell or "").split(",")
        if v.strip().lstrip("-").isdigit()
    }


def _ie_record(
    run_id: str, bssid: str, elements: set[int], exts: set[int]
) -> dict:
    """One capability row per run and observed BSSID.

    Presence is decided from the extension-element namespace, never from
    `wlan.tag.number == 255`: Wireshark does not report extension elements
    there, and gating on it hides every HE/EHT advertisement.
    """
    return {
        "run_id": run_id,
        "bssid": bssid,
        "elements": ",".join(str(e) for e in sorted(elements)),
        "ext_elements": ",".join(str(e) for e in sorted(exts)),
        "has_ht": 45 in elements,
        "has_vht": 191 in elements,
        "has_he": bool(exts & {35, 36}),
        "has_he_6ghz": 59 in exts,
        "has_eht": bool(exts & {106, 108}),
        "has_mld": 107 in exts,
        "has_multiple_bssid": 71 in elements,
        "has_rnr": 201 in elements,
        "has_bss_load": 11 in elements,
        "has_rsn": 48 in elements,
        "has_extended_capabilities": 127 in elements,
    }


def _canonical_mac(value: str) -> str:
    """Normalize a MAC to colon-separated lowercase, when hex-only.

    Notes
    -----
    tshark emits byte fields like the RNR neighbor BSSID as bare hex, while
    the collector writes address 1 with colons. Advertised-versus-observed
    comparisons are only valid when both sides share one spelling.
    """
    compact = value.replace(":", "").replace("-", "").lower()
    if len(compact) == 12 and all(c in "0123456789abcdef" for c in compact):
        return ":".join(compact[i:i + 2] for i in range(0, 12, 2))
    return value


def _rnr_record(
    run_id: str,
    pcap_name: str,
    row: dict[str, str],
    rnr_fields: list[str],
) -> dict:
    """One frame-grain RNR record.

    Notes
    -----
    Multi-occurrence frames stay ambiguous: every value cell keeps its raw
    comma-joined form and `structure_status` says so. Only a frame whose RNR
    fields are all single-valued may carry the normalized target band and
    frequency, because only then is the pairing between operating class and
    channel actually known.
    """
    record: dict = {
        "run_id": run_id,
        "pcap_file": pcap_name,
        "frame_number": int(row["frame_number"]),
        "frame_time_epoch": row["frame_time_epoch"],
        "tx_bssid": row["wlan_bssid"].lower(),
        "tx_ssid": probe.decode_ssid(row.get("wlan_ssid", "")),
        "op_class": None,
        "channel": None,
        "neighbor_bssid": None,
        "short_ssid": None,
        "bss_params": None,
        "mld_link_id": None,
        "mld_id": None,
        "disabled_link": None,
    }
    raw_values: dict[str, str] = {}
    for key, column in (
        ("rnr_op_class", "op_class"),
        ("rnr_channel", "channel"),
        ("rnr_bssid", "neighbor_bssid"),
        ("rnr_short_ssid", "short_ssid"),
        ("rnr_bss_params", "bss_params"),
        ("rnr_mld_link_id", "mld_link_id"),
        ("rnr_mld_id", "mld_id"),
        ("rnr_disabled_link", "disabled_link"),
    ):
        raw = (row.get(key) or "").strip()
        raw_values[key] = raw
        # The scalar column keeps the first occurrence only for convenience;
        # the raw_* column preserves the verbatim comma-joined cell, and the
        # structure status flags the whole record as ambiguous when any cell
        # was multi-valued. Nothing is ever paired positionally.
        record[f"raw_{column}"] = raw or None
        value = raw.split(",")[0].strip() or None if raw else None
        if column == "neighbor_bssid" and value:
            value = _canonical_mac(value)
        record[column] = value
    repeated = [key for key in rnr_fields if "," in raw_values.get(key, "")]
    record["structure_status"] = (
        "unpaired_multi_occurrence" if repeated else "single_occurrence"
    )
    record["unpaired_fields"] = ",".join(repeated) or None
    record["field_resolution_state"] = (
        "resolved" if rnr_fields else "unresolved_candidates"
    )
    record["target_band"] = None
    record["target_frequency_mhz"] = None
    if record["structure_status"] == "single_occurrence":
        op_class = record["op_class"]
        channel = record["channel"]
        if op_class and channel and op_class.isdigit() and channel.isdigit():
            band, freq = probe.opclass_to_freq(int(op_class), int(channel))
            record["target_band"] = band
            record["target_frequency_mhz"] = freq
    return record


def _bss_load_record(
    run_id: str,
    pcap_name: str,
    row: dict[str, str],
    qbss_fields: list[str],
) -> dict:
    """One frame-grain BSS Load record with mandatory packet identity."""
    record: dict = {
        "run_id": run_id,
        "pcap_file": pcap_name,
        "frame_number": int(row["frame_number"]),
        "frame_time_epoch": row["frame_time_epoch"],
        "bssid": row["wlan_bssid"].lower(),
        "ssid": probe.decode_ssid(row.get("wlan_ssid", "")),
    }
    for logical, key in (("station_count", "qbss_station_count"),
                         ("utilization", "qbss_utilization"),
                         ("admission_capacity", "qbss_admission")):
        raw = (row.get(key) or "").strip()
        # A frame carries one BSS Load element under one namespace; the first
        # non-empty candidate cell is that element's value. A repeated cell
        # would mean several BSS Load elements in one frame, which the raw
        # column preserves verbatim rather than silently reducing.
        first = raw.split(",")[0].strip() if raw else ""
        record[f"raw_{logical}"] = raw or None
        record[logical] = _int_or_none(first)
    return record


# =============================================================================
# Parquet emission
# =============================================================================
# Column types are declared per table, never inferred from data: an all-null
# column must keep its declared type so a sparse frequency or capability
# cannot change the shape of the derived layer between runs.

_STRING_COLUMNS: dict[str, set[str]] = {
    "run": {"run_id", "source_path", "classification", "attempt_state",
            "run_status",
            "started_utc", "extraction_status", "error",
            "derived_schema_id", "extractor_version", "tshark_version"},
    "frequencies": {"run_id", "band", "regulatory_state", "sample_status",
                    "pcap_file", "error"},
    "observations": {"run_id", "band", "bssid", "ssid", "first_seen",
                     "last_seen"},
    "ie_capabilities": {"run_id", "bssid", "elements", "ext_elements"},
    "rnr": {"run_id", "pcap_file", "frame_time_epoch", "tx_bssid",
            "tx_ssid", "op_class", "channel", "neighbor_bssid",
            "short_ssid", "bss_params", "mld_link_id",
            "mld_id", "disabled_link", "target_band",
            "structure_status", "unpaired_fields",
            "field_resolution_state",
            "raw_op_class", "raw_channel", "raw_neighbor_bssid",
            "raw_short_ssid", "raw_bss_params", "raw_mld_link_id",
            "raw_mld_id", "raw_disabled_link"},
    "bss_load": {"run_id", "pcap_file", "frame_time_epoch", "bssid",
                 "ssid", "raw_station_count", "raw_utilization",
                 "raw_admission_capacity"},
    "field_resolution": {"run_id", "logical_name", "status",
                         "resolved_field", "candidates"},
}

_INT_COLUMNS: dict[str, set[str]] = {
    "frequencies": {"frequency_mhz", "channel", "dwell_seconds",
                    "bssid_count", "beacon_count"},
    "observations": {"frequency_mhz", "channel", "beacons",
                     "beacon_interval_tu", "rssi_min_dbm", "rssi_max_dbm"},
    "rnr": {"frame_number", "target_frequency_mhz"},
    "bss_load": {"frame_number", "station_count", "utilization",
                 "admission_capacity"},
}

_FLOAT_COLUMNS: dict[str, set[str]] = {
    "observations": {"rssi_mean_dbm", "beacon_reception_ratio"},
}

_BOOL_COLUMNS: dict[str, set[str]] = {
    "run": {"eligible", "input_complete"},
    "ie_capabilities": {"has_ht", "has_vht", "has_he", "has_he_6ghz",
                        "has_eht", "has_mld", "has_multiple_bssid",
                        "has_rnr", "has_bss_load", "has_rsn",
                        "has_extended_capabilities"},
}


def table_schema(table: str) -> pa.Schema:
    """Build the explicit Arrow schema for one contract table."""
    fields = []
    for column in pilot.TABLES[table]:
        if column in _STRING_COLUMNS.get(table, set()):
            typ = pa.string()
        elif column in _BOOL_COLUMNS.get(table, set()):
            typ = pa.bool_()
        elif column in _FLOAT_COLUMNS.get(table, set()):
            typ = pa.float64()
        elif column in _INT_COLUMNS.get(table, set()):
            typ = pa.int64()
        else:
            raise ExtractionError(
                f"{table}.{column} has no declared type; extend the schema "
                "map rather than letting Arrow infer it"
            )
        fields.append(pa.field(column, typ, nullable=True))
    return pa.schema(fields)


def write_table(out_dir: Path, name: str, rows: list[dict]) -> dict:
    """Write one Parquet artifact and return its manifest entry."""
    table_name = name.removesuffix(".parquet")
    schema = table_schema(table_name)
    columns = list(pilot.TABLES[table_name])
    arrays = [
        pa.array([row.get(col) for row in rows],
                 type=schema.field(col).type)
        for col in columns
    ]
    path = out_dir / name
    pq.write_table(pa.Table.from_arrays(arrays, schema=schema), path)
    return {
        "name": name,
        "rows": len(rows),
        "sha256": sha256_file(path),
    }


# =============================================================================
# Run-level manifest
# =============================================================================


@dataclasses.dataclass
class EnrichResult:
    """Outcome of one enrichment invocation, consumed by the updater."""

    run_id: str
    status: str  # "succeeded" | "partial" | "failed"
    manifest: dict | None
    error: str | None = None


def write_manifest(out_dir: Path, manifest: dict) -> None:
    """Write manifest.json atomically: temp file, then rename.

    The manifest is the completion marker. A reader must never observe a
    half-written one, so the rename is the very last step of a derivation.
    """
    tmp = out_dir / (pilot.MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, out_dir / pilot.MANIFEST_NAME)


def read_manifest(out_dir: Path) -> dict | None:
    """Read an existing manifest, or None when absent or unparseable."""
    path = out_dir / pilot.MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def outputs_intact(out_dir: Path, manifest: dict) -> bool:
    """True when every recorded output exists with its recorded hash."""
    for entry in manifest.get("outputs", []):
        path = out_dir / entry["name"]
        if not path.is_file():
            return False
        if sha256_file(path) != entry.get("sha256"):
            return False
    return True


def enrich_run(
    run_dir: Path,
    out_dir: Path,
    classification,
    *,
    resolved: dict[str, str],
    unresolved: dict[str, list[str]],
    tshark_version: str,
) -> EnrichResult:
    """Enrich one classified run into `out_dir`.

    The flow is staged so a failure in the advanced (tshark) surfaces cannot
    take core collection health down with it: run/frequency/observation
    tables come from the source TSVs alone, advanced tables come from tshark,
    and the manifest -- which records exactly what succeeded -- is written
    last. A partial manifest is still a failure record: only `succeeded` is
    authoritative for the advanced surfaces.
    """
    from datetime import datetime, timezone

    run_id = classification.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    # Stage A: core tables from the source TSVs. No tshark involved.
    core_ok = True
    freq_rows: list[dict] = []
    obs_rows: list[dict] = []
    try:
        freq_rows = frequencies_rows(run_id, run_dir)
        obs_rows = observations_rows(run_id, run_dir)
    except Exception as exc:  # noqa: BLE001 - recorded, never raised past here
        core_ok = False
        errors.append(f"core tables: {exc}")

    # Stage B: advanced surfaces via tshark. Runs whose source carries no
    # populated capture (skips, failed runs) legitimately produce empty
    # advanced tables; that is a recorded zero, not an unresolved field.
    adv_ok = True
    ie_rows: list[dict] = []
    rnr_rows: list[dict] = []
    bss_rows: list[dict] = []
    if resolved:
        try:
            ie_rows, rnr_rows, bss_rows = advanced_rows(
                run_id, run_dir, resolved)
        except Exception as exc:  # noqa: BLE001
            adv_ok = False
            errors.append(f"advanced tables: {exc}")
    else:
        adv_ok = False
        errors.append(
            "advanced tables: no requested tshark fields resolved on this "
            "build; nothing was queried"
        )

    if not core_ok:
        status = "failed"
    elif not adv_ok:
        status = "partial"
    else:
        status = "succeeded"

    run_row = {
        "run_id": run_id,
        "source_path": str(run_dir),
        "classification": classification.membership.value,
        "attempt_state": (classification.attempt_state.value
                          if classification.attempt_state else None),
        "run_status": classification.run_status,
        "started_utc": classification.started_utc,
        "eligible": classification.eligible,
        "input_complete": classification.input_complete,
        "extraction_status": status,
        "error": "; ".join(errors) or None,
        "derived_schema_id": pilot.DERIVED_SCHEMA_ID,
        "extractor_version": pilot.EXTRACTOR_VERSION,
        "tshark_version": tshark_version,
    }

    try:
        outputs = [
            write_table(out_dir, "run.parquet", [run_row]),
            write_table(out_dir, "frequencies.parquet", freq_rows),
            write_table(out_dir, "observations.parquet", obs_rows),
            write_table(out_dir, "ie_capabilities.parquet", ie_rows),
            write_table(out_dir, "rnr.parquet", rnr_rows),
            write_table(out_dir, "bss_load.parquet", bss_rows),
            write_table(out_dir, "field_resolution.parquet",
                        field_resolution_rows(run_id, resolved, unresolved)),
        ]
    except Exception as exc:  # noqa: BLE001
        return EnrichResult(
            run_id=run_id, status="failed", manifest=None,
            error=f"artifact write: {exc}",
        )

    manifest = {
        "schema_id": pilot.DERIVED_SCHEMA_ID,
        "derived_version": pilot.DERIVED_VERSION,
        "extractor_version": pilot.EXTRACTOR_VERSION,
        "tshark_version": tshark_version,
        "run_id": run_id,
        "source_path": str(run_dir),
        "classification": {
            "membership": classification.membership.value,
            "attempt_state": (classification.attempt_state.value
                              if classification.attempt_state else None),
            "run_status": classification.run_status,
            "started_utc": classification.started_utc,
            "eligible": classification.eligible,
            "input_complete": classification.input_complete,
        },
        "status": status,
        "errors": errors,
        "source_files": source_files(run_dir),
        "outputs": outputs,
        "manifest_written_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
    }
    write_manifest(out_dir, manifest)
    return EnrichResult(run_id=run_id, status=status, manifest=manifest)


def needs_reprocess(
    out_dir: Path,
    current_files: list[dict],
    expected_schema: str = pilot.DERIVED_SCHEMA_ID,
    expected_extractor: str = pilot.EXTRACTOR_VERSION,
) -> tuple[bool, str]:
    """Decide whether a run must be (re)processed, and why.

    An unchanged successful run is recognized from source identity and output
    integrity; a new or changed input, a version bump, or a damaged output
    forces a reparse. Partial derivations are also retried: the missing
    advanced surfaces may resolve after an environment fix.
    """
    manifest = read_manifest(out_dir)
    if manifest is None:
        return True, "no derivation manifest"
    if manifest.get("status") not in ("succeeded", "partial"):
        return True, "prior derivation failed"
    if manifest.get("schema_id") != expected_schema:
        return True, "derived schema changed"
    if manifest.get("extractor_version") != expected_extractor:
        return True, "extractor version changed"
    if not identity_matches(manifest, current_files):
        return True, "source identity changed"
    if not outputs_intact(out_dir, manifest):
        return True, "derived outputs no longer match the manifest"
    return False, "unchanged"


def main() -> None:
    """Enrich one run directory directly (diagnostic path)."""
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <run_dir> <out_dir>")
    run_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    classification = pilot.classify_pilot_child(run_dir)
    if not classification.eligible:
        sys.exit(f"{run_dir} is not an eligible pilot attempt")
    resolved, unresolved = resolve_requested_fields()
    try:
        version = probe.tshark_version()
    except OSError:
        version = "unavailable"
    result = enrich_run(
        run_dir, out_dir, classification,
        resolved=resolved, unresolved=unresolved,
        tshark_version=version,
    )
    print(f"{result.run_id}: {result.status}")
    if result.error:
        print(f"  {result.error}")
    for error in (result.manifest or {}).get("errors", []):
        print(f"  {error}")


if __name__ == "__main__":
    main()
