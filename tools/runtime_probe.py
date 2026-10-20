"""Quiet capability check for Windows PowerShell; no inline Python quoting."""
import sys


def ready(ai=False):
    if sys.version_info < (3, 11):
        return False
    try:
        import cryptography
        if ai:
            import torch
            import transformers
            version = tuple(int(n) for n in torch.__version__.split('+')[0].split('.')[:2])
            return version >= (2, 6)
        return True
    except Exception:
        return False


if __name__ == '__main__':
    sys.exit(0 if ready('--ai' in sys.argv[1:]) else 1)
