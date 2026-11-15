#!/usr/bin/env python3
"""Verify every copied original file against the packaging SHA256 manifest."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parent.parent

def main():
    manifest=json.loads((ROOT/'docs/package_manifest.json').read_text())
    failures=[]
    for name,record in manifest['copied_files'].items():
        p=ROOT/manifest.get('relocated_metadata',{}).get(name,name)
        if not p.is_file():failures.append(name+': missing');continue
        if p.stat().st_size!=record['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=record['sha256']:
            failures.append(name+': changed')
    if failures:raise SystemExit('\n'.join(failures))
    print(f"Verified {len(manifest['copied_files'])} original files; all SHA256 hashes match.")

if __name__=='__main__':main()
