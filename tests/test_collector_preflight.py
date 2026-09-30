#!/usr/bin/env python3
"""Behavioral tests for the collector's regulatory domain preflight (IC-003).

The collector must establish the declared regulatory domain before frequency
discovery: read the effective domain, set the declared one if it differs,
verify, record the domain found and applied, and refuse the run (terminal
refusal record, header-only TSVs, no PCAP, non-zero exit) if it cannot.

The full collector script runs against stubbed `iw`, `ip`, and `tcpdump`
binaries on a PATH shim, so no radio and no host regulatory state is touched.
The stub's domain state lives in a per-test scratch directory; `iw reg set`
either converges or never converges depending on the scenario. Root is
required because the collector refuses to run as non-root; exercise with
`sudo python3 -m pytest tests/test_collector_preflight.py`.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(
    os.environ.get("COLLECTOR_UNDER_TEST", str(ROOT / "scripts" / "wifi-beacon-sample.sh"))
)
IFACE = "wlstub0"

PREFLIGHT_BEGIN = "# --- BEGIN DOMAIN PREFLIGHT BLOCK ---"
PREFLIGHT_END = "# --- END DOMAIN PREFLIGHT BLOCK ---"
DISCOVERY_BEGIN = "# --- BEGIN FREQUENCY DISCOVERY BLOCK ---"
DISCOVERY_END = "# --- END FREQUENCY DISCOVERY BLOCK ---"

IW_STUB = r"""#!/usr/bin/env bash
# Test stub for iw. State lives in $IW_STUB_STATE:
#   domain         current global domain (seeded from IW_STUB_INITIAL_DOMAIN)
#   phydomain      optional self-managed phy#3 country (override precedence)
#   setcalls       one line per `iw reg set` invocation
#   setfreq_count  count of `set freq` invocations (drives drift scenarios)
set -u
STATE="${IW_STUB_STATE:?IW_STUB_STATE not set}"
mkdir -p "$STATE"
domain() { cat "$STATE/domain" 2>/dev/null || printf '%s\n' "${IW_STUB_INITIAL_DOMAIN:-US}"; }
cmd="$1"
case "$cmd" in
  reg)
    if [[ "${2:-}" == "get" ]]; then
      printf 'global\ncountry %s: DFS-FCC\n\t(2402 - 2472 @ 40), (N/A, 30), (N/A)\n' "$(domain)"
      if [[ -f "$STATE/phydomain" ]]; then
        printf 'phy#3\ncountry %s: DFS-FCC\n' "$(cat "$STATE/phydomain")"
      fi
      exit 0
    fi
    if [[ "${2:-}" == "set" ]]; then
      echo "set ${3:-}" >> "$STATE/setcalls"
      if [[ "${IW_STUB_CONVERGE:-1}" == "1" ]]; then
        printf '%s\n' "$3" > "$STATE/domain"
        rm -f "$STATE/phydomain"
      fi
      exit 0
    fi
    exit 0
    ;;
  dev)
    if [[ $# -eq 1 ]]; then
      printf 'phy#3\n\tInterface %s\n\t\tifindex 5\n\t\twdev 0x1\n\t\taddr 00:c0:ca:00:00:01\n\t\ttype managed\n\t\twiphy 3\n' "$IW_STUB_IFACE"
      exit 0
    fi
    action="${3:-}"
    if [[ "$action" == "info" ]]; then
      ch="$(cat "$STATE/setfreq" 2>/dev/null || echo 2412)"
      printf 'Interface %s\n\tifindex 5\n\twdev 0x1\n\taddr 00:c0:ca:00:00:01\n\twiphy 3\n\ttype monitor\n\tchannel 1 (%s MHz), width: 20 MHz\n' "${2:-}" "$ch"
      exit 0
    fi
    if [[ "$action" == "set" ]]; then
      if [[ "${4:-}" == "freq" ]]; then
        n="$(cat "$STATE/setfreq_count" 2>/dev/null || echo 0)"
        n=$((n + 1))
        echo "$n" > "$STATE/setfreq_count"
        echo "$5" > "$STATE/setfreq"
        flip="${IW_STUB_FLIP_AFTER_SETFREQ:-}"
        if [[ -n "$flip" && "$n" -eq "$flip" ]]; then
          printf '00\n' > "$STATE/domain"
          rm -f "$STATE/phydomain"
        fi
      fi
      exit 0
    fi
    ;;
  phy)
    if [[ "$(domain)" == "US" ]]; then
      cat <<'EOT'
Wiphy phy3
	Band 1:
		Frequencies:
			* 2412.0 MHz [1] (30.0 dBm)
			* 2437.0 MHz [6] (30.0 dBm)
			* 2467.0 MHz [12] (30.0 dBm) (disabled)
			* 2472.0 MHz [13] (30.0 dBm) (disabled)
			* 2484.0 MHz [14] (30.0 dBm) (disabled)
	Band 2:
		Frequencies:
			* 5180.0 MHz [36] (23.0 dBm) (radar detection)
			* 5845.0 MHz [169] (23.0 dBm) (no IR)
	Band 4:
		Frequencies:
			* 5955.0 MHz [1] (12.0 dBm) (no IR)
			* 6115.0 MHz [33] (12.0 dBm) (no IR)
EOT
    else
      cat <<'EOT'
Wiphy phy3
	Band 1:
		Frequencies:
			* 2412.0 MHz [1] (30.0 dBm) (no IR)
			* 2437.0 MHz [6] (30.0 dBm) (no IR)
			* 2467.0 MHz [12] (30.0 dBm) (no IR)
			* 2472.0 MHz [13] (30.0 dBm) (no IR)
			* 2484.0 MHz [14] (30.0 dBm) (disabled)
	Band 2:
		Frequencies:
			* 5180.0 MHz [36] (23.0 dBm) (no IR)
			* 5845.0 MHz [169] (23.0 dBm) (disabled)
	Band 4:
		Frequencies:
			* 5955.0 MHz [1] (12.0 dBm) (disabled)
			* 6115.0 MHz [33] (12.0 dBm) (disabled)
EOT
    fi
    ;;
esac
exit 0
"""

IP_STUB = r"""#!/usr/bin/env bash
# Test stub for ip: the stub interface always exists, every form succeeds.
exit 0
"""

TCPDUMP_STUB = r"""#!/usr/bin/env bash
# Test stub for tcpdump: writes an empty radiotap pcap immediately, reports
# listening on stderr, then exits on its own. A background job inherits
# SIGINT ignored and a non-interactive shell cannot trap a signal ignored on
# entry, so the collector's kill -INT cannot stop this stub; exiting a
# moment after the dwell is equivalent for the collector's control flow.
set -u
out=""
prev=""
for a in "$@"; do
  if [[ "$prev" == "-w" ]]; then out="$a"; fi
  prev="$a"
done
printf '\xd4\xc3\xb2\xa1\x02\x00\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\x00\x00\x7f\x00\x00\x00' > "$out"
echo "tcpdump: listening on ${IW_STUB_IFACE:-stub0}, link-type radiotap" >&2
sleep 2
"""


def write_stubs(shim: Path) -> None:
    shim.mkdir(parents=True, exist_ok=True)
    for name, body in (("iw", IW_STUB), ("ip", IP_STUB), ("tcpdump", TCPDUMP_STUB)):
        path = shim / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)


def run_collector(
    tmp: Path,
    *,
    initial_domain: str,
    extra_env: dict[str, str] | None = None,
    collector: Path | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess:
    """Run the collector in a stubbed environment and return the result."""
    state = tmp / "state"
    state.mkdir(exist_ok=True)
    if initial_domain:
        (state / "domain").write_text(initial_domain + "\n", encoding="utf-8")
    shim = tmp / "shim"
    write_stubs(shim)
    env = os.environ.copy()
    env["PATH"] = f"{shim}:{env.get('PATH', '')}"
    env["IW_STUB_STATE"] = str(state)
    env["IW_STUB_IFACE"] = IFACE
    env["IW_STUB_INITIAL_DOMAIN"] = initial_domain
    env.update(extra_env or {})
    return subprocess.run(
        [
            "bash",
            str(collector or SCRIPT),
            "-i", IFACE,
            "-o", str(tmp / "out"),
            "-d", "1",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def run_dir(tmp: Path) -> Path:
    runs = [p for p in (tmp / "out").iterdir() if p.is_dir()]
    assert len(runs) == 1, f"expected one run directory, got {runs}"
    return runs[0]


def read_instrument(tmp: Path) -> dict:
    return json.loads(
        (run_dir(tmp) / "instrument.json").read_text(encoding="utf-8")
    )


def read_manifest(tmp: Path) -> list[dict]:
    with (run_dir(tmp) / "frequencies.tsv").open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def swap_blocks(text: str, first: tuple[str, str], second: tuple[str, str]) -> str:
    """Return text with the two marked blocks exchanged, markers intact."""
    a0 = text.index(first[0])
    a1 = text.index(first[1], a0) + len(first[1])
    b0 = text.index(second[0])
    b1 = text.index(second[1], b0) + len(second[1])
    block_a, block_b = text[a0:a1], text[b0:b1]
    between = text[a1:b0]
    return text[:a0] + block_b + between + block_a + text[b1:]


@unittest.skipUnless(os.geteuid() == 0, "collector refuses non-root; run under sudo")
class CollectorPreflightTests(unittest.TestCase):
    def test_help_declares_domain_option(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "-h"], capture_output=True, text=True, check=False
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("-r DOMAIN", result.stdout)

    def test_found_declared_domain_records_without_set(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            result = run_collector(tmp, initial_domain="US")
            self.assertEqual(0, result.returncode, result.stderr)
            instrument = read_instrument(tmp)
            self.assertEqual("wifi-beacon-survey/instrument/2", instrument["schema"])
            self.assertEqual("sweep", instrument["run_status"])
            self.assertEqual("US", instrument["regulatory_domain"])
            self.assertEqual("US", instrument["regulatory_domain_declared"])
            self.assertFalse(instrument["regulatory_domain_set_attempted"])
            self.assertEqual("already_declared", instrument["regulatory_domain_set_result"])
            self.assertEqual("US", instrument["regulatory_domain_at_discovery"])
            self.assertEqual("US", instrument["regulatory_domain_post_sweep"])
            state = tmp / "state"
            setcalls = state / "setcalls"
            self.assertFalse(
                setcalls.exists() and setcalls.read_text().strip(),
                "no `iw reg set` may be issued when the domain already reads US",
            )

    def test_found_world_domain_sets_and_verifies(self):
        # The "discovery reflects the post-set domain" test: discovery must run
        # only after the domain is established, so the manifest carries US flags.
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            result = run_collector(tmp, initial_domain="00")
            self.assertEqual(0, result.returncode, result.stderr)
            instrument = read_instrument(tmp)
            self.assertEqual("sweep", instrument["run_status"])
            self.assertEqual("00", instrument["regulatory_domain"])
            self.assertEqual("US", instrument["regulatory_domain_declared"])
            self.assertTrue(instrument["regulatory_domain_set_attempted"])
            self.assertEqual("established", instrument["regulatory_domain_set_result"])
            self.assertEqual("US", instrument["regulatory_domain_at_discovery"])
            self.assertEqual("US", instrument["regulatory_domain_post_sweep"])
            setcalls = tmp / "state" / "setcalls"
            self.assertEqual(1, len(setcalls.read_text().splitlines()))
            self.assertIn("set US", setcalls.read_text())

            manifest = read_manifest(tmp)
            self.assertEqual(9, len(manifest), "stub lists nine frequencies")
            by_freq = {row["frequency_mhz"]: row for row in manifest}
            for freq in ("5955", "6115"):
                self.assertEqual("no-ir", by_freq[freq]["regulatory_state"])
                self.assertEqual("sampled_empty", by_freq[freq]["sample_status"])
            for freq in ("2467", "2472", "2484"):
                self.assertEqual("disabled", by_freq[freq]["regulatory_state"])
                self.assertEqual("regulatory_skip", by_freq[freq]["sample_status"])

    def test_never_converges_refuses(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            start = time.monotonic()
            result = run_collector(
                tmp,
                initial_domain="00",
                extra_env={"IW_STUB_CONVERGE": "0"},
            )
            elapsed = time.monotonic() - start
            self.assertNotEqual(0, result.returncode, "refusal must exit non-zero")
            self.assertGreaterEqual(elapsed, 25, "refusal must honor the 30 s bound")
            self.assertLessEqual(elapsed, 60, f"refusal overran the bound: {elapsed:.1f}s")
            instrument = read_instrument(tmp)
            self.assertEqual("refused_regulatory_domain", instrument["run_status"])
            self.assertEqual("wifi-beacon-survey/instrument/2", instrument["schema"])
            self.assertTrue(instrument["regulatory_domain_set_attempted"])
            self.assertEqual("failed", instrument["regulatory_domain_set_result"])
            self.assertEqual("00", instrument["regulatory_domain_at_discovery"])
            self.assertIsNone(instrument["regulatory_domain_post_sweep"])
            run = run_dir(tmp)
            for name in ("frequencies.tsv", "aggregate.tsv"):
                lines = (run / name).read_text(encoding="utf-8").splitlines()
                self.assertEqual(1, len(lines), f"{name} must be header-only on refusal")
            self.assertEqual([], list(run.glob("*.pcap")), "refusal must write no PCAP")

    def test_post_sweep_drift_recorded_not_error(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            result = run_collector(
                tmp,
                initial_domain="US",
                extra_env={"IW_STUB_FLIP_AFTER_SETFREQ": "2"},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            instrument = read_instrument(tmp)
            self.assertEqual("sweep", instrument["run_status"])
            self.assertFalse(instrument["regulatory_domain_set_attempted"])
            self.assertEqual("00", instrument["regulatory_domain_post_sweep"])
            self.assertEqual("US", instrument["regulatory_domain_at_discovery"])

    def test_phy_override_wins_effective_domain(self):
        # A self-managed PHY country overrides the global domain, so the
        # preflight must see 00 (phy section) even while the host reads US.
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            state = tmp / "state"
            state.mkdir(parents=True)
            (state / "domain").write_text("US\n", encoding="utf-8")
            (state / "phydomain").write_text("00\n", encoding="utf-8")
            result = run_collector(tmp, initial_domain="")
            self.assertEqual(0, result.returncode, result.stderr)
            instrument = read_instrument(tmp)
            self.assertTrue(instrument["regulatory_domain_set_attempted"])
            self.assertEqual("established", instrument["regulatory_domain_set_result"])
            self.assertEqual("US", instrument["regulatory_domain_at_discovery"])

    def test_mutation_discovery_before_preflight_fails_discovery_test(self):
        # Scratch copy with frequency discovery moved ahead of the preflight.
        # The world-domain scenario must then fail its discovery assertion:
        # the manifest would carry the stale world flags instead of US flags.
        text = SCRIPT.read_text(encoding="utf-8")
        try:
            mutated_text = swap_blocks(
                text,
                (PREFLIGHT_BEGIN, PREFLIGHT_END),
                (DISCOVERY_BEGIN, DISCOVERY_END),
            )
        except ValueError:
            self.fail("preflight/discovery markers not found in collector script")
        self.assertNotEqual(text, mutated_text)
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            mutated = tmp / "mutated.sh"
            mutated.write_text(mutated_text, encoding="utf-8")
            mutated.chmod(0o755)
            result = run_collector(tmp, initial_domain="00", collector=mutated)
            self.assertEqual(0, result.returncode, result.stderr)
            manifest = read_manifest(tmp)
            by_freq = {row["frequency_mhz"]: row for row in manifest}
            stale = any(
                by_freq[f]["regulatory_state"] == "disabled"
                or by_freq[f]["sample_status"] == "regulatory_skip"
                for f in ("5955", "6115")
            )
            self.assertTrue(
                stale,
                "mutation was not detected: discovery ahead of preflight still "
                "produced US-flag rows, so this test guards nothing",
            )


if __name__ == "__main__":
    unittest.main()
