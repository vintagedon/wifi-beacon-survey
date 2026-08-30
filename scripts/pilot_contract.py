#!/usr/bin/env python3
"""
Script Name  : pilot_contract.py
Description  : Single-source contract for the pilot series: eligibility, attempt
               states, expected hourly slots, and the version 1 derived schema
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-08-28
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
This module is the machine-enforced form of `docs/pilot-analysis-contract.md`.
Every producer and consumer of pilot-derived data -- the enrichment stage, the
DuckDB builder, the Markdown briefing, and the test suite -- imports series
boundaries, classification rules, and table schemas from here. Nothing else in
the repository may restate eligibility logic, because two independent
implementations of "which runs count" is exactly how a commissioning run ends
up inside a trend.

The contract is provisional by design: it defines a derived analytical surface
that can be regenerated from retained evidence at any time. It is not the
PostgreSQL schema, and nothing here carries adoption language.

All functions are pure with injectable clocks, so tests can exercise synthetic
series without touching the live pilot tree.

Usage
-----
    Imported as a module by pilot_enrich.py, pilot_database.py,
    pilot_report.py, pilot-update.py, and the tests under tests/.

    python3 pilot_contract.py <pilot_dir>
        Print the live inventory classification (diagnostic aid, not the report)
"""

from __future__ import annotations

import dataclasses
import enum
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# =============================================================================
# Configuration
# =============================================================================

# Default locations. Every path is overridable at the CLI layer so tests never
# write into the live pilot tree or the canonical report.
DATA_ROOT_DEFAULT = Path("/opt/agents/repos/storage-mounted/wifi-beacon-survey")
PILOT_DIR_DEFAULT = DATA_ROOT_DEFAULT / "pilot"
DERIVED_ROOT_DEFAULT = DATA_ROOT_DEFAULT / "derived"
REPORTS_DIR_DEFAULT = DATA_ROOT_DEFAULT / "reports"

# Frozen semantic contract. These values are approved decisions, not executor
# choices; a defect in one is reported as a spec defect rather than redesigned.
PILOT_SERIES_START = "20260827-090003"
COMMISSIONING_RUNS: tuple[str, ...] = ("20260827-054734", "20260827-060013")
DERIVED_SCHEMA_ID = "wifi-beacon-survey/pilot-derived/1"
DERIVED_VERSION = "v1"
EXTRACTOR_VERSION = "pilot-enrich/1"

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}$")

# Per-run derived artifacts live at <derived_root>/pilot/<version>/runs/<run-id>/.
def derived_runs_root(derived_root: Path = DERIVED_ROOT_DEFAULT) -> Path:
    """Versioned per-run derived root for the current schema version."""
    return derived_root / "pilot" / DERIVED_VERSION / "runs"


def derived_db_path(derived_root: Path = DERIVED_ROOT_DEFAULT) -> Path:
    """Persistent DuckDB analytical projection."""
    return derived_root / "pilot.duckdb"


def canonical_report_path(reports_dir: Path = REPORTS_DIR_DEFAULT) -> Path:
    """Canonical generated briefing."""
    return reports_dir / "pilot-latest.md"


# The stable DuckDB view names this contract requires. The database builder and
# the report both assert against this tuple so a renamed view fails loudly.
VIEW_NAMES: tuple[str, ...] = (
    "pilot_runs",
    "pilot_frequencies",
    "pilot_observations",
    "pilot_ie_capabilities",
    "pilot_rnr",
    "pilot_bss_load",
    "pilot_field_resolution",
    "pilot_run_health",
    "pilot_hourly_metrics",
    "pilot_band_metrics",
    "pilot_capability_metrics",
    "pilot_6ghz_evidence",
)

# Required briefing sections, in required order. The report renderer asserts
# its own output against this tuple.
REPORT_SECTIONS: tuple[str, ...] = (
    "Scope and cutoff",
    "Collection health",
    "Coverage",
    "Longitudinal snapshot",
    "Capability advertisements",
    "RNR and 6 GHz evidence",
    "BSS Load",
    "Data-quality findings",
    "Commissioning reference",
    "Provenance",
)

# =============================================================================
# Derived table schemas
# =============================================================================
# One definition per derived artifact: column name to logical type. The
# enrichment stage writes these columns in this order, the DuckDB builder
# declares these types, and the tests assert both against this module. Logical
# types: "string", "int", "float", "bool". Nullable columns are marked in the
# NULLABLE set per table.

