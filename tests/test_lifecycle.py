import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from aporte_brasil.core import lifecycle
import test_app as baseline
import test_security as protected
from tools.check_git_safety import MODULES, allowed

app = baseline.app


class LifecycleTests(unittest.TestCase):
    def test_external_restart_only_stops_identified_app_and_respects_busy(self):
        with patch.object(lifecycle, 'local_json', return_value={'app': 'another-service'}) as request:
            with self.assertRaisesRegex(ValueError, 'não pertence'):
                lifecycle.stop_existing(12345)
            self.assertEqual(request.call_count, 1)
        with patch.object(lifecycle, 'local_json', side_effect=[{'app':'aporte-brasil'}, {'csrf':'synthetic'}, ValueError('Aguarde a análise')]):
            with self.assertRaisesRegex(ValueError, 'Aguarde'):
                lifecycle.stop_existing(12345)
        with patch.object(lifecycle, 'local_json', side_effect=[{'app':'aporte-brasil'}, {'csrf':'synthetic'}, {'ok':True}]) as request, patch.object(lifecycle, 'port_open', side_effect=[True, False]), patch.object(lifecycle.time, 'sleep'):
            self.assertTrue(lifecycle.stop_existing(12345))
            self.assertEqual(request.call_args.args, ('http://127.0.0.1:12345', '/api/security/exit', {}, 'synthetic'))
        with patch.object(lifecycle, 'local_json', side_effect=urllib.error.URLError('not running')), patch.object(lifecycle, 'port_open', return_value=False):
            self.assertFalse(lifecycle.stop_existing(12345))

    def test_running_server_timeout_and_frozen_command(self):
        with patch.object(lifecycle, 'local_json', side_effect=[{'app':'aporte-brasil'}, {'csrf':'synthetic'}, {'ok':True}]), patch.object(lifecycle, 'port_open', return_value=True), patch.object(lifecycle.time, 'monotonic', side_effect=[0, 21]):
            with self.assertRaisesRegex(ValueError, 'ainda não terminou'):
                lifecycle.stop_existing(12345)
        self.assertEqual(lifecycle.restart_command(Path('code'), 12345), [sys.executable, str(Path('code')/'app.py'), '--port','12345','--no-browser'])
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(lifecycle.restart_command(Path('code'),12345),[sys.executable,'--port','12345','--no-browser'])


class RestartHTTPTests(unittest.TestCase):
    setUp = protected.ProtectedAppTests.setUp
    tearDown = protected.ProtectedAppTests.tearDown
    request = protected.ProtectedAppTests.request

    def test_restart_requires_local_csrf_and_blocks_active_jobs(self):
        self.assertEqual(self.request('/api/security/restart',{},csrf=False)[0],403)
        self.assertEqual(self.request('/api/security/restart',{},origin='https://example.org')[0],403)
        with patch.dict(app.JOB, {'running':True}):
            self.assertEqual(self.request('/api/security/restart',{})[0],400)
        with patch.object(app.market_ai,'job_state',return_value={'running':True}):
            self.assertEqual(self.request('/api/security/restart',{})[0],400)
        with patch.object(app.market_signals,'job_state',return_value={'running':True}):
            self.assertEqual(self.request('/api/security/restart',{})[0],400)
        self.assertFalse(getattr(self.server,'stopping',False))

    def test_restart_invalidates_session_and_preserves_encrypted_wallet(self):
        app.mutate('/api/settings',{'profile':'SYNTHETIC RESTART TEST'})
        before=hashlib.sha256(app.VAULT.path.read_bytes()).digest()
        status,headers,raw=self.request('/api/security/restart',{})
        self.assertEqual(status,200);self.assertTrue(self.server.restart_requested)
        self.assertEqual(json.loads(raw)['previous_instance'],app.INSTANCE_ID)
        self.assertIn('Max-Age=0',headers['Set-Cookie'])
        self.thread.join(5);self.assertFalse(self.thread.is_alive())
        app.VAULT.close()
        self.assertFalse(app.VAULT.authorized(self.token))
        self.assertEqual(hashlib.sha256(app.VAULT.path.read_bytes()).digest(),before)
        app.VAULT.unlock(protected.PASSWORD)
        self.assertEqual(app.state()['settings']['profile'],'SYNTHETIC RESTART TEST')


@unittest.skipUnless(os.name=='nt','Windows launcher regression')
class WindowsLauncherTests(unittest.TestCase):
    def test_optional_ai_import_error_and_stderr_do_not_break_launcher(self):
        with tempfile.TemporaryDirectory(dir=app.ROOT/'tests',prefix='tmp-test-') as folder:
            root=Path(folder)
            (root/'torch.py').write_text("import sys\nprint('synthetic optional warning',file=sys.stderr)\nraise RuntimeError('synthetic missing optional dependency')\n",encoding='utf-8')
            env={**os.environ,'PYTHONPATH':str(root)}
            result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(app.ROOT/'Iniciar.ps1'),'-CheckOnly'],env=env,capture_output=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            self.assertIn(b'Python compativel:',result.stdout)
            self.assertNotIn(b'synthetic optional warning',result.stderr)
            self.assertNotIn(b'NativeCommandError',result.stderr)


