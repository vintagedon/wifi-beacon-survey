#!/usr/bin/env python3
"""
Script Name  : ingest_contract.py
Description  : Machine form of docs/ingestion-contract.md: source headers,
               column mappings, and type converters for the loader
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-09-29
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
This module is the single source of truth for how the collector's three
per-run files map into the wifi_beacon_survey base tables: the exact expected
TSV headers, the flattened instrument.json key-to-column mapping, and the
type converters for every column. The loader (ingest_load.py) and the tests
both import from here, so a header that drifts from the contract fails
validation instead of silently changing the projection.

Nothing here touches a database or a file; it is pure contract.

Usage
-----
    Imported as a module by ingest_load.py and the tests under tests/.
"""

from __future__ import annotations

from datetime import datetime, timezone

# =============================================================================
# Series identity
# =============================================================================

# The approved hourly-series beginning (run 20260827-090003). Expected UTC
# slots run from this hour through the last fully elapsed UTC hour. The two
# commissioning runs predate it and are excluded by the same rule.
SERIES_START_UTC = datetime(2026, 8, 27, 13, 0, 0, tzinfo=timezone.utc)

# The standing declared regulatory domain. Routing never consults the host's
# current domain; only what a run recorded about itself counts.
DECLARED_DOMAIN = "US"

# =============================================================================
# Exact source headers, frozen by the ingestion contract
# =============================================================================

FREQUENCY_HEADER = (
    "band\tfrequency_mhz\tchannel\tregulatory_state\tsample_status\t"
    "dwell_seconds\tpcap_file\tbssid_count\tbeacon_count\terror"
)
OBSERVATION_HEADER = (
    "band\tfrequency_mhz\tchannel\tbssid\tssid\tbeacons\tbeacon_interval_tu\t"
    "rssi_min_dbm\trssi_mean_dbm\trssi_max_dbm\tfirst_seen\tlast_seen\t"
    "beacon_reception_ratio"
)

# =============================================================================
# instrument.json key mapping
# =============================================================================
# Top-level keys map directly; nested usb.* and capture.* keys flatten with a
# prefix. The raw document is always stored as jsonb alongside. An
# instrument.json carrying a key absent from this mapping fails validation:
# the contract must be extended deliberately, not silently.

RUNS_TEXT_KEYS = (
    "schema",
    "run_status",
    "skip_reason",
    "interface",
    "phy",
    "regulatory_domain",
    "regulatory_domain_phy",
    "regulatory_domain_declared",
    "regulatory_domain_set_result",
    "regulatory_domain_at_discovery",
    "regulatory_domain_post_sweep",
)
RUNS_TEXT_TO_COLUMN = {
    "schema": "instrument_schema",
    "run_status": "run_status",
    "skip_reason": "skip_reason",
    "interface": "interface",
    "phy": "phy",
    "regulatory_domain": "regulatory_domain",
    "regulatory_domain_phy": "regulatory_domain_phy",
    "regulatory_domain_declared": "regulatory_domain_declared",
    "regulatory_domain_set_result": "regulatory_domain_set_result",
    "regulatory_domain_at_discovery": "regulatory_domain_at_discovery",
    "regulatory_domain_post_sweep": "regulatory_domain_post_sweep",
}

RUNS_BOOL_KEYS = ("interface_present", "regulatory_domain_set_attempted")

RUNS_TS_KEYS = ("started_utc",)

RUNS_NESTED_TEXT = {
    "usb": ("bus", "port", "device", "controller_pci", "driver"),
    "capture": ("bands", "bpf_filter"),
}
RUNS_NESTED_TEXT_TO_COLUMN = {
    ("usb", "bus"): "usb_bus",
    ("usb", "port"): "usb_port",
    ("usb", "device"): "usb_device",
    ("usb", "controller_pci"): "usb_controller_pci",
    ("usb", "driver"): "usb_driver",
    ("capture", "bands"): "capture_bands",
    ("capture", "bpf_filter"): "capture_bpf_filter",
}
RUNS_NESTED_INT = {
    ("usb", "speed_mbps"): "usb_speed_mbps",
    ("capture", "dwell_seconds"): "capture_dwell_seconds",
    ("capture", "snaplen"): "capture_snaplen",
}

