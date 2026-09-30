#!/usr/bin/env python3
"""Tests for the ingestion DDL and the source-to-column contract.

The mapping tests read the latest completed live run (read-only) and assert
every source header and instrument.json key maps to a declared column: zero
unmapped. The DDL tests apply sql/ingest/up.sql to the wifi_beacon_survey_test
database on pgsql01 and prove idempotence, survey/archive structural
identity, mutation detection, and the down/re-apply cycle. Database tests
need the pgsql01 credentials in the environment (run under the scoped Doppler
runtime) and are skipped otherwise. They only ever touch the test database.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_scripts = str(ROOT / "scripts")
if sys_scripts not in __import__("sys").path:
    __import__("sys").path.append(sys_scripts)

import ingest_contract as contract  # noqa: E402

PILOT_ROOT = Path(
    os.environ.get(
        "INGEST_PILOT_ROOT",
        "/opt/agents/repos/storage-mounted/wifi-beacon-survey/pilot",
    )
)
UP_SQL = ROOT / "sql" / "ingest" / "up.sql"
DOWN_SQL = ROOT / "sql" / "ingest" / "down.sql"
TEST_DB = os.environ.get("INGEST_TEST_DB", "wifi_beacon_survey_test")
PROJECT_SCHEMAS = ("survey", "archive", "ingest", "derived")

DB_ENV_VARS = ("PGSQL01_HOST", "PGSQL01_ADMIN_USER", "PGSQL01_ADMIN_PASSWORD")


def _connect(test_db: str = TEST_DB):
    import psycopg

    return psycopg.connect(
        host=os.environ["PGSQL01_HOST"],
        port=os.getenv("PGSQL01_PORT", "5432"),
        user=os.environ["PGSQL01_ADMIN_USER"],
        password=os.environ["PGSQL01_ADMIN_PASSWORD"],
        dbname=test_db,
        autocommit=True,
    )


def latest_completed_run() -> Path:
    """The newest pilot run whose instrument.json records a completed sweep."""
    best: tuple[str, Path] | None = None
    for child in PILOT_ROOT.iterdir():
        instrument = child / "instrument.json"
        if not instrument.is_file():
            continue
        try:
            doc = json.loads(instrument.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if doc.get("run_status") == "sweep":
            if best is None or child.name > best[0]:
                best = (child.name, child)
    if best is None:
        raise AssertionError("no completed run found under the pilot root")
    return best[1]


def schema_catalog_digest(conn, schema: str) -> str:
    """Digest of one schema's columns, constraints, and indexes.

    Schema names are normalised out of constraint and index definitions so
    the digest describes structure, not location: two structurally identical
    schemas digest equally regardless of their names.
    """
    rows: list[str] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, ordinal_position, column_name, data_type,
                   is_nullable, COALESCE(column_default, '')
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
            """,
            (schema,),
        )
        for row in cur.fetchall():
            rows.append("col:" + "\x1f".join(str(x) for x in row))
        cur.execute(
            """
            SELECT conrelid::regclass::text, conname, contype,
                   pg_get_constraintdef(pg_constraint.oid)
            FROM pg_constraint
            JOIN pg_namespace n ON n.oid = connamespace
            WHERE n.nspname = %s
            ORDER BY conrelid::regclass::text, conname
            """,
            (schema,),
        )
        for row in cur.fetchall():
            text = "\x1f".join(str(x) for x in row)
            rows.append("con:" + text.replace(schema, "S"))
        cur.execute(
            """
            SELECT indexrelid::regclass::text, pg_get_indexdef(idx.indexrelid)
            FROM pg_index idx
            JOIN pg_class c ON c.oid = idx.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
            ORDER BY indexrelid::regclass::text
            """,
            (schema,),
        )
        for row in cur.fetchall():
            text = "\x1f".join(str(x) for x in row)
            rows.append("idx:" + text.replace(schema, "S"))
    # Normalize first, sort second: ordering by raw schema-qualified names
    # would make identical structures with different schema names sort
    # differently and digest differently.
    return hashlib.sha256(
        ("\n".join(sorted(rows))).encode("utf-8")
    ).hexdigest()


