#!/usr/bin/env python3
"""
Script Name  : ingest_load.py
Description  : Drains the collector's per-run files into the wifi_beacon_survey
               PostgreSQL projection
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-09-29
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
The loader is the only writer of the wifi_beacon_survey projection. Each
invocation drains every attempt not yet reflected in the ledger and every
pending attempt that has become terminal; the historical backfill is the same
code path. It reads only instrument.json, frequencies.tsv, and aggregate.tsv
- never Parquet, DuckDB, Arrow, PCAP, or the per-frequency freq-*.tsv files.

Per run it validates headers and types against scripts/ingest_contract.py,
enforces the cross-file relationship between aggregate.tsv and the manifest,
and commits base rows and the ledger record in one transaction, or not at
all. An attempt already loaded with unchanged fingerprints is a no-op; a
changed fingerprint records source_changed and leaves base rows untouched.
Routing uses only what the run recorded about its own regulatory domain,
never the host's current domain. A whole drain holds a session advisory
lock, so two concurrent invocations serialize and never double-load.

Exit status is non-zero when any load failed or any source_changed occurred.
Archived, skipped, refused, and missing attempts are outcomes, not errors.

Usage
-----
    doppler run --project ml01 --config dev -- python3 scripts/ingest_load.py
        [--pilot-root PATH] [--database NAME]

    Credentials come from the environment (PGSQL01_HOST, PGSQL01_ADMIN_USER,
    PGSQL01_ADMIN_PASSWORD) resolved through the scoped Doppler runtime.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys_scripts = str(Path(__file__).resolve().parent)
if sys_scripts not in sys.path:
    sys.path.append(sys_scripts)

import ingest_contract as contract  # noqa: E402

LOADER_VERSION = "ingest-load/1"

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}$")

# Session-level advisory lock key for the drain. Any fixed nonzero integer
# works; the value only has to be the same one every invocation uses.
ADVISORY_LOCK_KEY = 73780220486921

DATA_ROOT_DEFAULT = Path("/opt/agents/repos/storage-mounted/wifi-beacon-survey")
PILOT_DIR_DEFAULT = DATA_ROOT_DEFAULT / "pilot"
DATABASE_DEFAULT = "wifi_beacon_survey"

INSTRUMENT_NAME = "instrument.json"
FREQUENCIES_NAME = "frequencies.tsv"
AGGREGATE_NAME = "aggregate.tsv"

# Attempt states and dispositions, frozen by docs/ingestion-contract.md.
STATE_COMPLETED = "completed"
STATE_SKIP = "receiver_absent_skip"
STATE_REFUSED = "refused"
STATE_FAILED = "failed"
STATE_RUNNING = "running"
STATE_MALFORMED = "malformed"

DISPOSITION_SURVEY = "survey"
DISPOSITION_ARCHIVE = "archive"
DISPOSITION_NOT_LOADED = "not_loaded"
DISPOSITION_PENDING = "pending"
DISPOSITION_UNRESOLVED = "unresolved_domain"

OUTCOME_LOADED = "loaded"
OUTCOME_SOURCE_CHANGED = "source_changed"
OUTCOME_CHECK_FAILED = "check_failed"

READINESS_TERMINAL = {
    "sweep",
    "skipped_no_interface",
    "refused_regulatory_domain",
    "failed",
}


# =============================================================================
# UTC slot identity
# =============================================================================


def utc_hour(moment: datetime) -> datetime:
    """Floor a UTC moment to the hour."""
    return moment.replace(minute=0, second=0, microsecond=0)


def expected_slots(now: datetime) -> list[datetime]:
    """Expected UTC hours: the series start hour through the last fully
    elapsed UTC hour.

    The current incomplete hour is never judged: at :45 or :59 past the
    hour, that hour has no expectation yet, because inventing one would
    report the instrument missing while it is mid-collection.
    """
    now = now.astimezone(timezone.utc)
    start = utc_hour(contract.SERIES_START_UTC)
    ceiling = utc_hour(now) - timedelta(hours=1)
    slots: list[datetime] = []
    slot = start
    while slot <= ceiling:
        slots.append(slot)
        slot += timedelta(hours=1)
    return slots


# =============================================================================
# Attempt classification
# =============================================================================


class Attempt:
    """One classified run directory and everything the ledger records."""

    def __init__(self, run_id: str, path: Path):
        self.run_id = run_id
        self.path = path
        self.started_utc: datetime | None = None
        self.state = STATE_MALFORMED
        self.disposition = DISPOSITION_NOT_LOADED
        self.reason = ""
        self.instrument_schema: str | None = None
        self.run_status: str | None = None
        self.regulatory_domain: str | None = None
        self.regulatory_domain_phy: str | None = None
        self.regulatory_domain_declared: str | None = None
        self.regulatory_domain_set_result: str | None = None
        self.regulatory_domain_at_discovery: str | None = None
        self.regulatory_domain_post_sweep: str | None = None
        self.interface_present: bool | None = None
        self.phy: str | None = None
        self.usb_device: str | None = None
        self.freq_rows: list[list] | None = None
        self.obs_rows: list[list] | None = None
        self.target_schema: str | None = None
        self.last_check_finding: str | None = None
        self.load_error: str | None = None

    def routed(self, disposition: str) -> "Attempt":
        self.disposition = disposition
        return self


def _read_instrument(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _read_tsv(path: Path, columns) -> list[list]:
    """Read a TSV and convert every cell to its declared type.

    Raises contract.ContractError on any header or value violation, which
    makes the attempt malformed rather than silently coerced.
    """
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration:
            raise contract.ContractError(f"{path.name} is empty")
        expected = [c[0] for c in columns]
        if header != expected:
            raise contract.ContractError(
                f"{path.name} header does not match the contract"
            )
        rows: list[list] = []
        for ordinal, raw in enumerate(reader):
            if not raw:
                continue
            if len(raw) != len(columns):
                raise contract.ContractError(
                    f"{path.name} row {ordinal} has {len(raw)} fields, "
                    f"expected {len(columns)}"
                )
            rows.append([
                contract.convert_value(value, conv, nullable)
                for value, (_, conv, nullable) in zip(raw, columns)
            ])
        return rows


def effective_domain_v1(doc: dict) -> str | None:
    """Effective domain of an instrument/1 run: the PHY's own country when
    the driver self-managed one, otherwise the global domain."""
    value = doc.get("regulatory_domain_phy") or doc.get("regulatory_domain")
    if value in (None, "", "unresolved"):
        return None
    return str(value)


def effective_route_v2(doc: dict, declared: str) -> str | None:
    """Routing domain of an instrument/2 run: survey only when both the
    discovery-time domain and the post-sweep domain equal the declared one."""
    discovery = doc.get("regulatory_domain_at_discovery")
    post = doc.get("regulatory_domain_post_sweep")
    if discovery in (None, "", "unresolved") or post in (None, "", "unresolved"):
        return None
    if discovery == declared and post == declared:
        return declared
    return f"{discovery}/{post}"


def route_completed(doc: dict) -> str | None:
    """The routing decision for a completed run, from the run's own record.

    Returns DECLARED_DOMAIN for survey, any other non-None value describing
    the domain evidence for archive, or None for an unresolved domain. The
    host's current domain is never an input.
    """
    schema = doc.get("schema")
    if schema == "wifi-beacon-survey/instrument/2":
        return effective_route_v2(doc, contract.DECLARED_DOMAIN)
    domain = effective_domain_v1(doc)
    if domain is None:
        return None
    return domain


def classify_attempt(path: Path) -> Attempt:
    """Assign exactly one attempt state and disposition to a run directory."""
    run_id = path.name
    attempt = Attempt(run_id, path)
    doc = _read_instrument(path / INSTRUMENT_NAME)
    if doc is None:
        attempt.reason = "instrument.json missing or unreadable"
        return attempt

    attempt.instrument_schema = doc.get("schema")
    attempt.run_status = doc.get("run_status")
    attempt.regulatory_domain = doc.get("regulatory_domain")
    attempt.regulatory_domain_phy = doc.get("regulatory_domain_phy")
    attempt.regulatory_domain_declared = doc.get("regulatory_domain_declared")
    attempt.regulatory_domain_set_result = doc.get("regulatory_domain_set_result")
    attempt.regulatory_domain_at_discovery = doc.get("regulatory_domain_at_discovery")
    attempt.regulatory_domain_post_sweep = doc.get("regulatory_domain_post_sweep")
    attempt.interface_present = doc.get("interface_present")
    attempt.phy = doc.get("phy")
    attempt.usb_device = (doc.get("usb") or {}).get("device")
    started = doc.get("started_utc")
    if started:
        try:
            attempt.started_utc = datetime.fromisoformat(
                str(started).replace("Z", "+00:00")
            )
        except ValueError:
            attempt.started_utc = None

    status = attempt.run_status
    if status == "running":
        attempt.state = STATE_RUNNING
        attempt.disposition = DISPOSITION_PENDING
        attempt.reason = "run in progress at last instrument write"
        return attempt
    if status not in READINESS_TERMINAL:
        attempt.state = STATE_MALFORMED
        attempt.reason = f"unknown run_status {status!r}"
        return attempt
    if status == "skipped_no_interface":
        attempt.state = STATE_SKIP
        attempt.reason = "receiver absent at run start; skip record written"
        return attempt
    if status == "refused_regulatory_domain":
        attempt.state = STATE_REFUSED
        attempt.reason = (
            "declared regulatory domain not established; run refused"
        )
        return attempt
    if status == "failed":
        attempt.state = STATE_FAILED
        attempt.reason = "collector exited before completing the sweep"
        return attempt

    # run_status == sweep: file readiness decides completed vs malformed.
    try:
        attempt.freq_rows = _read_tsv(
            path / FREQUENCIES_NAME, contract.FREQUENCY_COLUMNS
        )
        attempt.obs_rows = _read_tsv(
            path / AGGREGATE_NAME, contract.OBSERVATION_COLUMNS
        )
    except (contract.ContractError, OSError) as exc:
        attempt.state = STATE_MALFORMED
        attempt.reason = f"sweep record failed contract validation: {exc}"
        return attempt

    attempt.state = STATE_COMPLETED
    attempt.reason = "completed sweep with contract-valid manifest and aggregate"
    route = route_completed(doc)
    if route is None:
        attempt.disposition = DISPOSITION_UNRESOLVED
        attempt.reason += "; domain unresolved, not loaded"
    elif route == contract.DECLARED_DOMAIN:
        attempt.disposition = DISPOSITION_SURVEY
    else:
        attempt.disposition = DISPOSITION_ARCHIVE
    return attempt


# =============================================================================
# Cross-file check
# =============================================================================
# Verified across the whole retained archive before enforcement (gate 1.4):
# 757 completed runs, zero mismatches. Every aggregate band+frequency must
# appear in the manifest as sampled, and the per-frequency beacon sum and
# distinct-BSSID count must equal that manifest row's beacon_count and
# bssid_count.


def cross_file_check(
    freq_rows: list[list], obs_rows: list[list]
) -> str | None:
    """Return None when the relationship holds, else a finding string."""
    columns = [c[0] for c in contract.FREQUENCY_COLUMNS]
    obs_columns = [c[0] for c in contract.OBSERVATION_COLUMNS]
    f_band = columns.index("band")
    f_freq = columns.index("frequency_mhz")
    f_status = columns.index("sample_status")
    f_bssids = columns.index("bssid_count")
    f_beacons = columns.index("beacon_count")
    o_band = obs_columns.index("band")
    o_freq = obs_columns.index("frequency_mhz")
    o_bssid = obs_columns.index("bssid")
    o_beacons = obs_columns.index("beacons")

    sampled = {
        (row[f_band], row[f_freq]): row
        for row in freq_rows
        if row[f_status] == "sampled"
    }
    sums: dict = {}
    bssids: dict = {}
    for row in obs_rows:
        key = (row[o_band], row[o_freq])
        sums[key] = sums.get(key, 0) + row[o_beacons]
        bssids.setdefault(key, set()).add(row[o_bssid])
    for key in sums:
        if key not in sampled:
            return f"aggregate band/frequency {key} is not sampled in manifest"
    for key, manifest in sampled.items():
        if sums.get(key, 0) != manifest[f_beacons]:
            return (
                f"beacon sum {sums.get(key, 0)} != manifest "
                f"{manifest[f_beacons]} for {key}"
            )
        if len(bssids.get(key, set())) != manifest[f_bssids]:
            return (
                f"bssid count {len(bssids.get(key, set()))} != manifest "
                f"{manifest[f_bssids]} for {key}"
            )
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprints(run_dir: Path) -> tuple[str, str, str]:
    """Per-file SHA-256 of the three inputs; the triple is the fingerprint."""
    return (
        sha256_file(run_dir / INSTRUMENT_NAME),
        sha256_file(run_dir / FREQUENCIES_NAME),
        sha256_file(run_dir / AGGREGATE_NAME),
    )


# =============================================================================
# Database plumbing
# =============================================================================


def connect(database: str) -> "object":
    import psycopg

    return psycopg.connect(
        host=os.environ["PGSQL01_HOST"],
        port=os.getenv("PGSQL01_PORT", "5432"),
        user=os.environ["PGSQL01_ADMIN_USER"],
        password=os.environ["PGSQL01_ADMIN_PASSWORD"],
        dbname=database,
        autocommit=True,
    )


def insert_run(cur, attempt: Attempt, doc: dict) -> None:
    """Insert the runs row from the typed document plus the raw jsonb."""
    slot = utc_hour(attempt.started_utc) if attempt.started_utc else None
    cur.execute(
        f"""
        INSERT INTO {attempt.target_schema}.runs (
            run_id, instrument_schema, run_status, skip_reason, started_utc,
            slot_utc_hour, interface, interface_present, phy,
            regulatory_domain, regulatory_domain_phy,
            regulatory_domain_declared, regulatory_domain_set_attempted,
            regulatory_domain_set_result, regulatory_domain_at_discovery,
            regulatory_domain_post_sweep, usb_bus, usb_port, usb_device,
            usb_controller_pci, usb_speed_mbps, usb_driver,
            capture_dwell_seconds, capture_bands, capture_snaplen,
            capture_bpf_filter, raw
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s
        )
        """,
        (
            attempt.run_id,
            doc.get("schema"),
            doc.get("run_status"),
            doc.get("skip_reason"),
            attempt.started_utc,
            slot,
            doc.get("interface"),
            bool(doc.get("interface_present")),
            doc.get("phy"),
            doc.get("regulatory_domain"),
            doc.get("regulatory_domain_phy"),
            doc.get("regulatory_domain_declared"),
            doc.get("regulatory_domain_set_attempted"),
            doc.get("regulatory_domain_set_result"),
            doc.get("regulatory_domain_at_discovery"),
            doc.get("regulatory_domain_post_sweep"),
            (doc.get("usb") or {}).get("bus"),
            (doc.get("usb") or {}).get("port"),
            (doc.get("usb") or {}).get("device"),
            (doc.get("usb") or {}).get("controller_pci"),
            (doc.get("usb") or {}).get("speed_mbps"),
            (doc.get("usb") or {}).get("driver"),
            (doc.get("capture") or {}).get("dwell_seconds"),
            (doc.get("capture") or {}).get("bands"),
            (doc.get("capture") or {}).get("snaplen"),
            (doc.get("capture") or {}).get("bpf_filter"),
            json.dumps(doc, sort_keys=True),
        ),
    )


def insert_frequencies(cur, attempt: Attempt) -> None:
    columns = [c[0] for c in contract.FREQUENCY_COLUMNS]
    names = ", ".join(columns)
    marks = ", ".join(["%s"] * (len(columns) + 2))
    rows = [
        [attempt.run_id, ordinal, *row]
        for ordinal, row in enumerate(attempt.freq_rows)
    ]
    cur.executemany(
        f"INSERT INTO {attempt.target_schema}.frequencies "
        f"(run_id, source_row_ordinal, {names}) VALUES ({marks})",
        rows,
    )


def insert_observations(cur, attempt: Attempt) -> None:
    columns = [c[0] for c in contract.OBSERVATION_COLUMNS]
    names = ", ".join(columns)
    marks = ", ".join(["%s"] * (len(columns) + 2))
    rows = [
        [attempt.run_id, ordinal, *row]
        for ordinal, row in enumerate(attempt.obs_rows)
    ]
    cur.executemany(
        f"INSERT INTO {attempt.target_schema}.observations "
        f"(run_id, source_row_ordinal, {names}) VALUES ({marks})",
        rows,
    )


# The insert hooks exist as module attributes so tests can inject a failure
# after a run's first table insert and prove the transaction rolled back.
INSERT_HOOKS = {
    "runs": insert_run,
    "frequencies": insert_frequencies,
    "observations": insert_observations,
}


def load_attempt(conn, attempt: Attempt) -> str:
    """Load one completed attempt, or re-fingerprint an already-loaded one.

    Returns the outcome: loaded, source_changed, check_failed, noop, or
    failed. Base rows and the ledger record commit together or not at all.
    """
    fp = fingerprints(attempt.path)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT outcome, sha256_instrument, sha256_frequencies,
                   sha256_aggregate
            FROM ingest.loads
            WHERE run_id = %s
            ORDER BY load_id
            """,
            (attempt.run_id,),
        )
        rows = cur.fetchall()
    loaded_fps = [r[1:] for r in rows if r[0] == OUTCOME_LOADED]
    if loaded_fps and fp == loaded_fps[-1]:
        # Unchanged against the fingerprint the base rows were loaded from.
        return "noop"
    if rows and loaded_fps and fp == rows[-1][1:]:
        # Already reported as changed, and unchanged since: the finding
        # stands, no new row, no reload. The operator decides.
        return "noop"
    if loaded_fps:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ingest.loads
                        (run_id, outcome, loader_version,
                         sha256_instrument, sha256_frequencies,
                         sha256_aggregate)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (attempt.run_id, OUTCOME_SOURCE_CHANGED, LOADER_VERSION,
                     *fp),
                )
        return OUTCOME_SOURCE_CHANGED

    doc = _read_instrument(attempt.path / INSTRUMENT_NAME)
    finding = cross_file_check(attempt.freq_rows, attempt.obs_rows)
    outcome = OUTCOME_CHECK_FAILED if finding else OUTCOME_LOADED
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                if outcome == OUTCOME_LOADED:
                    INSERT_HOOKS["runs"](cur, attempt, doc)
                    INSERT_HOOKS["frequencies"](cur, attempt)
                    INSERT_HOOKS["observations"](cur, attempt)
                cur.execute(
                    """
                    INSERT INTO ingest.loads
                        (run_id, outcome, loader_version,
                         sha256_instrument, sha256_frequencies,
                         sha256_aggregate)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (attempt.run_id, outcome, LOADER_VERSION, *fp),
                )
    except Exception as exc:  # noqa: BLE001 - recorded, then surfaced
        # The transaction rolled back: zero rows from this run anywhere in
        # the base tables. The failure itself is ledgered so the drain
        # reports it; the next drain loads the run.
        attempt.load_error = str(exc)
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ingest.loads
                        (run_id, outcome, loader_version,
                         sha256_instrument, sha256_frequencies,
                         sha256_aggregate)
                    VALUES (%s, 'failed', %s, %s, %s, %s)
                    """,
                    (attempt.run_id, LOADER_VERSION, *fp),
                )
        return "failed"
    attempt.last_check_finding = finding
    return outcome


