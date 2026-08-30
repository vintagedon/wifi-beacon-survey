#!/usr/bin/env python3
"""Enrichment tests: replayable per-run Parquet, source identity, idempotence.

Builds synthetic pilot runs (tiny PCAPs with real IE bytes) into temp
directories and exercises the enrichment stage end-to-end. Requires tshark
and the shared venv; skips cleanly when tshark is absent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import _synthetic_pcap as synth  # noqa: E402

SCRIPT = ROOT / "scripts" / "pilot_enrich.py"
UPDATER = ROOT / "scripts" / "pilot-update.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def tshark_available() -> bool:
    import shutil as _shutil
    return _shutil.which("tshark") is not None


class EnrichmentTestBase(unittest.TestCase):
    """Shared setup: a synthetic pilot tree with one sweep-shaped run."""

    @classmethod
    def setUpClass(cls):
        if not tshark_available():
            raise unittest.SkipTest("tshark not available")
        cls.m = load_module(SCRIPT, "pilot_enrich_test")
        cls.contract = load_module(
            ROOT / "scripts" / "pilot_contract.py", "pilot_contract_test")
        cls.update = load_module(UPDATER, "pilot_update_test")
        cls.resolved, cls.unresolved = cls.m.resolve_requested_fields()
        cls.tshark_version = "test-tshark"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.pilot_root = self.base / "pilot"
        self.run_dir = self.pilot_root / "20260827-130002"
        synth.build_run_dir(self.run_dir)

    def classification(self, run_id="20260827-130002"):
        return self.contract.classify_pilot_child(self.pilot_root / run_id)

    def out_dir(self, run_id="20260827-130002"):
        """Versioned per-run derived directory, as the updater uses."""
        return self.contract.derived_runs_root(
            self.base / "derived") / run_id

    def enrich_default_run(self):
        return self.m.enrich_run(
            self.run_dir, self.out_dir(), self.classification(),
            resolved=self.resolved, unresolved=self.unresolved,
            tshark_version=self.tshark_version,
        )

    def read(self, out_dir: Path, table: str):
        import pyarrow.parquet as pq
        return pq.read_table(out_dir / f"{table}.parquet").to_pylist()


class EnrichedShapeTests(EnrichmentTestBase):

    def test_core_tables_replay_source_grain(self):
        result = self.enrich_default_run()
        self.assertEqual(result.status, "succeeded")
        out = self.out_dir()
        freq = self.read(out, "frequencies")
        obs = self.read(out, "observations")
        # One row per source TSV row, including sampled_empty and the 6 GHz
        # negative observation.
        self.assertEqual(len(freq), 3)
        self.assertEqual(len(obs), 4)
        empty_6g = [f for f in freq if f["band"] == "6GHz"]
        self.assertEqual(len(empty_6g), 1)
        self.assertEqual(empty_6g[0]["sample_status"], "sampled_empty")
        self.assertEqual(empty_6g[0]["beacon_count"], 0)
        # Source row order preserved exactly (grain = one row per source row).
        source_bssids = [
            line.split("\t")[3]
            for line in (self.run_dir / "aggregate.tsv")
            .read_text().splitlines()[1:]
        ]
        self.assertEqual([o["bssid"] for o in obs], source_bssids)

    def test_capability_presence_from_extension_namespace(self):
        self.enrich_default_run()
        out = self.out_dir()
        caps = {r["bssid"]: r for r in self.read(out, "ie_capabilities")}
        self.assertIn(synth.AP1, caps)
        ap1 = caps[synth.AP1]
        # Derived from resolved ext elements, never from tag.number == 255.
        self.assertTrue(ap1["has_he"])
        self.assertTrue(ap1["has_he_6ghz"])
        self.assertTrue(ap1["has_eht"])
        self.assertTrue(ap1["has_mld"])
        self.assertTrue(ap1["has_rnr"])
        self.assertTrue(ap1["has_bss_load"])
        self.assertEqual(ap1["ext_elements"], "35,59,106,107,108")
        # A BSSID with no capability elements still appears as observed.
        self.assertIn(synth.AP3, caps)
        self.assertFalse(caps[synth.AP3]["has_rnr"])
        self.assertEqual(caps[synth.AP3]["elements"], "0")

    def test_rnr_grains_and_safety(self):
        self.enrich_default_run()
        out = self.out_dir()
        rows = self.read(out, "rnr")
        by_tx = {}
        for row in rows:
            by_tx.setdefault(row["tx_bssid"], []).append(row)
        # AP1: safe single occurrences carry the normalized target band.
        ap1 = by_tx[synth.AP1]
        self.assertEqual(len(ap1), 2)
        for row in ap1:
            self.assertEqual(row["structure_status"], "single_occurrence")
            self.assertEqual(row["target_band"], "2.4GHz")
            self.assertEqual(row["target_frequency_mhz"], 2422)
            self.assertEqual(row["neighbor_bssid"], "00:00:00:11:22:33")
        # AP2's first frame carries one element with two neighbors: still
        # ONE frame-grain row, structurally ambiguous, raw cells preserved,
        # and no normalized target invented.
        ap2 = by_tx[synth.AP2]
        ambiguous = [r for r in ap2
                     if r["structure_status"] == "unpaired_multi_occurrence"]
        self.assertEqual(len(ambiguous), 1)
        row = ambiguous[0]
        # tshark dedupes identical adjacent occurrences, so the two
        # neighbors' shared operating class arrives as one value; the
        # distinct short SSIDs keep the comma that marks the ambiguity.
        self.assertIn(",", row["raw_short_ssid"])
        self.assertIn("rnr_short_ssid", row["unpaired_fields"])
        self.assertIsNone(row["target_band"])
        self.assertIsNone(row["target_frequency_mhz"])
        # AP2's second frame safely pairs a disabled 6 GHz link.
        disabled = [r for r in ap2
                    if r["structure_status"] == "single_occurrence"]
        self.assertEqual(len(disabled), 1)
        self.assertEqual(disabled[0]["target_band"], "6GHz")
        self.assertIn(disabled[0]["disabled_link"], ("True", "true", "1"))
        # AP4: single 6 GHz neighbor advertisement resolves to 6 GHz.
        ap4 = by_tx[synth.AP4]
        self.assertEqual(len(ap4), 1)
        self.assertEqual(ap4[0]["target_band"], "6GHz")
        self.assertEqual(ap4[0]["target_frequency_mhz"], 5975)

    def test_bss_load_rows_carry_packet_identity(self):
        self.enrich_default_run()
        out = self.out_dir()
        rows = self.read(out, "bss_load")
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row["pcap_file"])
            self.assertIsInstance(row["frame_number"], int)
            self.assertTrue(row["frame_time_epoch"])
            self.assertEqual(row["bssid"], synth.AP1)
            self.assertEqual(row["station_count"], 7)
            self.assertEqual(row["utilization"], 42)
            self.assertEqual(row["admission_capacity"], 300)
            # Raw cells preserved alongside parsed values.
            self.assertEqual(row["raw_utilization"], "42")

    def test_field_resolution_records_every_requested_field(self):
        self.enrich_default_run()
        out = self.out_dir()
        rows = self.read(out, "field_resolution")
        logical = {r["logical_name"] for r in rows}
        self.assertTrue(set(self.m.REQUESTED_FIELDS) <= logical)
        by_name = {r["logical_name"]: r for r in rows}
        for name in self.m.REQUESTED_FIELDS:
            row = by_name[name]
            if name in self.resolved:
                self.assertEqual(row["status"], "resolved")
                self.assertEqual(row["resolved_field"],
                                 self.resolved[name])
            else:
                self.assertEqual(row["status"], "unresolved")
                self.assertIn(name, row["candidates"])


class ManifestAndIdentityTests(EnrichmentTestBase):

    def test_manifest_hashes_and_rows_recompute(self):
        result = self.enrich_default_run()
        self.assertEqual(result.status, "succeeded")
        out = self.out_dir()
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "succeeded")
        self.assertEqual(manifest["schema_id"],
                         self.contract.DERIVED_SCHEMA_ID)
        for entry in manifest["outputs"]:
            path = out / entry["name"]
            self.assertTrue(path.is_file())
            self.assertEqual(self.m.sha256_file(path), entry["sha256"])
            import pyarrow.parquet as pq
            self.assertEqual(pq.read_metadata(path).num_rows, entry["rows"])
        # Source identity covers the TSVs, instrument.json, and every PCAP.
        names = {f["name"] for f in manifest["source_files"]}
        self.assertIn("frequencies.tsv", names)
        self.assertIn("aggregate.tsv", names)
        self.assertIn("instrument.json", names)
        self.assertIn("freq-2412.pcap", names)
        for entry in manifest["source_files"]:
            path = self.run_dir / entry["name"]
            self.assertEqual(path.stat().st_size, entry["size"])
            self.assertEqual(self.m.sha256_file(path), entry["sha256"])

    def test_enrichment_does_not_mutate_evidence(self):
        before = {
            p.name: (self.m.sha256_file(p), p.stat().st_size)
            for p in sorted(self.run_dir.glob("*"))
        }
        self.enrich_default_run()
        after = {
            p.name: (self.m.sha256_file(p), p.stat().st_size)
            for p in sorted(self.run_dir.glob("*"))
        }
        self.assertEqual(before, after)

    def test_atomic_manifest_never_left_half_written(self):
        self.enrich_default_run()
        out = self.out_dir()
        self.assertTrue((out / "manifest.json").is_file())
        self.assertFalse((out / ("manifest.json.tmp")).exists())


class UpdaterBehaviorTests(EnrichmentTestBase):

    def updater_enrich(self):
        return self.update.enrich_stage(self.pilot_root,
                                        self.base / "derived")

    def test_updater_processes_new_run_exactly_once(self):
        summaries = self.updater_enrich()
        self.assertEqual([s["run_id"] for s in summaries],
                         ["20260827-130002"])
        self.assertEqual(summaries[0]["outcome"], "processed")
        self.assertTrue(
            (self.out_dir() / "manifest.json").is_file())

    def test_unchanged_run_is_not_reparsed(self):
        self.updater_enrich()
        out = self.out_dir()
        before = {
            p.name: self.m.sha256_file(p) for p in sorted(out.glob("*"))
        }
        summaries = self.updater_enrich()
        self.assertEqual(summaries[0]["outcome"], "unchanged")
        after = {
            p.name: self.m.sha256_file(p) for p in sorted(out.glob("*"))
        }
        self.assertEqual(before, after)

    def test_changed_source_is_detected_and_reprocessed(self):
        self.updater_enrich()
        out = self.out_dir()
        old_manifest = json.loads((out / "manifest.json").read_text())
        # Mutate one source TSV value in the scratch copy. Source identity is
        # recomputed from files, so this cannot pass as the old run.
        agg = self.run_dir / "aggregate.tsv"
        text = agg.read_text().replace("TestNet", "Renamed")
        agg.write_text(text)
        summaries = self.updater_enrich()
        self.assertEqual(summaries[0]["outcome"], "processed")
        new_manifest = json.loads((out / "manifest.json").read_text())
        new_identity = {f["name"]: f["sha256"]
                        for f in new_manifest["source_files"]}
        old_identity = {f["name"]: f["sha256"]
                        for f in old_manifest["source_files"]}
        self.assertNotEqual(new_identity, old_identity)
        self.assertNotEqual(new_identity["aggregate.tsv"],
                            old_identity["aggregate.tsv"])

    def test_added_run_is_processed_and_others_left_alone(self):
        self.updater_enrich()
        first_out = self.out_dir() / "manifest.json"
        first_mtime = first_out.read_text()
        second = self.pilot_root / "20260827-140002"
        synth.build_run_dir(second)
        summaries = self.updater_enrich()
        self.assertEqual(len(summaries), 2)
        by_id = {s["run_id"]: s for s in summaries}
        self.assertEqual(by_id["20260827-130002"]["outcome"], "unchanged")
        self.assertEqual(by_id["20260827-140002"]["outcome"], "processed")
        self.assertEqual(first_out.read_text(), first_mtime)

    def test_running_run_is_deferred_not_enriched(self):
        instrument = self.run_dir / "instrument.json"
        doc = json.loads(instrument.read_text())
        doc["run_status"] = "running"
        instrument.write_text(json.dumps(doc))
        summaries = self.updater_enrich()
        self.assertEqual(summaries[0]["outcome"], "deferred")
        self.assertFalse((self.out_dir() / "manifest.json").exists())

    def test_skip_record_enriches_to_zero_row_artifacts(self):
        instrument = self.run_dir / "instrument.json"
        doc = json.loads(instrument.read_text())
        doc["run_status"] = "skipped_no_interface"
        instrument.write_text(json.dumps(doc))
        for name in ("freq-2412.pcap", "freq-2437.pcap", "freq-5955.pcap"):
            (self.run_dir / name).unlink()
        agg = self.run_dir / "aggregate.tsv"
        agg.write_text(agg.read_text().splitlines()[0] + "\n")
        freq = self.run_dir / "frequencies.tsv"
        freq.write_text(freq.read_text().splitlines()[0] + "\n")
        result = self.m.enrich_run(
            self.run_dir, self.out_dir(),
            self.classification(),
            resolved=self.resolved, unresolved=self.unresolved,
            tshark_version=self.tshark_version,
        )
        self.assertEqual(result.status, "succeeded")
        out = self.out_dir()
        self.assertEqual(len(self.read(out, "frequencies")), 0)
        self.assertEqual(len(self.read(out, "observations")), 0)
        self.assertEqual(len(self.read(out, "ie_capabilities")), 0)


class FailureSemanticsTests(EnrichmentTestBase):

    def test_unresolved_field_is_distinct_from_observed_zero(self):
        # Drop every RNR candidate from the resolved set: the field never
        # existed on this hypothetical build.
        resolved = {k: v for k, v in self.resolved.items()
                    if not k.startswith("rnr_")}
        unresolved = dict(self.unresolved)
        unresolved["rnr_op_class"] = list(
            self.m.REQUESTED_FIELDS["rnr_op_class"])
        self.m.enrich_run(
            self.run_dir, self.out_dir(), self.classification(),
            resolved=resolved, unresolved=unresolved,
            tshark_version=self.tshark_version,
        )
        rows = self.read(self.out_dir(), "field_resolution")
        by_name = {r["logical_name"]: r for r in rows}
        self.assertEqual(by_name["rnr_op_class"]["status"], "unresolved")
        self.assertEqual(
            by_name["rnr_op_class"]["candidates"],
            ",".join(self.m.REQUESTED_FIELDS["rnr_op_class"]))
        # Frames that carried element 201 are still recorded as frames, but
        # every unresolvable value is null -- never a zero, never a count of
        # advertisements the build could not read.
        rnr_rows = self.read(self.out_dir(), "rnr")
        self.assertTrue(rnr_rows)
        for row in rnr_rows:
            self.assertIsNone(row["op_class"])
            self.assertIsNone(row["neighbor_bssid"])
            self.assertEqual(row["field_resolution_state"],
                             "unresolved_candidates")

    def test_missing_frame_identity_fails_validation(self):
        # A build that cannot resolve frame.time_epoch must refuse to emit
        # BSS Load rows that would look longitudinal without packet time.
        resolved = {k: v for k, v in self.resolved.items()
                    if k != "frame_time_epoch"}
        result = self.m.enrich_run(
            self.run_dir, self.out_dir(), self.classification(),
            resolved=resolved, unresolved=self.unresolved,
            tshark_version=self.tshark_version,
        )
        self.assertEqual(result.status, "partial")
        self.assertTrue(any("frame_time_epoch" in e
                            for e in result.manifest["errors"]))
        # No apparently-longitudinal rows may exist.
        self.assertEqual(len(self.read(self.out_dir(), "bss_load")), 0)
        self.assertEqual(len(self.read(self.out_dir(), "rnr")), 0)

    def test_unreadable_source_tsv_records_failure(self):
        (self.run_dir / "frequencies.tsv").write_text("", encoding="utf-8")
        out_dir = self.out_dir()
        result = self.m.enrich_run(
            self.run_dir, out_dir, self.classification(),
            resolved=self.resolved, unresolved=self.unresolved,
            tshark_version=self.tshark_version,
        )
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.manifest["errors"])


if __name__ == "__main__":
    unittest.main()
