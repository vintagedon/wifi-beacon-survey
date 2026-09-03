#!/usr/bin/env python3
"""
Script Name  : pilot_report.py
Description  : Renders the deterministic pilot technical briefing from the
               DuckDB projection and the contract classifications
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-08-28
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
Renders `reports/pilot-latest.md`: a compact technical readout for the
operator and AI collaborators. The report is generated from fixed templates
and SQL results -- no LLM call, no network service, no wall-clock prose. For
a fixed source and code version the output is byte-identical and diffable;
its cutoff and `as of` value come from the latest included source event, not
from the clock.

Every numerical claim carries its numerator and denominator or names the view
row that holds both. Advertised-but-not-observed neighbors are always
qualified `nonconcurrent`: a sequential sweep cannot produce a calibrated
miss or a sensitivity conclusion. If an advanced surface is unavailable for a
run, the affected section says exactly that and never reuses stale values.

Writes are atomic: the briefing is rendered to a temporary file on the same
filesystem, validated, and only then moved over the canonical report.

Usage
-----
    Imported by pilot-update.py; also usable directly:

    python3 pilot_report.py [--pilot-root DIR] [--derived-root DIR]
                            [--reports-dir DIR] [--now ISO-DATETIME]
"""

# =============================================================================
# Imports
# =============================================================================

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import duckdb

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

RUN_TABLE_LIMIT = 12  # bounded per-run table; older runs summarized in totals

BAND_ORDER = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}


# =============================================================================
# Query helpers
# =============================================================================


def _connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def _rows(con, sql: str) -> list[tuple]:
    return con.execute(sql).fetchall()


def _fmt_pct(numerator: int, denominator: int) -> str:
    """Format a percentage that always shows both numbers."""
    if denominator == 0:
        return f"{numerator}/0 (no denominator)"
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.1f}%)"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2


# =============================================================================
# Report assembly
# =============================================================================