TABLES: dict[str, tuple[str, ...]] = {
    "run": (
        "run_id", "source_path", "classification", "attempt_state",
        "run_status", "started_utc", "eligible", "input_complete",
        "extraction_status", "error",
        "derived_schema_id", "extractor_version", "tshark_version",
    ),
    "frequencies": (
        "run_id", "band", "frequency_mhz", "channel", "regulatory_state",
        "sample_status", "dwell_seconds", "pcap_file", "bssid_count",
        "beacon_count", "error",
    ),
    "observations": (
        "run_id", "band", "frequency_mhz", "channel", "bssid", "ssid",
        "beacons", "beacon_interval_tu", "rssi_min_dbm", "rssi_mean_dbm",
        "rssi_max_dbm", "first_seen", "last_seen", "beacon_reception_ratio",
    ),
    "ie_capabilities": (
        "run_id", "bssid", "elements", "ext_elements",
        "has_ht", "has_vht", "has_he", "has_he_6ghz", "has_eht", "has_mld",
        "has_multiple_bssid", "has_rnr", "has_bss_load", "has_rsn",
        "has_extended_capabilities",
    ),
    "rnr": (
        "run_id", "pcap_file", "frame_number", "frame_time_epoch",
        "tx_bssid", "tx_ssid", "op_class", "channel", "neighbor_bssid",
        "short_ssid", "bss_params", "mld_link_id", "mld_id", "disabled_link",
        "target_band", "target_frequency_mhz", "structure_status",
        "unpaired_fields", "field_resolution_state",
        "raw_op_class", "raw_channel", "raw_neighbor_bssid", "raw_short_ssid",
        "raw_bss_params", "raw_mld_link_id", "raw_mld_id", "raw_disabled_link",
    ),
    "bss_load": (
        "run_id", "pcap_file", "frame_number", "frame_time_epoch", "bssid",
        "ssid", "station_count", "utilization", "admission_capacity",
        "raw_station_count", "raw_utilization", "raw_admission_capacity",
    ),
    "field_resolution": (
        "run_id", "logical_name", "status", "resolved_field", "candidates",
    ),
}

TABLE_NULLABLE: dict[str, set[str]] = {
    "run": {"run_status", "started_utc", "error"},
    "frequencies": {"error"},
    "observations": {
        "ssid", "beacon_interval_tu", "rssi_min_dbm", "rssi_mean_dbm",
        "rssi_max_dbm", "beacon_reception_ratio",
    },
    "ie_capabilities": set(),
    "rnr": {
        "tx_ssid", "op_class", "channel", "neighbor_bssid", "short_ssid",
        "bss_params", "mld_link_id", "mld_id", "disabled_link",
        "target_band", "target_frequency_mhz", "unpaired_fields",
    },
    "bss_load": {"ssid", "station_count", "utilization", "admission_capacity"},
    "field_resolution": {"resolved_field"},
}

# Manifest file names inside a per-run derived directory. The contract document
# maps the logical artifacts to these names; renaming one is a contract change.
MANIFEST_NAME = "manifest.json"

# =============================================================================
# Series membership and attempt states
# =============================================================================


class Membership(str, enum.Enum):
    """Why a pilot-tree child is or is not part of the pilot series."""

    COMMISSIONING = "commissioning_reference"
    PILOT = "pilot_series"
    OUTSIDE = "outside_series"


class AttemptState(str, enum.Enum):
    """Collection-health state of one pilot-series attempt.

    These are deliberately distinct: a skip is not a failure, a malformed run
    is not an empty sweep, and an absent hour is not any kind of run. Folding
    any two of these together would corrupt the downtime and failure counts
    the briefing reports.
    """

    COMPLETED_SWEEP = "completed_sweep"
    SKIPPED_NO_INTERFACE = "skipped_no_interface"
    FAILED = "failed"
    RUNNING = "running"
    MALFORMED = "malformed"
    MISSING_SLOT = "missing_hourly_slot"


@dataclasses.dataclass(frozen=True)
class RunClassification:
    """One classified child of the pilot tree."""

    run_id: str
    path: Path
    membership: Membership
    reason: str
    attempt_state: AttemptState | None = None
    run_status: str | None = None
    started_utc: str | None = None
    input_complete: bool = False

    @property
    def eligible(self) -> bool:
        """Eligible attempts are pilot-series members regardless of state.

        A failed or malformed attempt stays in the series and in every
        collection-health count; exclusion from health is how outages hide.
        """
        return self.membership is Membership.PILOT


def _read_instrument(run_dir: Path) -> dict | None:
    """Read instrument.json, returning None when absent or unparseable."""
    path = run_dir / "instrument.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _tsv_parsable(run_dir: Path, name: str) -> bool:
    """True when the named TSV exists and carries its header line."""
    path = run_dir / name
    if not path.is_file():
        return False
    try:
        first = path.read_text(encoding="utf-8").splitlines()[:1]
    except OSError:
        return False
    return bool(first) and first[0].strip() != ""


