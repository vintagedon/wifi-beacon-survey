#!/usr/bin/env bash
# =============================================================================
# Script Name  : wifi-beacon-sample.sh
# Description  : Runs a frequency-driven tri-band passive Wi-Fi beacon discovery sweep
# Repository   : wifi-beacon-survey
# Author       : VintageDon (https://github.com/vintagedon/)
# Created      : 2026-08-16
# Link         : https://github.com/vintagedon/wifi-beacon-survey
# =============================================================================
#
# DESCRIPTION
#   Passive 802.11 beacon discovery sweep for a dedicated monitor-mode interface
#   (ALFA AWUS036AXM / MT7921AUN on ml01). The sweep is frequency-driven: usable
#   2.4 GHz, 5 GHz, and 6 GHz frequencies are derived at runtime from the
#   selected PHY's kernel-reported regulatory state, then each permitted 20 MHz
#   frequency is tuned with `iw dev <iface> set freq <MHz>` and sampled for
#   beacons with tcpdump. Each sampled frequency yields one PCAP and one TSV
#   summary; the run also produces aggregate.tsv, frequencies.tsv (the sweep
#   manifest), run.log, and a terminal summary.
#
#   The collector is passive: it never associates, transmits, enables active
#   monitor mode, or alters the regulatory domain. Regulatory tuning refusals
#   are recorded results, not fatal errors.
#
# USAGE
#   sudo ./wifi-beacon-sample.sh [options]
#
# EXAMPLES
#   sudo ./wifi-beacon-sample.sh
#       Full tri-band sweep, 10 s dwell per frequency.
#
#   sudo ./wifi-beacon-sample.sh -i wlx00c0cab63b82 -d 30
#       Full sweep with 30 s dwell on an explicit interface.
#
#   sudo ./wifi-beacon-sample.sh -b "2.4" -d 2
#       Quick validation sweep of the 2.4 GHz band only.
#
# OUTPUT LOCATION
#   Sweeps are written to the data volume, never into the repository. Capture
#   artifacts are the project's primary evidence and are retained permanently;
#   keeping them out of the working tree prevents accidental Git inclusion.
#   The data root is /opt/agents/repos/storage-mounted/wifi-beacon-survey,
#   outside this repository.
#
# =============================================================================

set -Eeuo pipefail

# =============================================================================
# Configuration
# =============================================================================

IFACE="wlx00c0cab63b82"
DWELL=10
BANDS="2.4 5 6"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_OUT="/opt/agents/repos/storage-mounted/wifi-beacon-survey/sweeps"

# Run under sudo, so files land root-owned by default. Ownership across the
# agent tree is normalized to <invoking user>:agents; without this the sweep
# directory would be the one place that isn't, and the group would be whatever
# root's primary group happens to be.
OWNER_USER="${SUDO_USER:-$(id -un)}"
OWNER_GROUP="agents"

# =============================================================================
# Functions
# =============================================================================

usage() {
    cat <<'EOF'
Usage: sudo ./wifi-beacon-sample.sh [options]

Options:
  -i IFACE       Wireless interface to use (default: wlx00c0cab63b82)
  -d SECONDS     Dwell time per frequency (default: 10)
  -b "BANDS"     Space-separated band filter: any of "2.4" "5" "6" (default: all)
  -o DIR         Base output directory (default: /opt/agents/repos/storage-mounted/wifi-beacon-survey/sweeps)
  -h             Show this help

Output (in <BASE_OUT>/<timestamp>/):
  freq-<MHz>.pcap   One PCAP per sampled frequency (beacons only, may be empty)
  freq-<MHz>.tsv    Per-frequency BSSID summary
  frequencies.tsv   Sweep manifest: every kernel-listed frequency and its outcome
  aggregate.tsv     All BSSID observations across the sweep
  run.log           Full run log
EOF
}

die() {
    echo "FATAL: $*" >&2
    exit 1
}

# =============================================================================
# Main
# =============================================================================

while getopts ":i:d:b:o:h" opt; do
    case "$opt" in
        i) IFACE="$OPTARG" ;;
        d) DWELL="$OPTARG" ;;
        b) BANDS="$OPTARG" ;;
        o) BASE_OUT="$OPTARG" ;;
        h) usage; exit 0 ;;
        :) echo "ERROR: -$OPTARG requires an argument" >&2; exit 2 ;;
        \?) echo "ERROR: unknown option -$OPTARG" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: run as root, e.g. sudo $0" >&2
    exit 1
