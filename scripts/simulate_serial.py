#!/usr/bin/env python3
"""Replay fixture bytes into a new PTY; never opens an existing serial device."""
import argparse
import os
from pathlib import Path
import pty
import time


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fixture',type=Path)
    ap.add_argument('--interval',type=float,default=.2)
    ap.add_argument('--fragment',type=int,default=7)
    args=ap.parse_args()
    if args.interval<=0 or args.fragment<1:
        ap.error('interval and fragment must be positive')
    fixture=args.fixture or Path(__file__).resolve().parents[1]/'src/mul_lps_bridge/test/fixtures/follower_synthetic.txt'
    lines=fixture.read_bytes().splitlines(keepends=True)
    master,slave=pty.openpty()
    print(f'SYNTHETIC ONLY: serial_device:={os.ttyname(slave)}',flush=True)
    try:
        while True:
            for line in lines:
                for index in range(0,len(line),args.fragment):
                    os.write(master,line[index:index+args.fragment])
                    time.sleep(.001)
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        os.close(master)
        os.close(slave)


if __name__=='__main__':
    main()
