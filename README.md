# DOA FPGA project: modular multichannel PDM acquisition

A working acquisition prototype for microphone-array and direction-of-arrival (DOA) experiments. A Colorlight i5 FPGA captures two digital PDM microphones on each shared DATA line, packages the samples and sends them to a computer over Ethernet/UDP. The host controls recording through LiteX over USB/UART and saves raw data for later analysis.

**Start with Ubuntu 22.04.5 LTS, x86-64.** This is the operating system identified on the project machine. The tutorial covers a new installation, running the supplied bitstream and rebuilding the same 16-channel design. Commands use Bash. Hardware operation on a newly assembled replica must still be checked.

The supplied design performs **acquisition**, not embedded DOA estimation. No direction estimator, measurement dataset, thesis, Python virtual environment or installed FPGA toolchain is included in this folder. DOA processing runs separately on a computer. The modular prototype can be extended for further studies.

## 1. What is included

```text
.
├── README.md
├── capture_pdm_lossy.py          # requested short name; calls unchanged implementation
├── capture_pdm_udp_lossy.py      # original loss-aware host receiver
├── pdm_udp_share.py              # requested short name; calls unchanged implementation
├── pdm_udp_stereo_shared.py      # original Migen/LiteX FPGA design
├── csr.csv                      # register map matching the supplied bitstream
├── build/                       # COMPLETE copy of the original build tree
│   └── colorlight_i5/
│       ├── csr.json
│       ├── gateware/            # .bit, .svf, Verilog, LPF, JSON, logs, initialization files
│       └── software/            # generated BIOS, libraries, sources and build products
├── dependencies.lock.json       # locally observed LiteX-family repository revisions
├── requirements.txt
├── patches/
│   └── litex-boards-dynamic-link.patch
├── scripts/
│   ├── install_dependencies.py
│   ├── build.sh
│   ├── read_registers.py
│   ├── record.sh
│   └── verify_package.py
└── docs/
    ├── setup_original.txt       # original setup.txt, unchanged
    ├── package_manifest.json    # copied-file hashes and observed configuration
    ├── VALIDATION.md
    └── THIRD_PARTY_NOTICES.md
```

The filenames requested for this package were not present verbatim in the source project. The two short-name files are small launchers for the actual originals. Both original implementations are copied without changes.

`build/` is an archive of generated files, approximately 118 MiB on disk. Its nested picolibc Git pointer is preserved separately under `docs/archived_metadata/` for upload portability. New builds go into `build_local/`, which is ignored by Git. Do not run the archived `.ys` or software Makefiles as a portable build recipe: they contain original absolute paths. Use `scripts/build.sh` to generate paths for your computer.

## 2. Hardware and wiring

### Components

| Component | Purpose / requirement |
|---|---|
| Colorlight i5, revision 7.0 | ECP5 LFE5U-25F, 381-ball package; this is the platform selected by the source. Other board revisions need separate validation. |
| Compatible i5 breakout board | Exposes GPIO and Ethernet; the referenced breakout schematic contains an STM32F103C8T6 with DAPLink/CMSIS-DAP support. |
| USB data cable | Connects the breakout programmer and USB CDC serial interface to Ubuntu. A charge-only cable will not work. |
| Ethernet cable and host Ethernet interface | The saved build selects Ethernet PHY 0; connect the corresponding board port. |
| 16 compatible digital PDM microphones | Eight shared DATA lines, two microphones per line, with complementary L/R selection. |
| Microphone supply, common ground and wiring | Use the selected microphone's documented supply and I/O levels. Do not supply microphones from FPGA GPIO. |
| Mechanical mount | The author's prototype uses connectable 3D-printed line sections holding four microphones each. CAD files and measured assembly tolerances are not included. |
| Sound source | Needed to check actual acoustic capture; playback equipment and level are not specified by this source bundle. |

The shared-line source comments describe MP34DT01-style phase sharing. Other project versions mention a different sensor, so the installed microphone model is **not established by these files**. Before replicating the wiring, confirm the actual sensor datasheet, supply, tri-state sharing and L/R phase convention. The FPGA extension uses `LVCMOS33`; compatibility with a particular microphone must be established electrically.