# =============================================================================
# Drain
# =============================================================================


def upsert_attempt(cur, attempt: Attempt) -> None:
    """Record the current classification of one attempt in the ledger.

    A loaded attempt's ledger row is final; the drain only reclassifies
    attempts with no base rows (pending to terminal, or a re-read of an
    unloaded attempt).
    """
    slot = utc_hour(attempt.started_utc) if attempt.started_utc else None
    cur.execute(
        """
        INSERT INTO ingest.attempts (
            run_id, slot_utc_hour, started_utc, instrument_schema,
            run_status, attempt_state, disposition, reason,
            regulatory_domain, regulatory_domain_phy,
            regulatory_domain_declared, regulatory_domain_set_result,
            regulatory_domain_at_discovery, regulatory_domain_post_sweep,
            interface_present, phy, usb_device
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (run_id) DO NOTHING
        """,
        (
            attempt.run_id,
            slot,
            attempt.started_utc,
            attempt.instrument_schema,
            attempt.run_status,
            attempt.state,
            attempt.disposition,
            attempt.reason,
            attempt.regulatory_domain,
            attempt.regulatory_domain_phy,
            attempt.regulatory_domain_declared,
            attempt.regulatory_domain_set_result,
            attempt.regulatory_domain_at_discovery,
            attempt.regulatory_domain_post_sweep,
            attempt.interface_present,
            attempt.phy,
            attempt.usb_device,
        ),
    )
    if cur.rowcount == 0:
        # Existing row: refresh it only while it has never been loaded.
        cur.execute(
            """
            UPDATE ingest.attempts a SET
                started_utc = %s, instrument_schema = %s, run_status = %s,
                attempt_state = %s, disposition = %s, reason = %s,
                regulatory_domain = %s, regulatory_domain_phy = %s,
                regulatory_domain_declared = %s,
                regulatory_domain_set_result = %s,
                regulatory_domain_at_discovery = %s,
                regulatory_domain_post_sweep = %s,
                interface_present = %s, phy = %s, usb_device = %s
            WHERE a.run_id = %s AND NOT EXISTS (
                SELECT 1 FROM ingest.loads l
                WHERE l.run_id = a.run_id
                  AND l.outcome IN ('loaded', 'source_changed')
            )
            """,
            (
                attempt.started_utc,
                attempt.instrument_schema,
                attempt.run_status,
                attempt.state,
                attempt.disposition,
                attempt.reason,
                attempt.regulatory_domain,
                attempt.regulatory_domain_phy,
                attempt.regulatory_domain_declared,
                attempt.regulatory_domain_set_result,
                attempt.regulatory_domain_at_discovery,
                attempt.regulatory_domain_post_sweep,
                attempt.interface_present,
                attempt.phy,
                attempt.usb_device,
                attempt.run_id,
            ),
        )