fi

if ! [[ "$DWELL" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: dwell time must be a positive integer" >&2
    exit 2
fi

for band in $BANDS; do
    case "$band" in
        2.4|5|6) ;;
        *) echo "ERROR: invalid band '$band' (allowed: 2.4 5 6)" >&2; exit 2 ;;
    esac
done

for cmd in iw ip tcpdump python3 date mkdir mktemp awk tee seq grep; do
    command -v "$cmd" >/dev/null 2>&1 || die "required command not found: $cmd"
done

if ! ip link show "$IFACE" >/dev/null 2>&1; then
    die "interface not found: $IFACE"
fi

if [[ "$IFACE" == "wlo1" ]]; then
    die "refusing to operate on the ml01 management interface wlo1"
fi

STAMP="$(date '+%Y%m%d-%H%M%S')"
OUTDIR="${BASE_OUT%/}/$STAMP"
mkdir -p "$OUTDIR"
chown "${OWNER_USER}:${OWNER_GROUP}" "${BASE_OUT%/}" 2>/dev/null || true

LOG="$OUTDIR/run.log"
AGG="$OUTDIR/aggregate.tsv"
MANIFEST="$OUTDIR/frequencies.tsv"
PHYINFO="$OUTDIR/phy-info.txt"
FREQ_TABLE="$OUTDIR/.freq-table.tsv"

exec > >(tee -a "$LOG") 2>&1

# Keep at most one tcpdump alive if the script exits mid-dwell.
TCPDUMP_PID=""
cleanup() {
    if [[ -n "$TCPDUMP_PID" ]] && kill -0 "$TCPDUMP_PID" 2>/dev/null; then
        kill -INT "$TCPDUMP_PID" 2>/dev/null || true
    fi

    # The sweep needs root for monitor-mode control, so every artifact would
    # otherwise be root-owned and out of step with the rest of the agent tree.
    # This runs on the failure path too: a partial sweep is still evidence and
    # still has to be readable. Failures here are non-fatal because losing the
    # capture over an ownership problem would be the worse outcome.
    if [[ -d "${OUTDIR:-}" ]]; then
        chown -R "${OWNER_USER}:${OWNER_GROUP}" "$OUTDIR" 2>/dev/null || true
        chmod -R g+rX "$OUTDIR" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "Tri-band beacon discovery sweep starting"
echo "  interface : $IFACE"
echo "  dwell     : ${DWELL}s/frequency"
echo "  bands     : ${BANDS}"
echo "  output    : $OUTDIR"
echo

# -----------------------------------------------------------------------------
# Interface handling: resolve PHY, ensure ordinary passive monitor mode, up.
# -----------------------------------------------------------------------------

# iw dev groups interfaces under "phy#N" headers; iw phy takes the bare name.
PHY="$(iw dev | awk -v iface="$IFACE" '$1 ~ /^phy#/ {phy=$1} $1=="Interface" && $2==iface {print phy; exit}')"
[[ -n "$PHY" ]] || die "could not resolve PHY for interface $IFACE"
PHY="${PHY//#/}"
echo "  phy       : $PHY"

CURRENT_TYPE="$(iw dev "$IFACE" info | awk '$1=="type" {print $2; exit}')"
if [[ "$CURRENT_TYPE" != "monitor" ]]; then
    echo "Switching $IFACE from ${CURRENT_TYPE:-unknown} to monitor mode"
    ip link set "$IFACE" down
    iw dev "$IFACE" set type monitor
fi
ip link set "$IFACE" up

TYPE_NOW="$(iw dev "$IFACE" info | awk '$1=="type" {print $2; exit}')"
[[ "$TYPE_NOW" == "monitor" ]] || die "failed to place $IFACE into monitor mode"

# -----------------------------------------------------------------------------
# Frequency discovery from kernel-reported PHY/regulatory state.
# AI NOTE: channel numbers are metadata only. Tuning and file naming must stay
# frequency-based because 2.4 GHz and 6 GHz channel numbers collide (both have
# a "channel 1", at 2412 and 5955 MHz respectively).
# -----------------------------------------------------------------------------

iw phy "$PHY" info > "$PHYINFO"

python3 - "$PHYINFO" "$FREQ_TABLE" $BANDS <<'PY' || die "frequency discovery failed"
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
wanted = sys.argv[3:]

# Matches lines like: "* 2412.0 MHz [1] (30.0 dBm)" or "* 5955.0 MHz [1] (12.0 dBm) (no IR)"
freq_re = re.compile(r"^\s*\*\s+(\d+(?:\.\d+)?)\s+MHz\s+\[(\d+)\]\s*(.*)$")
paren_re = re.compile(r"\(([^)]*)\)")

def classify(freq):
    if freq < 4900:
        return "2.4GHz"
    if freq < 5925:
        return "5GHz"
    return "6GHz"

def state_from_flags(text):
    tokens = [t.strip() for t in paren_re.findall(text)]
    tokens = [t for t in tokens if t and "dBm" not in t]
    parts = []
    for t in tokens:
        if t == "disabled":
            parts.append("disabled")
        elif t == "no IR":
            parts.append("no-ir")
        elif t == "radar detection":
            parts.append("radar")
        else:
            parts.append(t.replace(" ", "-"))
    return "+".join(parts) if parts else "permitted"

# First occurrence wins; the kernel lists each frequency once per band section.
seen = {}
with open(src, "r", errors="replace") as fh:
    for line in fh:
        m = freq_re.match(line)
        if not m:
            continue
        freq = int(round(float(m.group(1))))
        if freq in seen:
            continue
        seen[freq] = (int(m.group(2)), state_from_flags(m.group(3)))

band_order = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}
wanted_bands = {f"{b}GHz" for b in wanted}
rows = []
for freq, (chan, state) in seen.items():
    band = classify(freq)
    if band not in wanted_bands:
        continue
    rows.append((band_order[band], freq, chan, state))
