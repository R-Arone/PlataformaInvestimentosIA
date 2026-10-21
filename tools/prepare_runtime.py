"""Prepare code dependencies only. Never import the app or open a wallet."""
import hashlib
import argparse
import os
from pathlib import Path
import subprocess
import sys


def run(command, timeout=240):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Keep diagnostics local; the launcher displays them on failure.
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Falha ao preparar o ambiente Python.')
    return result


def runtime_ready(python, probe):
    try:
        return subprocess.run([str(python), str(probe)], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def prepare(root, base_python=None):
    root = Path(root).resolve()
    requirements = root/'requirements.txt'
    probe = root/'tools/runtime_probe.py'
    environment = root/'.venv'
    python = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    marker = environment/'.aporte-requirements.sha256'
    expected = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not python.is_file():
        print('Preparando o ambiente local. Aguarde...', file=sys.stderr, flush=True)
        run([str(base_python or sys.executable), '-m', 'venv', '--system-site-packages', str(environment)])
    previous = marker.read_text(encoding='ascii').strip() if marker.is_file() else ''
    if previous != expected or not runtime_ready(python, probe):
        print('Atualizando os componentes da plataforma. A primeira preparacao pode precisar de internet...', file=sys.stderr, flush=True)
        run([str(python), '-m', 'pip', '--disable-pip-version-check', '--no-input', 'install', '-r', str(requirements)])
        if not runtime_ready(python, probe):
            raise RuntimeError('O ambiente ainda nao esta pronto. Instale Python 3.11+ com suporte a SQLite e tente novamente.')
        # A failed install never marks an update as completed.
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(expected, encoding='ascii')
        temporary.replace(marker)
    return python


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try:
        if args.restart:
            # Stop the identified old process before updating loaded DLLs on Windows.
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            import lifecycle
            lifecycle.stop_existing(args.port)
        print(prepare(Path(__file__).resolve().parents[1]), flush=True)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Nao foi possivel preparar a plataforma: '+str(exc), file=sys.stderr)
        sys.exit(1)