def _gather(db_path: Path, pilot_root: Path, reports_dir: Path,
            derived_root: Path) -> dict:
    """Collect every query result the report renders."""
    con = _connect(db_path)
    try:
        data = {}
        data["runs"] = _rows(con, """
            SELECT run_id, attempt_state, started_utc, extraction_status,
                   input_complete, tshark_version
            FROM pilot_runs ORDER BY run_id""")
        data["health_rows"] = _rows(con, """
            SELECT run_id, state, eligible, in_trend, reason, started_utc,
                   input_complete, extraction_status
            FROM pilot_run_health ORDER BY run_id""")
        data["coverage"] = _rows(con, """
            SELECT band,
                   SUM(populated_frequencies), SUM(sampled_empty_frequencies),
                   SUM(regulatory_skips), SUM(capture_errors),
                   SUM(attempted_frequencies), SUM(observed_bssids),
                   SUM(beacon_frames)
            FROM pilot_band_metrics GROUP BY band""")
        data["hourly"] = _rows(con, """
            SELECT run_id, started_utc, observed_bssids, beacon_frames,
                   sampled_frequencies, sampled_empty_frequencies,
                   manifest_frequencies, mean_rssi_dbm
            FROM pilot_hourly_metrics ORDER BY run_id""")
        data["capabilities_latest"] = _rows(con, """
            SELECT run_id, observed_bssids,
                   advertises_he, advertises_he_6ghz, advertises_eht,
                   advertises_mld, advertises_multiple_bssid
            FROM pilot_capability_metrics
            ORDER BY run_id DESC LIMIT 1""")
        data["capabilities_totals"] = _rows(con, """
            SELECT
                SUM(advertises_he), SUM(advertises_he_6ghz),
                SUM(advertises_eht), SUM(advertises_mld),
                SUM(advertises_multiple_bssid), SUM(carries_rnr),
                SUM(carries_bss_load), SUM(observed_bssids)
            FROM pilot_capability_metrics""")
        data["unresolved_fields"] = _rows(con, """
            SELECT DISTINCT logical_name FROM pilot_field_resolution
            WHERE status = 'unresolved' ORDER BY logical_name""")
        data["ambiguity"] = _rows(con, """
            SELECT COUNT(*), COUNT(DISTINCT run_id) FROM pilot_rnr
            WHERE structure_status = 'unpaired_multi_occurrence'""")
        data["bss_load"] = _rows(con, """
            SELECT COUNT(*), COUNT(DISTINCT bssid), MIN(station_count),
                   MAX(station_count), MIN(utilization), MAX(utilization),
                   COUNT(DISTINCT run_id)
            FROM pilot_bss_load""")
        data["extraction_failures"] = _rows(con, """
            SELECT run_id, extraction_status, error FROM pilot_runs
            WHERE extraction_status IN ('partial', 'failed')
            ORDER BY run_id""")
        data["6ghz_latest"] = _rows(con, """
            SELECT * FROM pilot_6ghz_evidence ORDER BY run_id DESC LIMIT 1""")
        data["6ghz_totals"] = _rows(con, """
            SELECT
                SUM(direct_bssids), SUM(direct_beacons),
                SUM(sampled_frequencies), SUM(sampled_empty_frequencies),
                SUM(manifest_frequencies), SUM(advertised_6ghz_neighbors),
                SUM(advertised_6ghz_disabled_links),
                SUM(unresolved_operating_classes), SUM(ambiguous_rnr_rows),
                SUM(advertised_not_observed_nonconcurrent)
            FROM pilot_6ghz_evidence""")
        data["view_names"] = list(pilot.VIEW_NAMES)
    finally:
        con.close()

    # Commissioning summary straight from the source files: these runs are
    # not part of the derived layer and never enter trend queries.
    commissioning = []
    for run_id in pilot.COMMISSIONING_RUNS:
        run_dir = pilot_root / run_id
        freq_path = run_dir / "frequencies.tsv"
        agg_path = run_dir / "aggregate.tsv"
        entry = {"run_id": run_id, "present": freq_path.is_file()}
        if freq_path.is_file():
            lines = freq_path.read_text().splitlines()[1:]
            rows = [line.split("\t") for line in lines if line.strip()]
            entry["frequencies"] = len(rows)
            entry["sampled"] = sum(1 for r in rows
                                   if len(r) > 4 and r[4] == "sampled")
        if agg_path.is_file():
            lines = agg_path.read_text().splitlines()[1:]
            entry["observations"] = len(lines)
            entry["bssids"] = len({line.split("\t")[3]
                                   for line in lines if line.strip()})
        commissioning.append(entry)
    data["commissioning"] = commissioning
    data["pilot_root"] = pilot_root
    data["derived_root"] = derived_root
    data["db_path"] = db_path
    data["report_path"] = pilot.canonical_report_path(reports_dir)
    return data