def classify_pilot_child(
    path: Path,
    series_start: str = PILOT_SERIES_START,
    commissioning: tuple[str, ...] = COMMISSIONING_RUNS,
) -> RunClassification:
    """Assign exactly one membership and one attempt state to a pilot child.

    Notes
    -----
    The decision order matters. Commissioning names win first so the two
    pre-instrument sweeps classify as reference runs even though they carry no
    instrument.json. The series-start comparison is a plain string compare,
    which is exact for the fixed-width run-id format.
    """
    name = path.name
    if not RUN_ID_RE.match(name):
        return RunClassification(
            run_id=name, path=path, membership=Membership.OUTSIDE,
            reason="directory name is not a run timestamp",
        )
    if not path.is_dir():
        return RunClassification(
            run_id=name, path=path, membership=Membership.OUTSIDE,
            reason="not a directory",
        )
    if name in commissioning:
        return RunClassification(
            run_id=name, path=path, membership=Membership.COMMISSIONING,
            reason="named commissioning/reference run; predates instrument.json "
                   "and the approved series start",
        )
    if name < series_start:
        return RunClassification(
            run_id=name, path=path, membership=Membership.OUTSIDE,
            reason=f"predates the approved series start {series_start} and is "
                   "not a named commissioning run",
        )

    # Pilot-series member: state comes from instrument.json plus file evidence.
    instrument = _read_instrument(path)
    if instrument is None:
        return RunClassification(
            run_id=name, path=path, membership=Membership.PILOT,
            attempt_state=AttemptState.MALFORMED,
            reason="instrument.json missing or unreadable",
        )
    status = instrument.get("run_status")
    started = instrument.get("started_utc")
    if status == "running":
        state, reason, complete = (
            AttemptState.RUNNING, "run in progress at last instrument write",
            False,
        )
    elif status == "skipped_no_interface":
        complete = _tsv_parsable(path, "frequencies.tsv") and \
            _tsv_parsable(path, "aggregate.tsv")
        state, reason = AttemptState.SKIPPED_NO_INTERFACE, (
            "receiver absent at run start; skip record written"
            if complete else
            "receiver absent but skip record incomplete"
        )
    elif status == "failed":
        state, reason, complete = (
            AttemptState.FAILED,
            "collector exited before completing the sweep", False,
        )
    elif status == "sweep":
        complete = _tsv_parsable(path, "frequencies.tsv") and \
            _tsv_parsable(path, "aggregate.tsv")
        if complete:
            state, reason = (
                AttemptState.COMPLETED_SWEEP,
                "instrument records a completed sweep with parseable manifest "
                "and aggregate",
            )
        else:
            state, reason = (
                AttemptState.MALFORMED,
                "run_status=sweep but frequencies.tsv or aggregate.tsv is "
                "missing or unreadable",
            )
    else:
        state, reason, complete = (
            AttemptState.MALFORMED,
            f"unknown run_status {status!r}", False,
        )
    return RunClassification(
        run_id=name, path=path, membership=Membership.PILOT,
        attempt_state=state, reason=reason, run_status=status,
        started_utc=started, input_complete=complete,
    )


def inventory_pilot(
    pilot_dir: Path,
    series_start: str = PILOT_SERIES_START,
    commissioning: tuple[str, ...] = COMMISSIONING_RUNS,
) -> list[RunClassification]:
    """Classify every direct child of the pilot tree, sorted by run id."""
    if not pilot_dir.is_dir():
        raise FileNotFoundError(f"pilot tree not found: {pilot_dir}")
    return sorted(
        (classify_pilot_child(p, series_start, commissioning)
         for p in pilot_dir.iterdir()),
        key=lambda c: c.run_id,
    )


# =============================================================================
# Expected hourly slots and run health
# =============================================================================


def parse_run_hour(run_id: str) -> datetime:
    """Parse a run id into the naive local hour it occupies.

    Notes
    -----
    Run ids are written by the collector in host-local time (`date
    '+%Y%m%d-%H%M%S'`), so slot identity is local wall-clock hours. This is a
    known DST-facing limitation, documented in the contract: a fall-back hour
    would produce two attempts mapping to one slot id. The pilot window has no
    DST transition.
    """
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"not a run id: {run_id!r}")
    return datetime.strptime(run_id, "%Y%m%d-%H%M%S").replace(
        minute=0, second=0
    )


def slot_of(run_id: str) -> str:
    """The expected-slot id a run id occupies: its local wall-clock hour."""
    return parse_run_hour(run_id).strftime("%Y%m%d-%H") + "0000"