rows.sort()

if not rows:
    sys.stderr.write("no frequencies found for bands: %s\n" % " ".join(sorted(wanted_bands)))
    raise SystemExit(1)

with open(dst, "w", encoding="utf-8") as out:
    for _, freq, chan, state in rows:
        out.write(f"{classify(freq)}\t{freq}\t{chan}\t{state}\n")
PY

PERMITTED="$(awk -F'\t' '$4 != "disabled"' "$FREQ_TABLE" | wc -l | tr -d ' ')"
DISABLED="$(awk -F'\t' '$4 == "disabled"' "$FREQ_TABLE" | wc -l | tr -d ' ')"
echo "Frequency discovery: $(wc -l < "$FREQ_TABLE" | tr -d ' ') listed, ${PERMITTED} permitted, ${DISABLED} disabled"
echo

printf 'band\tfrequency_mhz\tchannel\tregulatory_state\tsample_status\tdwell_seconds\tpcap_file\tbssid_count\tbeacon_count\terror\n' > "$MANIFEST"
printf 'band\tfrequency_mhz\tchannel\tbssid\tssid\tbeacons\tbeacon_interval_tu\trssi_min_dbm\trssi_mean_dbm\trssi_max_dbm\tfirst_seen\tlast_seen\tbeacon_reception_ratio\n' > "$AGG"

# Append one manifest row. All fields must be tab-safe single lines.
manifest_row() {
    local band="$1" freq="$2" chan="$3" reg="$4" status="$5" dwell="$6" pcap="$7" bssids="$8" beacons="$9" err="${10:-}"
    err="${err//$'\t'/ }"
    err="${err//$'\n'/ }"
    err="${err//$'\r'/ }"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$band" "$freq" "$chan" "$reg" "$status" "$dwell" "$pcap" "$bssids" "$beacons" "$err" >> "$MANIFEST"
}

