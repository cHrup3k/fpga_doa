#!/usr/bin/env python3
"""Read the acquisition configuration through a running UART LiteX server."""
import argparse,json
from pathlib import Path
from litex import RemoteClient

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csr-csv',type=Path,default=Path(__file__).resolve().parent.parent/'csr.csv')
    parser.add_argument('--host',default='localhost')
    parser.add_argument('--port',type=int,default=1234)
    args=parser.parse_args()
    wb=RemoteClient(host=args.host,port=args.port,csr_csv=str(args.csr_csv),timeout=5.0,raise_on_timeout=True)
    wb.open()
    try:
        fields=['channels','pdm_frequency','bytes_per_sample','samples_per_packet','packet_bytes','active','done','dropped_frames']
        values={name:getattr(wb.regs,'pdm_udp_'+name).read() for name in fields}
        print(json.dumps(values,indent=2))
        assert values['bytes_per_sample']==(values['channels']+7)//8,'Unexpected channel stride'
        assert values['packet_bytes']==32+values['bytes_per_sample']*values['samples_per_packet'],'Unexpected packet size'
    finally:wb.close()

if __name__=='__main__':main()
