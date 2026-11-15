#!/usr/bin/env python3
"""Clone recorded LiteX revisions into .deps and install into the active venv."""
from pathlib import Path
import argparse,json,subprocess,sys
ROOT=Path(__file__).resolve().parent.parent

def run(*args,cwd=None):
    print('+',' '.join(map(str,args)),flush=True)
    subprocess.run(list(map(str,args)),cwd=cwd,check=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-only',action='store_true',help='Install Migen/LiteX plus receiver requirements; no FPGA cores needed for prebuilt capture.')
    args=parser.parse_args()
    if sys.prefix==sys.base_prefix:
        raise SystemExit('Activate the project .venv first. Do not install into system Python.')
    deps=ROOT/'.deps';deps.mkdir(exist_ok=True)
    run(sys.executable,'-m','pip','install','-r',ROOT/'requirements.txt')
    records=json.loads((ROOT/'dependencies.lock.json').read_text())['repositories']
    for record in records:
        if args.host_only and record['name'] not in ['migen','litex']:continue
        dest=deps/record['name']
        if not dest.exists():
            run('git','clone','--no-checkout',record['url'],dest)
            run('git','checkout','--detach',record['commit'],cwd=dest)
            run('git','submodule','update','--init','--recursive',cwd=dest)
        else:
            actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=dest,text=True).strip()
            if actual!=record['commit']:
                raise SystemExit(f'{dest} has another commit. Preserve your work and use a fresh project directory.')
        if record.get('patch'):
            patch=ROOT/record['patch']
            applicable=subprocess.run(['git','apply','--check',str(patch)],cwd=dest,capture_output=True).returncode==0
            if applicable:run('git','apply',patch,cwd=dest)
            elif subprocess.run(['git','apply','--reverse','--check',str(patch)],cwd=dest,capture_output=True).returncode!=0:
                raise SystemExit(f'Cannot apply or recognize required patch in {dest}')
        run(sys.executable,'-m','pip','install','--no-build-isolation','--editable',dest)
    print('Dependencies ready. Keep .venv activated; see README.md for toolchain PATH and hardware steps.')

if __name__=='__main__':main()
