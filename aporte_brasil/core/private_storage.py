"""Authenticated encrypted SQLite snapshots. Plaintext databases stay in memory.

This is a small local vault, not a new cipher. AES-GCM and scrypt are supplied
by cryptography. The fixed header is authenticated and parameters are versioned.
"""
from contextlib import contextmanager, closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC=b'APORTE-VAULT\x00\x01'
MAX_BYTES=200_000_000
IDLE_SECONDS=30*60

class LockedError(ValueError):
    pass

def data_dir():
    explicit=os.environ.get('APORTE_DATA_DIR')
    if explicit:return Path(explicit).expanduser().absolute()
    base=Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))
    return base/'AporteBrasil'/'data'

def password_bytes(value):
    if not isinstance(value,str) or not 12<=len(value)<=256:
        raise ValueError('Use uma senha de 12 a 256 caracteres. Espaços são permitidos.')
    return value.encode('utf-8')

def derive(password,salt):
    return Scrypt(salt=salt,length=32,n=2**17,r=8,p=1).derive(password_bytes(password))

def encrypt(data,key,salt):
    nonce=secrets.token_bytes(12)
    header=MAGIC+salt+nonce
    return header+AESGCM(key).encrypt(nonce,data,header)

def decrypt_key(payload,key):
    start=len(MAGIC)
    if not isinstance(payload,bytes) or not payload.startswith(MAGIC) or not start+44<=len(payload)<=MAX_BYTES:
        raise ValueError('Arquivo protegido inválido ou maior que 200 MB.')
    header=payload[:start+28];nonce=payload[start+16:start+28]
    try:return AESGCM(key).decrypt(nonce,payload[start+28:],header)
    except InvalidTag:raise ValueError('Senha incorreta ou arquivo protegido danificado.') from None

def decrypt_password(payload,password):
    if not isinstance(payload,bytes) or not payload.startswith(MAGIC) or len(payload)<len(MAGIC)+44 or len(payload)>MAX_BYTES:
        raise ValueError('Arquivo protegido inválido ou maior que 200 MB.')
    salt=payload[len(MAGIC):len(MAGIC)+16]
    key=derive(password,salt)
    return decrypt_key(payload,key),key,salt

def memory_db(image=None):
    c=sqlite3.connect(':memory:',timeout=30)
    if image:
        if not image.startswith(b'SQLite format 3\x00'):c.close();raise ValueError('O arquivo não contém um banco SQLite compatível.')
        # A standalone SQLite backup has no WAL file. Set its read/write versions
        # to rollback format before deserializing it into an in-memory database.
        image=image[:18]+b'\x01\x01'+image[20:]
        try:
            c.deserialize(image)
            if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Banco de dados danificado.')
        except Exception:
            c.close();raise
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA temp_store=MEMORY')
    return c

def read_sqlite(path):
    path=Path(path).resolve(strict=True)
    if path.stat().st_size>MAX_BYTES:raise ValueError('Banco antigo maior que 200 MB.')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=30)) as source,closing(sqlite3.connect(':memory:')) as destination:
        source.backup(destination)
        image=destination.serialize()
    with closing(memory_db(image)) as checked:
        return checked.serialize()

def atomic_write(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        with open(temporary,'xb') as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)

