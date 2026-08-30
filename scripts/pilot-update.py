#!/usr/bin/env python3
"""
Script Name  : pilot-update.py
Description  : Stable entrypoint for the pilot derived layer: per-run
               enrichment, the DuckDB projection, and the canonical briefing
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-08-28
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
Runs the pilot analysis pipeline defined by `docs/pilot-analysis-contract.md`
in its rebuild order: retained evidence -> versioned per-run Parquet ->
DuckDB -> Markdown briefing.

The enrich stage is idempotent and incremental. An unchanged successful run is
recognized from source identity and is never re-parsed; a new or changed input
cannot be mistaken for an already processed run. A run still marked `running`
is deferred, because enriching a mid-sweep directory would snapshot a verdict
the collector has not reached yet; the next invocation picks it up after the
collector's terminal write.

All roots default to the live production paths and are overridable so tests
and validation sweeps never touch the live pilot tree or canonical report.

Usage
-----
    python3 pilot-update.py [--stage all|enrich|database|report]
                            [--pilot-root DIR] [--derived-root DIR]
                            [--reports-dir DIR] [--now ISO-DATETIME]

Examples
--------
    python3 pilot-update.py
        Full update against the production paths

    python3 pilot-update.py --stage enrich --pilot-root /tmp/kilo/pilot
        Enrichment only against a scratch pilot tree
"""

# =============================================================================
# Imports
# =============================================================================

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

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
pilot_enrich = _load_sibling("pilot_enrich_mod", "pilot_enrich.py")
probe = _load_sibling("probe_surfaces", "probe-surfaces.py")


# =============================================================================
# Enrichment stage
# =============================================================================


def enrich_stage(pilot_root: Path, derived_root: Path) -> list[dict]:
    """Enrich every eligible attempt, processing only what changed.

    Returns one summary row per eligible attempt. Every eligible run ends as
    `processed`, `unchanged`, or `deferred` -- a silently absent run id is a
    defect, so the summary is the caller's reconciliation input.
    """
    inventory = pilot.inventory_pilot(pilot_root)
    resolved, unresolved = pilot_enrich.resolve_requested_fields()
    try:
        tshark_version = probe.tshark_version()
    except OSError:
        tshark_version = "unavailable"
    runs_root = pilot.derived_runs_root(derived_root)

    summaries: list[dict] = []
    for cls in inventory:
        if not cls.eligible:
            continue
        summary = {"run_id": cls.run_id, "attempt_state":
                   cls.attempt_state.value if cls.attempt_state else None}
        if cls.attempt_state is pilot.AttemptState.RUNNING:
            summary["outcome"] = "deferred"
            summary["detail"] = "run in progress; enrichment deferred"
            summaries.append(summary)
            continue
        out_dir = runs_root / cls.run_id
        current_files = pilot_enrich.source_files(cls.path)
        needed, why = pilot_enrich.needs_reprocess(out_dir, current_files)
        if not needed:
            summary["outcome"] = "unchanged"
            summary["detail"] = why
            summaries.append(summary)
            continue
        result = pilot_enrich.enrich_run(
            cls.path, out_dir, cls,
            resolved=resolved, unresolved=unresolved,
            tshark_version=tshark_version,
        )
        summary["outcome"] = "processed"
        summary["detail"] = why
        summary["status"] = result.status
        summary["error"] = result.error
        summaries.append(summary)
    return summaries


# =============================================================================
# Database and report stages (gates 3 and 4 of the spec)
# =============================================================================


def database_stage(pilot_root: Path, derived_root: Path,
                   now: datetime | None) -> None:
    """Rebuild the DuckDB analytical projection from versioned Parquet."""
    pilot_database = _load_sibling("pilot_database_mod", "pilot_database.py")
    pilot_database.build_database(pilot_root, derived_root, now=now)


def report_stage(pilot_root: Path, derived_root: Path,
                 reports_dir: Path, now: datetime | None) -> Path:
    """Render the canonical briefing from the database and classifications."""
    pilot_report = _load_sibling("pilot_report_mod", "pilot_report.py")
    return pilot_report.render_report(
        pilot_root, derived_root, reports_dir, now=now)


# =============================================================================
# Entry point
# =============================================================================


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Update the pilot derived layer, database, and briefing.")
    ap.add_argument("--stage", choices=("all", "enrich", "database", "report"),
                    default="all")
    ap.add_argument("--pilot-root", type=Path, default=pilot.PILOT_DIR_DEFAULT)
    ap.add_argument("--derived-root", type=Path,
                    default=pilot.DERIVED_ROOT_DEFAULT)
    ap.add_argument("--reports-dir", type=Path,
                    default=pilot.REPORTS_DIR_DEFAULT)
    ap.add_argument("--now", type=str, default=None,
                    help="override the clock for expected-slot math "
                         "(ISO datetime, local time)")
    args = ap.parse_args()

    now = datetime.fromisoformat(args.now) if args.now else None

    if args.stage in ("all", "enrich"):
        summaries = enrich_stage(args.pilot_root, args.derived_root)
        for row in summaries:
            line = f"{row['run_id']}: {row['outcome']}"
            if row.get("status"):
                line += f" ({row['status']})"
            if row.get("error"):
                line += f" {row['error']}"
            print(line)
        processed = sum(1 for r in summaries if r["outcome"] == "processed")
        print(f"enrich: {len(summaries)} eligible attempts, "
              f"{processed} processed")

    if args.stage in ("all", "database"):
        database_stage(args.pilot_root, args.derived_root, now)
        print("database: rebuilt views from versioned Parquet")

    if args.stage in ("all", "report"):
        report_path = report_stage(
            args.pilot_root, args.derived_root, args.reports_dir, now)
        print(f"report: {report_path}")


if __name__ == "__main__":
    main()
