#!/usr/bin/env python3
"""Idempotently render deployment files; never install/enable/restart a service."""
import argparse
import getpass
from pathlib import Path
import re


def render(root, output, alr, device='', baud=115200, user=None):
    user=user or getpass.getuser()
    if alr not in range(132,136) or baud<=0:
        raise ValueError('invalid ALR/baud')
    # EnvironmentFile is systemd syntax. Reject metacharacters rather than risk
    # shell/systemd interpolation of a serial path or installation location.
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*',user):
        raise ValueError('unsupported service user')
    for value in (str(root),device):
        if value and not re.fullmatch(r'/[A-Za-z0-9_./:-]+',value):
            raise ValueError('deployment paths require absolute paths without spaces/metacharacters')
    output.mkdir(parents=True,exist_ok=True)
    text=(root/'systemd'/'mul-lps-bridge@.service.in').read_text()
    (output/'mul-lps-bridge@.service').write_text(text.replace('@WORKSPACE@',str(root)).replace('@USER@',user))
    (output/f'{alr}.env').write_text(f'ALR_ID={alr}\nSERIAL_DEVICE={device}\nBAUD_RATE={baud}\n')
    return output


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--alr-id',type=int,choices=range(132,136),required=True)
    ap.add_argument('--device',default='')
    ap.add_argument('--baud',type=int,default=115200)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    root=Path(__file__).resolve().parent.parent
    output=render(root,args.output or root/'deployment',args.alr_id,args.device,args.baud)
    print(f'Rendered {output}; no system configuration or service changed.')


if __name__=='__main__':
    main()
