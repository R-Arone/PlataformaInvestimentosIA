import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('git_safety',ROOT/'tools/check_git_safety.py')
safety=importlib.util.module_from_spec(spec);spec.loader.exec_module(safety)

class GitSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='tmp-test-');self.root=Path(self.tmp.name)
        self.git('init','-b','main');self.git('config','user.name','Synthetic test');self.git('config','user.email','test@localhost')
    def tearDown(self):self.tmp.cleanup()
    def git(self,*args):return subprocess.run(['git',*args],cwd=self.root,capture_output=True,check=True)
    def check(self,flag='--staged'):
        return subprocess.run([sys.executable,str(ROOT/'tools/check_git_safety.py'),flag],cwd=self.root,capture_output=True)
    def test_allowlist_refuses_databases_backups_spreadsheets_and_screenshots(self):
        for name in ('data/carteira.sqlite3','carteira.aporteb','extrato.xlsx','operacoes.csv','backup.json','interface-v8.png','private/anything.py',
                     'static/model-comparison-data.json','static/private.json','tests/test_bayesian_live.py','packaging/Install.ps1'):
            self.assertFalse(safety.allowed(name),name)
        for name in ('app.py','aporte_brasil/core/private_storage.py','static/security.js','.githooks/pre-push','SECURITY.md'):
            self.assertTrue(safety.allowed(name),name)
    def test_staged_private_file_refused_even_forced_into_index(self):
        (self.root/'data').mkdir();(self.root/'data/carteira.sqlite3').write_bytes(b'SQLite format 3\x00TEST')
        self.git('add','data/carteira.sqlite3');self.assertEqual(self.check().returncode,1)
    def test_renamed_database_content_refused(self):
        (self.root/'app.py').write_bytes(b'SQLite format 3\x00TEST')
        self.git('add','app.py');self.assertEqual(self.check().returncode,1)
    def test_deleted_private_file_is_still_refused_in_history(self):
        (self.root/'backup.json').write_text('{}');self.git('add','backup.json');self.git('commit','-m','Synthetic history')
        self.git('rm','backup.json');self.git('commit','-m','Remove synthetic file')
        self.assertEqual(self.check('--history').returncode,1)

    def test_sensitive_source_is_refused_without_printing_the_value(self):
        samples=[b'ghp_'+b'x'*30, b'C:'+b'/Users/'+b'private-user/document',
                 b'person'+b'@gmail'+b'.com',b'-----BEGIN '+b'PRIVATE KEY-----']
        for payload in samples:
            with self.subTest(kind=payload[:4]):
                (self.root/'app.py').write_bytes(payload);self.git('add','app.py')
                result=self.check();self.assertEqual(result.returncode,1)
                self.assertNotIn(payload,result.stderr)

    def test_each_historical_path_is_checked_for_identical_blobs(self):
        (self.root/'app.py').write_text('same harmless content')
        (self.root/'backup.json').write_text('same harmless content')
        self.git('add','.');self.git('commit','-m','Duplicate content')
        self.git('rm','backup.json');self.git('commit','-m','Remove local artifact')
        self.assertEqual(self.check('--history').returncode,1)

    def test_published_ref_is_audited_without_unrelated_local_branches(self):
        (self.root/'app.py').write_text('print("public source")')
        self.git('add','.');self.git('commit','-m','Clean source')
        self.git('switch','-c','local-only')
        (self.root/'backup.json').write_text('{}');self.git('add','.');self.git('commit','-m','Local artifact')
        self.git('switch','main')
        result=subprocess.run([sys.executable,str(ROOT/'tools/check_git_safety.py'),'--history','--ref','HEAD'],cwd=self.root,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.check('--history').returncode,1)

    def test_ignored_json_and_private_files_cannot_be_added_normally(self):
        (self.root/'.gitignore').write_bytes((ROOT/'.gitignore').read_bytes())
        for name in ('data/carteira.db','static/private.json','.env','extract.csv','tests/ui-experiment/result.py'):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic')
            self.assertEqual(self.git('check-ignore',name).returncode,0)

if __name__=='__main__':unittest.main()
