#!/usr/bin/env python3
"""
Script Name  : pilot_database.py
Description  : Rebuilds the persistent DuckDB projection from the versioned
               per-run Parquet layer and the checked-in SQL
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-08-28
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
Builds `derived/pilot.duckdb` entirely from files: the version 1 per-run
Parquet artifacts and derivation manifests, the checked-in view SQL under
`sql/pilot/`, and the collection-health projection computed from the pilot
tree by `pilot_contract.py`. No manually created view or table is ever
required; a fresh database built into a scratch target from the same Parquet
returns identical results.

Ingestion rules follow the contract:

- Every derivation manifest contributes its run row, so failed derivations
  stay visible in `pilot_runs`.
- Core artifacts (run, frequencies, observations) are ingested from
  `succeeded` and `partial` manifests only, and only when their recorded
  output hash still matches the file.
- Advanced artifacts (IE capabilities, RNR, BSS Load) are ingested from
  `succeeded` manifests only, so a partial derivation can never leave stale
  advanced values looking current.
- Every eligible attempt other than a `running` run must carry a manifest;
  a silently absent run id is a reconciliation error, not a gap.

Usage
-----
    Imported by pilot-update.py; also usable directly:

    python3 pilot_database.py [--pilot-root DIR] [--derived-root DIR]
                              [--target PATH] [--now ISO-DATETIME]
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

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

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

SQL_FILE = _SCRIPTS_DIR.parent / "sql" / "pilot" / "pilot_views.sql"

# Artifacts ingestable from non-succeeded manifests: the core collection
# health surface must survive an advanced-surface failure.
CORE_TABLES = ("run", "frequencies", "observations")


class ReconciliationError(RuntimeError):
    """Raised when derived files and manifests disagree."""


# =============================================================================
# Manifest discovery and verification
# =============================================================================


def load_manifests(runs_root: Path) -> list[dict]:
    """Read every derivation manifest under the versioned runs root."""
    manifests = []
    if not runs_root.is_dir():
        return manifests
    for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        manifest = pilot_enrich.read_manifest(run_dir)
        if manifest is not None:
            manifests.append(manifest)
    return manifests


def verify_output(out_dir: Path, manifest: dict, name: str) -> list[tuple]:
    """Return the rows of one recorded output, verifying its hash first.

    An output whose file is missing or whose hash no longer matches the
    manifest is not ingested: reconciliation failures surface loudly in the
    return value instead of quietly accepting a plausible table.
    """
    entry = next((o for o in manifest.get("outputs", [])
                  if o["name"] == f"{name}.parquet"), None)
    if entry is None:
        raise ReconciliationError(
            f"{manifest.get('run_id')}: manifest does not record {name}"
        )
    path = out_dir / entry["name"]
    if not path.is_file():
        raise ReconciliationError(
            f"{manifest.get('run_id')}: missing output {entry['name']}"
        )
    if pilot_enrich.sha256_file(path) != entry.get("sha256"):
        raise ReconciliationError(
            f"{manifest.get('run_id')}: output {entry['name']} no longer "
            "matches the manifest hash"
        )
    table = pq.read_table(path)
    if table.num_rows != entry.get("rows"):
        raise ReconciliationError(
            f"{manifest.get('run_id')}: output {entry['name']} has "
            f"{table.num_rows} rows, manifest records {entry.get('rows')}"
        )
    return table


# =============================================================================
# Database build
# =============================================================================


def _empty_like(
    con: duckdb.DuckDBPyConnection, name: str, table: str
) -> None:
    """Create an empty staging table with the contract's declared schema."""
    empty = pa.Table.from_pylist([], schema=pilot_enrich.table_schema(table))
    con.register("stg_empty", empty)
    try:
        con.execute(
            f"CREATE OR REPLACE TABLE stg_{name} AS SELECT * FROM stg_empty"
        )
    finally:
        con.unregister("stg_empty")


