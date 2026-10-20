"""Exercise Windows kill recovery with isolated, deliberately unresponsive servers."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_APP = '''import argparse, os, socket, subprocess, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--port', type=int, default=8765)
p.add_argument('--no-browser', action='store_true')
a = p.parse_args()
s = socket.socket()
s.bind(('127.0.0.1', a.port)); s.listen()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])
Path(__file__).with_name(str(a.port)+'.ready').write_text(str(os.getpid())+' '+str(child.pid))
# Accept TCP connections but never answer HTTP, simulating an internal deadlock.
while True: time.sleep(1)
'''


@unittest.skipUnless(os.name == 'nt', 'Windows process recovery')
class RecoveryLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/'tests', prefix='tmp-test-')
        self.folder = Path(self.tmp.name)
        self.code = self.folder/'code with spaces'
        self.code.mkdir()
        for name in ('Iniciar.ps1', 'Encerrar.ps1'):
            shutil.copyfile(ROOT/name, self.code/name)
        (self.code/'app.py').write_text(SYNTHETIC_APP, encoding='utf-8')
        (self.code/'tools').mkdir()
        (self.code/'tools/runtime_probe.py').write_text('raise SystemExit(0)\n')
        self.processes = []
        self.descendants = set()

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, timeout=15)
            process.wait(timeout=10)
        for pid in self.descendants:
            # Only child PIDs created in this test; avoid orphaning fixture sleepers.
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, timeout=15)
        self.tmp.cleanup()

    def port(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def wait_ready(self, root, port, previous=None):
        deadline = time.monotonic()+20
        marker = root/f'{port}.ready'
        while time.monotonic() < deadline:
            if marker.exists():
                pid, child = map(int, marker.read_text().split())
                if pid != previous:
                    self.descendants.add(child)
                    return pid, child
            time.sleep(.1)
        self.fail('Isolated server did not start')

    def start(self, root, port, script='app.py', extra=()):
        process = subprocess.Popen([sys.executable, '-u', str(root/script), '--port', str(port), *extra],
                                   creationflags=subprocess.CREATE_NO_WINDOW,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(process)
        return process, self.wait_ready(root, port)

    def stop(self, port, root=None):
        return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                               '-File', str((root or self.code)/'Iniciar.ps1'), '-StopOnly',
                               '-Port', str(port)], capture_output=True, timeout=25)

    def test_stop_kills_hung_server_and_children_preserving_other_copies_and_ports(self):
        port = self.port()
        target, (_, child) = self.start(self.code, port)
        other_port = self.port()
        other, _ = self.start(self.code, other_port)
        foreign_root = self.folder/'another copy'
        foreign_root.mkdir()
        (foreign_root/'app.py').write_text(SYNTHETIC_APP)
        foreign, _ = self.start(foreign_root, self.port())
        # Passing app.py as data to another script must not identify it as the app.
        (self.code/'worker.py').write_text(SYNTHETIC_APP.replace('a = p.parse_args()', 'a, _ = p.parse_known_args()'))
        worker, _ = self.start(self.code, self.port(), 'worker.py', [str(self.code/'app.py')])
        # No runtime is available in this copy; stopping must still work.
        (self.code/'tools/runtime_probe.py').unlink()
        result = self.stop(port)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        target.wait(timeout=5)
        self.assertIsNone(other.poll())
        self.assertIsNone(foreign.poll())
        self.assertIsNone(worker.poll())
        check = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                                f'if (Get-Process -Id {child} -ErrorAction SilentlyContinue) {{ exit 1 }}'],
                               capture_output=True, timeout=10)
        self.assertEqual(check.returncode, 0, 'Fixture child survived forced stop')

    def test_foreign_service_on_port_is_not_killed(self):
        foreign_root = self.folder/'foreign'
        foreign_root.mkdir()
        (foreign_root/'app.py').write_text(SYNTHETIC_APP)
        port = self.port()
        foreign, _ = self.start(foreign_root, port)
        result = self.stop(port)
        self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
        self.assertIsNone(foreign.poll())

    def test_force_restart_replaces_unresponsive_process(self):
        port = self.port()
        old, (old_pid, _) = self.start(self.code, port)
        launcher = subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                     '-File', str(self.code/'Iniciar.ps1'), '-ForceRestart',
                                     '-NoBrowser', '-Port', str(port)],
                                    creationflags=subprocess.CREATE_NO_WINDOW,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(launcher)
        new_pid, _ = self.wait_ready(self.code, port, old_pid)
        self.assertNotEqual(new_pid, old_pid)
        old.wait(timeout=5)
        result = self.stop(port)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        launcher.wait(timeout=5)

    def test_check_only_cannot_kill(self):
        port = self.port()
        target, _ = self.start(self.code, port)
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(self.code/'Iniciar.ps1'), '-StopOnly', '-CheckOnly',
                                 '-Port', str(port)], capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(target.poll())


if __name__ == '__main__':
    unittest.main()
