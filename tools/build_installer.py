"""Command-line entry point for the same builder used by Preferences."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aporte_brasil.core.installer_builder import Builder

if __name__=='__main__':
    builder=Builder(Path(__file__).resolve().parents[1])
    builder.start()
    previous=''
    while True:
        status=builder.status()
        if status['detail'] != previous:
            print(status['detail'], flush=True);previous=status['detail']
        if not status['running']:break
        time.sleep(1)
    if status['error']:
        print(status['error']);sys.exit(1)
    print(builder.root/'release'/status['artifact']['filename'])
