# Package validation

Prepared on Ubuntu 22.04.5 LTS on 2026-11-15.

## Checks completed

- Copied the full parent `build/` tree, the two original implementations and `csr.csv`.
- Verified all **3,876 original files** against size and SHA256 metadata. One nested picolibc `.git` pointer retains its bytes under `docs/archived_metadata/picolibc_git_pointer.txt`; its relocation is recorded in the manifest.
- Parsed every packaged Python entry point and checked every Bash helper with `bash -n`.
- Ran `--help` for the original scripts, both requested-name launchers, the dependency installer and register reader, including launch from outside the project root. These checks used the available local LiteX source checkouts without changing or installing system packages.
- Checked receiver header parsing, missing-packet ranges and synthetic missing-region payload packing without connecting to hardware.
- Checked the supplied build's 60 MHz system configuration, all eight DATA-pin constraints and the matching copied CSR file.
- Recorded local dependency commits and the modified LiteX-Boards target patch needed for dynamic link handling.
- Staged the package in a disposable Git index using the documented commands. Every copied original file was included and no embedded Git links were produced. The actual project Git repository was not changed. Details: `github_upload_check.json`.
- Checked individual file sizes for GitHub's 100 MiB per-file limit. No file exceeds that limit; the largest is approximately 22.4 MiB.

See `validation.json` for machine-readable results. `package_manifest.json` records every original copied-file hash. To verify again:

```bash
python scripts/verify_package.py
```

The preserved sources do not rely on the packaging machine's directory when launched through the provided helpers. Archived generated Makefiles and synthesis scripts still contain their original paths and should be regenerated for a new machine.

## Not exercised during packaging

No fresh Ubuntu installation, network dependency installation, complete FPGA synthesis, JTAG programming, live microphone capture or acoustic verification was performed. The exact FPGA bitstream was preserved rather than regenerated. Commands in the README are a replication procedure assembled from actual project settings and upstream installation documentation, not a claim that an end-to-end new-machine hardware test has just passed.

No GitHub upload or repository commit was made. The package deliberately preserves third-party build material and its existing notices; no new project license was selected.