def _render(data: dict, now: datetime | None) -> str:
    """Render the full briefing. Deterministic for fixed inputs."""
    # Eligibility-aware health counts: commissioning rows carry the
    # completed-sweep state but count separately, never as pilot attempts.
    state_counts: dict[str, int] = {}
    covered_hours: set[str] = set()
    for row in data["health_rows"]:
        run_id, state, eligible = row[0], row[1], row[2]
        if not eligible and state == "completed_sweep":
            state_counts["commissioning_reference"] = \
                state_counts.get("commissioning_reference", 0) + 1
            continue
        state_counts[state] = state_counts.get(state, 0) + 1
        if state != "missing_hourly_slot":
            covered_hours.add(f"{run_id[:8]}-{run_id[9:11]}")
    expected = state_counts.get("missing_hourly_slot", 0) + len(covered_hours)
    discovered = sum(count for state, count in state_counts.items()
                     if state != "missing_hourly_slot"
                     and state != "commissioning_reference")
    hourly = data["hourly"]
    latest_hourly = hourly[-1] if hourly else None
    latest_run = data["runs"][-1] if data["runs"] else None

    # Cutoff: the latest included source event -- an event from a run the
    # derived layer actually carries -- never the wall clock. A newer
    # attempt still `running` is reported in health but is not included.
    cutoff_sources = [r[2] for r in data["runs"] if r[2]]
    cutoff = max(cutoff_sources) if cutoff_sources else "no source events"
    latest_input = data["health_rows"][-1][0] if data["health_rows"] else "n/a"
    last_success = latest_hourly[0] if latest_hourly else "none yet"
    report_dir = data["report_path"].parent
    docs_dir = _SCRIPTS_DIR.parent / "docs"
    contract_link = Path(os.path.relpath(
        docs_dir / "pilot-analysis-contract.md", report_dir
    )).as_posix()
    collection_review_link = Path(os.path.relpath(
        docs_dir / "2026-08-27-hourly-collection-review.md", report_dir
    )).as_posix()

    lines: list[str] = []
    add = lines.append

    date = str(cutoff)[:10] if cutoff and cutoff != "no source events" \
        else "1970-01-01"
    add("<!--")
    add("---")
    add('title: "Pilot Technical Briefing"')
    add('description: "Generated collection-health and longitudinal readout for the hourly Wi-Fi beacon pilot"')
    add('author: "VintageDon (https://github.com/vintagedon/)"')
    add(f'date: "{date}"')
    add('version: "1.0"')
    add('status: "Generated"')
    add("tags:")
    add("  - type: report")
    add("  - domain: dataset")
    add("  - tech: [python, duckdb, markdown]")
    add("related_documents:")
    add(f'  - "[Pilot Analysis Contract]({contract_link})"')
    add(f'  - "[Hourly Collection Review]({collection_review_link})"')
    add("---")
    add("-->")
    add("")
    add("# Pilot Technical Briefing")
    add("")
    add("Generated from the versioned derived layer by `scripts/pilot_report.py`.")
    add("This file is regenerated after every collection attempt; treat the")
    add("retained PCAP as the source of record.")
    add("")

    # -- 1. Scope and cutoff -------------------------------------------------
    add("## 1. Scope and cutoff")
    add("")
    add(f"- Approved series start: `{pilot.PILOT_SERIES_START}`")
    add(f"- Latest input included: `{latest_input}`")
    add(f"- Most recent successful sweep: `{last_success}`")
    add(f"- Commissioning runs shown separately, excluded from trends: "
        f"{', '.join(f'`{r}`' for r in pilot.COMMISSIONING_RUNS)}")
    add(f"- Derived schema: `{pilot.DERIVED_SCHEMA_ID}` "
        f"(extractor `{pilot.EXTRACTOR_VERSION}`, "
        f"tshark {latest_run[5] if latest_run else 'unknown'})")
    add(f"- Data cutoff (latest included source event): {cutoff}")
    add("")

    # -- 2. Collection health ------------------------------------------------
    add("## 2. Collection health")
    add("")
    add("| Metric | Value |")
    add("|--------|-------|")
    add(f"| Commissioning runs (excluded from all counts below) | "
        f"{state_counts.get('commissioning_reference', 0)} |")
    add(f"| Expected hourly slots | {expected} |")
    add(f"| Discovered attempts | {discovered} |")
    add(f"| Completed sweeps | {state_counts.get('completed_sweep', 0)} |")
    add(f"| Skipped (receiver absent) | {state_counts.get('skipped_no_interface', 0)} |")
    add(f"| Failed | {state_counts.get('failed', 0)} |")
    add(f"| Running | {state_counts.get('running', 0)} |")
    add(f"| Malformed/incomplete | {state_counts.get('malformed', 0)} |")
    add(f"| Missing hourly slots | {state_counts.get('missing_hourly_slot', 0)} |")
    if latest_run:
        add(f"| Last discovered attempt | `{latest_run[0]}` ({latest_run[1]}) |")
    statuses = {}
    for run in data["runs"]:
        statuses[run[3]] = statuses.get(run[3], 0) + 1
    status_text = ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items()))
    add(f"| Derivation status | {status_text or 'none'} |")
    add("")

    # -- 3. Coverage ----------------------------------------------------------
    add("## 3. Coverage")
    add("")
    add("Trend runs only. *Populated* = sampled with at least one beacon;")
    add("*attempted* = every manifest row (denominator for the bands below).")
    add("")
    add("| Band | Attempted | Sampled | Sampled-empty | Regulatory skip |"
        " Capture error | BSSIDs | Beacons |")
    add("|------|-----------|---------|---------------|-----------------|"
        "---------------|--------|---------|")
    for band, sampled, empty, skips, errors, attempted, bssids, beacons \
            in sorted(data["coverage"], key=lambda r: BAND_ORDER.get(r[0], 9)):
        add(f"| {band} | {attempted} | {sampled} | {empty} | {skips} | "
            f"{errors} | {bssids} | {beacons} |")
    add("")

    # -- 4. Longitudinal snapshot ---------------------------------------------
    add("## 4. Longitudinal snapshot")
    add("")
    add(f"Trend runs: {len(hourly)} "
        f"(denominator: `pilot_hourly_metrics`, commissioning excluded).")
    add("")
    if hourly:
        bssid_counts = [r[2] for r in hourly]
        beacon_counts = [r[3] for r in hourly]
        add(f"- Unique BSSIDs per run: latest {bssid_counts[-1]}, "
            f"min {min(bssid_counts)}, median {_median(bssid_counts):.0f}, "
            f"max {max(bssid_counts)}")
        add(f"- Beacon frames per run: latest {beacon_counts[-1]}, "
            f"min {min(beacon_counts)}, median {_median(beacon_counts):.0f}, "
            f"max {max(beacon_counts)}")
        add("")
        add(f"Per-run detail, last {min(len(hourly), RUN_TABLE_LIMIT)} of "
            f"{len(hourly)} trend runs (full series in `pilot_hourly_metrics`):")
        add("")
        add("| Run | BSSIDs | Beacons | Sampled | Sampled-empty | Mean RSSI dBm |")
        add("|-----|--------|---------|---------|---------------|---------------|")
        for run_id, _started, bssids, beacons, sampled, empty, _total, rssi \
                in hourly[-RUN_TABLE_LIMIT:]:
            rssi_text = f"{rssi:.1f}" if rssi is not None else "n/a"
            add(f"| `{run_id}` | {bssids} | {beacons} | {sampled} | {empty} | "
                f"{rssi_text} |")
        omitted = len(hourly) - min(len(hourly), RUN_TABLE_LIMIT)
        if omitted > 0:
            add(f"\n({omitted} earlier trend runs omitted from this table; "
                "totals above cover all of them.)")
    else:
        add("No trend runs available.")
    add("")

    # -- 5. Capability advertisements ------------------------------------------
    add("## 5. Capability advertisements")
    add("")
    add("*Advertises* reports what the AP sent in its beacons. It is not a")
    add("certification claim or a device-generation estimate.")
    add("")
    if data["capabilities_totals"]:
        row = data["capabilities_totals"][0]
        (he, he6, eht, mld, mbssid, rnr, qbss, denom) = row
        denom = denom or 0
        add(f"Across all {len(hourly)} trend runs, against a denominator of "
            f"{denom} observed BSSID capability rows (`denominator` = rows in"
            " `pilot_capability_metrics`):")
        add("")
        add("| Capability | Advertises | Denominator |")
        add("|------------|-----------|-------------|")
        add(f"| HE (Wi-Fi 6) | {he or 0} | {denom} |")
        add(f"| HE 6 GHz (Wi-Fi 6E) | {he6 or 0} | {denom} |")
        add(f"| EHT (Wi-Fi 7) | {eht or 0} | {denom} |")
        add(f"| Multi-Link (EHT MLO) | {mld or 0} | {denom} |")
        add(f"| Multiple BSSID | {mbssid or 0} | {denom} |")
        add(f"| RNR carried | {rnr or 0} | {denom} |")
        add(f"| BSS Load carried | {qbss or 0} | {denom} |")
        add("")
        if data["capabilities_latest"]:
            run_id, denom, he_n, he6_n, eht_n, mld_n, mbssid_n = \
                data["capabilities_latest"][0]
            add(f"Latest trend run `{run_id}`: "
                f"{_fmt_pct(he_n or 0, denom or 0)} advertise HE, "
                f"{_fmt_pct(he6_n or 0, denom or 0)} advertise HE 6 GHz, "
                f"{_fmt_pct(eht_n or 0, denom or 0)} advertise EHT, "
                f"{_fmt_pct(mld_n or 0, denom or 0)} advertise Multi-Link, "
                f"{_fmt_pct(mbssid_n or 0, denom or 0)} advertise Multiple "
                "BSSID (numerator/denominator from "
                "`pilot_capability_metrics`).")
            add("")
    else:
        add("No capability metrics available.")
    add("")

    # -- 6. RNR and 6 GHz evidence ---------------------------------------------
    add("## 6. RNR and 6 GHz evidence")
    add("")
    if data["6ghz_totals"]:
        row = data["6ghz_totals"][0]
        (d_bssids, d_beacons, sampled, sampled_empty, manifest_freqs,
         advertised, disabled, unresolved_oc, ambiguous, not_observed) = row
        add("Across all trend runs:")
        add("")
        add(f"- Direct 6 GHz beacon observations: {d_bssids or 0} BSSIDs, "
            f"{d_beacons or 0} frames "
            f"(`pilot_6ghz_evidence.direct_bssids`/`direct_beacons`)")
        add(f"- 6 GHz frequencies sampled-empty: {sampled_empty or 0} of "
            f"{manifest_freqs or 0} manifest rows -- recorded negative"
            " observations, not gaps")
        add(f"- RNR-advertised 6 GHz neighbors: {advertised or 0} "
            f"(lower bound; excludes {ambiguous or 0} structurally "
            "ambiguous RNR frames)")
        add(f"- Advertised 6 GHz links flagged disabled: {disabled or 0}")
        add(f"- Unresolved 6 GHz operating classes: {unresolved_oc or 0}")
        add(f"- Advertised-but-not-observed (nonconcurrent): {not_observed or 0}")
        add("")
        if (d_bssids or 0) == 0:
            add("No 6 GHz beacons were directly observed in this window.")
            add("This states only the direct observation count: it is not a")
            add("claim that no 6 GHz AP exists and not evidence that the")
            add("receiver is calibrated for 6 GHz. An advertised neighbor")
            add("that was not observed in a later sequential dwell is")
            add("**nonconcurrent** timing-aware evidence -- not a miss rate,")
            add("not a sensitivity measurement, and not a dwell conclusion.")
        else:
            add("Advertised-but-not-observed neighbors are nonconcurrent")
            add("sequential evidence and never a calibrated miss rate.")
        add("")
    else:
        add("No 6 GHz evidence view rows available.")
    add("")

    # -- 7. BSS Load ------------------------------------------------------------
    add("## 7. BSS Load")
    add("")
    if data["bss_load"] and data["bss_load"][0][0]:
        frames, bssids, stn_min, stn_max, util_min, util_max, runs = \
            data["bss_load"][0]
        add(f"{frames} beacon frames across {bssids} BSSIDs in {runs}")
        add("enriched runs carried a BSS Load element (`pilot_bss_load`)."
            " Station")
        add(f"count ranged {stn_min}-{stn_max}; channel utilization ranged")
        add(f"{util_min}-{util_max} of 255 "
            f"({util_min}/255 = {100 * (util_min or 0) / 255:.1f}%; "
            f"{util_max}/255 = {100 * (util_max or 0) / 255:.1f}%).")
        add("")
        add("These values are **advertised by the AP** -- its own association")
        add("count and its own sensed medium busy fraction. They are not")
        add("receiver-measured congestion.")
    else:
        add("No BSS Load elements were extracted in this window.")
    add("")

    # -- 8. Data-quality findings ------------------------------------------------
    add("## 8. Data-quality findings")
    add("")
    findings: list[str] = []
    if data["unresolved_fields"]:
        names = ", ".join(f"`{r[0]}`" for r in data["unresolved_fields"])
        findings.append(
            f"Unresolved tshark fields (extraction-quality finding, distinct "
            f"from an observed zero): {names}")
    amb_frames, amb_runs = data["ambiguity"][0] if data["ambiguity"] \
        else (0, 0)
    if amb_frames:
        findings.append(
            f"{amb_frames} structurally ambiguous RNR frame rows across "
            f"{amb_runs} runs; retained unpaired, never positionally paired")
    for run_id, status, error in data["extraction_failures"]:
        findings.append(
            f"Derivation `{status}` for `{run_id}`: {error or 'no detail'}")
    for state in ("failed", "malformed", "running"):
        n = state_counts.get(state, 0)
        if n:
            findings.append(f"{n} attempt(s) in state `{state}`")
    missing = state_counts.get("missing_hourly_slot", 0)
    if missing:
        missing_ids = ", ".join(
            f"`{r[0]}`" for r in data["health_rows"]
            if r[1] == "missing_hourly_slot")
        findings.append(
            f"{missing} expected hourly slot(s) with no attempt: {missing_ids}")
    if not findings:
        add("No findings. Every requested field resolved, no derivation")
        add("failed, no RNR row was structurally ambiguous, and every")
        add("expected slot held an attempt.")
    else:
        for finding in findings:
            add(f"- {finding}")
    add("")

    # -- 9. Commissioning reference ----------------------------------------------
    add("## 9. Commissioning reference")
    add("")
    add("The two pre-series runs are excluded from every pilot trend above;")
    add("they are summarized here for visibility only.")
    add("")
    add("| Run | Frequencies | Sampled | Observations | BSSIDs |")
    add("|-----|-------------|---------|--------------|--------|")
    for entry in data["commissioning"]:
        if entry.get("present"):
            add(f"| `{entry['run_id']}` | {entry.get('frequencies', 0)} | "
                f"{entry.get('sampled', 0)} | "
                f"{entry.get('observations', 0)} | "
                f"{entry.get('bssids', 0)} |")
        else:
            add(f"| `{entry['run_id']}` | absent from the pilot tree | | | |")
    add("")

    # -- 10. Provenance ------------------------------------------------------------
    add("## 10. Provenance")
    add("")
    add(f"- Source root: `{data['pilot_root']}`")
    add(f"- Derived root: `{data['derived_root']}`")
    add(f"- Database: `{data['db_path']}`")
    add(f"- Report: `{data['report_path']}`")
    add(f"- Views: {', '.join(f'`{v}`' for v in data['view_names'])}")
    add(f"- Data cutoff: {cutoff}")
    add(f"- Contract: `docs/pilot-analysis-contract.md` "
        f"(`{pilot.DERIVED_SCHEMA_ID}`)")
    add("")
    return "\n".join(lines) + "\n"


