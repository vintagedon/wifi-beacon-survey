"""Synthetic beacon PCAP fixture builder for the enrichment tests.

Element payloads for the extension namespace are lifted verbatim from live
pilot captures (20260829-220002/freq-2447.pcap, frame 2) so they dissect
cleanly on the installed tshark 4.2.2. The one synthetic element (HE 6 GHz,
ext 59 -- absent from the live run) emits its tag number correctly while
raising a dissector warning, and is therefore kept in its own frame.

Imported by tests/test_pilot_enrich.py; the leading underscore keeps unittest
discovery from treating it as a test module.
"""

import struct
from pathlib import Path

_PCAP_MAGIC = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 127)


def ie(tag: int, payload: bytes) -> bytes:
    return bytes([tag, len(payload)]) + payload


def radiotap() -> bytes:
    # flags field present, value 0 = FCS omitted
    return struct.pack("<BBH", 0, 0, 9) + struct.pack("<I", 0x00000002) + b"\x00"


def beacon(addr: str, seq: int = 0, elements: bytes = b"",
           ts: float = 0.0, interval: int = 100) -> bytes:
    fc = struct.pack("<H", 0x0080)
    dur = struct.pack("<H", 0)
    da = b"\xff" * 6
    sa = bytes.fromhex(addr.replace(":", ""))
    sc = struct.pack("<H", seq << 4)
    body = struct.pack("<Q", int(ts * 1_000_000) << 0) if False else \
        struct.pack("<Q", 0) + struct.pack("<H", interval) + struct.pack("<H", 0x0011)
    return radiotap() + fc + dur + da + sa + sa + sc + body + elements


def write_pcap(path: Path, packets: list[tuple[float, bytes]]) -> None:
    """Write radiotap packets with (timestamp_epoch, raw_bytes) pairs."""
    with open(path, "wb") as fh:
        fh.write(_PCAP_MAGIC)
        for ts, pkt in packets:
            sec = int(ts)
            usec = int(round((ts - sec) * 1_000_000))
            fh.write(struct.pack("<IIII", sec, usec, len(pkt), len(pkt)))
            fh.write(pkt)


def bss_load(stations: int, utilization: int, admission: int) -> bytes:
    return ie(11, struct.pack("<HBH", stations, utilization, admission))


def ext_element(ext_id: int, payload: bytes) -> bytes:
    return ie(255, bytes([ext_id]) + payload)


def tbtt13(bssid_hex: str, short_ssid: int, params: int = 0x00,
           psd: int = 0x00) -> bytes:
    info = b"\xff" + bytes.fromhex(bssid_hex.replace(":", "")) \
        + struct.pack("<I", short_ssid) + bytes([params, psd])
    assert len(info) == 13
    return info


def tbtt16(bssid_hex: str, short_ssid: int, params: int, mld_id: int,
           link_id: int, disabled: bool) -> bytes:
    return tbtt13(bssid_hex, short_ssid, params) + bytes(
        [mld_id, link_id & 0x0F, 0x20 if disabled else 0x00])


def rnr_element(op_class: int, channel: int, infos: list[bytes]) -> bytes:
    # TBTT Information Count is the number of ADDITIONAL infos beyond the
    # first; the dissector parses count+1 infos off the element end.
    count = len(infos) - 1
    header = bytes([(count & 0x0F) << 4, len(infos[0]), op_class, channel])
    return ie(201, header + b"".join(infos))


# Real extension-namespace payloads lifted from the live pilot.
HE_CAPS = bytes.fromhex("0500081a44100220ce926f09af0c110c00fafffaff091c07")
EHT_CAPS = bytes.fromhex("8300e801017e1860081200222222")
EHT_OPER = bytes.fromhex("0111000000000800")
MULTI_LINK = bytes.fromhex("b0010d828a069b7d9e000401000100")
# Synthetic (no live ext-59 exists): carries the element number cleanly.
HE_6GHZ = bytes.fromhex("030000000000")

AP1 = "aa:bb:cc:00:11:22"
AP2 = "dd:ee:ff:00:22:33"
AP3 = "11:22:33:44:55:66"
AP4 = "60:70:80:00:33:44"

T_BASE = 1_787_000_000.0


def ap1_elements(with_6ghz: bool) -> bytes:
    els = (
        ie(0, b"TestNet")
        + ie(3, bytes([1]))
        + bss_load(7, 42, 300)
        + rnr_element(81, 3, [tbtt13("000000112233", 0x12345678, params=0x0A)])
        + ext_element(35, HE_CAPS)
        + ext_element(108, EHT_CAPS)
        + ext_element(106, EHT_OPER)
        + ext_element(107, MULTI_LINK)
    )
    if with_6ghz:
        els += ext_element(59, HE_6GHZ)
    return els