def schemas_applied(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM pg_namespace
            WHERE nspname = ANY(%s)
            """,
            (list(PROJECT_SCHEMAS),),
        )
        return cur.fetchone()[0] == len(PROJECT_SCHEMAS)


def apply_file(conn, path: Path, rename: dict[str, str] | None = None) -> None:
    """Execute a SQL file. rename maps schema names for scratch copies."""
    sql = path.read_text(encoding="utf-8")
    if rename:
        for old, new in rename.items():
            sql = re.sub(rf"\b{old}\b", new, sql)
    with conn.cursor() as cur:
        cur.execute(sql)


@unittest.skipUnless(
    all(os.environ.get(v) for v in DB_ENV_VARS),
    "database tests need pgsql01 credentials; run under the Doppler runtime",
)
class IngestDdlTests(unittest.TestCase):
    def setUp(self):
        self.conn = _connect()
        if not schemas_applied(self.conn):
            apply_file(self.conn, UP_SQL)

    def tearDown(self):
        self.conn.close()

    def test_10_apply_twice_catalog_identical(self):
        def whole_catalog() -> str:
            digests = [
                schema_catalog_digest(self.conn, s) for s in PROJECT_SCHEMAS[:2]
            ]
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name, column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema IN ('ingest', 'derived')
                    ORDER BY table_schema, table_name, ordinal_position
                    """
                )
                blob = "\n".join(
                    "\x1f".join(str(x) for x in row) for row in cur.fetchall()
                )
            return hashlib.sha256(
                ("\n".join(digests) + "\n" + blob).encode("utf-8")
            ).hexdigest()

        before = whole_catalog()
        apply_file(self.conn, UP_SQL)
        after = whole_catalog()
        self.assertEqual(before, after, "second DDL apply changed the catalog")

    def test_20_survey_archive_identical(self):
        self.assertEqual(
            schema_catalog_digest(self.conn, "survey"),
            schema_catalog_digest(self.conn, "archive"),
            "survey and archive base tables differ in structure",
        )

    def test_30_altered_column_in_one_schema_is_detected(self):
        rename = {
            "survey": "mutation_survey",
            "archive": "mutation_archive",
            "ingest": "mutation_ingest",
            "derived": "mutation_derived",
        }
        try:
            apply_file(self.conn, UP_SQL, rename=rename)
            with self.conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE mutation_archive.runs "
                    "ALTER COLUMN phy TYPE varchar(32)"
                )
            self.assertNotEqual(
                schema_catalog_digest(self.conn, "mutation_survey"),
                schema_catalog_digest(self.conn, "mutation_archive"),
                "the identity check failed to detect an altered column",
            )
        finally:
            with self.conn.cursor() as cur:
                cur.execute(
                    "DROP SCHEMA IF EXISTS mutation_derived CASCADE"
                )
                cur.execute(
                    "DROP SCHEMA IF EXISTS mutation_ingest CASCADE"
                )
                cur.execute(
                    "DROP SCHEMA IF EXISTS mutation_archive CASCADE"
                )
                cur.execute(
                    "DROP SCHEMA IF EXISTS mutation_survey CASCADE"
                )

    def test_40_down_script_removes_everything_and_reapply_restores(self):
        apply_file(self.conn, DOWN_SQL)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM pg_namespace WHERE nspname = ANY(%s)
                """,
                (list(PROJECT_SCHEMAS),),
            )
            self.assertEqual(0, cur.fetchone()[0])
        apply_file(self.conn, UP_SQL)
        self.assertTrue(schemas_applied(self.conn))
        self.assertEqual(
            schema_catalog_digest(self.conn, "survey"),
            schema_catalog_digest(self.conn, "archive"),
        )


class SourceMappingTests(unittest.TestCase):
    def test_source_headers_match_declared_columns(self):
        self.assertEqual(
            [c[0] for c in contract.FREQUENCY_COLUMNS],
            contract.FREQUENCY_HEADER.split("\t"),
        )
        self.assertEqual(
            [c[0] for c in contract.OBSERVATION_COLUMNS],
            contract.OBSERVATION_HEADER.split("\t"),
        )

    def test_latest_completed_run_maps_with_zero_unmapped(self):
        run = latest_completed_run()
        instrument = json.loads(
            (run / "instrument.json").read_text(encoding="utf-8")
        )
        keys = set()
        for key, value in instrument.items():
            if isinstance(value, dict):
                keys.update(f"{key}.{sub}" for sub in value)
            else:
                keys.add(key)
        documented = contract.runs_documented_keys()
        unmapped = keys - documented
        self.assertEqual(
            set(),
            unmapped,
            f"run {run.name} carries keys the contract does not map: "
            f"{sorted(unmapped)}",
        )
        for name in ("frequencies.tsv", "aggregate.tsv"):
            header = (run / name).read_text(encoding="utf-8").splitlines()[0]
            expected = (
                contract.FREQUENCY_HEADER
                if name == "frequencies.tsv"
                else contract.OBSERVATION_HEADER
            )
            self.assertEqual(expected, header, f"run {run.name} {name}")

    def test_mutation_extra_header_column_fails(self):
        mutated = contract.FREQUENCY_HEADER + "\tfake_extra_column"
        with self.assertRaises(contract.ContractError):
            contract.validate_headers(mutated, contract.OBSERVATION_HEADER)
        with self.assertRaises(contract.ContractError):
            contract.validate_headers(
                contract.FREQUENCY_HEADER,
                contract.OBSERVATION_HEADER + "\tfake_extra_column",
            )


if __name__ == "__main__":
    unittest.main()
