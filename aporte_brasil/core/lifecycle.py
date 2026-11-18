"""Restart only the identified local Aporte server, without touching wallet data."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def local_json(base, path, data=None, csrf=''):
    headers = {'Accept': 'application/json'}
    if data is not None:
        headers.update({'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Origin': base})
    request = urllib.request.Request(base + path, data=None if data is None else json.dumps(data).encode(), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=3) as response:
            raw = response.read(100_001)
            if len(raw) > 100_000:
                raise ValueError('Resposta local inesperada. Nenhum outro processo foi encerrado.')
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read(10_000)).get('error', '')
        except (ValueError, AttributeError):
            message = ''
        raise ValueError(message or 'O aplicativo recusou o encerramento. Abra a versão atual e tente novamente.') from None


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.5):
            return True
    except (ConnectionRefusedError, TimeoutError):
        return False


def stop_existing(port, timeout=20):
    base = f'http://127.0.0.1:{port}'
    try:
        health = local_json(base, '/api/health')
    except (urllib.error.URLError, OSError):
        if not port_open(port):
            return False
        raise ValueError('A porta está ocupada por um serviço que não foi reconhecido. Nenhum processo foi encerrado.') from None
    except ValueError:
        raise ValueError('Não foi possível reconhecer o aplicativo nesta porta. Nenhum processo foi encerrado.') from None
    if not isinstance(health, dict) or health.get('app') != 'aporte-brasil':
        raise ValueError('Esta porta não pertence ao Aporte Brasil. Nenhum outro processo foi encerrado.')
    status = local_json(base, '/api/security/status')
    if not isinstance(status, dict) or not isinstance(status.get('csrf'), str) or not status['csrf']:
        raise ValueError('Não foi possível conferir a proteção local. Use Encerrar aplicativo na versão aberta.')
    result = local_json(base, '/api/security/exit', {}, status['csrf'])
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise ValueError('O aplicativo não confirmou o encerramento.')
    deadline = time.monotonic() + timeout
    while port_open(port):
        if time.monotonic() >= deadline:
            raise ValueError('O encerramento ainda não terminou. Aguarde e tente Reiniciar Aporte Brasil novamente.')
        time.sleep(.15)
    return True


def restart_command(root, port):
    command = [sys.executable]
    if not getattr(sys, 'frozen', False):
        command.append(str(Path(root) / 'app.py'))
    return [*command, '--port', str(port), '--no-browser']


def replace_process(root, port):
    command = restart_command(root, port)
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.flush()
    if os.name=='nt':
        # Independent of the old command window, which may close after its Python exits.
        env=dict(os.environ)
        if getattr(sys,'frozen',False):env['PYINSTALLER_RESET_ENVIRONMENT']='1'
        elif (Path(root)/'Iniciar.ps1').is_file():
            # A UI restart after git pull also prepares changed dependencies.
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
                     '-File',str(Path(root)/'Iniciar.ps1'),'-Port',str(port),'-NoBrowser']
        subprocess.Popen(command,env=env,close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW,
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    else:
        os.execv(command[0], command)