def ap2_elements() -> bytes:
    return (
        ie(0, b"Mesh")
        + rnr_element(129, 37, [tbtt13("000000aabbcc", 0xAABBCCDD, params=0x04),
                                tbtt13("000000112244", 0x11223344)])
    )


def ap2_disabled_element() -> bytes:
    """A safely paired 6 GHz neighbor with an administratively disabled
    link, in its own frame so it counts as a single occurrence."""
    return (
        ie(0, b"Mesh")
        + rnr_element(131, 5, [tbtt16("000000556677", 0x55667788, 0x00,
                                      mld_id=3, link_id=2, disabled=True)])
    )


def build_run_dir(run_dir: Path) -> None:
    """Build a synthetic single-pcap run directory shaped like a pilot run."""
    run_dir.mkdir(parents=True, exist_ok=True)
    ap4_els = (
        ie(0, b"SixGhzAdv")
        + rnr_element(131, 5, [tbtt13("000000607080", 0x60708090)])
    )
    write_pcap(run_dir / "freq-2412.pcap", [
        (T_BASE + 0.25, beacon(AP1, elements=ap1_elements(with_6ghz=False), ts=T_BASE)),
        (T_BASE + 5.25, beacon(AP1, seq=1, elements=ap1_elements(with_6ghz=True),
                               ts=T_BASE + 5)),
        (T_BASE + 9.75, beacon(AP2, seq=2, elements=ap2_elements(),
                               ts=T_BASE + 9.5)),
        (T_BASE + 9.8, beacon(AP2, seq=5, elements=ap2_disabled_element(),
                              ts=T_BASE + 9.7)),
        (T_BASE + 9.9, beacon(AP3, seq=3, elements=ie(0, b"NoRnr"),
                              ts=T_BASE + 9.75)),
        (T_BASE + 9.95, beacon(AP4, seq=4, elements=ap4_els,
                               ts=T_BASE + 9.9)),
    ])
    # An empty 2.4 GHz frequency and an empty 6 GHz frequency: negative
    # observations that must survive into Parquet.
    (run_dir / "freq-2437.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + bytes(20))
    (run_dir / "freq-5955.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + bytes(20))

    freq_header = ("band\tfrequency_mhz\tchannel\tregulatory_state\t"
                   "sample_status\tdwell_seconds\tpcap_file\tbssid_count\t"
                   "beacon_count\terror\n")
    (run_dir / "frequencies.tsv").write_text(
        freq_header
        + "2.4GHz\t2412\t1\tpermitted\tsampled\t10\tfreq-2412.pcap\t4\t5\t\n"
        + "2.4GHz\t2437\t6\tpermitted\tsampled_empty\t10\tfreq-2437.pcap\t0\t0\t\n"
        + "6GHz\t5955\t1\tno-ir\tsampled_empty\t10\tfreq-5955.pcap\t0\t0\t\n",
        encoding="utf-8")

    agg_header = ("band\tfrequency_mhz\tchannel\tbssid\tssid\tbeacons\t"
                  "beacon_interval_tu\trssi_min_dbm\trssi_mean_dbm\t"
                  "rssi_max_dbm\tfirst_seen\tlast_seen\t"
                  "beacon_reception_ratio\n")
    (run_dir / "aggregate.tsv").write_text(
        agg_header
        + f"2.4GHz\t2412\t1\t{AP1}\tTestNet\t2\t100\t-70\t-69.5\t-69\t"
          "2026-08-27T13:00:03.459251Z\t2026-08-27T13:00:08.265788Z\t0.200\n"
        + f"2.4GHz\t2412\t1\t{AP2}\tMesh\t1\t100\t-80\t-80.0\t-80\t"
          "2026-08-27T13:00:09.750000Z\t2026-08-27T13:00:09.750000Z\t0.100\n"
        + f"2.4GHz\t2412\t1\t{AP3}\tNoRnr\t1\t100\t-90\t-89.0\t-89\t"
          "2026-08-27T13:00:09.900000Z\t2026-08-27T13:00:09.900000Z\t0.100\n"
        + f"2.4GHz\t2412\t1\t{AP4}\tSixGhzAdv\t1\t100\t-75\t-75.0\t-75\t"
          "2026-08-27T13:00:09.950000Z\t2026-08-27T13:00:09.950000Z\t0.100\n",
        encoding="utf-8")

    instrument = {
        "schema": "wifi-beacon-survey/instrument/1",
        "run_status": "sweep",
        "skip_reason": None,
        "started_utc": "2026-08-27T13:00:03Z",
        "interface_present": True,
    }
    import json
    (run_dir / "instrument.json").write_text(json.dumps(instrument),
                                             encoding="utf-8")
