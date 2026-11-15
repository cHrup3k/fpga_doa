# Source and third-party notices

The original project scripts were copied without replacing their headers or assigning a new license. No project-wide license was selected by this packaging task. This file records provenance; it does not relicense any content.

- `pdm_udp_stereo_shared.py` and `capture_pdm_udp_lossy.py`: copied from the parent project, unchanged. Their short-name launchers and tutorial helpers were added for this package.
- `build/`: complete generated output from the local LiteX/Colorlight build, including generated SoC/CPU HDL, BIOS, compiled objects and software sources. Retain the copyright/license material embedded in this tree. In particular, the copied `software/picolibc_src/` contains upstream library notices and licenses.
- LiteX, Migen, LiteX-Boards and LiteX cores are separate upstream projects. Their repositories and observed commits are listed in `../dependencies.lock.json`. Their licenses remain those of the respective upstream projects.
- The bundled patch is the local change to LiteX-Boards' `litex_boards/targets/colorlight_i5.py`. The upstream file identifies BSD-2-Clause licensing and its copyright holder. The patch only enables dynamic PHY link handling.
- FPGA tool binaries are not redistributed here. Obtain OSS CAD Suite and openFPGALoader from the linked upstream sources.
- Board documentation and schematics are linked from the original Colorlight-FPGA-Projects repository, not copied into this package.

This package does not contain the author's recordings or thesis. Publication of this folder does not imply any additional license grant for original code or third-party build content.
