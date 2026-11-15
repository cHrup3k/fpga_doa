#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
record_seconds="${1:-5}"
# mktemp creates a fresh directory atomically so existing captures are not overwritten.
mkdir -p "$PROJECT_DIR/captures"
capture_dir="$(mktemp -d "$PROJECT_DIR/captures/capture_$(date +%Y%m%d_%H%M%S)_XXXXXX")"
csr_path="${CSR_CSV:-$PROJECT_DIR/csr.csv}"
csr_path="$(realpath "$csr_path")"
cd "$capture_dir"
printf 'Recording directory: %s\n' "$capture_dir"
# The loss-aware receiver prints final FPGA counters; retain them alongside raw data.
python "$PROJECT_DIR/capture_pdm_lossy.py" \
  --seconds "$record_seconds" --csr-csv "$csr_path" \
  --bind-ip "${PDM_HOST_IP:-192.168.1.100}" \
  --udp-port "${PDM_UDP_PORT:-2000}" 2>&1 | tee capture.log
