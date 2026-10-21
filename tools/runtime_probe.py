"""Quiet capability check for Windows PowerShell; no inline Python quoting."""
import sys


def ready(ai=False, base=False):
    if sys.version_info < (3, 11):
        return False
    try:
        import sqlite3
        if not all(hasattr(sqlite3.Connection, name) for name in ('serialize', 'deserialize')):
            return False
        if base:
            return True
        import cryptography
        import tzdata
        if ai:
            import torch
            import transformers
            version = tuple(int(n) for n in torch.__version__.split('+')[0].split('.')[:2])
            return version >= (2, 6)
        return True
    except Exception:
        return False


if __name__ == '__main__':
    available = ready('--ai' in sys.argv[1:], '--base' in sys.argv[1:])
    if available and '--executable' in sys.argv[1:]:
        print(sys.executable)
    sys.exit(0 if available else 1)
