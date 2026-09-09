<!--
---
title: "Operations Runbook"
description: "Known failure modes of the receiver on ml01 and how to diagnose them"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-09-09"
version: "1.2"
status: "Active"
tags:
  - type: runbook
  - domain: instrument
  - tech: [bash]
related_documents:
  - "[Repository root](../README.md)"
  - "[Instrument Changelog](instrument-changelog.md)"
  - "[Collector](../scripts/wifi-beacon-sample.sh)"
---
-->

# Operations Runbook

Failure modes observed on this receiver, with the evidence that distinguishes them. Every entry here has actually happened; nothing is anticipatory.

When the interface is absent the collector now records the downtime rather than failing silently: it creates the run directory, writes manifest and aggregate headers with zero frequency rows, and writes `instrument.json` with `run_status=skipped_no_interface`, then exits 0. For the earlier ten-day outage, which predates that behaviour, `dmesg` and Semaphore task history are the only evidence, and they remain the reference for anything in this document that occurred before the skip record existed.

---

## 1. Triage Order

```bash
ip link show wlx00c0cab63b82     # is there a netdev at all
lsusb -t                          # which controller, which speed, which driver
sudo dmesg -T | grep -iE 'usb|mt79|xhci|bluetooth' | tail -40
iw reg get                        # regulatory domain
iw dev wlx00c0cab63b82 info       # type, should be monitor or managed
```

`ip link show` is the authoritative test. Plain `lsusb` will list a device that never finished enumerating, so a MediaTek line there does not mean the receiver is usable. A device stuck at address zero appears as `Device 000` and is absent from `lsusb -t`.

---

## 2. Failure: Enumeration Fails on One USB Controller

**Observed**: 2026-08-16, again 2026-08-25 through 2026-08-27. This enumeration failure accounts for only the last two to three days of the outage. The full ten-day gap from 2026-08-17 was the hourly schedule never having been armed (review finding R1); the receiver was healthy until the 08-25 reboot, which is when this fault surfaced.

**Signature**:

```
usb 4-2: new SuperSpeed USB device number 7 using xhci_hcd
usb 4-2: New USB device found, idVendor=0e8d, idProduct=7961
xhci_hcd 0000:0b:00.3: Timeout while waiting for setup device command
usb 4-2: device not accepting address 7, error -62
usb usb4-port2: attempt power cycle
usb usb4-port2: unable to enumerate USB device
```

Descriptors read successfully, then Address Device times out with `-62` (ETIME) across several address attempts and a port power cycle. This is a link-layer failure, not a power failure; a supply problem typically shows `-71` during descriptor reads instead.

**Cause**: ml01 has two USB controllers. On `0000:0b:00.3` (Bus 003 at 480M, Bus 004 at 10000M) the adapter does not complete enumeration. On the other controller (Bus 001 at 480M, Bus 002 at 10000M) it enumerates normally at high speed.

**Resolution**: use a port on Bus 001. Confirm with `lsusb -t`, which should show the MediaTek device at `480M` with `Driver=mt7921u`.

**Not the cause**: a 6 ft USB 3 extension cable was suspected and tested out. The failure reproduces identically with the adapter plugged directly into the affected controller.

**Persistence**: none. This is a physical fact about which port the adapter occupies and there is no configuration holding it. If the adapter is ever moved, this failure returns. A udev rule keyed on the controller path would let the collector refuse to run when the adapter lands on the wrong one, and has not been written.

**Bandwidth note**: high speed is sufficient. A full tri-band sweep produces roughly 2.1 to 2.7 MB (measured across the first hourly series; larger since IC-001 raised BSSID counts), and beacon-filtered monitor capture on a 20 MHz channel does not approach USB 2.0 throughput.

---

## 3. Failure: btusb Wedges the Combo Device

**Observed**: 2026-08-16, resolved at the time with `modprobe -r btusb`, which was never made persistent.

**Background**: the MT7921AU is a combined Wi-Fi and Bluetooth device. `btusb` binds USB interfaces 0 through 2, `mt7921u` binds interface 3. If the Bluetooth function fails to initialise, it can take the whole device down before the Wi-Fi function probes, which surfaces as:

```
mt7921u: probe of 4-2:1.3 failed with error -5
```

**Signature on a marginal link**:

```
Bluetooth: hci1: Device setup in 2970834 usecs
Bluetooth: hci1: Opcode 0x0c03 failed: -110
usb 1-6: device descriptor read/64, error -110
```

`hci1` is the MediaTek's Bluetooth function, not the onboard Realtek radio at `0bda:0852`. Setup taking seconds rather than milliseconds indicates the device is struggling before HCI_Reset times out.

**Recurrence, 2026-09-07 to 2026-09-09**: the adapter's Bluetooth function wedged the USB core on ml01 twice. A probe stuck in uninterruptible sleep held the USB core and module locks, so `lsusb` stopped after its first line, a subsequent `modprobe` hung, and `reboot` never completed while the host still answered ping. Physically unplugging the adapter did not clear it; only a hard power cycle did. The receiver was absent for 41 consecutive hourly runs, `20260907-090003` through `20260909-010003`, each recorded as `skipped_no_interface`. Host-side diagnosis is in `/opt/agents/repos/work-logs/2026-09-09-infra-worklog-00-ml01-ups-swap-nut-telemetry-and-usb-bt-blacklist.md`.