def drain(conn, pilot_root: Path, now: datetime | None = None) -> dict:
    """Drain every outstanding attempt. Returns a summary dict."""
    now = now or datetime.now(timezone.utc)
    report: dict = {
        "states": {},
        "dispositions": {},
        "outcomes": {},
        "failures": [],
        "check_findings": [],
    }
    cur = conn.cursor()
    cur.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
    try:
        slots = expected_slots(now)
        cur.executemany(
            "INSERT INTO ingest.slots (slot_utc_hour) VALUES (%s) "
            "ON CONFLICT (slot_utc_hour) DO NOTHING",
            [(s,) for s in slots],
        )
        conn.commit()

        run_dirs = sorted(
            p for p in pilot_root.iterdir()
            if p.is_dir() and RUN_ID_RE.match(p.name)
            and p.name >= "20260827-090003"
        )
        for path in run_dirs:
            attempt = classify_attempt(path)
            if attempt.state == STATE_COMPLETED:
                attempt.target_schema = (
                    "survey" if attempt.disposition == DISPOSITION_SURVEY
                    else "archive"
                )
            upsert_attempt(cur, attempt)
            conn.commit()
            report["states"][attempt.state] = (
                report["states"].get(attempt.state, 0) + 1
            )
            report["dispositions"][attempt.disposition] = (
                report["dispositions"].get(attempt.disposition, 0) + 1
            )
            if attempt.disposition not in (DISPOSITION_SURVEY, DISPOSITION_ARCHIVE):
                continue
            outcome = load_attempt(conn, attempt)
            report["outcomes"][outcome] = (
                report["outcomes"].get(outcome, 0) + 1
            )
            if getattr(attempt, "last_check_finding", None):
                report["check_findings"].append(
                    (attempt.run_id, attempt.last_check_finding)
                )
            if outcome in (OUTCOME_SOURCE_CHANGED, "failed"):
                report["failures"].append((attempt.run_id, outcome))
            conn.commit()
    finally:
        cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
        conn.commit()
        cur.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pilot-root", type=Path, default=PILOT_DIR_DEFAULT,
        help="Pilot run-directory root (default: the live pilot root)",
    )
    parser.add_argument(
        "--database", default=DATABASE_DEFAULT,
        help="Target database (default: wifi_beacon_survey)",
    )
    args = parser.parse_args(argv)

    conn = connect(args.database)
    try:
        report = drain(conn, args.pilot_root)
    finally:
        conn.close()

    print("Drain summary:")
    for label, key in (("  attempt states", "states"),
                       ("  dispositions", "dispositions"),
                       ("  load outcomes", "outcomes")):
        counts = report[key]
        print(f"{label}: " + (", ".join(
            f"{k}={v}" for k, v in sorted(counts.items())
        ) or "none"))
    for run_id, outcome in report["failures"]:
        print(f"FAILURE: {run_id}: {outcome}")
    for run_id, finding in report["check_findings"]:
        print(f"CROSS-FILE FINDING: {run_id}: {finding}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
