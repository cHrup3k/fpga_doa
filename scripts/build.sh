#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
# New builds never overwrite the supplied build/ snapshot.
exec python pdm_udp_share.py \
  --build \
  --pdm-clk-pins "${PDM_CLK_PINS:-F5 E6 H16 F18 B3 K4 F1 E4}" \
  --pdm-data-pins "${PDM_DATA_PINS:-E18 G16 E5 F4 K5 A2 F2 E1}" \
  --eth-phy 0 \
  --uart-name=crossover \
  --with-uartbone \
  --uart-baudrate=115200 \
  --integrated-rom-size=0xc000 \
  --l2-size=2048 \
  --output-dir "$PROJECT_DIR/build_local/colorlight_i5" \
  --csr-csv "$PROJECT_DIR/build_local/csr.csv" \
  "$@"