# Parse one frequency's PCAP into its TSV summary. Stdlib only: reads the
# radiotap-prefixed beacon frames directly (BSSID, SSID, beacon interval, RSSI)
# because tcpdump's text output does not decode the beacon interval field.
summarize_pcap() {
    local band="$1" freq="$2" chan="$3" pcap="$4" summary="$5"

    python3 - "$band" "$freq" "$chan" "$pcap" "$summary" "$DWELL" <<'PY'
import struct
import sys
from collections import defaultdict
from datetime import datetime, timezone

band, freq, chan = sys.argv[1], sys.argv[2], sys.argv[3]
pcap_path, summary_path, dwell = sys.argv[4], sys.argv[5], float(sys.argv[6])

# Radiotap field (size, alignment) for presence bits 0..5. Fields are laid out
# in ascending bit order, so the offset of bit 5 (dBm antenna signal) depends
# only on which of bits 0..4 are present.
RADIOTAP_FIELDS = {
    0: (8, 8),  # TSFT
    1: (1, 1),  # flags
    2: (1, 1),  # rate
    3: (4, 2),  # channel
    4: (2, 2),  # FHSS
    5: (1, 1),  # dBm antenna signal
}

def read_pcap(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 24:
        raise ValueError("PCAP truncated: missing global header")
    magic = data[:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        end, frac_div = "<", 1e6
    elif magic == b"\xa1\xb2\xc3\xd4":
        end, frac_div = ">", 1e6
    elif magic == b"\x4d\x3c\xb2\xa1":
        end, frac_div = "<", 1e9
    elif magic == b"\xa1\xb2\x3c\x4d":
        end, frac_div = ">", 1e9
    else:
        raise ValueError("unrecognized PCAP magic")
    linktype = struct.unpack(end + "I", data[20:24])[0]
    if linktype != 127:
        raise ValueError(f"unexpected link type {linktype}, expected 127 (radiotap)")
    pos = 24
    while pos + 16 <= len(data):
        ts_sec, ts_frac, incl_len, _ = struct.unpack(end + "IIII", data[pos:pos + 16])
        pos += 16
        pkt = data[pos:pos + incl_len]
        if len(pkt) < incl_len:
            raise ValueError("PCAP truncated inside packet record")
        pos += incl_len
        yield ts_sec + ts_frac / frac_div, pkt

def radiotap_rssi(pkt):
    """Strongest dBm antenna-signal value in the radiotap header, or None."""
    if len(pkt) < 8:
        return None
    it_len = struct.unpack("<H", pkt[2:4])[0]
    if it_len < 8 or it_len > len(pkt):
        return None
    # Presence words form a chain from offset 4; bit 31 set means another word.
    p = 4
    words = []
    while p + 4 <= it_len:
        word = struct.unpack("<I", pkt[p:p + 4])[0]
        words.append(word)
        p += 4
        if not (word >> 31) & 1:
            break
    pos = p
    bit = 0
    rssi = None
    for word in words:
        for b in range(32):
            if (word >> b) & 1:
                if bit > 5:
                    return rssi
                size, align = RADIOTAP_FIELDS[bit]
                pos = (pos + align - 1) & ~(align - 1)
                if bit == 5 and pos + 1 <= it_len:
                    val = struct.unpack("<b", pkt[pos:pos + 1])[0]
                    if rssi is None or val > rssi:
                        rssi = val
                pos += size
            bit += 1
    return rssi

def parse_beacon(pkt):
    """Return (bssid, ssid, interval_tu) for a radiotap-prefixed beacon frame."""
    if len(pkt) < 4:
        return None
    it_len = struct.unpack("<H", pkt[2:4])[0]
    off = it_len
    if len(pkt) < off + 24:
        return None
    fc = pkt[off]
    ftype, fsub = (fc >> 2) & 0x3, (fc >> 4) & 0xF
    if ftype != 0 or fsub != 8:
        return None
    # Address 3 is the BSSID in a beacon management header.
    bssid = ":".join(f"{b:02x}" for b in pkt[off + 16:off + 22])
    interval = None
    if len(pkt) >= off + 34:
        interval = struct.unpack("<H", pkt[off + 32:off + 34])[0]
    ssid = ""
    ie_pos = off + 36
    if len(pkt) >= ie_pos + 2 and pkt[ie_pos] == 0:
        ssid_len = pkt[ie_pos + 1]
        raw = pkt[ie_pos + 2:ie_pos + 2 + ssid_len]
        ssid = raw.decode("utf-8", errors="replace")
        ssid = ssid.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    return bssid, ssid, interval

rows = defaultdict(lambda: {
    "ssid": "", "count": 0, "rssis": [],
    "first": None, "last": None, "interval": None,
})

for ts, pkt in read_pcap(pcap_path):
    parsed = parse_beacon(pkt)
    if parsed is None:
        continue
    bssid, ssid, interval = parsed
    rec = rows[bssid]
    rec["count"] += 1
    if ssid:
        rec["ssid"] = ssid
    if interval:
        rec["interval"] = interval
    rssi = radiotap_rssi(pkt)
    if rssi is not None:
        rec["rssis"].append(rssi)
    stamp = (
        datetime.fromtimestamp(ts, timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    if rec["first"] is None:
        rec["first"] = stamp
    rec["last"] = stamp

with open(summary_path, "w", encoding="utf-8") as out:
    out.write(
        "band\tfrequency_mhz\tchannel\tbssid\tssid\tbeacons\tbeacon_interval_tu\t"
        "rssi_min_dbm\trssi_mean_dbm\trssi_max_dbm\tfirst_seen\tlast_seen\t"
        "beacon_reception_ratio\n"
    )
    for bssid in sorted(rows):
        rec = rows[bssid]
        rssis = rec["rssis"]
        if rssis:
            min_text = str(min(rssis))
            mean_text = f"{sum(rssis) / len(rssis):.1f}"
            max_text = str(max(rssis))
        else:
            min_text = mean_text = max_text = ""
        interval = rec["interval"]
        ratio_text = ""
        if interval:
            expected = dwell / (interval * 0.001024)
            # Deliberately unclamped: values slightly above 1.0 are legitimate
            # timing-boundary artifacts and stay observable per the spec.
            ratio_text = f"{rec['count'] / expected:.3f}"
        out.write(
            f"{band}\t{freq}\t{chan}\t{bssid}\t{rec['ssid']}\t{rec['count']}\t"
            f"{interval or ''}\t{min_text}\t{mean_text}\t{max_text}\t"
            f"{rec['first'] or ''}\t{rec['last'] or ''}\t{ratio_text}\n"
        )

print(f"COUNTS\t{len(rows)}\t{sum(r['count'] for r in rows.values())}")
PY
}

# -----------------------------------------------------------------------------
# Discovery sweep
# -----------------------------------------------------------------------------

sampled=0
sampled_empty=0
refused=0
capture_errors=0

while IFS=$'\t' read -r BAND FREQ CHAN REGSTATE; do
    echo "== ${BAND} ${FREQ} MHz (ch ${CHAN}, ${REGSTATE}) =="

    if [[ "$REGSTATE" == "disabled" ]]; then
        echo "SKIP: frequency disabled by regulatory state"
        manifest_row "$BAND" "$FREQ" "$CHAN" "$REGSTATE" "regulatory_skip" 0 "" "" "" "disabled by regulatory state"
        continue
    fi

    # Collector health: a vanished or de-monitorized interface is fatal, unlike
    # a per-frequency tuning refusal.
    if ! ip link show "$IFACE" >/dev/null 2>&1; then
        die "interface $IFACE disappeared mid-sweep"
    fi
    TYPE_NOW="$(iw dev "$IFACE" info 2>/dev/null | awk '$1=="type" {print $2; exit}')"
    [[ "$TYPE_NOW" == "monitor" ]] || die "$IFACE left monitor mode mid-sweep (type: ${TYPE_NOW:-unknown})"

    SETFREQ_ERR="$(mktemp)"
    if ! iw dev "$IFACE" set freq "$FREQ" 2>"$SETFREQ_ERR"; then
        ERRMSG="$(tr '\n' ' ' < "$SETFREQ_ERR" | tr -s ' ')"
        rm -f "$SETFREQ_ERR"
        echo "SKIP: tuning refused: ${ERRMSG:-unknown error}"
        manifest_row "$BAND" "$FREQ" "$CHAN" "$REGSTATE" "regulatory_skip" 0 "" "" "" "set freq refused: ${ERRMSG:-unknown error}"
        refused=$((refused + 1))
        continue
    fi
    rm -f "$SETFREQ_ERR"

    ACTUAL="$(iw dev "$IFACE" info | awk '/channel/ {gsub(/[()]/, ""); print $3; exit}')"
    if [[ "$ACTUAL" != "$FREQ" ]]; then
        echo "SKIP: tuning did not stick (interface reports ${ACTUAL:-nothing} MHz)"
        manifest_row "$BAND" "$FREQ" "$CHAN" "$REGSTATE" "regulatory_skip" 0 "" "" "" "tune mismatch: reports ${ACTUAL:-nothing} MHz"
        refused=$((refused + 1))
        continue
    fi

    PCAP="$OUTDIR/freq-${FREQ}.pcap"
    SUMMARY="$OUTDIR/freq-${FREQ}.tsv"
    TCPDUMP_LOG="$(mktemp)"
    rm -f "$PCAP" "$SUMMARY"

    echo "Capturing beacon frames on ${FREQ} MHz for ${DWELL}s"

    # No -I flag: the interface is already in monitor mode, and asking libpcap
    # for rfmon again makes tcpdump abort with "That device doesn't support
    # monitor mode" on this driver.
    TCPDUMP_PID=""
    tcpdump \
        -i "$IFACE" \
        -U \
        -s 1024 \
        -w "$PCAP" \
        'type mgt subtype beacon' \
        >/dev/null 2>"$TCPDUMP_LOG" &
    TCPDUMP_PID=$!

    # Wait until tcpdump is actually capturing before counting dwell time.
    LISTENING=0
    for _ in $(seq 1 100); do
        if ! kill -0 "$TCPDUMP_PID" 2>/dev/null; then
            break
        fi
        if grep -q 'listening on' "$TCPDUMP_LOG" 2>/dev/null; then
            LISTENING=1
            break
        fi
        sleep 0.1
    done

    if [[ "$LISTENING" -ne 1 ]]; then
        wait "$TCPDUMP_PID" 2>/dev/null || true
        TCPDUMP_PID=""
        cp "$TCPDUMP_LOG" "$OUTDIR/freq-${FREQ}.tcpdump.log"
        rm -f "$TCPDUMP_LOG" "$PCAP"
        echo "ERROR: tcpdump failed to start on ${FREQ} MHz:" >&2
        tail -n 5 "$OUTDIR/freq-${FREQ}.tcpdump.log" >&2 || true
        manifest_row "$BAND" "$FREQ" "$CHAN" "$REGSTATE" "capture_error" 0 "" "" "" "tcpdump failed to start; see freq-${FREQ}.tcpdump.log"
        capture_errors=$((capture_errors + 1))
        continue
    fi

    sleep "$DWELL"

    # Verify the capture process stayed alive for the whole dwell rather than
    # assuming startup success implied continued capture.
    if ! kill -0 "$TCPDUMP_PID" 2>/dev/null; then
        wait "$TCPDUMP_PID" 2>/dev/null || true
        TCPDUMP_PID=""
        cp "$TCPDUMP_LOG" "$OUTDIR/freq-${FREQ}.tcpdump.log"
        rm -f "$TCPDUMP_LOG" "$PCAP"
        echo "ERROR: tcpdump died during dwell on ${FREQ} MHz:" >&2
        tail -n 5 "$OUTDIR/freq-${FREQ}.tcpdump.log" >&2 || true
        manifest_row "$BAND" "$FREQ" "$CHAN" "$REGSTATE" "capture_error" "$DWELL" "" "" "" "tcpdump exited during dwell; see freq-${FREQ}.tcpdump.log"
        capture_errors=$((capture_errors + 1))
        continue
    fi

    kill -INT "$TCPDUMP_PID" 2>/dev/null || true
    wait "$TCPDUMP_PID" 2>/dev/null || true
    TCPDUMP_PID=""
    rm -f "$TCPDUMP_LOG"

    if [[ ! -s "$PCAP" ]]; then
        echo "ERROR: no PCAP written for ${FREQ} MHz" >&2
        manifest_row "$BAND" "$FREQ" "$CHAN" "$REGSTATE" "capture_error" "$DWELL" "" "" "" "PCAP missing or empty"
        capture_errors=$((capture_errors + 1))
        continue
    fi

    # Parser failure is a collector failure and is fatal, never a zero-BSSID row.
    if ! COUNTS="$(summarize_pcap "$BAND" "$FREQ" "$CHAN" "$PCAP" "$SUMMARY")"; then
        die "beacon parser failed for ${FREQ} MHz (PCAP: $PCAP)"
    fi

    UNIQUE="$(awk -F'\t' '{print $2}' <<<"$COUNTS")"
    BEACONS="$(awk -F'\t' '{print $3}' <<<"$COUNTS")"

    tail -n +2 "$SUMMARY" >> "$AGG"

    if [[ "${BEACONS:-0}" -gt 0 ]]; then
        STATUS="sampled"
        sampled=$((sampled + 1))
        echo "Captured: ${UNIQUE} unique BSSID(s), ${BEACONS} beacon(s)"
    else
        STATUS="sampled_empty"
        sampled_empty=$((sampled_empty + 1))
        echo "Captured: 0 beacons (negative observation retained)"
    fi

    manifest_row "$BAND" "$FREQ" "$CHAN" "$REGSTATE" "$STATUS" "$DWELL" "freq-${FREQ}.pcap" "$UNIQUE" "$BEACONS" ""
    echo
done < "$FREQ_TABLE"

rm -f "$FREQ_TABLE"

echo "Sweep complete"
echo "  output            : $OUTDIR"
echo

# -----------------------------------------------------------------------------
# Terminal summary
# -----------------------------------------------------------------------------

python3 - "$MANIFEST" "$AGG" <<'PY' || die "terminal summary failed"
import csv
import sys

manifest_path, agg_path = sys.argv[1], sys.argv[2]

with open(manifest_path, newline="", encoding="utf-8") as fh:
    manifest = list(csv.DictReader(fh, delimiter="\t"))
with open(agg_path, newline="", encoding="utf-8") as fh:
    agg = list(csv.DictReader(fh, delimiter="\t"))

by_freq = {}
for row in agg:
    by_freq.setdefault((row["band"], int(row["frequency_mhz"])), []).append(row)

print("Per-frequency observations (populated frequencies only):")
print(f"{'Band':<8} {'Freq':>5} {'Ch':>4} {'BSSIDs':>8} {'Beacons':>9} {'Strongest mean':>15} {'Weakest mean':>15}")

band_order = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}
keys = sorted(by_freq, key=lambda k: (band_order.get(k[0], 9), k[1]))
for band, freq in keys:
    rows = by_freq[(band, freq)]
    beacons = sum(int(r["beacons"]) for r in rows)
    means = [float(r["rssi_mean_dbm"]) for r in rows if r["rssi_mean_dbm"]]
    strong = f"{max(means):.1f} dBm" if means else "n/a"
    weak = f"{min(means):.1f} dBm" if means else "n/a"
    chan = rows[0]["channel"]
    print(f"{band:<8} {freq:>5} {chan:>4} {len(rows):>8} {beacons:>9} {strong:>15} {weak:>15}")

attempted = sampled = empty = skipped = errors = disabled = 0
for m in manifest:
    status = m["sample_status"]
    if status == "sampled":
        sampled += 1
    elif status == "sampled_empty":
        empty += 1
    elif status == "capture_error":
        errors += 1
    elif status == "regulatory_skip":
        if "disabled" in (m["error"] or ""):
            disabled += 1
        else:
            skipped += 1
attempted = sampled + empty + skipped + errors

total_beacons = sum(int(m["beacon_count"] or 0) for m in manifest)
unique_bssids = {r["bssid"] for r in agg}
by_band = {}
for r in agg:
    by_band.setdefault(r["band"], set()).add(r["bssid"])

print()
print("Totals:")
print(f"  frequencies listed     : {len(manifest)} ({disabled} disabled at discovery)")
print(f"  frequencies attempted  : {attempted}")
print(f"  frequencies sampled    : {sampled + empty} (populated: {sampled}, empty: {empty})")
print(f"  skipped/refused        : {skipped}")
print(f"  capture errors         : {errors}")
print(f"  unique BSSIDs observed : {len(unique_bssids)}")
band_text = ", ".join(f"{b}: {len(s)}" for b, s in sorted(by_band.items(), key=lambda kv: band_order.get(kv[0], 9)))
print(f"  BSSIDs by band         : {band_text} (multi-band BSSIDs count once in the global total)")
print(f"  total beacon frames    : {total_beacons}")
print()

if errors:
    sys.exit(1)
if sampled + empty == 0:
    print("ERROR: no frequencies were successfully sampled", file=sys.stderr)
    sys.exit(1)
PY
