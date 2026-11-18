import base64
from contextlib import closing
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from aporte_brasil.core import private_storage as store
import test_app as baseline

app=baseline.app
PASSWORD='teste exclusivo sem dados reais 123'
NEW_PASSWORD='outra senha exclusiva de teste 456'

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=app.ROOT/'tests',prefix='tmp-test-')
        self.root=Path(self.tmp.name);self.v=store.Vault(self.root/'private')
    def tearDown(self):self.v.close();self.tmp.cleanup()
    def create(self):return self.v.create(PASSWORD,PASSWORD)

    def test_encryption_wrong_password_tampering_and_unique_nonces(self):
        self.create()
        with self.v.connect() as c:c.execute('CREATE TABLE t(x)');c.execute('INSERT INTO t VALUES (?)',('PRIVATE-FINANCIAL-TEST',))
        first=self.v.export();second=self.v.export()
        self.assertNotEqual(first,second);self.assertNotIn(b'PRIVATE-FINANCIAL-TEST',first)
        self.assertNotIn(b'SQLite format 3',self.v.path.read_bytes())
        with self.assertRaises(ValueError):store.decrypt_password(first,NEW_PASSWORD)
        for index in (len(store.MAGIC),len(first)-1):
            changed=bytearray(first);changed[index]^=1
            with self.assertRaises(ValueError):store.decrypt_password(bytes(changed),PASSWORD)
        for bad in (b'',b'APORTE-VAULT\x00\x02',b'not a vault'):
            with self.assertRaises(ValueError):store.decrypt_password(bad,PASSWORD)

    def test_atomic_failure_and_exception_preserve_committed_records(self):
        self.create()
        with self.v.connect() as c:c.execute('CREATE TABLE t(x)');c.execute('INSERT INTO t VALUES (1)')
        saved=self.v.path.read_bytes()
        with self.assertRaises(OSError),patch('aporte_brasil.core.private_storage.atomic_write',side_effect=OSError('disk full')):
            with self.v.connect() as c:c.execute('INSERT INTO t VALUES (2)')
        self.assertEqual(self.v.path.read_bytes(),saved)
        with self.assertRaises(ValueError):
            with self.v.connect() as c:c.execute('INSERT INTO t VALUES (3)');raise ValueError('stop')
        with self.v.connect() as c:self.assertEqual([r[0] for r in c.execute('SELECT x FROM t')],[1])
        self.assertFalse(list(self.v.directory.glob('*.sqlite*')))

    def test_preview_rollback_creates_no_changes_and_no_cleartext(self):
        self.create()
        with self.v.connect() as c:c.execute('CREATE TABLE t(x)')
        before=self.v.path.read_bytes()
        with self.v.connect() as c:
            c.execute('SAVEPOINT preview');c.execute('INSERT INTO t VALUES (2)');c.execute('ROLLBACK TO preview');c.execute('RELEASE preview')
        with self.v.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM t').fetchone()[0],0)
        # SQLite can change internal counters after a rolled-back savepoint;
        # the financial content, rather than ciphertext bytes, must stay intact.
        image,_,_=store.decrypt_password(self.v.path.read_bytes(),PASSWORD)
        with closing(store.memory_db(image)) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM t').fetchone()[0],0)
        self.v.lock();self.assertIsNone(self.v.image)
        with self.assertRaises(store.LockedError):
            with self.v.connect():pass

    def test_wal_migration_and_all_old_backups_preserved_encrypted(self):
        old=self.root/'legacy';old.mkdir();primary=old/'carteira.sqlite3';backup=old/'old-backup.sqlite3'
        with closing(sqlite3.connect(primary)) as c:
            c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE t(x)');c.execute('INSERT INTO t VALUES (?)',('PRIVATE-OLD',));c.commit()
            with closing(sqlite3.connect(backup)) as dest:c.backup(dest)
            self.v.close();self.v=store.Vault(self.root/'private',primary,[old])
            with self.assertRaisesRegex(ValueError,'Confirme'):self.v.create(PASSWORD,PASSWORD)
            self.assertTrue(primary.exists());self.assertFalse(self.v.path.exists())
            # Close the writer before migration, while leaving its WAL snapshot included.
        token=self.v.create(PASSWORD,PASSWORD,True)
        self.assertTrue(self.v.authorized(token));self.assertFalse(primary.exists());self.assertFalse(backup.exists())
        with self.v.connect() as c:self.assertEqual(c.execute('SELECT x FROM t').fetchone()[0],'PRIVATE-OLD')
        files=list((self.v.directory/'backups').glob('*.aporteb'));self.assertEqual(len(files),2)
        for file in files:
            image,_,_=store.decrypt_password(file.read_bytes(),PASSWORD)
            with closing(store.memory_db(image)) as c:self.assertEqual(c.execute('SELECT x FROM t').fetchone()[0],'PRIVATE-OLD')
        self.v.close();self.v=store.Vault(self.root/'private');self.v.unlock(PASSWORD)
        with self.v.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM t').fetchone()[0],1)

    def test_migration_copy_failure_keeps_originals(self):
        old=self.root/'legacy';old.mkdir();primary=old/'carteira.sqlite3'
        with closing(sqlite3.connect(primary)) as c:c.execute('CREATE TABLE t(x)');c.execute('INSERT INTO t VALUES (3)');c.commit()
        self.v.close();self.v=store.Vault(self.root/'private',primary,[old])
        original=store.atomic_write
        def fail_copy(path,data):
            if Path(path).parent.name=='backups':raise OSError('test failure')
            return original(path,data)
        with patch('aporte_brasil.core.private_storage.atomic_write',side_effect=fail_copy),self.assertRaisesRegex(ValueError,'cofre foi criado'):self.v.create(PASSWORD,PASSWORD,True)
        self.assertTrue(primary.exists());self.v.unlock(PASSWORD);self.v.protect_legacy();self.assertFalse(primary.exists())

    def test_idle_expiration_and_changed_password_keeps_old_backup_password(self):
        token=self.create();backup=self.v.export();self.v.change_password(PASSWORD,NEW_PASSWORD,NEW_PASSWORD)
        store.decrypt_password(backup,PASSWORD)
        with self.assertRaises(ValueError):store.decrypt_password(self.v.path.read_bytes(),PASSWORD)
        self.v.sessions[token]-=store.IDLE_SECONDS+1
        self.assertFalse(self.v.authorized(token));self.assertIsNone(self.v.key);self.assertIsNone(self.v.image)
        self.assertTrue(self.v.authorized(self.v.unlock(NEW_PASSWORD)))

    def test_two_processes_cannot_open_same_wallet(self):
        self.v.acquire_instance();other=store.Vault(self.v.directory)
        try:
            with self.assertRaises(ValueError):other.acquire_instance()
        finally:other.close()

    def test_forgotten_password_new_wallet_preserves_old_encryption(self):
        self.create()
        with self.v.connect() as c:c.execute('CREATE TABLE t(x)');c.execute("INSERT INTO t VALUES ('OLD-PRIVATE-DATA')")
        old=self.v.path.read_bytes()
        with self.assertRaises(ValueError):self.v.fresh_start(NEW_PASSWORD,NEW_PASSWORD,True)
        self.v.lock()
        with self.assertRaises(ValueError):self.v.fresh_start(NEW_PASSWORD,NEW_PASSWORD,False)
        self.assertEqual(self.v.path.read_bytes(),old)
        token,name=self.v.fresh_start(NEW_PASSWORD,NEW_PASSWORD,True)
        self.assertTrue(self.v.authorized(token));archive=self.v.directory/'backups'/name
        self.assertEqual(archive.read_bytes(),old)
        with self.assertRaises(ValueError):store.decrypt_password(archive.read_bytes(),NEW_PASSWORD)
        image,_,_=store.decrypt_password(archive.read_bytes(),PASSWORD)
        with closing(store.memory_db(image)) as c:self.assertEqual(c.execute('SELECT x FROM t').fetchone()[0],'OLD-PRIVATE-DATA')
        with self.v.connect() as c:self.assertFalse(c.execute("SELECT name FROM sqlite_master WHERE name='t'").fetchone())

class ProtectedAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=app.ROOT/'tests',prefix='tmp-test-');self.root=Path(self.tmp.name)
        self.old_vault=app.VAULT;self.old_path=app.DB_PATH
        app.DB_PATH=self.root/'private/carteira.sqlite3';app.VAULT=store.Vault(app.DB_PATH.parent)
        self.token=app.VAULT.create(PASSWORD,PASSWORD);app.init_db();self.day=app.today().isoformat()
        with app.connect() as c:c.execute("UPDATE settings SET value='false' WHERE key='auto_refresh'")
        self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();app.VAULT.close();app.VAULT=self.old_vault;app.DB_PATH=self.old_path;self.tmp.cleanup()
    def request(self,path,data=None,token=None,csrf=True,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        headers={}
        if token:headers['Cookie']='aporte_session='+token
        if data is not None:headers.update({'Content-Type':'application/json','X-CSRF-Token':app.CSRF if csrf else 'wrong'})
        if origin:headers['Origin']=origin
        c.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,headers)
        response=c.getresponse();result=(response.status,dict(response.getheaders()),response.read());c.close();return result

    def test_read_export_and_writes_require_session_and_csrf(self):
        for path in ('/api/state','/api/catalog','/api/export','/api/ai/job'):
            self.assertEqual(self.request(path)[0],401);self.assertEqual(self.request(path,token='forged')[0],401)
        self.assertEqual(self.request('/api/settings',{'profile':'test'})[0],401)
        self.assertEqual(self.request('/api/settings',{'profile':'test'},self.token,csrf=False)[0],403)
        self.assertEqual(self.request('/api/settings',{'profile':'test'},self.token,origin='https://example.org')[0],403)
        self.assertEqual(self.request('/api/ai/models',{})[0],401)
        for path in ('/api/ai/import','/api/ai/import/commit','/api/ai/import/discard','/api/ai/exposure','/api/ai/instrument-quotes',
                     '/api/issuer/analyze','/api/issuer/report','/api/issuer/financials','/api/issuer/auto','/api/issuer/quality-facts','/api/fii/quality-facts','/api/allocation/recommend'):
            self.assertEqual(self.request(path,{})[0],401)
            self.assertEqual(self.request(path,{},self.token,csrf=False)[0],403)
        self.assertEqual(self.request('/api/ai/scenario',{'question':'Cenário público'},self.token,csrf=False)[0],403)
        self.assertEqual(self.request('/api/ai/job',token=self.token)[0],200)
        self.assertEqual(self.request('/api/state',token=self.token)[0],200)
        status,headers,payload=self.request('/api/export',token=self.token)
        self.assertEqual(status,200);self.assertIn('.aporteb',headers['Content-Disposition']);self.assertTrue(payload.startswith(store.MAGIC))
        self.assertNotIn(b'brapi_token',payload)

    def test_saving_bdr_starts_its_quote_refresh(self):
        with patch.object(app,'start_refresh',return_value={'running':True}) as refresh:
            status,_,body=self.request('/api/assets',{'ticker':'AAPL34','asset_type':'bdr','name':'Apple BDR','sector':'Tecnologia'},self.token)
        self.assertEqual(status,200)
        record=json.loads(body)
        refresh.assert_called_once_with(record['id'])
        self.assertTrue(record['refresh']['running'])

    def test_http_unlock_cookie_lock_and_restart_persistence(self):
        self.assertEqual(self.request('/api/security/lock',{},self.token)[0],200)
        self.assertEqual(self.request('/api/state',token=self.token)[0],401)
        status,headers,_=self.request('/api/security/unlock',{'password':PASSWORD})
        self.assertEqual(status,200);self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        new_token=headers['Set-Cookie'].split(';')[0].split('=',1)[1]
        self.assertEqual(self.request('/api/settings',{'profile':'PRIVATE-PROFILE'},new_token)[0],200)
        app.VAULT.lock();app.VAULT.unlock(PASSWORD)
        self.assertEqual(app.state()['settings']['profile'],'PRIVATE-PROFILE')
        self.assertNotIn(b'PRIVATE-PROFILE',app.VAULT.path.read_bytes())

    def test_b3_preview_commit_dedupe_and_encrypted_restore(self):
        baseline.AppTests.asset(self)
        d={'csv':f'Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\nEntrada;{self.day};Compra;ABCD3;XP;10;20;200'}
        from aporte_brasil.importers import b3_import
        p=b3_import.preview(app,d);self.assertIsNotNone(p['token']);self.assertEqual(app.state()['assets'][0]['position']['quantity'],0)
        b3_import.commit(app,{'token':p['token'],'confirm_records':True})
        payload=app.VAULT.export();self.assertNotIn(b'ABCD3',payload)
        status,_,_=self.request('/api/security/restore',{'file':base64.b64encode(payload).decode(),'password':PASSWORD},self.token)
        self.assertEqual(status,200);self.assertEqual(app.state()['assets'][0]['position']['quantity'],10)
        self.assertEqual(b3_import.preview(app,d)['skipped'],1)
        backups=list((app.VAULT.directory/'backups').glob('*'));self.assertTrue(backups)
        for file in backups:self.assertTrue(file.read_bytes().startswith(store.MAGIC))
        self.assertFalse(list(self.root.rglob('*.sqlite3')))

if __name__=='__main__':unittest.main()