# =============================================================================
# Entry points
# =============================================================================


def render_report(
    pilot_root: Path = pilot.PILOT_DIR_DEFAULT,
    derived_root: Path = pilot.DERIVED_ROOT_DEFAULT,
    reports_dir: Path = pilot.REPORTS_DIR_DEFAULT,
    now: datetime | None = None,
) -> Path:
    """Render the briefing and atomically replace the canonical report."""
    db_path = pilot.derived_runs_root(derived_root).parents[2] / "pilot.duckdb"
    if not db_path.is_file():
        raise FileNotFoundError(
            f"database not found at {db_path}; run the database stage first")
    data = _gather(db_path, pilot_root, reports_dir, derived_root)
    text = _render(data, now)

    # Section-order self-check against the contract before anything lands.
    positions = []
    for index, section in enumerate(pilot.REPORT_SECTIONS, start=1):
        marker = f"## {index}. {section}"
        position = text.find(marker)
        if position < 0:
            raise AssertionError(f"report is missing section: {marker}")
        positions.append(position)
    if positions != sorted(positions):
        raise AssertionError("report sections out of required order")

    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = pilot.canonical_report_path(reports_dir)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(reports_dir), prefix=".pilot-latest-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    # mkstemp creates 0600; the canonical report is group-readable like the
    # rest of the storage tree.
    os.chmod(tmp_name, 0o644)
    os.replace(tmp_name, report_path)
    return report_path


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-root", type=Path, default=pilot.PILOT_DIR_DEFAULT)
    ap.add_argument("--derived-root", type=Path,
                    default=pilot.DERIVED_ROOT_DEFAULT)
    ap.add_argument("--reports-dir", type=Path,
                    default=pilot.REPORTS_DIR_DEFAULT)
    ap.add_argument("--now", type=str, default=None)
    args = ap.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else None
    path = render_report(args.pilot_root, args.derived_root,
                         args.reports_dir, now=now)
    print(f"report: {path}")


if __name__ == "__main__":
    main()