The STM32 is the programming/communication bridge. FPGA logic captures the microphones. A VexRiscv soft processor is present in the LiteX SoC. The host receives raw data. Do not confuse these roles or assume the STM32 calculates DOA.

### Supplied GPIO assignment

Pin names below are **FPGA package pad names**, not SODIMM connector contact numbers. Translate them using the exact breakout schematic/pinout. The local board documentation used by the project is available in [Colorlight-FPGA-Projects](https://github.com/wuxx/Colorlight-FPGA-Projects), including its [breakout schematic](https://github.com/wuxx/Colorlight-FPGA-Projects/blob/master/schematic/i5-i9-extboard.pdf).

| Pair | CLK pad | DATA pad | Low-phase, L/R = GND | High-phase, L/R = VDD |
|---|---|---|---|---|
| 0 | F5 | E18 | mic0 | mic1 |
| 1 | E6 | G16 | mic2 | mic3 |
| 2 | H16 | E5 | mic4 | mic5 |
| 3 | F18 | F4 | mic6 | mic7 |
| 4 | B3 | K5 | mic8 | mic9 |
| 5 | K4 | A2 | mic10 | mic11 |
| 6 | F1 | F2 | mic12 | mic13 |
| 7 | E4 | E1 | mic14 | mic15 |

Join the two microphone DATA outputs in a pair only if the microphones support complementary phase sharing. Connect their L/R inputs to opposite documented logic levels. All modules share ground. All listed CLK outputs carry the same internally generated PDM clock.

The module has a nominal 25 MHz oscillator. This design uses a 60 MHz system clock and nominal 2.5 MHz PDM clock. Opposite phases are sampled about 200 ns apart, not at one identical electrical instant. The format groups them into a logical frame. Physical array coordinates are separate from logical channel order and must be recorded for later DOA processing.

## 3. Install Ubuntu and the base packages

Install **Ubuntu 22.04.5 LTS Desktop, 64-bit** on the recording computer, or start from that version already installed. This guide uses native Linux for USB and Ethernet access. If using a VM, USB programmer pass-through and a correctly bridged recording interface are additional requirements.

Check the system:

```bash
cat /etc/os-release
uname -m
```

The architecture should be `x86_64`. Install base tools and the RISC-V bare-metal compiler:

```bash
sudo apt update
sudo apt install -y \
  build-essential git curl wget ca-certificates xz-utils \
  python3 python3-venv python3-dev python3-pip \
  meson ninja-build cmake pkg-config \
  gcc-riscv64-unknown-elf binutils-riscv64-unknown-elf \
  libusb-1.0-0 libftdi1-2 libhidapi-hidraw0 \
  iproute2 iputils-ping usbutils
```

`gcc-riscv64-unknown-elf` builds the VexRiscv BIOS. The original generated build names this compiler family; the locally observed compiler is GCC 10.2.0. Meson and Ninja support the software library build. No Verilator, proprietary Lattice toolchain or full embedded Linux image is needed for this design.

## 4. Obtain this project and create its Python environment

Copy this folder's contents into a directory such as `~/doa-fpga`. If published on GitHub, clone that repository and enter its project directory. All commands below start in the directory containing this README and `csr.csv`.

```bash
cd ~/doa-fpga
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

Use the project environment rather than `sudo pip`. There are two dependency paths:

**Only run the supplied bitstream:**

```bash
python scripts/install_dependencies.py --host-only
```

This installs receiver requirements plus Migen and LiteX at the recorded repository revisions. The host needs NumPy, PySerial and LiteX RemoteClient/`litex_server`; synthesis cores are unnecessary for this path.

**Rebuild the FPGA and run it:**

```bash
python scripts/install_dependencies.py
```

This additionally installs LiteX-Boards, LiteEth, LiteDRAM, LiteICLink, LiteSPI, LiteSATA, LiteSDCard, LiteScope, VexRiscv HDL data and compiler runtime/C-library data. Repositories are cloned into `.deps/`, checked out at recorded commits, and installed in editable mode. Software-data submodules are initialized recursively. Pip can also install their declared Python dependencies.

**Important project-specific patch:** the full installer applies `patches/litex-boards-dynamic-link.patch` to the pinned Colorlight i5 target. It adds `with_dynamic_link=True` to its RGMII PHY construction, matching the local target used by this project. A plain upstream checkout without this patch is not the same source environment. The installer refuses to replace an existing dependency checkout at a different revision.

The [official LiteX installation guide](https://github.com/enjoy-digital/litex/wiki/Installation) explains the editable Git installation workflow. This package records local dependency revisions instead of silently selecting today's upstream master. The exact historical revisions of every library were not logged at synthesis time, so the lock file describes the **observed local source environment**, not a promise of a bit-identical rebuild.

## 5. Install the FPGA tools

Use the Linux x64 **OSS CAD Suite** archive. It supplies Yosys, nextpnr-ecp5, Project Trellis tools including `ecppack`, and openFPGALoader. Yosys alone is not sufficient.

The local suite version is `20260907`. The following command uses its [2026-09-07 release](https://github.com/YosysHQ/oss-cad-suite-build/releases/tag/2026-09-07):

```bash
mkdir -p "$HOME/tools"
cd "$HOME/tools"
curl -fL --retry 3 \
  -o oss-cad-suite-linux-x64-20260907.tgz \
  https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-09-07/oss-cad-suite-linux-x64-20260907.tgz
tar -xzf oss-cad-suite-linux-x64-20260907.tgz
export PATH="$HOME/tools/oss-cad-suite/bin:$PATH"
cd ~/doa-fpga
source .venv/bin/activate
```

Do not extract over an unrelated existing `oss-cad-suite` installation. Use a separate tools directory in that case. The upstream [OSS CAD Suite installation instructions](https://github.com/YosysHQ/oss-cad-suite-build#installation) describe alternative platforms and PATH setup.

**Activate in this order in each new terminal:**

```bash
export PATH="$HOME/tools/oss-cad-suite/bin:$PATH"
cd ~/doa-fpga
source .venv/bin/activate
```

This keeps the Ubuntu Python 3.10 virtual environment in front of the suite's bundled Python. Sourcing the suite's `environment` file after the project venv can replace its Python environment; this guide uses PATH-only activation.

Check the tools:

```bash
command -v python yosys nextpnr-ecp5 ecppack openFPGALoader litex_server
yosys -V
nextpnr-ecp5 --version
openFPGALoader --Version
riscv64-unknown-elf-gcc --version
python capture_pdm_lossy.py --help
```

Observed local versions are Yosys `0.68+195` (git `435977e97-dirty`), nextpnr `0.11.1-22-g3cfc28d0`, and openFPGALoader `1.1.1`. They are recorded as provenance, not inferred from the build's modification time.

## 6. Set up USB access

Add the user to the serial and programmer groups:

```bash
sudo usermod -aG dialout,plugdev "$USER"
```

Log out and back in for group changes. Install programmer udev rules if your system does not already have them:

```bash
curl -fL \
  https://raw.githubusercontent.com/trabucayre/openFPGALoader/master/99-openfpgaloader.rules \
  -o /tmp/99-openfpgaloader.rules
sudo install -m 644 /tmp/99-openfpgaloader.rules /etc/udev/rules.d/99-openfpgaloader.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Disconnect and reconnect the USB cable. These instructions follow the programmer's [installation and udev guide](https://trabucayre.github.io/openFPGALoader/guide/install.html). Check enumeration:

```bash
lsusb
ls -l /dev/serial/by-id/
ls -l /dev/ttyACM*
```

The old setup used `/dev/ttyACM1`; this number is not portable. Select the corresponding DAPLink CDC device, preferably its stable `/dev/serial/by-id/...` path. Close other serial-terminal programs before starting `litex_server`.

## 7. Choose the supplied build or make a new one

### A. Use the supplied 16-channel bitstream

Verify the copied files:

```bash
python scripts/verify_package.py
```

Use these files together:

```text
Bitstream: build/colorlight_i5/gateware/colorlight_i5.bit
Registers: csr.csv
```

This is the shortest route for identical wiring and board revision. Skip synthesis and continue with Section 8. Every copied file retains its original bytes. One nested picolibc `.git` pointer was moved to `docs/archived_metadata/picolibc_git_pointer.txt` so Git treats the software sources as ordinary files rather than an embedded repository. It has not been reprogrammed onto hardware as part of packaging.

### B. Rebuild the same design

Complete the **full** dependency installation from Section 4 and the toolchain installation. Then run:

```bash
bash scripts/build.sh
```

The script contains the build options from the original `setup.txt` and writes:

```text
Bitstream: build_local/colorlight_i5/gateware/colorlight_i5.bit
Registers: build_local/csr.csv
```

It uses PHY 0, UART crossover, UARTBone at 115200 baud, ROM size `0xc000`, L2 size `2048`, the eight DATA pins and eight CLK pins in Section 2. It does not delete or overwrite the archived `build/` tree.

The sequence builds the VexRiscv BIOS, generates Verilog and constraints, synthesizes with Yosys, places/routes with nextpnr-ecp5 and packs the ECP5 bitstream with `ecppack`. Do not substitute a build generated for another FPGA package or board revision.

The archived nextpnr command contains `--timing-allow-fail`. Its presence means a generated bitstream alone does **not** demonstrate timing closure. Check the timing messages of your new build; never describe a rebuild as timing-verified solely because it emitted a `.bit` file.

## 8. Program the FPGA over JTAG

For the supplied build:

```bash
openFPGALoader -c cmsisdap build/colorlight_i5/gateware/colorlight_i5.bit
```

For your rebuilt design:

```bash
openFPGALoader -c cmsisdap build_local/colorlight_i5/gateware/colorlight_i5.bit
```

This is volatile FPGA configuration. No flash-writing option is used. After a power cycle, load the bitstream again. If the USB interface rejects permission, resolve group/udev access from Section 6. For diagnosis only, the original setup ran the loader using `sudo` and an explicit binary path.

Connect a USB **data** cable to the breakout programmer, power the board and connect the intended Ethernet port. The STM32's programmer firmware is assumed to be present; this package contains the FPGA image, not a replacement STM32 firmware image.

## 9. Configure the recording Ethernet interface

The gateware constants are:

```text
FPGA IPv4:       192.168.1.50
Destination IP:  192.168.1.100
PDM UDP port:    2000
UART server:    TCP localhost:1234
```

The TCP server is a host-side bridge to the serial control interface. PDM data arrives on the separate Ethernet/UDP path.

Find the dedicated host recording interface:

```bash
ip -br link
```

Replace `enp3s0` below with its actual name. On an interface intended for this direct connection:

```bash
PDM_IF=enp3s0
sudo ip link set dev "$PDM_IF" up
sudo ip addr add 192.168.1.100/24 dev "$PDM_IF"
ip -br addr show dev "$PDM_IF"
ping -c 3 192.168.1.50
```

If the address is already present, do not add it again. These `ip` settings are temporary; configure the same address through NetworkManager if you want persistence. Avoid a conflicting route through Wi-Fi or another interface using the same subnet. A dedicated Ethernet link is simplest. Ping after loading also helps establish address resolution before the first recording.

Allow inbound UDP port 2000 on this interface if a host firewall blocks it. With UFW enabled, a narrow rule for this source and destination is:

```bash
sudo ufw allow in on "$PDM_IF" from 192.168.1.50 to 192.168.1.100 port 2000 proto udp
```

For sustained reception, temporarily raise Linux receive-buffer limits:

```bash
sudo sysctl -w net.core.rmem_max=33554432
sudo sysctl -w net.core.rmem_default=33554432
```

The receiver requests a large socket buffer. A small kernel limit can still cause packet loss. No global firewall disable or persistent sysctl change is required by this guide.

## 10. Start control and record data

Keep the virtual environment active in both terminals.

### Terminal 1: serial control server

Use the port found in Section 6. The following uses the original example only:

```bash
litex_server --uart --uart-port=/dev/ttyACM1 --uart-baudrate=115200
```

Leave it running. The server defaults to TCP port 1234.

### Terminal 2: register check

For the supplied bitstream:

```bash
python scripts/read_registers.py --csr-csv csr.csv
```

For the rebuilt bitstream:

```bash
python scripts/read_registers.py --csr-csv build_local/csr.csv
```

For the supplied 16-channel configuration, expect:

```text
channels          16
pdm_frequency     2500000
bytes_per_sample  2
samples_per_packet 688
packet_bytes      1408
```

The two-channel values shown in the old `setup.txt` are an earlier example, not the values for the eight-DATA-line build. Do not proceed with a mismatched register map. Use the `csr.csv` generated with the loaded bitstream.

### Record five seconds into a new folder

Using the supplied build:

```bash
bash scripts/record.sh 5
```

Using your rebuilt design:

```bash
CSR_CSV="$PWD/build_local/csr.csv" bash scripts/record.sh 5
```

Each invocation creates a unique directory under `captures/` and retains `capture.log`, including the final FPGA drop counters. Files are never intentionally written into the source tree's recording examples. A first short trial can be discarded if address resolution caused initial missing packets; inspect the validity map before treating the next trial as complete.

Equivalent direct invocation, from a **new empty** recording directory, is:

```bash
python /absolute/path/to/doa-fpga/capture_pdm_lossy.py \
  --seconds 5 \
  --csr-csv /absolute/path/to/doa-fpga/csr.csv
```

The direct receiver writes several fixed filenames in its current directory. Reusing that directory overwrites its earlier output. Prefer `record.sh` for routine use.

Expected output files:

| File | Content |
|---|---|
| `capture_udp_interleaved.bin` | Header-free, time-major raw PDM payload, with missing network regions filled. |
| `mic0.pdm` to `mic15.pdm` | Separate bit-packed streams; earliest time sample is the most significant bit in a byte. |
| `packet_valid.bin` | One byte per expected packet: `1` received, `0` missing. |
| `loss_map.csv` | Missing packet ranges and corresponding nominal time/sample intervals. |
| `capture.log` | Console record from the helper, including readback and final counters. |

At 16 channels, a frame is two bytes. In byte 0, bits 0 to 7 are mic0 to mic7; in byte 1, bits 0 to 7 are mic8 to mic15. One frame represents one 2.5 MHz PDM period. Two microphones on a shared DATA line occupy different clock phases.

The payload rate is approximately **5 MB/s**, before network headers. Five seconds needs about 25 MB for the combined stream and another 25 MB for all channel files. The receiver also unpacks the complete recording in memory when splitting channels, so long recordings need additional RAM. Start with short trials.

Missing regions contain **synthetic 50% PDM**, not real microphone samples. Exclude them in later analysis, including the support of any decimation filter. A successful file write does not mean a loss-free acoustic record. Check host loss and `dropped_frames` separately. The original receiver prints internal loss counters but does not store original UDP headers; `record.sh` preserves its console log for that reason.

## 11. Change microphone count or GPIOs

One DATA pin carries two logical channels. Pin-list position defines the pair order. The clock list must contain either one shared CLK pin or the same number of pins as the DATA list.

Example: two DATA lines, four microphones, one shared clock:

```bash
PDM_DATA_PINS="E18 G16" PDM_CLK_PINS="F5" bash scripts/build.sh
```

Rewire to match, load the **new** bitstream, read its registers using **its new** CSR map, then record with `CSR_CSV="$PWD/build_local/csr.csv"`. The receiver obtains channel and packet dimensions from the FPGA registers rather than a fixed sixteen-channel constant.

Changing the source GPIO list requires a new FPGA build. It is not runtime rerouting. Avoid reset, UART, memory and Ethernet pin conflicts, and verify I/O bank voltages. The four-microphone printed sections can be connected into longer lines; other shapes need their actual coordinates supplied to a separate DOA estimator. No mount CAD or arbitrary-geometry analysis is provided in this capture package.

The current source accepts **1 to 64 DATA lines**, or **2 to 128 logical microphones**. The bundled demonstrated configuration is 16 channels. The upper code limit is not a validated hardware capacity. More than 100 DATA lines would require source and data-path changes, a free-pin budget, power distribution, stable buffered clock fan-out and likely a PCB designed for that array. At 202 logical channels, raw frames require 26 bytes each and 65 MB/s; this exceeds the ideal 60 MB/s capacity of the present one-byte-per-60-MHz-cycle serializer even before other stalls.

## 12. Troubleshooting

| Symptom | Check |
|---|---|
| `ModuleNotFoundError` for LiteX/Migen | Activate `.venv`; run the appropriate dependency installer. Check `command -v python`. |
| Missing LiteEth/LiteDRAM or CPU/software data | Use the full installer; initialize software-data submodules through it. |
| No RISC-V compiler | Install the Ubuntu packages from Section 3 and check `riscv64-unknown-elf-gcc --version`. |
| No `ecppack` or ECP5 backend | Use the OSS CAD Suite ECP5 tools, not an incomplete Yosys-only installation. |
| CMSIS-DAP cannot open | Verify data cable, board power, programmer enumeration and group/udev access. |
| No serial port | Check `/dev/serial/by-id/`, USB connection and programmer firmware. Port numbering can change. |
| Register read hangs or fails | Correct CDC port, 115200 baud, running server, loaded UARTBone-enabled bitstream, matching CSR file, no competing serial terminal. |
| Ping or UDP fails | Correct PHY 0 port, cable/link, host static address, gateware destination IP, route and firewall. |
| Receiver stays waiting | Confirm FPGA control and Ethernet separately. This receiver can keep waiting if the FPGA never asserts `done`; interrupt it and diagnose before retrying. |
| Many missing packets | Shorten the trial, raise receive buffers, check host load, direct link and counters; initial ARP resolution can lose early data. |
| FPGA `dropped_frames` is nonzero | Inspect serializer/FIFO backpressure and timing; host packet validity alone cannot diagnose internal loss. |
| Captured files exist but look wrong | Verify actual microphone model, power, clock validity, L/R sharing, physical pin translation and channel order. |
| Archived synthesis script fails on another PC | Regenerate with `scripts/build.sh`; archived scripts contain original absolute paths. |

## 13. Uploading the folder to GitHub

The **contents of this directory** can form a repository root named, for example, `doa-fpga-project`, or a folder inside a larger repository. `build/` is intentionally included. `.gitignore` excludes new captures, environments, downloaded tools and fresh builds.

For a new local repository **outside an existing Git checkout**, a typical sequence is:

```bash
git init -b main
git add .
# Preserve every archived build file despite upstream ignore rules inside vendored sources.
git add -f build
git status --short
git commit -m "Add modular PDM FPGA acquisition prototype and reproduction guide"
```

Then connect the intended remote and push it yourself, or copy this directory into an existing repository and commit it there. No GitHub upload, remote creation or commit was performed when preparing this package.

Use Git rather than trying to upload the entire generated tree through the browser. The supplied largest file is under GitHub's 100 MiB single-file limit, but the full tree has many files and substantial generated content. See [GitHub's large-file documentation](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github). Do not commit `captures/`, `.venv/`, `.deps/` or the toolchain archive. Keep the supplied `build/` only if the full archived build is desired, as in this package.

## 14. Provenance and replication limits

The complete parent-project `build/`, both original Python implementations and matching `csr.csv` were copied and hash-checked. Original source and recordings were left in place. The dependency patch was captured from the local LiteX-Boards checkout. See [package manifest](docs/package_manifest.json), [validation report](docs/VALIDATION.md) and [third-party notices](docs/THIRD_PARTY_NOTICES.md).

The tutorial was prepared from `setup.txt`, acquisition source, generated files, local toolchain metadata and upstream documentation. New hardware loading, a fresh Ubuntu installation, a full new synthesis and a new acoustic recording were not performed during packaging. Missing microphone identity, exact mount dimensions, programmer firmware version and physical wiring details must be supplied by someone replicating the assembly. The guide identifies those boundaries instead of presenting an unknown component as confirmed.
