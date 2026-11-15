#!/usr/bin/env python3

from migen import *
from migen.genlib.cdc import MultiReg

from litex.gen import LiteXModule
from litex.build.generic_platform import Pins, Subsignal, IOStandard
from litex.build.parser import LiteXArgumentParser
from litex.soc.integration.builder import Builder
from litex.soc.interconnect import stream
from litex.soc.interconnect.csr import CSRStatus, CSRStorage

from liteeth.common import convert_ip

from litex_boards.platforms import colorlight_i5
from litex_boards.targets.colorlight_i5 import BaseSoC


SYS_CLK_FREQ = 60_000_000
PDM_CLK_FREQ = 2_500_000

LOCAL_IP  = "192.168.1.50"
REMOTE_IP = "192.168.1.100"
UDP_PORT  = 2000

HEADER_BYTES      = 32
MAX_PACKET_BYTES  = 1408
DATA_CAPACITY     = MAX_PACKET_BYTES - HEADER_BYTES

# Enough for several PDM packets. The packetizer only starts when a complete
# payload is already present.
SAMPLE_FIFO_DEPTH = 8192

# Give the Etherbone START write time to finish before the first PDM sample is
# captured. This also keeps control traffic away from the beginning of stream.
START_DELAY_MS     = 20
START_DELAY_CYCLES = (SYS_CLK_FREQ // 1000) * START_DELAY_MS


class PDMStereoSharedUDPStreamer(LiteXModule):
    def __init__(self, pdm, udp, data_lines,
                 remote_ip=REMOTE_IP, udp_port=UDP_PORT):

        assert 1 <= data_lines <= 64

        # Each physical DATA line carries two microphones:
        #   channel 2*n     = L/R=GND, valid while CLK is LOW
        #   channel 2*n + 1 = L/R=VDD, valid while CLK is HIGH
        channels = 2 * data_lines

        bytes_per_sample  = (channels + 7) // 8
        samples_per_packet = DATA_CAPACITY // bytes_per_sample
        data_bytes         = samples_per_packet * bytes_per_sample
        packet_bytes       = HEADER_BYTES + data_bytes

        # ------------------------------------------------------------------
        # LiteEth UDP user port.
        #
        # We intentionally drive the UDP user endpoint directly instead of
        # putting LiteEthStream2UDPTX in front of it. We already have our own
        # full-packet FIFO/packetizer, so this keeps one source of packet
        # length/last handling out of the path.
        # ------------------------------------------------------------------

        udp_ep = udp.crossbar.get_port(
            udp_port,
            dw=8,
            cd="etherbone",
            depth=32,
        )

        u = udp_ep.sink

        # ------------------------------------------------------------------
        # PDM clock: 60 MHz / 24 = 2.5 MHz.
        # All requested CLK pins carry the same internal clock.
        # ------------------------------------------------------------------

        divider = SYS_CLK_FREQ // PDM_CLK_FREQ
        assert divider == 24
        half = divider // 2

        phase     = Signal(max=divider)
        pdm_clk_r = Signal(reset=1)

        self.comb += pdm.clk.eq(Replicate(pdm_clk_r, len(pdm.clk)))

        self.sync.etherbone += [
            If(phase == (half - 1),
                pdm_clk_r.eq(0),
                phase.eq(half),
            ).Elif(phase == (divider - 1),
                pdm_clk_r.eq(1),
                phase.eq(0),
            ).Else(
                phase.eq(phase + 1)
            )
        ]

        # ------------------------------------------------------------------
        # Synchronize shared DATA lines and sample BOTH clock phases.
        #
        # MP34DT01 stereo sharing:
        #   L/R=GND -> DATA valid while CLK is LOW
        #   L/R=VDD -> DATA valid while CLK is HIGH
        #
        # We sample near the middle of each half-cycle, well away from
        # the transition/high-Z hand-off.
        # ------------------------------------------------------------------

        pdm_sync = Signal(data_lines)
        self.specials += MultiReg(pdm.data, pdm_sync, odomain="etherbone")

        sample_high_phase = half // 2
        sample_low_phase  = half + half // 2

        sample_high_tick = Signal()
        sample_low_tick  = Signal()

        self.comb += [
            sample_high_tick.eq(phase == sample_high_phase),
            sample_low_tick.eq(phase == sample_low_phase),
        ]

        # Stored HIGH-half samples (L/R=VDD microphones).
        high_samples = Signal(data_lines)

        # One logical frame contains one bit from every microphone.
        # Pair ordering:
        #   bit0 = DATA0 / L/R=GND
        #   bit1 = DATA0 / L/R=VDD
        #   bit2 = DATA1 / L/R=GND
        #   bit3 = DATA1 / L/R=VDD
        #   ...
        logical_frame = Signal(channels)
        last_frame    = Signal(channels)

        for i in range(data_lines):
            self.comb += [
                logical_frame[2*i + 0].eq(pdm_sync[i]),
                logical_frame[2*i + 1].eq(high_samples[i]),
            ]

        # ------------------------------------------------------------------
        # Byte FIFO containing time-major PDM frames.
        #
        # For one shared DATA line / two microphones:
        #   byte bit0 = MIC0 = L/R=GND (LOW phase)
        #        bit1 = MIC1 = L/R=VDD (HIGH phase)
        #
        # For four DATA lines / eight microphones:
        #   bit0/1 = pair on DATA0
        #   bit2/3 = pair on DATA1
        #   bit4/5 = pair on DATA2
        #   bit6/7 = pair on DATA3
        #
        # For 128 microphones (64 shared DATA lines), each logical
        # sample frame occupies 16 bytes.
        # ------------------------------------------------------------------

        self.sample_fifo = sample_fifo = ClockDomainsRenamer("etherbone")(
            stream.SyncFIFO(
                [("data", 8)],
                depth=SAMPLE_FIFO_DEPTH,
                buffered=True,
            )
        )

        frame_width = 8 * bytes_per_sample
        frame_shift = Signal(frame_width)
        bytes_left  = Signal(max=max(bytes_per_sample + 1, 2))

        # ------------------------------------------------------------------
        # Host control.
        #
        # Host writes:
        #   target_samples = whole number of sample frames to acquire
        #   target_packets = matching whole number of UDP packets
        #   start          = 0 -> 1 -> 0
        #
        # target_samples must equal target_packets * samples_per_packet.
        # ------------------------------------------------------------------

        self.start          = CSRStorage(1,  reset=0, description="Start capture on 0->1 edge.")
        self.target_samples = CSRStorage(32, reset=0, description="Number of PDM time samples to capture.")
        self.target_packets = CSRStorage(32, reset=0, description="Number of UDP packets expected.")

        self.active         = CSRStatus(1,  description="PDM acquisition is currently active.")
        self.done           = CSRStatus(1,  description="Requested capture has been handed to LiteEth.")
        self.samples_done   = CSRStatus(32, description="PDM sample frames accepted in current capture.")
        self.packets_done   = CSRStatus(32, description="UDP packets handed to LiteEth in current capture.")
        self.dropped_frames = CSRStatus(32, description="PDM frames lost because local serializer/FIFO stalled.")
        self.fifo_level     = CSRStatus(32, description="Current local sample FIFO level in bytes.")
        self.packet_state   = CSRStatus(2,  description="0 WAIT, 1 HEADER, 2 DATA.")
        self.pdm_inputs     = CSRStatus(channels, description="Last complete logical PDM frame (LOW/HIGH pairs).")

        self.channels           = CSRStatus(8,  description="Configured microphone channel count.")
        self.bytes_per_sample   = CSRStatus(8,  description="Bytes per simultaneous PDM sample frame.")
        self.samples_per_packet = CSRStatus(16, description="PDM time samples in one UDP packet.")
        self.packet_bytes       = CSRStatus(16, description="UDP payload bytes including custom 32-byte header.")
        self.pdm_frequency      = CSRStatus(32, description="PDM clock/sample frequency in Hz.")

        capture_active = Signal()
        done_flag      = Signal()
        samples_count  = Signal(32)
        packets_count  = Signal(32)
        dropped_count  = Signal(32)

        start_d     = Signal()
        start_pulse = Signal()
        self.comb += start_pulse.eq(self.start.storage & ~start_d)
        self.sync.etherbone += start_d.eq(self.start.storage)

        start_delay = Signal(max=START_DELAY_CYCLES + 1)
        armed       = Signal()

        # ------------------------------------------------------------------
        # Packet header, 32 bytes, network/big-endian fields.
        #
        #  0..3   magic               "PDM1"
        #  4      version             1
        #  5      channel count
        #  6      bytes/sample
        #  7      flags               0
        #  8..11  packet sequence
        # 12..19  first sample index
        # 20..23  PDM frequency
        # 24..27  dropped frame count
        # 28..29  samples/packet
        # 30..31  reserved
        # ------------------------------------------------------------------

        sequence         = Signal(32)
        first_sample     = Signal(64)
        dropped_snapshot = Signal(32)

        header_index = Signal(max=HEADER_BYTES)
        data_count   = Signal(max=data_bytes + 1)

        pdm_freq = PDM_CLK_FREQ
        spp      = samples_per_packet

        header = Array([
            ord("P"), ord("D"), ord("M"), ord("1"),
            1,
            channels,
            bytes_per_sample,
            0,

            sequence[24:32],
            sequence[16:24],
            sequence[8:16],
            sequence[0:8],

            first_sample[56:64],
            first_sample[48:56],
            first_sample[40:48],
            first_sample[32:40],
            first_sample[24:32],
            first_sample[16:24],
            first_sample[8:16],
            first_sample[0:8],

            (pdm_freq >> 24) & 0xff,
            (pdm_freq >> 16) & 0xff,
            (pdm_freq >>  8) & 0xff,
            (pdm_freq >>  0) & 0xff,

            dropped_snapshot[24:32],
            dropped_snapshot[16:24],
            dropped_snapshot[8:16],
            dropped_snapshot[0:8],

            (spp >> 8) & 0xff,
            (spp >> 0) & 0xff,
            0,
            0,
        ])

        ST_WAIT   = 0
        ST_HEADER = 1
        ST_DATA   = 2
        state = Signal(2, reset=ST_WAIT)

        # ------------------------------------------------------------------
        # Direct UDP endpoint drive.
        # ------------------------------------------------------------------

        self.comb += [
            u.valid.eq(0),
            u.first.eq(0),
            u.last.eq(0),
            u.data.eq(0),
            u.last_be.eq(1),
            u.error.eq(0),

            u.src_port.eq(udp_port),
            u.dst_port.eq(udp_port),
            u.ip_address.eq(convert_ip(remote_ip)),
            u.length.eq(packet_bytes),

            sample_fifo.source.ready.eq(0),

            If(state == ST_HEADER,
                u.valid.eq(1),
                u.first.eq(header_index == 0),
                u.data.eq(header[header_index]),

            ).Elif(state == ST_DATA,
                u.valid.eq(sample_fifo.source.valid),
                u.data.eq(sample_fifo.source.data),
                u.last.eq(data_count == (data_bytes - 1)),
                sample_fifo.source.ready.eq(u.ready),
            )
        ]

        # Byte serializer into local FIFO.
        self.comb += [
            sample_fifo.sink.valid.eq(bytes_left != 0),
            sample_fifo.sink.data.eq(frame_shift[:8]),
        ]

        # Status.
        self.comb += [
            self.active.status.eq(capture_active),
            self.done.status.eq(done_flag),
            self.samples_done.status.eq(samples_count),
            self.packets_done.status.eq(packets_count),
            self.dropped_frames.status.eq(dropped_count),
            self.fifo_level.status.eq(sample_fifo.level),
            self.packet_state.status.eq(state),
            self.pdm_inputs.status.eq(last_frame),

            self.channels.status.eq(channels),
            self.bytes_per_sample.status.eq(bytes_per_sample),
            self.samples_per_packet.status.eq(samples_per_packet),
            self.packet_bytes.status.eq(packet_bytes),
            self.pdm_frequency.status.eq(PDM_CLK_FREQ),
        ]

        # ------------------------------------------------------------------
        # Main capture + packetizer state.
        # ------------------------------------------------------------------

        self.sync.etherbone += [
            If(start_pulse,
                # New acquisition.
                capture_active.eq(0),
                done_flag.eq(0),
                armed.eq(1),
                start_delay.eq(START_DELAY_CYCLES),

                samples_count.eq(0),
                packets_count.eq(0),
                dropped_count.eq(0),

                sequence.eq(0),
                first_sample.eq(0),
                dropped_snapshot.eq(0),

                frame_shift.eq(0),
                bytes_left.eq(0),

                header_index.eq(0),
                data_count.eq(0),
                state.eq(ST_WAIT),

            ).Else(
                # Small quiet period after the Etherbone START write.
                If(armed,
                    If(start_delay != 0,
                        start_delay.eq(start_delay - 1)
                    ).Else(
                        armed.eq(0),
                        If((self.target_samples.storage != 0) &
                           (self.target_packets.storage != 0),
                            capture_active.eq(1)
                        ).Else(
                            done_flag.eq(1)
                        )
                    )
                ),

                # Serialize a previously latched simultaneous PDM frame.
                If(sample_fifo.sink.valid & sample_fifo.sink.ready,
                    frame_shift.eq(frame_shift >> 8),
                    bytes_left.eq(bytes_left - 1),
                ),

                # HIGH phase: capture the L/R=VDD microphones.
                # Do this continuously so a START command does not have to
                # align to a particular PDM clock edge.
                If(sample_high_tick,
                    high_samples.eq(pdm_sync)
                ),

                # LOW phase: current DATA is from the L/R=GND microphones.
                # Combine it with the previously stored HIGH-half samples,
                # producing one simultaneous logical sample frame.
                If(sample_low_tick,
                    last_frame.eq(logical_frame),

                    If(capture_active,
                        If(bytes_left == 0,
                            frame_shift.eq(logical_frame),
                            bytes_left.eq(bytes_per_sample),
                            samples_count.eq(samples_count + 1),

                            If((samples_count + 1) >= self.target_samples.storage,
                                capture_active.eq(0)
                            )
                        ).Else(
                            dropped_count.eq(dropped_count + 1)
                        )
                    )
                ),

                # Build a UDP packet only when the whole raw-data portion is
                # already present in the local FIFO.
                If(state == ST_WAIT,
                    If((packets_count < self.target_packets.storage) &
                       (sample_fifo.level >= data_bytes),
                        dropped_snapshot.eq(dropped_count),
                        header_index.eq(0),
                        data_count.eq(0),
                        state.eq(ST_HEADER)
                    )

                ).Elif(state == ST_HEADER,
                    If(u.valid & u.ready,
                        If(header_index == (HEADER_BYTES - 1),
                            data_count.eq(0),
                            state.eq(ST_DATA)
                        ).Else(
                            header_index.eq(header_index + 1)
                        )
                    )

                ).Elif(state == ST_DATA,
                    If(u.valid & u.ready,
                        If(data_count == (data_bytes - 1),
                            packets_count.eq(packets_count + 1),
                            sequence.eq(sequence + 1),
                            first_sample.eq(first_sample + samples_per_packet),
                            data_count.eq(0),
                            state.eq(ST_WAIT),

                            If((packets_count + 1) >= self.target_packets.storage,
                                done_flag.eq(1)
                            )
                        ).Else(
                            data_count.eq(data_count + 1)
                        )
                    )
                )
            )
        ]


class PDMUDPSoC(BaseSoC):
    def __init__(self,
                 pdm_clk_pins,
                 pdm_data_pins,
                 toolchain="trellis",
                 eth_phy=0,
                 **kwargs):

        data_lines = len(pdm_data_pins)

        BaseSoC.__init__(
            self,
            board="i5",
            revision="7.0",
            toolchain=toolchain,
            sys_clk_freq=SYS_CLK_FREQ,

            with_etherbone=True,
            eth_ip=LOCAL_IP,
            eth_phy=eth_phy,

            with_led_chaser=False,
            **kwargs
        )

        self.platform.add_extension([
            ("pdm", 0,
                Subsignal("clk",  Pins(" ".join(pdm_clk_pins))),
                Subsignal("data", Pins(" ".join(pdm_data_pins))),
                IOStandard("LVCMOS33"),
            )
        ])

        pdm = self.platform.request("pdm")

        self.pdm_udp = PDMStereoSharedUDPStreamer(
            pdm       = pdm,
            udp       = self.ethcore_etherbone.udp,
            data_lines= data_lines,
            remote_ip = REMOTE_IP,
            udp_port  = UDP_PORT,
        )


def main():
    parser = LiteXArgumentParser(
        platform=colorlight_i5.Platform,
        description="Colorlight i5 shared-line stereo PDM pairs -> UDP."
    )

    parser.add_target_argument(
        "--pdm-clk-pins",
        default="F5",
        help=(
            'Common PDM clock output pin, or one clock pin per DATA pair. '
            'For the current two-microphone setup use "F5".'
        )
    )

    parser.add_target_argument(
        "--pdm-data-pins",
        required=True,
        help=(
            'Shared PDM DATA pins, one physical line per microphone pair. '
            'Each line carries L/R=GND + L/R=VDD. '
            'For the current two-microphone setup use "E5".'
        )
    )

    parser.add_target_argument(
        "--eth-phy",
        default=0,
        type=int,
        help="Colorlight Ethernet PHY index (default: 0)."
    )

    args = parser.parse_args()

    pdm_clk_pins = args.pdm_clk_pins.replace(",", " ").split()
    pdm_data_pins = args.pdm_data_pins.replace(",", " ").split()

    if not pdm_clk_pins:
        raise ValueError("Need at least one PDM CLK pin.")

    if len(pdm_clk_pins) not in (1, len(pdm_data_pins)):
        raise ValueError(
            "Use one shared PDM CLK pin, or exactly one CLK pin per shared DATA pair."
        )

    if not (1 <= len(pdm_data_pins) <= 64):
        raise ValueError(
            "Need between 1 and 64 shared PDM DATA pins "
            "(2 to 128 logical microphones)."
        )

    soc = PDMUDPSoC(
        pdm_clk_pins  = pdm_clk_pins,
        pdm_data_pins = pdm_data_pins,
        toolchain     = args.toolchain,
        eth_phy       = args.eth_phy,
        **parser.soc_argdict,
    )

    builder = Builder(soc, **parser.builder_argdict)

    if args.build:
        builder.build(**parser.toolchain_argdict)


if __name__ == "__main__":
    main()
