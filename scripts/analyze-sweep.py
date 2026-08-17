#!/usr/bin/env python3
"""
Script Name  : analyze-sweep.py
Description  : Profiles one completed beacon sweep: coverage, reception bounds, identity
Repository   : wifi-beacon-survey
Author       : VintageDon (https://github.com/vintagedon/)
Created      : 2026-08-16
Link         : https://github.com/vintagedon/wifi-beacon-survey

Description
-----------
Reads `frequencies.tsv` (the per-frequency sweep manifest) and `aggregate.tsv`
(per-BSSID observations) from a sweep directory and reports what the sweep
measured: band coverage including explicit non-observations, a positive-control
check per band, reception-ratio bounds against the theoretical maximum,
radio-family resolution across BSSIDs, SSID and RF profiling, and data-quality
flags. Optionally emits typed Parquet.

Read-only against sweep artifacts. It never modifies capture data and has no
opinion about acquisition.

Usage
-----
    python3 analyze-sweep.py <sweep_dir> [--parquet <out_dir>]

Examples
--------
    python3 analyze-sweep.py /opt/agents/repos/storage-mounted/wifi-beacon-survey/sweeps/20260816-024440
        Profile report to stdout

    python3 analyze-sweep.py <sweep_dir> --parquet ./out
        Same, plus typed Parquet artifacts written to ./out
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

import pandas as pd

# ---------------------------------------------------------------------------
# Explicit schemas. Never let the reader infer types: an SSID like "2437" would
# be typed as an integer in one sweep and a string in the next, which silently
# breaks any glob across the series.
# ---------------------------------------------------------------------------

FREQ_DTYPES = {
    "band": "string",
    "frequency_mhz": "Int64",
    "channel": "Int64",
    "regulatory_state": "string",
    "sample_status": "string",
    "dwell_seconds": "Int64",
    "pcap_file": "string",
    "bssid_count": "Int64",
    "beacon_count": "Int64",
    "error": "string",
}

AGG_DTYPES = {
    "band": "string",
    "frequency_mhz": "Int64",
    "channel": "Int64",
    "bssid": "string",
    "ssid": "string",
    "beacons": "Int64",
    "beacon_interval_tu": "Int64",
    "rssi_min_dbm": "Int64",
    "rssi_mean_dbm": "Float64",
    "rssi_max_dbm": "Int64",
    "beacon_reception_ratio": "Float64",
}

TU_SECONDS = 1024e-6  # one 802.11 time unit

# SSID patterns that identify factory/ISP defaults rather than user-chosen names.
ISP_DEFAULT_PATTERNS = [
    (re.compile(r"^SpectrumSetup-", re.I), "charter_spectrum"),
    (re.compile(r"^ATT-WIFI-", re.I), "att"),
    (re.compile(r"^Verizon_", re.I), "verizon"),
    (re.compile(r"^Breezeline", re.I), "breezeline"),
    (re.compile(r"^CenturyLink", re.I), "centurylink"),
    (re.compile(r"^NETGEAR\d*$", re.I), "netgear_oem"),
    (re.compile(r"^(TP-Link|Linksys|ASUS|Xfinity)", re.I), "vendor_oem"),
]

# SSIDs broadcast by many unrelated radios as a shared/community service.
SHARED_SERVICE_PATTERNS = [
    (re.compile(r"^Spectrum Mobile$", re.I), "charter_community"),
    (re.compile(r"^xfinitywifi$", re.I), "comcast_community"),
    (re.compile(r"^optimumwifi$", re.I), "altice_community"),
]


# ---------------------------------------------------------------------------
# MAC helpers
# ---------------------------------------------------------------------------

def mac_octets(bssid: str) -> list[int]:
    return [int(o, 16) for o in bssid.split(":")]


def is_locally_administered(bssid: str) -> bool:
    """U/L bit (bit 1 of the first octet). Set means the address was assigned
    by the device, not from an IEEE-registered OUI, so OUI lookup is invalid."""
    return bool(mac_octets(bssid)[0] & 0x02)


def is_multicast(bssid: str) -> bool:
    return bool(mac_octets(bssid)[0] & 0x01)


def oui(bssid: str) -> str | None:
    """Only meaningful for globally administered addresses."""
    return None if is_locally_administered(bssid) else bssid[:8].lower()


def radio_family_key(bssid: str) -> str:
    """Heuristic grouping of BSSIDs likely emitted by one physical radio.

    Multi-SSID APs derive virtual BSSIDs by varying the first octet and the low
    nibble of the last octet while holding octets 2-5 constant. Grouping on
    octets 2-5 plus the high nibble of octet 6 collapses those back together.

    This is a hypothesis, not ground truth. It belongs in analysis, never in
    the collector, and it should be reported as probable rather than asserted.
    """
    o = mac_octets(bssid)
    return ":".join(f"{b:02x}" for b in o[1:5]) + f":{o[5] >> 4:x}_"


def classify_ssid(ssid: str | None) -> dict:
    s = "" if ssid is None or pd.isna(ssid) else str(ssid)
    out = {
        "hidden": s == "",
        "length": len(s),
        "isp_default": False,
        "provider_family": None,
        "shared_service": False,
    }
    for pat, fam in ISP_DEFAULT_PATTERNS:
        if pat.search(s):
            out["isp_default"] = True
            out["provider_family"] = fam
            break
    for pat, fam in SHARED_SERVICE_PATTERNS:
        if pat.search(s):
            out["shared_service"] = True
            out["provider_family"] = fam
            break
    return out


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_sweep(sweep_dir: pathlib.Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    freq_path = sweep_dir / "frequencies.tsv"
    agg_path = sweep_dir / "aggregate.tsv"
    for p in (freq_path, agg_path):
        if not p.exists():
            sys.exit(f"missing {p}")

    freq = pd.read_csv(freq_path, sep="\t", dtype=FREQ_DTYPES, keep_default_na=False,
                       na_values=[""])
    agg = pd.read_csv(agg_path, sep="\t", dtype=AGG_DTYPES, keep_default_na=False,
                      na_values=[], parse_dates=["first_seen", "last_seen"])
    # An empty SSID field is a hidden network, not a missing value.
    agg["ssid"] = agg["ssid"].fillna("")
    return freq, agg


def enrich(agg: pd.DataFrame) -> pd.DataFrame:
    df = agg.copy()
    if df.empty:
        empty_columns = {
            "locally_administered": "boolean",
            "multicast": "boolean",
            "oui": "string",
            "radio_family": "string",
            "hidden": "boolean",
            "length": "Int64",
            "isp_default": "boolean",
            "provider_family": "string",
            "shared_service": "boolean",
            "dwell_span_s": "Float64",
        }
        for name, dtype in empty_columns.items():
            df[name] = pd.Series(index=df.index, dtype=dtype)
        return df

    df["locally_administered"] = df["bssid"].map(is_locally_administered)
    df["multicast"] = df["bssid"].map(is_multicast)
    df["oui"] = df["bssid"].map(oui)
    df["radio_family"] = df["bssid"].map(radio_family_key)
    ssid_feats = pd.DataFrame(list(df["ssid"].map(classify_ssid)), index=df.index)
    df = pd.concat([df, ssid_feats], axis=1)
    df["dwell_span_s"] = (df["last_seen"] - df["first_seen"]).dt.total_seconds()
    return df


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def h(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def report_coverage(freq: pd.DataFrame) -> None:
    h("Coverage")
    total = len(freq)
    attempted = (freq["sample_status"] != "regulatory_skip").sum()
    populated = (freq["sample_status"] == "sampled").sum()
    empty = (freq["sample_status"] == "sampled_empty").sum()
    skipped = (freq["sample_status"] == "regulatory_skip").sum()
    print(f"frequencies in regulatory table : {total}")
    print(f"attempted                       : {attempted}")
    print(f"  populated                     : {populated}")
    print(f"  empty (negative observation)  : {empty}")
    print(f"skipped (regulatory)            : {skipped}")

    print()
    by_band = freq.groupby("band", observed=True).apply(
        lambda g: pd.Series({
            "freqs": len(g),
            "attempted": int((g["sample_status"] != "regulatory_skip").sum()),
            "populated": int((g["sample_status"] == "sampled").sum()),
            "bssids": int(g["bssid_count"].fillna(0).sum()),
            "beacons": int(g["beacon_count"].fillna(0).sum()),
        }), include_groups=False)
    print(by_band.to_string())

    print()
    print("regulatory state x outcome:")
    print(pd.crosstab(freq["regulatory_state"], freq["sample_status"]).to_string())


def report_positive_control(freq: pd.DataFrame) -> None:
    """A band that returned nothing everywhere is ambiguous: either no APs were
    present, or the receiver never worked on that band. Those are different
    facts and the sweep cannot distinguish them on its own."""
    h("Positive-control check")
    for band, g in freq[freq["sample_status"] != "regulatory_skip"].groupby("band", observed=True):
        detections = int((g["sample_status"] == "sampled").sum())
        n = len(g)
        if detections == 0:
            regs = ", ".join(sorted(g["regulatory_state"].dropna().unique()))
            print(f"  {band:>7}: 0/{n} frequencies produced any beacon  [UNVALIDATED - "
                  f"reg state: {regs}]")
            print(f"           absence on {band} is not evidence of absence until a known "
                  f"{band} AP is detected from this position")
        else:
            print(f"  {band:>7}: {detections}/{n} frequencies produced beacons  [receiver confirmed]")


def report_reception_calibration(agg: pd.DataFrame, freq: pd.DataFrame) -> None:
    """Report the best observed ratio without treating it as calibration.

    A single sweep maximum is only a lower bound on instrument performance. It
    cannot separate capture timing, link loss, AP behavior, and RF conditions.
    """
    h("Reception-ratio calibration")
    if agg.empty or agg["beacon_interval_tu"].dropna().empty:
        print("no BSSID observations; reception calibration is unavailable")
        return

    dwell = freq.loc[freq["dwell_seconds"] > 0, "dwell_seconds"].mode()
    dwell_s = int(dwell.iloc[0]) if len(dwell) else 10
    interval_s = float(agg["beacon_interval_tu"].mode().iloc[0]) * TU_SECONDS
    expected = dwell_s / interval_s
    observed_max = int(agg["beacons"].max())
    ceiling = agg["beacon_reception_ratio"].max()
    print(f"dwell                       : {dwell_s} s")
    print(f"modal beacon interval       : {agg['beacon_interval_tu'].mode().iloc[0]} TU "
          f"({interval_s * 1000:.1f} ms)")
    print(f"theoretical expected count  : {expected:.1f}")
    print(f"best observed count         : {observed_max}")
    print(f"observed ratio upper bound  : {ceiling:.3f}")
    print(f"unattributed shortfall      : {(1 - ceiling) * 100:.1f}% "
          f"({(1 - ceiling) * dwell_s:.2f} s relative to the nominal dwell)")
    n_at_bound = int((agg["beacon_reception_ratio"] >= ceiling - 1e-9).sum())
    print(f"observations at upper bound : {n_at_bound} of {len(agg)}")
    print("note: this single-sweep maximum is not a calibrated loss estimate; "
          "controlled repeated measurements are required")


def report_identity(df: pd.DataFrame) -> None:
    h("BSSID inventory and identity resolution")
    bssids = df["bssid"].nunique()
    families = df["radio_family"].nunique()
    laa = df.groupby("bssid", observed=True)["locally_administered"].first()
    print(f"unique BSSIDs                    : {bssids}")
    print(f"probable physical radios         : {families}  "
          f"({bssids / families:.2f} BSSIDs per radio)")
    print(f"locally administered             : {int(laa.sum())} "
          f"({laa.mean() * 100:.0f}%)  - OUI lookup invalid for these")
    print(f"globally administered            : {int((~laa).sum())} "
          f"({(~laa).mean() * 100:.0f}%)  - OUI resolvable")
    print(f"multicast bit set                : "
          f"{int(df.groupby('bssid', observed=True)['multicast'].first().sum())}")

    print("\nprobable radio families (BSSIDs grouped by octets 2-5 + high nibble of 6):")
    fam = df.groupby("radio_family", observed=True).agg(
        bssids=("bssid", "nunique"),
        ssids=("ssid", lambda s: sorted({x if x else "<hidden>" for x in s})),
        bands=("band", lambda s: sorted(set(s))),
        rssi=("rssi_mean_dbm", "mean"),
    ).sort_values("bssids", ascending=False)
    for key, row in fam.iterrows():
        print(f"  {key:>16}  {row['bssids']} BSSID(s)  {'/'.join(row['bands']):<12} "
              f"{row['rssi']:>7.1f} dBm  {', '.join(row['ssids'])}")


def report_ssid(df: pd.DataFrame) -> None:
    h("SSID profile")
    per_bssid = df.groupby("bssid", observed=True).first()
    print(f"unique SSID strings   : {df.loc[df['ssid'] != '', 'ssid'].nunique()}")
    print(f"hidden BSSIDs         : {int(per_bssid['hidden'].sum())} of {len(per_bssid)} "
          f"({per_bssid['hidden'].mean() * 100:.0f}%)")
    print(f"ISP/OEM default names : {int(per_bssid['isp_default'].sum())}")
    print(f"shared-service SSIDs  : {int(per_bssid['shared_service'].sum())}")

    shared = df[df["shared_service"]]
    if not shared.empty:
        print("\nshared-service SSIDs seen across multiple radio families:")
        for ssid, g in shared.groupby("ssid", observed=True):
            print(f"  {ssid!r}: {g['bssid'].nunique()} BSSIDs across "
                  f"{g['radio_family'].nunique()} distinct radio families")

    fams = per_bssid[per_bssid["provider_family"].notna()]["provider_family"]
    if not fams.empty:
        print("\nprovider families inferred from SSID pattern:")
        for k, v in fams.value_counts().items():
            print(f"  {k:<22} {v}")


def report_rf(df: pd.DataFrame) -> None:
    h("RF profile")
    per_band = df.groupby("band", observed=True).agg(
        obs=("bssid", "size"),
        bssids=("bssid", "nunique"),
        rssi_min=("rssi_min_dbm", "min"),
        rssi_mean=("rssi_mean_dbm", "mean"),
        rssi_max=("rssi_max_dbm", "max"),
        ratio_mean=("beacon_reception_ratio", "mean"),
    )
    print(per_band.to_string(float_format=lambda x: f"{x:.2f}"))

    print("\nchannel occupancy (populated frequencies only):")
    occ = df.groupby(["band", "frequency_mhz", "channel"], observed=True).agg(
        bssids=("bssid", "nunique"), beacons=("beacons", "sum"),
    ).sort_values("bssids", ascending=False)
    print(occ.to_string())

    multi = df.groupby("bssid", observed=True)["frequency_mhz"].nunique()
    multi = multi[multi > 1]
    if len(multi):
        print(f"\nBSSIDs observed on more than one frequency: {len(multi)}")
        for b, n in multi.sort_values(ascending=False).items():
            g = df[df["bssid"] == b]
            freqs = ", ".join(str(int(f)) for f in sorted(g["frequency_mhz"].unique()))
            label = g["ssid"].iloc[0] or "<hidden>"
            print(f"  {b}  {label:<22} {n} freqs: {freqs}")
        print("  (same BSSID on adjacent channels is usually sidelobe/overlap leakage, "
              "not a second radio)")


def report_data_quality(df: pd.DataFrame, freq: pd.DataFrame) -> None:
    h("Data quality flags")
    flags = []
    thin = df[df["beacons"] < 10]
    if not thin.empty:
        flags.append(f"{len(thin)} observation(s) with <10 beacons - ratio is noisy at "
                     f"this count (min {int(df['beacons'].min())})")
    inverted = df[df["rssi_max_dbm"] - df["rssi_min_dbm"] > 15]
    if not inverted.empty:
        flags.append(f"{len(inverted)} observation(s) with >15 dB spread between min and "
                     f"max RSSI - check for rate/antenna diversity or a moving reflector")
    if (df["beacon_reception_ratio"] > 1.0).any():
        flags.append("reception ratio exceeds 1.0 - expected-count model is wrong")
    err = freq[freq["error"].notna() & (freq["error"] != "")]
    non_reg = err[err["sample_status"] != "regulatory_skip"]
    flags.append(f"{len(non_reg)} capture error(s) outside regulatory skips")
    for f in flags:
        print(f"  - {f}")


# ---------------------------------------------------------------------------
# Parquet emission
# ---------------------------------------------------------------------------

def write_parquet(df: pd.DataFrame, freq: pd.DataFrame, sweep_id: str,
                  out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    obs = df.copy()
    obs.insert(0, "sweep_id", sweep_id)
    fr = freq.copy()
    fr.insert(0, "sweep_id", sweep_id)
    obs.to_parquet(out_dir / "observations.parquet", index=False)
    fr.to_parquet(out_dir / "frequencies.parquet", index=False)
    print(f"\nwrote {out_dir / 'observations.parquet'} ({len(obs)} rows)")
    print(f"wrote {out_dir / 'frequencies.parquet'} ({len(fr)} rows)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep_dir", type=pathlib.Path)
    ap.add_argument("--parquet", type=pathlib.Path, default=None)
    args = ap.parse_args()

    sweep_dir = args.sweep_dir.resolve()
    sweep_id = sweep_dir.name
    freq, agg = load_sweep(sweep_dir)
    df = enrich(agg)

    print(f"sweep: {sweep_id}")
    print(f"window: {df['first_seen'].min()} -> {df['last_seen'].max()}")

    report_coverage(freq)
    report_positive_control(freq)
    if df.empty:
        for title in (
            "Reception-ratio calibration",
            "BSSID inventory and identity resolution",
            "SSID profile",
            "RF profile",
        ):
            h(title)
            print("no BSSID observations")
        report_data_quality(df, freq)
        if args.parquet:
            write_parquet(df, freq, sweep_id, args.parquet)
        return

    report_reception_calibration(agg, freq)
    report_identity(df)
    report_ssid(df)
    report_rf(df)
    report_data_quality(df, freq)

    if args.parquet:
        write_parquet(df, freq, sweep_id, args.parquet)


if __name__ == "__main__":
    main()