def expected_slots(
    series_start: str = PILOT_SERIES_START,
    now: datetime | None = None,
) -> list[str]:
    """Hourly slot ids from the approved series start through the last
    elapsed local hour boundary.

    Notes
    -----
    The ceiling is the most recent elapsed hour, never the wall clock itself:
    inventing slots for the partially elapsed current hour would report the
    instrument as missing while it is mid-collection.
    """
    now = now or datetime.now()
    start_hour = parse_run_hour(series_start)
    ceiling = now.replace(minute=0, second=0, microsecond=0)
    if ceiling < start_hour:
        return []
    slots: list[str] = []
    slot = start_hour
    while slot <= ceiling:
        slots.append(slot.strftime("%Y%m%d-%H") + "0000")
        slot += timedelta(hours=1)
    return slots


@dataclasses.dataclass(frozen=True)
class HealthRow:
    """One row of collection health: either a discovered attempt or an
    absent hour."""

    run_id: str
    state: AttemptState
    eligible: bool
    in_trend: bool
    reason: str
    started_utc: str | None = None
    input_complete: bool = False

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def build_run_health(
    inventory: list[RunClassification],
    slots: list[str],
) -> list[HealthRow]:
    """Reconcile discovered attempts against expected hourly slots.

    Notes
    -----
    Every pilot-series member produces a health row whatever its state, and
    every expected slot with no attempt in it produces a missing-hour row.
    Commissioning runs appear here flagged out of every trend denominator so
    they stay visible without contaminating the series.
    """
    rows: list[HealthRow] = []
    covered: set[str] = set()
    for cls in inventory:
        if cls.membership is Membership.COMMISSIONING:
            rows.append(HealthRow(
                run_id=cls.run_id, state=AttemptState.COMPLETED_SWEEP,
                eligible=False, in_trend=False, reason=cls.reason,
                started_utc=cls.started_utc, input_complete=cls.input_complete,
            ))
            continue
        if cls.membership is not Membership.PILOT:
            continue
        covered.add(slot_of(cls.run_id))
        rows.append(HealthRow(
            run_id=cls.run_id, state=cls.attempt_state or AttemptState.MALFORMED,
            eligible=True, in_trend=cls.attempt_state is AttemptState.COMPLETED_SWEEP,
            reason=cls.reason, started_utc=cls.started_utc,
            input_complete=cls.input_complete,
        ))
    for slot in slots:
        if slot not in covered:
            rows.append(HealthRow(
                run_id=slot, state=AttemptState.MISSING_SLOT,
                eligible=True, in_trend=False,
                reason="expected hourly slot with no attempt in the pilot tree",
            ))
    return sorted(rows, key=lambda r: r.run_id)


def health_counts(rows: list[HealthRow]) -> dict[str, int]:
    """Count health rows by state, plus discovered and missing totals.

    Commissioning rows carry the completed-sweep state but are counted
    separately so a "completed" total can never silently include them.
    """
    counts = {state.value: 0 for state in AttemptState}
    counts["commissioning_reference"] = 0
    for row in rows:
        if not row.eligible and row.state is AttemptState.COMPLETED_SWEEP:
            counts["commissioning_reference"] += 1
            continue
        counts[row.state.value] += 1
    counts["discovered_attempts"] = sum(
        1 for r in rows if r.state is not AttemptState.MISSING_SLOT
    )
    # Expected slots = hours still missing plus hours an attempt covered.
    slot_rows = sum(1 for r in rows if r.state is AttemptState.MISSING_SLOT)
    covered_hours = {
        slot_of(r.run_id) for r in rows
        if r.state is not AttemptState.MISSING_SLOT and r.eligible
    }
    counts["expected_slots"] = slot_rows + len(covered_hours)
    return counts


# =============================================================================
# Diagnostic entry point
# =============================================================================


def main() -> None:
    """Print the live inventory classification for a pilot directory."""
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} <pilot_dir>")
    inventory = inventory_pilot(Path(sys.argv[1]))
    slots = expected_slots()
    health = build_run_health(inventory, slots)
    for cls in inventory:
        state = cls.attempt_state.value if cls.attempt_state else "-"
        print(f"{cls.run_id}\t{cls.membership.value}\t{state}\t{cls.reason}")
    print(f"\nexpected slots: {len(slots)} ({slots[0]}..{slots[-1]})"
          if slots else "\nexpected slots: 0")
    print(f"health rows   : {len(health)}")
    for state, count in sorted(health_counts(health).items()):
        print(f"  {state:<24} {count}")


if __name__ == "__main__":
    main()