class Vault:
    def __init__(self,directory,legacy_primary=None,legacy_dirs=()):
        self.directory=Path(directory).absolute();self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'carteira.aporteb'
        self.mutex=threading.RLock();self.key=None;self.salt=None;self.image=None
        self.sessions={};self.failures=0;self.retry_at=0;self.local=threading.local()
        marker=self.directory/'migration-sources.json'
        stored=json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
        self.legacy_primary=Path(stored['primary']) if stored.get('primary') else (Path(legacy_primary).absolute() if legacy_primary else None)
        self.legacy_dirs=list(dict.fromkeys([Path(p).absolute() for p in stored.get('directories',[])]+[Path(p).absolute() for p in legacy_dirs]))
        if self.legacy_primary:self.legacy_dirs=list(dict.fromkeys([self.legacy_primary.parent]+self.legacy_dirs))
        if not self.path.exists() and self.legacy_primary and self.legacy_primary.exists():
            atomic_write(marker,json.dumps({'primary':str(self.legacy_primary),'directories':[str(p) for p in self.legacy_dirs]}).encode())
        self.instance_file=None

    def acquire_instance(self):
        self.instance_file=open(self.directory/'application.lock','a+b')
        self.instance_file.seek(0);self.instance_file.write(b'0');self.instance_file.flush();self.instance_file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.instance_file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.instance_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.instance_file.close();self.instance_file=None
            raise ValueError('Esta carteira já está aberta em outro processo. Feche-o antes de abrir outra cópia.') from None

    def old_files(self):
        files=[]
        for directory in self.legacy_dirs:
            if directory.exists():
                for path in directory.iterdir():
                    if path.is_file() and path.suffix.lower() in ('.sqlite3','.sqlite','.db') and path.resolve() not in files:
                        files.append(path.resolve())
        return sorted(files)

    def status(self,token=None):
        authenticated=self.authorized(token,touch=False) if token else False
        return {'initialized':self.path.exists(),'authenticated':authenticated,'legacy_files':len(self.old_files()),
                'idle_minutes':IDLE_SECONDS//60,'retry_seconds':max(0,round(self.retry_at-time.monotonic()+.5)),
                'encrypted':self.path.exists()}

    def new_session(self):
        token=secrets.token_urlsafe(32);self.sessions[token]=time.monotonic();return token

    def authorized(self,token,touch=True):
        with self.mutex:
            current=time.monotonic()
            expired=[t for t,stamp in self.sessions.items() if current-stamp>=IDLE_SECONDS]
            for t in expired:self.sessions.pop(t,None)
            if expired and not self.sessions:self.lock()
            if token not in self.sessions or self.key is None:return False
            if touch:self.sessions[token]=current
            return True

    def lock(self):
        with self.mutex:
            self.sessions.clear();self.key=None;self.salt=None;self.image=None

    def unlock(self,password):
        with self.mutex:
            if time.monotonic()<self.retry_at:raise ValueError('Aguarde alguns segundos antes de tentar outra senha.')
            if not self.path.exists():raise ValueError('Crie a senha local primeiro.')
            try:
                image,key,salt=decrypt_password(self.path.read_bytes(),password)
                with closing(memory_db(image)) as c:image=c.serialize()
            except (ValueError,sqlite3.Error):
                self.failures+=1;self.retry_at=time.monotonic()+min(60,2**min(self.failures,6))
                raise ValueError('Senha incorreta ou arquivo protegido danificado.') from None
            self.key=key;self.salt=salt;self.image=image;self.failures=0;self.retry_at=0
            return self.new_session()

    def protect_legacy(self):
        if self.key is None:raise LockedError('Desbloqueie a carteira primeiro.')
        # Every plaintext file receives a verified encrypted copy before any
        # removal. Stop on changed files so concurrent legacy writes cannot vanish.
        copies=[]
        for source in self.old_files():
            image=read_sqlite(source)
            suffix=hashlib.sha256(str(source).encode()+image).hexdigest()[:12]
            target=self.directory/'backups'/('migrado-'+source.stem+'-'+suffix+'.aporteb')
            payload=encrypt(image,self.key,self.salt);atomic_write(target,payload)
            if decrypt_key(target.read_bytes(),self.key)!=image:raise ValueError('A conferência da cópia protegida falhou. Os arquivos antigos foram mantidos.')
            copies.append((source,hashlib.sha256(image).digest()))
        for source,digest in copies:
            if hashlib.sha256(read_sqlite(source)).digest()!=digest:
                raise ValueError('O banco antigo mudou durante a migração. Feche a versão antiga e tente novamente. Nenhum arquivo alterado foi removido.')
        for source,_ in copies:
            # Only exact discovered database paths and their SQLite sidecars.
            source.unlink()
            for suffix in ('-wal','-shm','-journal'):Path(str(source)+suffix).unlink(missing_ok=True)

    def create(self,password,confirmation,confirm_migration=False):
        with self.mutex:
            if self.path.exists():raise ValueError('Já existe uma carteira protegida. Use sua senha para abrir.')
            if password!=confirmation:raise ValueError('As senhas não coincidem.')
            password_bytes(password)
            old=self.old_files()
            if old and confirm_migration is not True:raise ValueError('Confirme a migração dos bancos e backups antigos para cópias criptografadas.')
            if self.legacy_primary and self.legacy_primary.exists():image=read_sqlite(self.legacy_primary)
            else:
                with closing(memory_db()) as c:
                    c.execute('PRAGMA user_version=0');image=c.serialize()
            salt=secrets.token_bytes(16);key=derive(password,salt)
            self.key=key;self.salt=salt;self.image=image
            try:
                payload=encrypt(image,key,salt)
                if decrypt_key(payload,key)!=image:raise ValueError('Não foi possível conferir a criptografia.')
                atomic_write(self.path,payload)
                self.protect_legacy()
            except Exception as exc:
                self.lock()
                if isinstance(exc,OSError) and self.path.exists():
                    raise ValueError('O cofre foi criado, mas a migração das cópias antigas não terminou. Feche a versão antiga do aplicativo, atualize a página e abra com a nova senha. Em Preferências, conclua a proteção das cópias restantes.') from None
                raise
            return self.new_session()

    @contextmanager
    def connect(self):
        with self.mutex:
            if self.key is None:raise LockedError('A carteira está bloqueada. Digite sua senha para abrir.')
            if getattr(self.local,'active',False):raise RuntimeError('Conexões aninhadas ao cofre não são permitidas.')
            self.local.active=True
            c=None
            try:
                c=memory_db(self.image)
                with c:yield c
                image=c.serialize()
                if image!=self.image:
                    atomic_write(self.path,encrypt(image,self.key,self.salt))
                    self.image=image
            finally:
                if c is not None:c.close()
                self.local.active=False

    def backup(self,c,name):
        with self.mutex:
            if self.key is None:raise LockedError('A carteira está bloqueada.')
            target=self.directory/'backups'/(Path(name).stem+'.aporteb')
            atomic_write(target,encrypt(c.serialize(),self.key,self.salt));return target

    def export(self):
        with self.mutex:
            if self.key is None:raise LockedError('A carteira está bloqueada.')
            with closing(memory_db(self.image)) as c:
                tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'settings' in tables:c.execute("DELETE FROM settings WHERE key='brapi_token'")
                if 'runtime' in tables:c.execute("DELETE FROM runtime WHERE key='form_nonce'")
                c.commit();image=c.serialize()
            return encrypt(image,self.key,self.salt)

    def fresh_start(self,password,confirmation,confirmed=False):
        with self.mutex:
            if self.key is not None:raise ValueError('Bloqueie a carteira antes de criar outra por esquecimento de senha.')
            if not self.path.exists():raise ValueError('Crie sua primeira carteira na tela inicial.')
            if confirmed is not True:raise ValueError('Confirme que a nova carteira ficará vazia e que a senha antiga continua necessária para recuperar os dados anteriores.')
            if password!=confirmation:raise ValueError('As senhas não coincidem.')
            salt=secrets.token_bytes(16);key=derive(password,salt)
            with closing(memory_db()) as c:c.execute('PRAGMA user_version=0');image=c.serialize()
            old=self.path.read_bytes()
            from datetime import datetime
            archive=self.directory/'backups'/('carteira-anterior-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)+'.aporteb')
            atomic_write(archive,old)
            if archive.read_bytes()!=old:raise ValueError('Não foi possível conferir o arquivo anterior; a carteira foi mantida.')
            atomic_write(self.path,encrypt(image,key,salt))
            self.sessions.clear();self.key=key;self.salt=salt;self.image=image
            return self.new_session(),archive.name

    def change_password(self,current,password,confirmation):
        with self.mutex:
            if self.key is None:raise LockedError('Desbloqueie a carteira primeiro.')
            decrypt_password(self.path.read_bytes(),current)
            if password!=confirmation:raise ValueError('As senhas não coincidem.')
            salt=secrets.token_bytes(16);key=derive(password,salt)
            atomic_write(self.path,encrypt(self.image,key,salt));self.key=key;self.salt=salt

    def close(self):
        self.lock()
        if self.instance_file:self.instance_file.close();self.instance_file=None