@unittest.skipUnless(os.name=='nt','Real Windows process restart')
class RestartProcessTests(unittest.TestCase):
    def test_ui_and_launcher_restart_reload_changed_code_without_password_leak(self):
        with tempfile.TemporaryDirectory(dir=app.ROOT/'tests',prefix='tmp-test-') as folder:
            root=Path(folder);code=root/'code with spaces';code.mkdir()
            # Runtime modules only; no real wallet, model cache or personal files.
            for name in MODULES:
                shutil.copyfile(app.ROOT/name,code/name)
            (code/'static').mkdir()
            for file in (app.ROOT/'static').iterdir():
                if file.is_file() and allowed('static/'+file.name):shutil.copyfile(file,code/'static'/file.name)
            (code/'tools').mkdir()
            shutil.copyfile(app.ROOT/'tools/runtime_probe.py',code/'tools/runtime_probe.py')
            shutil.copyfile(app.ROOT/'tools/check_git_safety.py',code/'tools/check_git_safety.py')
            shutil.copyfile(app.ROOT/'Iniciar.ps1',code/'Iniciar.ps1')
            shutil.copyfile(app.ROOT/'Encerrar.ps1',code/'Encerrar.ps1')
            env={**os.environ,'APORTE_DATA_DIR':str(root/'private'),'APORTE_DB':str(root/'absent.sqlite3')}
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            base=f'http://127.0.0.1:{port}';children=[]
            def request(path,data=None,token=''):
                headers={'Origin':base}
                if data is not None:headers.update({'Content-Type':'application/json','X-CSRF-Token':lifecycle.local_json(base,'/api/security/status')['csrf']})
                if token:headers['Cookie']='aporte_session='+token
                req=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
                with urllib.request.urlopen(req,timeout=5) as response:
                    return json.load(response),response.headers
            def wait_instance(previous='',version=None):
                deadline=time.monotonic()+35
                while time.monotonic()<deadline:
                    try:
                        health,_=request('/api/health')
                        if health['instance']!=previous and (version is None or health['version']==version):return health
                    except (OSError,ValueError):pass
                    time.sleep(.1)
                details=(root/'runtime.log').read_text(encoding='utf-8',errors='replace') if (root/'runtime.log').exists() else ''
                self.fail('New source process did not become ready: '+details[-1500:])
            try:
                with (root/'runtime.log').open('wb') as log:
                    children.append(subprocess.Popen([sys.executable,'-u',str(code/'app.py'),'--port',str(port),'--no-browser'],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW))
                first=wait_instance()
                _,headers=request('/api/security/create',{'password':protected.PASSWORD,'confirmation':protected.PASSWORD})
                token=headers['Set-Cookie'].split(';')[0].split('=',1)[1]
                request('/api/settings',{'profile':'SYNTHETIC PERSISTENCE','auto_refresh':False},token)
                wallet=root/'private/carteira.aporteb';before=hashlib.sha256(wallet.read_bytes()).digest()
                source=code/'app.py'
                source.write_text(re.sub(r'APP_VERSION = \d+',f"APP_VERSION = {first['version']+1}",source.read_text(encoding='utf-8'),count=1),encoding='utf-8')
                request('/api/security/restart',{})
                second=wait_instance(first['instance'],first['version']+1)
                self.assertEqual(hashlib.sha256(wallet.read_bytes()).digest(),before)
                with self.assertRaises(urllib.error.HTTPError) as caught:request('/api/state',token=token)
                self.assertEqual(caught.exception.code,401)
                children.append(subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(code/'Iniciar.ps1'),'-Restart','-NoBrowser','-Port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW))
                third=wait_instance(second['instance'],second['version'])
                self.assertEqual(hashlib.sha256(wallet.read_bytes()).digest(),before)
                _,headers=request('/api/security/unlock',{'password':protected.PASSWORD})
                token=headers['Set-Cookie'].split(';')[0].split('=',1)[1]
                state,_=request('/api/state',token=token)
                self.assertEqual(state['settings']['profile'],'SYNTHETIC PERSISTENCE')
                # Deadlock every POST in the next real server. Recovery must bypass HTTP.
                source.write_text(source.read_text(encoding='utf-8').replace(
                    '    args = parser.parse_args()',
                    '    args = parser.parse_args()\n    REQUEST_LOCK.acquire()'),encoding='utf-8')
                request('/api/security/restart',{})
                stuck=wait_instance(third['instance'])
                before=hashlib.sha256(wallet.read_bytes()).digest()
                source.write_text(source.read_text(encoding='utf-8').replace(
                    '\n    REQUEST_LOCK.acquire()',''),encoding='utf-8')
                children.append(subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(code/'Iniciar.ps1'),'-ForceRestart','-NoBrowser','-Port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW))
                wait_instance(stuck['instance'])
                self.assertEqual(hashlib.sha256(wallet.read_bytes()).digest(),before)
                _,headers=request('/api/security/unlock',{'password':protected.PASSWORD})
                token=headers['Set-Cookie'].split(';')[0].split('=',1)[1]
                state,_=request('/api/state',token=token)
                self.assertEqual(state['settings']['profile'],'SYNTHETIC PERSISTENCE')
            finally:
                try:request('/api/security/exit',{})
                except (OSError,ValueError):pass
                for child in children:
                    try:child.wait(timeout=10)
                    except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=10)
                deadline=time.monotonic()+5
                while lifecycle.port_open(port) and time.monotonic()<deadline:time.sleep(.1)


if __name__=='__main__':unittest.main()
