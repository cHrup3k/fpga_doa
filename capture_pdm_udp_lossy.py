#!/usr/bin/env python3

import argparse
import csv
import socket
import struct
import time
from pathlib import Path

import numpy as np
from litex import RemoteClient


HEADER_FMT  = ">4sBBBBIQIIHH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAGIC       = b"PDM1"


def parse_header(packet):
    (
        magic,
        version,
        channels,
        stride,
        flags,
        sequence,
        first_sample,
        pdm_freq,
        dropped_frames,
        samples_in_packet,
        reserved,
    ) = struct.unpack(HEADER_FMT, packet[:HEADER_SIZE])

    return {
        "magic": magic,
        "version": version,
        "channels": channels,
        "stride": stride,
        "flags": flags,
        "sequence": sequence,
        "first_sample": first_sample,
        "pdm_freq": pdm_freq,
        "dropped_frames": dropped_frames,
        "samples": samples_in_packet,
        "reserved": reserved,
    }


def make_neutral_payload(channels, stride, samples, first_sample):
    """
    Synthetic 50% PDM used ONLY to mark missing UDP regions while preserving
    the original time axis. Every active microphone alternates 0/1 in time.
    """
    frame0 = bytes(stride)

    mask = bytearray(stride)
    for ch in range(channels):
        mask[ch // 8] |= 1 << (ch % 8)
    frame1 = bytes(mask)

    out = bytearray(samples * stride)
    p = 0
    for i in range(samples):
        frame = frame1 if ((first_sample + i) & 1) else frame0
        out[p:p+stride] = frame
        p += stride
    return bytes(out)


def pulse_start(wb, target_packets, samples_per_packet):
    target_samples = target_packets * samples_per_packet

    wb.regs.pdm_udp_target_samples.write(target_samples)
    wb.regs.pdm_udp_target_packets.write(target_packets)

    wb.regs.pdm_udp_start.write(0)
    wb.regs.pdm_udp_start.write(1)
    wb.regs.pdm_udp_start.write(0)

    return target_samples


def missing_ranges(valid):
    """Return inclusive [start,end] ranges of missing packet numbers."""
    ranges = []
    start = None

    for i, ok in enumerate(valid):
        if not ok and start is None:
            start = i
        elif ok and start is not None:
            ranges.append((start, i - 1))
            start = None

    if start is not None:
        ranges.append((start, len(valid) - 1))

    return ranges


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Controlled PDM/UDP capture that ALWAYS saves the timeline. "
            "Missing UDP packets are replaced with synthetic 50% PDM and "
            "listed separately in a loss map."
        )
    )
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--bind-ip", default="192.168.1.100")
    ap.add_argument("--udp-port", type=int, default=2000)
    ap.add_argument("--csr-csv", default="csr.csv")
    ap.add_argument("--server-host", default="localhost")
    ap.add_argument("--server-port", type=int, default=1234)
    ap.add_argument("--output", default="capture_udp_interleaved.bin")
    ap.add_argument("--timeout", type=float, default=2.0)
    args = ap.parse_args()

    if args.seconds <= 0:
        raise SystemExit("--seconds must be > 0")

    # ------------------------------------------------------------------
    # UDP receiver first: bind BEFORE START.
    # ------------------------------------------------------------------
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 * 1024 * 1024)
    actual_rcvbuf = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
    sock.bind((args.bind_ip, args.udp_port))
    sock.settimeout(args.timeout)

    # ------------------------------------------------------------------
    # Read FPGA configuration over UARTBone server.
    # ------------------------------------------------------------------
    wb = RemoteClient(
        host=args.server_host,
        port=args.server_port,
        csr_csv=args.csr_csv,
        timeout=5.0,
        raise_on_timeout=True,
    )
    wb.open()

    try:
        channels     = wb.regs.pdm_udp_channels.read()
        stride       = wb.regs.pdm_udp_bytes_per_sample.read()
        spp          = wb.regs.pdm_udp_samples_per_packet.read()
        packet_bytes = wb.regs.pdm_udp_packet_bytes.read()
        pdm_freq     = wb.regs.pdm_udp_pdm_frequency.read()

        payload_bytes = stride * spp
        assert packet_bytes == HEADER_SIZE + payload_bytes

        target_packets = max(1, int(round(args.seconds * pdm_freq / spp)))
        target_samples = target_packets * spp
        actual_seconds = target_samples / pdm_freq

        print("Loss-tolerant PDM/UDP capture")
        print("--------------------------------")
        print("channels          :", channels)
        print("bytes/sample      :", stride)
        print("PDM frequency     :", pdm_freq, "Hz")
        print("samples/packet    :", spp)
        print("UDP payload       :", packet_bytes, "bytes")
        print("SO_RCVBUF         :", actual_rcvbuf, "bytes")
        print("requested time    :", args.seconds, "s")
        print("actual time       :", f"{actual_seconds:.6f}", "s")
        print("target packets    :", target_packets)
        print("target samples    :", target_samples)
        print()

        # ------------------------------------------------------------------
        # Pre-create the COMPLETE time axis with neutral 50% PDM.
        # Received packets overwrite their correct sequence locations.
        # ------------------------------------------------------------------
        out_path = Path(args.output)

        with out_path.open("wb") as f:
            for seq in range(target_packets):
                first_sample = seq * spp
                f.write(
                    make_neutral_payload(
                        channels=channels,
                        stride=stride,
                        samples=spp,
                        first_sample=first_sample,
                    )
                )

        valid = bytearray(target_packets)

        # Clear any datagrams left from an older capture.
        sock.setblocking(False)
        flushed = 0
        while True:
            try:
                sock.recvfrom(2048)
                flushed += 1
            except BlockingIOError:
                break
        sock.settimeout(args.timeout)

        if flushed:
            print("Flushed stale packets:", flushed)

        # START: sequence counter is reset to 0 by the FPGA gateware.
        pulse_start(wb, target_packets, spp)

        print("START sent. Receiving...")
        print()

        received_unique = 0
        duplicates      = 0
        bad_packets     = 0
        out_of_range    = 0

        t0 = time.monotonic()
        last_report = t0

        with out_path.open("r+b", buffering=0) as f:
            while received_unique < target_packets:
                try:
                    packet, _addr = sock.recvfrom(2048)
                except socket.timeout:
                    # If the FPGA has already completed, no reason to wait.
                    fpga_done = wb.regs.pdm_udp_done.read()
                    if fpga_done:
                        break
                    continue

                if len(packet) != packet_bytes or len(packet) < HEADER_SIZE:
                    bad_packets += 1
                    continue

                try:
                    h = parse_header(packet)
                except Exception:
                    bad_packets += 1
                    continue

                if h["magic"] != MAGIC or h["version"] != 1:
                    bad_packets += 1
                    continue

                if (h["channels"] != channels or
                    h["stride"] != stride or
                    h["samples"] != spp):
                    bad_packets += 1
                    continue

                seq = h["sequence"]

                if seq >= target_packets:
                    out_of_range += 1
                    continue

                payload = packet[HEADER_SIZE:]
                if len(payload) != payload_bytes:
                    bad_packets += 1
                    continue

                if valid[seq]:
                    duplicates += 1
                    continue

                # Random-access write puts this packet at its true time location.
                f.seek(seq * payload_bytes)
                f.write(payload)

                valid[seq] = 1
                received_unique += 1

                now = time.monotonic()
                if now - last_report >= 0.5:
                    missing_now = target_packets - received_unique
                    print(
                        f"\rreceived={received_unique}/{target_packets}"
                        f"  missing={missing_now}"
                        f"  bad={bad_packets}"
                        f"  dup={duplicates}",
                        end="",
                        flush=True,
                    )
                    last_report = now

        print()

        # Final FPGA status over UARTBone.
        fpga_done    = wb.regs.pdm_udp_done.read()
        fpga_active  = wb.regs.pdm_udp_active.read()
        fpga_samples = wb.regs.pdm_udp_samples_done.read()
        fpga_packets = wb.regs.pdm_udp_packets_done.read()
        fpga_dropped = wb.regs.pdm_udp_dropped_frames.read()
        fifo_level   = wb.regs.pdm_udp_fifo_level.read()

    finally:
        wb.close()
        sock.close()

    missing = [i for i, ok in enumerate(valid) if not ok]
    ranges  = missing_ranges(valid)

    # ------------------------------------------------------------------
    # Save packet-valid mask + loss map.
    # ------------------------------------------------------------------
    valid_path = Path("packet_valid.bin")
    valid_path.write_bytes(bytes(valid))

    loss_path = Path("loss_map.csv")
    with loss_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "first_missing_packet",
            "last_missing_packet",
            "packet_count",
            "first_missing_sample",
            "last_missing_sample_exclusive",
            "start_time_s",
            "end_time_s",
        ])

        for a, b in ranges:
            first_sample = a * spp
            end_sample   = (b + 1) * spp
            w.writerow([
                a,
                b,
                b - a + 1,
                first_sample,
                end_sample,
                f"{first_sample / pdm_freq:.9f}",
                f"{end_sample / pdm_freq:.9f}",
            ])

    print()
    print("FPGA status")
    print("--------------------------------")
    print("done              :", fpga_done)
    print("active            :", fpga_active)
    print("samples_done      :", fpga_samples)
    print("packets_done      :", fpga_packets)
    print("dropped_frames    :", fpga_dropped)
    print("fifo_level        :", fifo_level)

    print()
    print("Host receive")
    print("--------------------------------")
    print("received packets  :", sum(valid))
    print("missing packets   :", len(missing))
    print("packet loss       :", f"{100.0 * len(missing) / target_packets:.3f}%")
    print("bad packets       :", bad_packets)
    print("duplicates        :", duplicates)
    print("out of range      :", out_of_range)
    print("loss ranges       :", len(ranges))

    print()
    print("Saved")
    print("--------------------------------")
    print(out_path, "- de-packetized, full time axis")
    print(valid_path, "- 1 byte/packet: 1=real, 0=missing")
    print(loss_path, "- missing regions with sample/time positions")

    # ------------------------------------------------------------------
    # Split interleaved time-major file into conventional PDM files.
    # ------------------------------------------------------------------
    raw = np.fromfile(out_path, dtype=np.uint8)
    frames = raw.reshape(-1, stride)

    bits = np.unpackbits(
        frames,
        axis=1,
        bitorder="little",
    )[:, :channels]

    print()
    print("Per-channel files")
    print("--------------------------------")
    for ch in range(channels):
        packed = np.packbits(
            bits[:, ch],
            bitorder="big",
        )

        path = Path(f"mic{ch}.pdm")
        path.write_bytes(packed.tobytes())

        density = float(bits[:, ch].mean() * 100.0)

        print(
            f"mic{ch}: {len(packed):9d} B"
            f"  ones={density:8.4f}%"
            f"  -> {path}"
        )

    if missing:
        print()
        print(
            "NOTE: missing network regions in mic*.pdm contain synthetic "
            "50% PDM, not microphone data. Use loss_map.csv / packet_valid.bin "
            "to exclude them from analysis."
        )


if __name__ == "__main__":
    main()
