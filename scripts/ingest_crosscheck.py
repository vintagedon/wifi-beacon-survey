#!/usr/bin/env python3
"""
Script Name  : ingest_crosscheck.py
Description  : Compares the PostgreSQL projection against the legacy DuckDB
               pilot surface: run metrics, band coverage, and missing slots
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-09-29
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
The gate 1.5 cross-check, kept as a tool so the cutover in spec 02 can
re-run it. For every run present in both derived.run_metrics and the legacy
pilot_hourly_metrics, it compares observed BSSIDs, beacon frames, every
frequency outcome count, and mean RSSI; band_coverage against
pilot_band_metrics the same way; and derived.slot_health no_run slots
against the legacy missing_hourly_slot set, mapped to UTC.

The legacy database is opened read-only. Exit is non-zero on any mismatch.

Usage
-----
    doppler run --project ml01 --config dev -- python3 \
        scripts/ingest_crosscheck.py [--database wifi_beacon_survey_test]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys_scripts = str(Path(__file__).resolve().parent)
if sys_scripts not in sys.path:
    sys.path.append(sys_scripts)

import ingest_load  # noqa: E402

PILOT_DUCKDB_DEFAULT = (
    Path("/opt/agents/repos/storage-mounted/wifi-beacon-survey")
    / "derived" / "pilot.duckdb"
)


def legacy_hourly(duckdb_path: Path) -> dict:
    import duckdb

    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT run_id, observed_bssids, beacon_frames,
                   sampled_frequencies, sampled_empty_frequencies,
                   regulatory_skips, capture_errors, manifest_frequencies,
                   mean_rssi_dbm
            FROM pilot_hourly_metrics
            """
        ).fetchall()
    finally:
        con.close()
    return {r[0]: r[1:] for r in rows}


def legacy_band(duckdb_path: Path) -> dict:
    import duckdb

    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT run_id, band, observed_bssids, beacon_frames,
                   populated_frequencies, sampled_empty_frequencies,
                   regulatory_skips, capture_errors, attempted_frequencies
            FROM pilot_band_metrics
            """
        ).fetchall()
    finally:
        con.close()
    return {(r[0], r[1]): r[2:] for r in rows}


def legacy_missing_slots(duckdb_path: Path) -> set[str]:
    import duckdb

    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT run_id FROM pilot_run_health
            WHERE state = 'missing_hourly_slot'
            """
        ).fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


def projection_hourly(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_id, observed_bssids, beacon_frames,
                   sampled_frequencies, sampled_empty_frequencies,
                   regulatory_skips, capture_errors, manifest_frequencies,
                   mean_rssi_dbm
            FROM derived.run_metrics
            """
        )
        return {r[0]: r[1:] for r in cur.fetchall()}


def projection_band(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_id, band, bssids, beacons, sampled_frequencies,
                   sampled_empty_frequencies, regulatory_skips,
                   capture_errors, attempted_frequencies
            FROM derived.band_coverage
            """
        )
        return {(r[0], r[1]): r[2:] for r in cur.fetchall()}


def projection_no_run_slots(conn) -> set[datetime]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_utc_hour FROM derived.slot_health "
            "WHERE slot_state = 'no_run'"
        )
        return {r[0] for r in cur.fetchall()}


def local_slot_to_utc(slot_id: str) -> datetime:
    """Map a legacy local-hour slot id to its UTC hour.

    Legacy slot ids are the collector's local-time directory hour
    (YYYYMMDD-HH0000). ML01 is America/New_York, so the mapping is via the
    zone; an ambiguous local hour (DST fall-back) maps to its earlier UTC
    offset, which the pilot window never exercises.
    """
    from zoneinfo import ZoneInfo

    naive = datetime.strptime(slot_id, "%Y%m%d-%H%M%S")
    local = naive.replace(tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc).replace(minute=0, second=0)


def compare(label, left, right, mismatches, key):
    if left != right:
        mismatches.append(f"{label} {key}: projection={left!r} legacy={right!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", default="wifi_beacon_survey_test",
        help="Projection database to compare (default: the test database)",
    )
    parser.add_argument(
        "--duckdb", type=Path, default=PILOT_DUCKDB_DEFAULT,
        help="Legacy pilot.duckdb (opened read-only)",
    )
    args = parser.parse_args(argv)

    mismatches: list[str] = []
    legacy_runs = legacy_hourly(args.duckdb)
    legacy_bands = legacy_band(args.duckdb)
    legacy_missing = legacy_missing_slots(args.duckdb)

    conn = ingest_load.connect(args.database)
    try:
        proj_runs = projection_hourly(conn)
        proj_bands = projection_band(conn)
        proj_missing = projection_no_run_slots(conn)
    finally:
        conn.close()

    common = sorted(set(proj_runs) & set(legacy_runs))
    print(f"runs in both surfaces: {len(common)} "
          f"(projection {len(proj_runs)}, legacy {len(legacy_runs)})")
    for run_id in common:
        p, l = proj_runs[run_id], legacy_runs[run_id]
        for i, field in enumerate(
            ("observed_bssids", "beacon_frames", "sampled_frequencies",
             "sampled_empty_frequencies", "regulatory_skips",
             "capture_errors", "manifest_frequencies")
        ):
            compare("run_metrics", p[i], l[i], mismatches, f"{run_id}.{field}")
        # Mean RSSI: both surfaces round the mean of per-observation means
        # to one decimal; compare as floats with a hair of tolerance for
        # binary representation.
        if p[7] is not None and l[7] is not None:
            if abs(float(p[7]) - float(l[7])) > 0.051:
                mismatches.append(
                    f"run_metrics {run_id}.mean_rssi_dbm: "
                    f"projection={p[7]!r} legacy={l[7]!r}"
                )
        elif p[7] != l[7]:
            mismatches.append(
                f"run_metrics {run_id}.mean_rssi_dbm: "
                f"projection={p[7]!r} legacy={l[7]!r}"
            )

    common_bands = sorted(set(proj_bands) & set(legacy_bands))
    print(f"run/band rows in both surfaces: {len(common_bands)} "
          f"(projection {len(proj_bands)}, legacy {len(legacy_bands)})")
    for key in common_bands:
        p, l = proj_bands[key], legacy_bands[key]
        for i, field in enumerate(
            ("bssids", "beacons", "sampled_frequencies",
             "sampled_empty_frequencies", "regulatory_skips",
             "capture_errors", "attempted_frequencies")
        ):
            compare("band_coverage", p[i], l[i], mismatches, f"{key}.{field}")

    legacy_missing_utc = {local_slot_to_utc(s) for s in legacy_missing}
    print(f"no_run slots: projection {len(proj_missing)}, "
          f"legacy {len(legacy_missing)} ({len(legacy_missing_utc)} after "
          f"local-to-UTC mapping)")
    only_projection = proj_missing - legacy_missing_utc
    only_legacy = legacy_missing_utc - proj_missing
    for slot in sorted(only_projection):
        mismatches.append(f"slot_health no_run only in projection: {slot}")
    for slot in sorted(only_legacy):
        mismatches.append(f"missing_hourly_slot only in legacy: {slot}")

    if mismatches:
        print(f"\nMISMATCHES ({len(mismatches)}):")
        for m in mismatches[:50]:
            print(f"  {m}")
        return 1
    print("\nCross-check clean: every shared metric matches exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