def build_database(
    pilot_root: Path = pilot.PILOT_DIR_DEFAULT,
    derived_root: Path = pilot.DERIVED_ROOT_DEFAULT,
    target: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Build (or rebuild) the DuckDB projection from files.

    The build is total: staging tables are recreated from Parquet and views
    from checked-in SQL on every invocation, so database-internal state is
    never the only copy of a transformation.
    """
    db_path = target or pilot.derived_runs_root(derived_root).parents[2] \
        / "pilot.duckdb"
    runs_root = pilot.derived_runs_root(derived_root)

    manifests = load_manifests(runs_root)
    inventory = pilot.inventory_pilot(pilot_root)
    eligible_ids = {c.run_id for c in inventory if c.eligible}
    manifest_ids = {m.get("run_id") for m in manifests}
    running_ids = {
        c.run_id for c in inventory
        if c.eligible and c.attempt_state is pilot.AttemptState.RUNNING
    }
    missing = eligible_ids - manifest_ids - running_ids
    if missing:
        raise ReconciliationError(
            "eligible attempts without a derivation manifest: "
            f"{sorted(missing)}"
        )

    # Health projection: every eligible attempt plus every expected slot.
    health = pilot.build_run_health(inventory, pilot.expected_slots(now=now))

    con = duckdb.connect(str(db_path))
    try:
        con.execute("PRAGMA threads=4")

        # Ingest per artifact with per-output hash verification. A failed
        # derivation contributes its run row only; a partial one contributes
        # the core tables; only a succeeded one contributes advanced tables.
        table_names = tuple(
            a.removesuffix(".parquet") for a in pilot_enrich.ARTIFACT_NAMES)
        ingested: dict[str, list[pa.Table]] = {t: [] for t in table_names}
        for manifest in manifests:
            status = manifest.get("status")
            run_id = manifest.get("run_id")
            out_dir = runs_root / str(run_id)
            if status == "succeeded":
                allowed = set(table_names)
            elif status == "partial":
                allowed = set(CORE_TABLES)
            else:
                allowed = {"run"}
            for table_name in table_names:
                if table_name not in allowed:
                    continue
                ingested[table_name].append(
                    verify_output(out_dir, manifest, table_name))

        for table_name, tables in ingested.items():
            if tables:
                union = pa.concat_tables(
                    tables, promote_options="default")
                con.register("stg_incoming", union)
                con.execute(
                    f"CREATE OR REPLACE TABLE stg_{table_name} AS "
                    "SELECT * FROM stg_incoming")
                con.unregister("stg_incoming")
            else:
                _empty_like(con, table_name, table_name)

        # Health staging table from the contract projection.
        health_table = pa.table({
            "run_id": [r.run_id for r in health],
            "state": [r.state.value for r in health],
            "eligible": [r.eligible for r in health],
            "in_trend": [r.in_trend for r in health],
            "reason": [r.reason for r in health],
            "started_utc": [r.started_utc for r in health],
            "input_complete": [r.input_complete for r in health],
        })
        con.register("stg_health", health_table)
        con.execute("CREATE OR REPLACE TABLE stg_run_health AS "
                    "SELECT * FROM stg_health")
        con.unregister("stg_health")

        # Views from checked-in SQL: the single definition of analytical
        # semantics, so a fresh rebuild cannot drift from the persistent DB.
        if not SQL_FILE.is_file():
            raise ReconciliationError(f"view SQL missing: {SQL_FILE}")
        con.execute(SQL_FILE.read_text(encoding="utf-8"))

        present = {
            row[0] for row in con.execute(
                "SELECT view_name FROM duckdb_views()").fetchall()
        }
        missing_views = [v for v in pilot.VIEW_NAMES if v not in present]
        if missing_views:
            raise ReconciliationError(
                f"required views missing after build: {missing_views}"
            )
    finally:
        con.close()
    return db_path


# =============================================================================
# Independent reconciliation helpers (used by tests and the report)
# =============================================================================


def query(db_path: Path, sql: str) -> list[tuple]:
    """Run one query against the persistent database."""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def main() -> None:
    """Rebuild the database directly (diagnostic path)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-root", type=Path, default=pilot.PILOT_DIR_DEFAULT)
    ap.add_argument("--derived-root", type=Path,
                    default=pilot.DERIVED_ROOT_DEFAULT)
    ap.add_argument("--target", type=Path, default=None)
    ap.add_argument("--now", type=str, default=None)
    args = ap.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else None
    path = build_database(args.pilot_root, args.derived_root,
                          target=args.target, now=now)
    print(f"database: {path}")


if __name__ == "__main__":
    main()