RUNS_FLAT_KEYS = frozenset(
    RUNS_TEXT_KEYS + RUNS_BOOL_KEYS + RUNS_TS_KEYS
)


def runs_documented_keys() -> set[str]:
    """Every instrument.json key the contract maps to a runs column."""
    return set(RUNS_FLAT_KEYS) | {
        f"{section}.{field}"
        for section, fields in RUNS_NESTED_TEXT.items()
        for field in fields
    } | {f"{s}.{f}" for (s, f) in RUNS_NESTED_INT}


# =============================================================================
# TSV column contracts: name, converter, nullable
# =============================================================================

CONV_TEXT = "text"
CONV_INT = "int"
CONV_NUMERIC = "numeric"
CONV_TS = "timestamptz"

FREQUENCY_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    # (source column, converter, nullable) - order matches the header.
    ("band", CONV_TEXT, False),
    ("frequency_mhz", CONV_INT, False),
    ("channel", CONV_INT, False),
    ("regulatory_state", CONV_TEXT, False),
    ("sample_status", CONV_TEXT, False),
    ("dwell_seconds", CONV_INT, False),
    ("pcap_file", CONV_TEXT, True),
    ("bssid_count", CONV_INT, True),
    ("beacon_count", CONV_INT, True),
    ("error", CONV_TEXT, True),
)

OBSERVATION_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    # ssid is NOT NULL in the database: an empty source SSID is a hidden
    # network and stays an empty string, never null (pilot contract, s.3).
    ("band", CONV_TEXT, False),
    ("frequency_mhz", CONV_INT, False),
    ("channel", CONV_INT, False),
    ("bssid", CONV_TEXT, False),
    ("ssid", "ssid", False),
    ("beacons", CONV_INT, False),
    ("beacon_interval_tu", CONV_INT, True),
    ("rssi_min_dbm", CONV_NUMERIC, True),
    ("rssi_mean_dbm", CONV_NUMERIC, True),
    ("rssi_max_dbm", CONV_NUMERIC, True),
    ("first_seen", CONV_TS, True),
    ("last_seen", CONV_TS, True),
    ("beacon_reception_ratio", CONV_NUMERIC, True),
)


class ContractError(ValueError):
    """A source file violates the ingestion contract."""


def convert_value(raw: str | None, converter: str, nullable: bool) -> object:
    """Convert one source cell to its declared type.

    An empty cell is null for nullable columns. The ssid converter keeps the
    empty string (a hidden network is an empty SSID, never null). A value
    that will not parse raises ContractError: the attempt is malformed, never
    silently coerced.
    """
    if raw is None or raw == "":
        if converter == "ssid":
            return ""
        if nullable:
            return None
        raise ContractError(f"empty value for non-nullable column ({converter})")
    try:
        if converter == CONV_TEXT or converter == "ssid":
            return raw
        if converter == CONV_INT:
            return int(raw)
        if converter == CONV_NUMERIC:
            return float(raw)
        if converter == CONV_TS:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ContractError(
            f"value {raw!r} does not parse as {converter}"
        ) from exc
    raise ContractError(f"unknown converter {converter!r}")


def validate_headers(
    frequencies_header: str, observations_header: str
) -> None:
    """Headers must match the contract exactly, or the attempt is malformed."""
    if frequencies_header != FREQUENCY_HEADER:
        raise ContractError(
            "frequencies.tsv header does not match the contract: "
            f"got {frequencies_header!r}"
        )
    if observations_header != OBSERVATION_HEADER:
        raise ContractError(
            "aggregate.tsv header does not match the contract: "
            f"got {observations_header!r}"
        )