**Current state**: the Bluetooth function is blocked at the module layer. `/etc/modprobe.d/ml01-alfa-mt7921.conf` carries `blacklist btmtk` and `install btusb /bin/false`, and initramfs was rebuilt. `modprobe btusb` returns nonzero immediately instead of hanging, and `mt7921u` binds normally on a Bus 001 port.

**If it recurs**:

```bash
sudo systemctl stop bluetooth
sudo modprobe -r btusb
ip link show wlx00c0cab63b82
```

A plain `blacklist btusb` is not enough and was the form originally written here. A blacklist suppresses autoload by alias only, so an explicit `modprobe btusb` still loads the module, and that is precisely the command that wedges the host. `install btusb /bin/false` makes it fail with a nonzero return instead. Blocking `btusb` outright is device-agnostic and takes the onboard Realtek radio with it; ml01 has no Bluetooth requirement, so the blunt form is acceptable here. A udev rule unbinding `btusb` from `0e8d:7961` alone is the targeted alternative.

**Verification**: `btusb` absent from `lsmod`, and `modprobe btusb` returning nonzero. Do not expect `btmtk` to be absent, and do not read its presence as a failed fix. Module dependencies are inserted before the install command runs, so at boot udev pulls in `btmtk`, `btrtl`, `btintel`, and `btbcm`, then `/bin/false` stops `btusb` itself. `btmtk` sits resident at refcount 0 with nothing able to bind through it, and `blacklist btmtk` does not prevent this because a blacklist does not govern dependency insertion. Confirmed on ml01 across the 2026-09-09 boot: `journalctl -b | grep 'install command'` shows the block firing during udev enumeration.

**Diagnostic caution**: absence of `Bluetooth:` lines in `dmesg` does not exonerate `btusb`. If the device never reaches address assignment, no interface driver binds and none logs anything. Compare across controllers before drawing a conclusion.

---

## 4. Failure: Regulatory Domain Reverts to World

**Observed**: 2026-08-16, 2026-08-27, and again 2026-09-05, each time across a driver reload. The 2026-09-05 occurrence went undetected for 53 consecutive runs and is recorded as [IC-002](instrument-changelog.md).

**Signature**: `iw reg get` reports `country 00` behaviour. In the sweep manifest this appears as 2467, 2472, and 2484 MHz flagged `no-ir` rather than `disabled`, every 5 GHz frequency flagged `no-ir`, 5845, 5865, and 5885 MHz flagged `disabled`, and all 59 6 GHz frequencies flagged `disabled` with `regulatory_skip` at dwell 0. In `instrument.json` it appears as `regulatory_domain: "00"`, which is the cheapest check and the one to automate.

**Severity**: worse than the 2.4 GHz signature suggests. Country 00 exposes no 5925-7125 MHz block at all, so the entire 6 GHz band stops being enumerated rather than being swept and found empty. A run under world domain looks successful and produces no 6 GHz measurement whatsoever.

**Effect on capture**: reception is unaffected, since no-IR restricts transmission only and this receiver never transmits. The effect is on the frequency set. The collector derives its sweep from live kernel regulatory state, so a domain change silently alters which frequencies are visited. Under world, 2467 MHz gets swept where US skips it.

**Resolution**:

```bash
sudo iw reg set US
iw reg get
```

**Persistence**: not yet solved, but no longer an open question. `sudo iw reg set US` took on 2026-09-09 and `iw reg get` returns no `phy#` section, so this driver is not self-managing its domain and the collection contract can pin it rather than only asserting it. The intended pin is `options cfg80211 ieee80211_regdom=US` under `/etc/modprobe.d` with an initramfs rebuild, verified across a cold boot. Not yet applied.

**Design note**: the collector records per-frequency regulatory state in `frequencies.tsv`, so a domain change lands in the evidence rather than silently altering the series. That property should be stated in the collection contract rather than left implicit.

---

## 5. Gaps

Known and not yet addressed:

- Nothing asserts which USB controller the adapter is on, so section 2 recurs silently.
- The regulatory domain is set by hand after any driver reload. The module-layer pin in section 4 is known to be workable and is not applied.
- Nothing asserts the domain at run start, so a reverted domain produces a run that looks successful while silently sweeping a different frequency set. This is what made IC-002 cost 53 runs instead of one.
- A scheduled run that never fires leaves no record at all, unlike an absent receiver. The 2026-09-09 02:00 slot is the example: the host was rebooting when the job triggered, so there is no run directory to distinguish it from a slot that was never scheduled.

Recently addressed: an absent receiver now produces a skip record (`run_status=skipped_no_interface`) instead of nothing, so instrument downtime is recorded in the series rather than inferred from Semaphore history. That path was exercised for 41 consecutive runs during the 2026-09-07 outage with no failures. The Bluetooth wedge in section 3 is now blocked at the module layer.
