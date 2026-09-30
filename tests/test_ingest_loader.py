#!/usr/bin/env python3
"""Behavioral tests for the ingestion loader against synthetic fixtures.

Fixtures live in a scratch tree and the target is always the
wifi_beacon_survey_test database on pgsql01: neither live target is ever
touched. The fixture set covers the dispositions the contract freezes: US
and world completions (instrument/1), a PHY-override case, an instrument/2
completion with post-sweep drift, a refusal, a receiver-absent skip, a
failure, a running attempt, a malformed sweep (truncated TSV), two attempts
in one UTC hour, a missing hour, a pre-series directory that must be
excluded, and sampled-empty plus regulatory-skip manifest rows.

Database tests need the pgsql01 credentials in the environment; run under
the scoped Doppler runtime.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "scripts"))

import ingest_load  # noqa: E402

TEST_DB = os.environ.get("INGEST_TEST_DB", "wifi_beacon_survey_test")
DB_ENV_VARS = ("PGSQL01_HOST", "PGSQL01_ADMIN_USER", "PGSQL01_ADMIN_PASSWORD")
DRAIN_NOW = datetime(2026, 8, 28, 21, 0, 0, tzinfo=timezone.utc)

FREQ_HEADER = [
    "band", "frequency_mhz", "channel", "regulatory_state", "sample_status",
    "dwell_seconds", "pcap_file", "bssid_count", "beacon_count", "error",
]
OBS_HEADER = [
    "band", "frequency_mhz", "channel", "bssid", "ssid", "beacons",
    "beacon_interval_tu", "rssi_min_dbm", "rssi_mean_dbm", "rssi_max_dbm",
    "first_seen", "last_seen", "beacon_reception_ratio",
]

TS = "2026-08-28T12:00:10.000000Z"


def write_tsv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def us_manifest_rows() -> list[list]:
    return [
        ["2.4GHz", "2412", "1", "permitted", "sampled", "10",
         "freq-2412.pcap", "2", "5", ""],
        ["2.4GHz", "2467", "12", "disabled", "regulatory_skip", "0",
         "", "", "", "disabled by regulatory state"],
        ["6GHz", "5955", "1", "no-ir", "sampled_empty", "10",
         "freq-5955.pcap", "0", "0", ""],
    ]


def us_obs_rows() -> list[list]:
    return [
        ["2.4GHz", "2412", "1", "aa:bb:cc:00:00:01", "TestNet", "3", "100",
         "-50", "-45.5", "-40", TS, TS, "0.500"],
        ["2.4GHz", "2412", "1", "aa:bb:cc:00:00:02", "", "2", "100",
         "-61", "-60.0", "-59", TS, TS, "0.333"],
    ]


def world_manifest_rows() -> list[list]:
    # World-domain completion: 2467 sampled_empty under no-ir, 6 GHz
    # regulatory_skip, and one populated frequency with two BSSIDs.
    return [
        ["2.4GHz", "2412", "1", "no-ir", "sampled", "10",
         "freq-2412.pcap", "2", "4", ""],
        ["2.4GHz", "2467", "12", "no-ir", "sampled_empty", "10",
         "freq-2467.pcap", "0", "0", ""],
        ["6GHz", "5955", "1", "disabled", "regulatory_skip", "0",
         "", "", "", "disabled by regulatory state"],
    ]


def world_obs_rows() -> list[list]:
    return [
        ["2.4GHz", "2412", "1", "aa:bb:cc:00:00:01", "TestNet", "2", "100",
         "-52", "-51.0", "-50", TS, TS, "0.333"],
        ["2.4GHz", "2412", "1", "aa:bb:cc:00:00:03", "OtherNet", "2", "100",
         "-70", "-66.5", "-63", TS, TS, "0.333"],
    ]


def make_instrument(
    run_id: str, *, schema: int, status: str, started_utc: str,
    domain: str, domain_phy: str | None = None,
    at_discovery: str | None = None, post_sweep: str | None = None,
    set_result: str | None = None, interface_present: bool = True,
) -> dict:
    doc: dict = {
        "schema": f"wifi-beacon-survey/instrument/{schema}",
        "run_status": status,
        "skip_reason": None,
        "started_utc": started_utc,
        "interface": "wlstub0",
        "interface_present": interface_present,
        "phy": "phy1",
        "regulatory_domain": domain,
        "regulatory_domain_phy": domain_phy,
        "usb": {
            "bus": "001", "port": "06", "device": "1-6",
            "controller_pci": "0000:00:14.0", "speed_mbps": "480",
            "driver": "mt7921u",
        },
        "capture": {
            "dwell_seconds": 10, "bands": "2.4 5 6", "snaplen": 1024,
            "bpf_filter": "type mgt subtype beacon",
        },
    }
    if schema == 2:
        doc.update({
            "regulatory_domain_declared": "US",
            "regulatory_domain_set_attempted": set_result is not None,
            "regulatory_domain_set_result": set_result,
            "regulatory_domain_at_discovery": at_discovery,
            "regulatory_domain_post_sweep": post_sweep,
        })
    return doc


class FixtureTree:
    """The frozen fixture set, built once into a scratch tree.

    The prefix shifts every run id's year digit so a second tree can
    coexist with the first in the same database without colliding.
    """

    def __init__(self, root: Path, prefix: str = "2026"):
        self.root = root
        self.prefix = prefix
        self._build()

    def _run(
        self, run_id: str, doc: dict, manifest: list[list] | None,
        obs: list[list] | None, truncate_freq: bool = False,
    ) -> Path:
        d = self.root / run_id
        d.mkdir(parents=True)
        (d / "instrument.json").write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8"
        )
        if manifest is None:
            # Skip/refused shape: header-only TSVs.
            write_tsv(d / "frequencies.tsv", FREQ_HEADER, [])
            write_tsv(d / "aggregate.tsv", OBS_HEADER, [])
            return d
        if truncate_freq:
            write_tsv(d / "frequencies.tsv", FREQ_HEADER,
                      [manifest[0][:5]])
        else:
            write_tsv(d / "frequencies.tsv", FREQ_HEADER, manifest)
        write_tsv(d / "aggregate.tsv", OBS_HEADER, obs or [])
        return d

    def _build(self) -> None:
        self.us_v1 = f"{self.prefix}0828-080003"
        self._run(
            self.us_v1,
            make_instrument(self.us_v1, schema=1, status="sweep",
                            started_utc="2026-08-28T12:00:03Z",
                            domain="US"),
            us_manifest_rows(), us_obs_rows(),
        )
        self.world_v1 = f"{self.prefix}0828-090003"
        self._run(
            self.world_v1,
            make_instrument(self.world_v1, schema=1, status="sweep",
                            started_utc="2026-08-28T13:00:03Z",
                            domain="00"),
            world_manifest_rows(), world_obs_rows(),
        )
        # PHY-override: global reads US, the self-managed PHY reads 00, and
        # the override wins. Same UTC hour as the world run: two attempts in
        # one slot.
        self.phy_override = f"{self.prefix}0828-100003"
        self._run(
            self.phy_override,
            make_instrument(self.phy_override, schema=1, status="sweep",
                            started_utc="2026-08-28T13:30:03Z",
                            domain="US", domain_phy="00"),
            us_manifest_rows(), us_obs_rows(),
        )
        # instrument/2 with post-sweep drift: routed to archive.
        self.v2_drift = f"{self.prefix}0828-110003"
        self._run(
            self.v2_drift,
            make_instrument(self.v2_drift, schema=2, status="sweep",
                            started_utc="2026-08-28T15:00:03Z",
                            domain="US", at_discovery="US",
                            post_sweep="00"),
            us_manifest_rows(), us_obs_rows(),
        )
        self.refused = f"{self.prefix}0828-120003"
        self._run(
            self.refused,
            make_instrument(self.refused, schema=2,
                            status="refused_regulatory_domain",
                            started_utc="2026-08-28T16:00:03Z",
                            domain="00", at_discovery="00",
                            set_result="failed"),
            None, None,
        )
        self.skipped = f"{self.prefix}0828-130003"
        self._run(
            self.skipped,
            make_instrument(self.skipped, schema=2,
                            status="skipped_no_interface",
                            started_utc="2026-08-28T17:00:03Z",
                            domain="US", interface_present=False),
            None, None,
        )
        self.failed = f"{self.prefix}0828-140003"
        self._run(
            self.failed,
            make_instrument(self.failed, schema=1, status="failed",
                            started_utc="2026-08-28T18:00:03Z",
                            domain="US"),
            None, None,
        )
        self.running = f"{self.prefix}0828-150003"
        self._run(
            self.running,
            make_instrument(self.running, schema=1, status="running",
                            started_utc="2026-08-28T19:00:03Z",
                            domain="US"),
            None, None,
        )
        self.malformed = f"{self.prefix}0828-160003"
        self._run(
            self.malformed,
            make_instrument(self.malformed, schema=1, status="sweep",
                            started_utc="2026-08-28T20:00:03Z",
                            domain="US"),
            us_manifest_rows(), us_obs_rows(), truncate_freq=True,
        )
        # Pre-series commissioning directory: excluded by the series start.
        (self.root / f"{self.prefix}0827-054734").mkdir()
        (self.root / f"{self.prefix}0827-054734" / "run.log").write_text(
            "commissioning\n", encoding="utf-8"
        )


def db_connect():
    import psycopg

    return psycopg.connect(
        host=os.environ["PGSQL01_HOST"],
        port=os.getenv("PGSQL01_PORT", "5432"),
        user=os.environ["PGSQL01_ADMIN_USER"],
        password=os.environ["PGSQL01_ADMIN_PASSWORD"],
        dbname=TEST_DB,
        autocommit=True,
    )


def table_digest(conn, table: str) -> str:
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table}")
        lines = [repr(row) for row in sorted(cur.fetchall(), key=repr)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def attempt_rows(conn) -> dict[str, tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, attempt_state, disposition FROM ingest.attempts"
        )
        return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def base_counts(conn) -> dict[str, int]:
    counts = {}
    with conn.cursor() as cur:
        for table in ("survey.runs", "survey.frequencies",
                      "survey.observations", "archive.runs",
                      "archive.frequencies", "archive.observations",
                      "ingest.loads"):
            cur.execute(f"SELECT count(*) FROM {table}")
            counts[table] = cur.fetchone()[0]
    return counts


@unittest.skipUnless(
    all(os.environ.get(v) for v in DB_ENV_VARS),
    "loader tests need pgsql01 credentials; run under the Doppler runtime",
)
class LoaderBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fixtures = FixtureTree(Path(cls.tmp.name))
        cls.conn = db_connect()
        with cls.conn.cursor() as cur:
            for table in ("survey.observations", "survey.frequencies",
                          "survey.runs", "archive.observations",
                          "archive.frequencies", "archive.runs",
                          "ingest.loads", "ingest.attempts", "ingest.slots"):
                cur.execute(f"TRUNCATE {table} CASCADE")
        ingest_load.drain(cls.conn, cls.fixtures.root, now=DRAIN_NOW)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def count_fixture_rows(self, run_id: str) -> tuple[int, int]:
        """Count a fixture's TSV data rows independently of the loader."""
        run_dir = self.fixtures.root / run_id
        with (run_dir / "frequencies.tsv").open(newline="") as fh:
            freq = sum(1 for row in csv.reader(fh, delimiter="\t") if row) - 1
        with (run_dir / "aggregate.tsv").open(newline="") as fh:
            obs = sum(1 for row in csv.reader(fh, delimiter="\t") if row) - 1
        return freq, obs

    def test_05_incomplete_hour_never_judged(self):
        # 21:00Z has no attempt. With the clock at :45 and at :59 inside
        # that hour, the hour is not expected and slot_health has no row
        # for it; once the hour ends, the drain creates it as no_run.
        hour = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
        for minute in (45, 59):
            slots = ingest_load.expected_slots(
                datetime(2026, 8, 28, 21, minute, tzinfo=timezone.utc)
            )
            self.assertNotIn(hour, slots)
        self.assertIn(
            hour,
            ingest_load.expected_slots(
                datetime(2026, 8, 28, 22, 0, tzinfo=timezone.utc)
            ),
        )
        ingest_load.drain(
            self.conn, self.fixtures.root,
            now=datetime(2026, 8, 28, 21, 59, tzinfo=timezone.utc),
        )
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingest.slots WHERE slot_utc_hour = %s",
                (hour,),
            )
            self.assertEqual(0, cur.fetchone()[0])
            cur.execute(
                "SELECT count(*) FROM derived.slot_health "
                "WHERE slot_utc_hour = %s",
                (hour,),
            )
            self.assertEqual(0, cur.fetchone()[0])
        ingest_load.drain(
            self.conn, self.fixtures.root,
            now=datetime(2026, 8, 28, 22, 0, tzinfo=timezone.utc),
        )
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT slot_state FROM derived.slot_health "
                "WHERE slot_utc_hour = %s",
                (hour,),
            )
            self.assertEqual([("no_run",)], cur.fetchall())

    def test_10_fixture_dispositions(self):
        rows = attempt_rows(self.conn)
        self.assertEqual(
            ("completed", "survey"), rows[self.fixtures.us_v1],
        )
        self.assertEqual(
            ("completed", "archive"), rows[self.fixtures.world_v1],
        )
        self.assertEqual(
            ("completed", "archive"), rows[self.fixtures.phy_override],
            "PHY-override must route on the phy country, not the global US",
        )
        self.assertEqual(
            ("completed", "archive"), rows[self.fixtures.v2_drift],
            "post-sweep drift must archive",
        )
        self.assertEqual(("refused", "not_loaded"), rows[self.fixtures.refused])
        self.assertEqual(
            ("receiver_absent_skip", "not_loaded"), rows[self.fixtures.skipped],
        )
        self.assertEqual(("failed", "not_loaded"), rows[self.fixtures.failed])
        self.assertEqual(("running", "pending"), rows[self.fixtures.running])
        self.assertEqual(
            ("malformed", "not_loaded"), rows[self.fixtures.malformed],
        )
        self.assertNotIn(
            f"{self.fixtures.prefix}0827-054734", rows,
            "pre-series directory must be excluded",
        )

    def test_20_two_attempts_share_one_slot_and_missing_hour_is_no_run(self):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT slot_utc_hour, count(*) FROM ingest.attempts
                WHERE run_id IN (%s, %s) GROUP BY slot_utc_hour
                """,
                (self.fixtures.world_v1, self.fixtures.phy_override),
            )
            self.assertEqual([(datetime(2026, 8, 28, 13, 0,
                                        tzinfo=timezone.utc), 2)],
                             cur.fetchall())
            cur.execute(
                """
                SELECT slot_state FROM derived.slot_health
                WHERE slot_utc_hour = %s
                """,
                (datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc),),
            )
            self.assertEqual([("no_run",)], cur.fetchall())

    def test_30_base_row_counts_match_independent_counts(self):
        counts = base_counts(self.conn)
        freq, obs = self.count_fixture_rows(self.fixtures.us_v1)
        self.assertEqual(1, counts["survey.runs"])
        self.assertEqual(freq, counts["survey.frequencies"])
        self.assertEqual(obs, counts["survey.observations"])
        freq, obs = self.count_fixture_rows(self.fixtures.world_v1)
        self.assertEqual(3, counts["archive.runs"])
        self.assertEqual(3 * freq, counts["archive.frequencies"])
        self.assertEqual(3 * obs, counts["archive.observations"])

    def test_40_negative_observations_present(self):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT sample_status, count(*) FROM archive.frequencies
                WHERE run_id = %s GROUP BY sample_status ORDER BY 1
                """,
                (self.fixtures.world_v1,),
            )
            self.assertEqual(
                [("regulatory_skip", 1), ("sampled", 1),
                 ("sampled_empty", 1)],
                cur.fetchall(),
            )

    def test_50_second_drain_is_a_noop(self):
        before = {t: table_digest(self.conn, t) for t in (
            "survey.runs", "survey.frequencies", "survey.observations",
            "archive.runs", "archive.frequencies", "archive.observations",
        )}
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingest.loads")
            loads_before = cur.fetchone()[0]
        report = ingest_load.drain(
            self.conn, self.fixtures.root, now=DRAIN_NOW
        )
        after = {t: table_digest(self.conn, t) for t in before}
        self.assertEqual(before, after, "a noop drain changed base rows")
        self.assertEqual(
            report["outcomes"].get("noop", 0),
            4, "four loaded runs must fingerprint as noops",
        )
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingest.loads")
            self.assertEqual(loads_before, cur.fetchone()[0])

    def test_60_source_changed_records_without_reload(self):
        freq_path = self.fixtures.root / self.fixtures.us_v1 / "frequencies.tsv"
        original = freq_path.read_text(encoding="utf-8")
        freq_path.write_text(
            original + "2.4GHz\t2437\t6\tpermitted\tsampled\t10\t"
            "freq-2437.pcap\t1\t1\t\n",
            encoding="utf-8",
        )
        try:
            # The CLI path must exit non-zero on the drain where the
            # source_changed first occurs.
            self.assertEqual(1, ingest_load.main([
                "--pilot-root", str(self.fixtures.root),
                "--database", TEST_DB,
            ]), "drain with a source_changed must exit non-zero")
            before = {t: table_digest(self.conn, t) for t in (
                "survey.frequencies", "survey.observations", "survey.runs",
            )}
            # Unchanged since the finding: a further drain is a no-op with
            # no new failure.
            report = ingest_load.drain(
                self.conn, self.fixtures.root, now=DRAIN_NOW
            )
            self.assertNotIn(
                (self.fixtures.us_v1, "source_changed"), report["failures"]
            )
            after = {t: table_digest(self.conn, t) for t in before}
            self.assertEqual(before, after, "source_changed reloaded base rows")
        finally:
            freq_path.write_text(original, encoding="utf-8")
        report = ingest_load.drain(
            self.conn, self.fixtures.root, now=DRAIN_NOW
        )
        # The source fingerprint is unchanged again, but the loads ledger
        # still carries source_changed as the latest outcome: the operator
        # decides, the loader never silently re-loads.
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT outcome FROM ingest.loads WHERE run_id = %s
                ORDER BY load_id
                """,
                (self.fixtures.us_v1,),
            )
            outcomes = [r[0] for r in cur.fetchall()]
        self.assertEqual(["loaded", "source_changed"], outcomes)
        self.assertNotIn(
            (self.fixtures.us_v1, "source_changed"), report["failures"]
        )

    def test_70_injected_failure_is_atomic_and_retry_loads(self):
        original = ingest_load.INSERT_HOOKS["observations"]

        def boom(cur, attempt):
            raise RuntimeError("injected failure after first insert")

        ingest_load.INSERT_HOOKS["observations"] = boom
        try:
            # Use the still-pending attempt so the failure applies to a run
            # with no prior load, after flipping it to terminal.
            inst = self.fixtures.root / self.fixtures.running / "instrument.json"
            doc = json.loads(inst.read_text(encoding="utf-8"))
            doc.update({
                "run_status": "sweep",
                "regulatory_domain_set_attempted": False,
                "regulatory_domain_set_result": "already_declared",
                "regulatory_domain_at_discovery": "US",
                "regulatory_domain_post_sweep": "US",
            })
            inst.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
            write_tsv(
                self.fixtures.root / self.fixtures.running / "frequencies.tsv",
                FREQ_HEADER, us_manifest_rows(),
            )
            write_tsv(
                self.fixtures.root / self.fixtures.running / "aggregate.tsv",
                OBS_HEADER, us_obs_rows(),
            )
            report = ingest_load.drain(
                self.conn, self.fixtures.root, now=DRAIN_NOW
            )
            self.assertIn(
                (self.fixtures.running, "failed"), report["failures"]
            )
            with self.conn.cursor() as cur:
                for table in ("survey.runs", "survey.frequencies",
                              "survey.observations"):
                    cur.execute(
                        f"SELECT count(*) FROM {table} WHERE run_id = %s",
                        (self.fixtures.running,),
                    )
                    self.assertEqual(0, cur.fetchone()[0], table)
                cur.execute(
                    """
                    SELECT outcome FROM ingest.loads WHERE run_id = %s
                    """,
                    (self.fixtures.running,),
                )
                self.assertEqual(["failed"], [r[0] for r in cur.fetchall()])
        finally:
            ingest_load.INSERT_HOOKS["observations"] = original
        ingest_load.drain(self.conn, self.fixtures.root, now=DRAIN_NOW)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT disposition FROM ingest.attempts WHERE run_id = %s",
                (self.fixtures.running,),
            )
            self.assertEqual([("survey",)], cur.fetchall())

    def test_80_host_domain_is_never_an_input(self):
        # The drain above ran on a host whose current domain reads US while
        # three fixtures record world evidence: their dispositions stayed
        # archive, which is the assertion. The mutation check imports a
        # scratch copy whose routing consults the host domain instead and
        # proves that change flips dispositions, so this suite guards the
        # property.
        mutated_source = (ROOT / "scripts" / "ingest_load.py").read_text(
            encoding="utf-8"
        ).replace(
            "def route_completed(doc: dict) -> str | None:\n"
            '    """The routing decision for a completed run, from the run'
            "'s own record.",
            "def route_completed(doc: dict) -> str | None:\n"
            "    return os.environ['FAKE_HOST_DOMAIN']\n"
            '    """The routing decision for a completed run, from the run'
            "'s own record.",
            1,
        )
        self.assertNotEqual(
            (ROOT / "scripts" / "ingest_load.py").read_text(encoding="utf-8"),
            mutated_source,
            "mutation anchor not found in ingest_load.py",
        )
        module_path = Path(self.tmp.name) / "mutated_load.py"
        module_path.write_text(mutated_source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "mutated_load", module_path
        )
        mutated = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mutated)

        mroot = Path(self.tmp.name) / "mutroot"
        mfixtures = FixtureTree(mroot, prefix="2027")
        os.environ["FAKE_HOST_DOMAIN"] = "US"
        try:
            mutated.drain(self.conn, mfixtures.root, now=DRAIN_NOW)
            rows = attempt_rows(self.conn)
            self.assertEqual(
                ("completed", "survey"), rows[mfixtures.world_v1],
                "mutation was not detected: host-domain routing did not "
                "change the disposition, so this test guards nothing",
            )
        finally:
            os.environ.pop("FAKE_HOST_DOMAIN", None)
            with self.conn.cursor() as cur:
                for table in ("survey.frequencies", "survey.observations",
                              "survey.runs", "archive.frequencies",
                              "archive.observations", "archive.runs",
                              "ingest.loads", "ingest.attempts"):
                    cur.execute(
                        f"DELETE FROM {table} WHERE run_id LIKE '2027%'"
                    )

    def test_90_concurrent_drains_end_in_one_state(self):
        procs = [
            subprocess.Popen(
                [
                    sys.executable, str(ROOT / "scripts" / "ingest_load.py"),
                    "--pilot-root", str(self.fixtures.root),
                    "--database", TEST_DB,
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for _ in range(2)
        ]
        for proc in procs:
            out, err = proc.communicate(timeout=300)
            self.assertEqual(0, proc.returncode, out + err)
        counts = base_counts(self.conn)
        self.assertEqual(2, counts["survey.runs"])
        self.assertEqual(3, counts["archive.runs"])
        freq, obs = self.count_fixture_rows(self.fixtures.us_v1)
        self.assertEqual(2 * freq, counts["survey.frequencies"])
        freq, obs = self.count_fixture_rows(self.fixtures.world_v1)
        self.assertEqual(3 * freq, counts["archive.frequencies"])

if __name__ == "__main__":
    unittest.main()
