"""Updates prepare code dependencies and leave each user's wallet alone."""
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/'tests', prefix='tmp-test-')
        self.root = Path(self.tmp.name)
        (self.root/'requirements.txt').write_text('synthetic-dependency==1\n')
        self.environment = self.root/'.venv'
        self.python = self.environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.python.parent.mkdir(parents=True)
        self.python.touch()
        self.marker = self.environment/'.aporte-requirements.sha256'
        self.expected = hashlib.sha256((self.root/'requirements.txt').read_bytes()).hexdigest()
        self.wallet = self.root/'private/carteira.aporteb'
        self.wallet.parent.mkdir()
        self.wallet.write_bytes(b'SYNTHETIC WALLET MUST NOT CHANGE')

    def tearDown(self):
        self.assertEqual(self.wallet.read_bytes(), b'SYNTHETIC WALLET MUST NOT CHANGE')
        self.tmp.cleanup()

    def test_unchanged_dependencies_open_offline_without_installing(self):
        self.marker.write_text(self.expected)
        with patch.object(runtime, 'runtime_ready', return_value=True), patch.object(runtime, 'run') as run:
            self.assertEqual(runtime.prepare(self.root), self.python)
        run.assert_not_called()

    def test_changed_requirements_install_locally_once_and_preserve_optional_models(self):
        self.marker.write_text('previous version')
        optional = self.environment/'optional-model.bin'
        optional.write_bytes(b'existing local model')
        with patch.object(runtime, 'runtime_ready', return_value=True), patch.object(runtime, 'run') as run:
            runtime.prepare(self.root)
        self.assertEqual(run.call_args.args[0][0], str(self.python))
        self.assertEqual(run.call_args.args[0][-1], str(self.root/'requirements.txt'))
        self.assertEqual(self.marker.read_text(), self.expected)
        self.assertEqual(optional.read_bytes(), b'existing local model')

    def test_failed_update_keeps_old_marker_so_next_open_retries(self):
        self.marker.write_text('previous version')
        with patch.object(runtime, 'run', side_effect=RuntimeError('synthetic offline failure')):
            with self.assertRaises(RuntimeError):
                runtime.prepare(self.root)
        self.assertEqual(self.marker.read_text(), 'previous version')


@unittest.skipUnless(os.name == 'nt', 'Windows launcher integration')
class FreshCheckoutTests(unittest.TestCase):
    def test_click_prepares_a_fresh_checkout_then_opens_offline(self):
        import cryptography
        from aporte_brasil.core import private_storage
        with tempfile.TemporaryDirectory(dir=ROOT/'tests', prefix='tmp-test-') as folder:
            workspace = Path(folder)
            source = workspace/'author code'
            (source/'tools').mkdir(parents=True)
            for name in ('runtime_probe.py','prepare_runtime.py'):
                shutil.copyfile(ROOT/'tools'/name, source/'tools'/name)
            shutil.copyfile(ROOT/'Iniciar.ps1', source/'Iniciar.ps1')
            shutil.copytree(ROOT/'aporte_brasil', source/'aporte_brasil', ignore=shutil.ignore_patterns('__pycache__'))
            # Use the installed version and disable indexes: this test downloads nothing.
            (source/'requirements.txt').write_text('cryptography=='+cryptography.__version__+'\ntzdata\n')
            (source/'.gitignore').write_text('.venv/\nopened.txt\n')
            program = 'from pathlib import Path\nPath(__file__).with_name("opened.txt").write_text("fresh version")\n'
            (source/'app.py').write_text(program)
            def git(cwd, *args):
                return subprocess.run(['git',*args], cwd=cwd, capture_output=True, check=True)
            git(source, 'init','-b','main')
            git(source, 'config','user.name','Synthetic test')
            git(source, 'config','user.email','test@localhost')
            git(source, 'add','.')
            git(source, 'commit','-m','Synthetic first version')
            root = workspace/'fresh code with spaces'
            git(workspace, 'clone',str(source),str(root))
            wallets = []
            for name in ('author-private','friend-private'):
                vault = private_storage.Vault(workspace/name)
                vault.create('synthetic password for update 123','synthetic password for update 123')
                wallets.append((vault.path,vault.path.read_bytes()))
                vault.close()
            self.assertNotEqual(wallets[0][1],wallets[1][1])
            env = {**os.environ, 'PIP_NO_INDEX':'1','APORTE_DATA_DIR':str(workspace/'friend-private')}
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port = sock.getsockname()[1]
            command = ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'Iniciar.ps1'),'-NoBrowser','-Python',sys.executable,'-Restart','-Port',str(port)]
            result = subprocess.run(command, env=env, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertEqual((root/'opened.txt').read_text(), 'fresh version')
            marker = root/'.venv/.aporte-requirements.sha256'
            self.assertTrue(marker.is_file())
            before = marker.stat().st_mtime_ns
            # Receive an actual git pull and click again, offline for dependencies.
            (source/'app.py').write_text(program.replace('fresh version','updated version'))
            git(source, 'add','app.py')
            git(source, 'commit','-m','Synthetic code update')
            git(root, 'pull','--ff-only')
            result = subprocess.run(command, env=env, capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertEqual((root/'opened.txt').read_text(), 'updated version')
            self.assertEqual(marker.stat().st_mtime_ns, before)
            for path, original in wallets:
                self.assertEqual(path.read_bytes(), original)
                private_storage.decrypt_password(original,'synthetic password for update 123')
            tracked = git(root,'ls-files').stdout
            self.assertNotIn(b'.aporteb',tracked)
            self.assertNotIn(b'.venv',tracked)


if __name__ == '__main__':
    unittest.main()
