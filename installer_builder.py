"""Build a shareable Windows installer from a restricted source snapshot.

This module never opens the wallet. Inputs and destinations are controlled here,
not by HTTP callers. Optional ML environments and model caches are excluded.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import traceback
import zipfile

from tools.check_git_safety import MODULES

STATIC = ('index.html', 'app.js', 'expanded.js', 'research.js', 'insights.js',
          'developments.js', 'planning.js', 'decisions.js', 'context.js', 'ai.js', 'exposures.js', 'quality.js', 'international.js',
          'positions.js', 'signals.js', 'models.js', 'model-comparison-data.json', 'us.js', 'security.js', 'installer.js',
          'stocks.js', 'buy-hold.js', 'fii-research.js', 'company-model.js', 'factor-analysis.js', 'intelligence.js', 'tesouro.js', 'style.css', 'favicon.svg')
PACKAGING = ('Instalar.cmd', 'Install.ps1', 'Uninstall.ps1', 'LEIA-ME.txt')
EXCLUDED = ('torch', 'transformers', 'chronos', 'numpy', 'scipy', 'pandas',
            'matplotlib', 'PIL', 'IPython', 'pytest', 'tkinter')
NAME = re.compile(r'AporteBrasil-Instalador-Windows-v([1-9]\d{0,3})-([0-9]{8}-[0-9]{6}-[a-f0-9]{8})\.zip\Z')
PRIVATE_EXT = {'.aporteb', '.db', '.sqlite', '.sqlite3', '.xlsx', '.xls', '.csv',
               '.safetensors', '.pt', '.pth', '.ckpt'}
PRIVATE_DIRS = {'data', 'private', 'backups', 'imports', 'exports', '.git', '.venv',
                'models', 'torch', 'transformers', 'chronos'}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def linked(path):
    attributes = path.lstat()
    return path.is_symlink() or bool(getattr(attributes, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def checked(root, relative, directory=False):
    """Reject links/junctions on every component, including an output parent."""
    root = Path(root).absolute()
    path = root / relative
    if '..' in Path(relative).parts or Path(relative).is_absolute():
        raise ValueError('Caminho de geração inválido.')
    for component in (root, *[root.joinpath(*Path(relative).parts[:i]) for i in range(1, len(Path(relative).parts)+1)]):
        if component.exists() or component.is_symlink():
            if linked(component):
                raise ValueError('A geração não aceita atalhos de pasta ou links nos arquivos do projeto.')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Arquivo fora da pasta do projeto.')
    if directory:
        path.mkdir(parents=True, exist_ok=True)
    elif not path.is_file():
        raise ValueError('Arquivo de código ausente: '+str(relative))
    return path


def snapshot(root, destination):
    names = sorted(MODULES) + ['tools/check_git_safety.py']
    names += ['static/'+name for name in STATIC] + ['packaging/'+name for name in PACKAGING]
    hashes = {}
    for name in names:
        source = checked(root, name)
        payload = source.read_bytes()
        if payload.startswith((b'SQLite format 3', b'APORTE-VAULT', b'MZ', b'PK\x03\x04')):
            raise ValueError('Conteúdo inesperado em um arquivo de código: '+name)
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    match = re.search(r'^APP_VERSION = (\d+)\s*$', (destination/'app.py').read_text(encoding='utf-8'), re.M)
    if not match or not 1 <= int(match[1]) <= 9999:
        raise ValueError('Versão do aplicativo não reconhecida.')
    return int(match[1]), hashes


def clean_environment(root, work):
    keys = ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE', 'PATH', 'TEMP', 'TMP',
            'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
            'PROCESSOR_ARCHITECTURE', 'PATHEXT')
    env = {key:value for key,value in os.environ.items() if key.upper() in keys}
    env.update(PYTHONPATH=str(root/'build-tools'), PYTHONNOUSERSITE='1',
               PYINSTALLER_CONFIG_DIR=str(work/'cache'), PIP_CACHE_DIR=str(root/'build'/'installer-deps-cache'))
    return env


def run(command, cwd, env, log, timeout=1200):
    with log.open('ab') as output:
        result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:
        raise ValueError('Um componente de geração falhou. Consulte o registro na pasta build e tente novamente.')


def compiler_command(python, source, work):
    command = [str(python), '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--windowed', '--noupx', '--name', 'AporteBrasil', '--collect-all', 'cryptography',
               '--collect-data', 'tzdata', '--add-data', str(source/'static')+os.pathsep+'static',
               '--distpath', str(work/'dist'), '--workpath', str(work/'compile'),
               '--specpath', str(work/'spec')]
    for module in EXCLUDED:
        command += ['--exclude-module', module]
    # Also include modules used through dynamic import in the HTTP handlers.
    for name in sorted(MODULES):
        if name != 'app.py': command += ['--hidden-import', name[:-3]]
    return command + [str(source/'app.py')]


def audit_payload(directory):
    files = []
    for path in sorted(directory.rglob('*')):
        if linked(path): raise ValueError('O pacote contém um link de arquivo ou pasta.')
        if not path.is_file(): continue
        relative = path.relative_to(directory)
        if (path.suffix.lower() in PRIVATE_EXT or path.name.lower().startswith('.env')
            or any(part.lower() in PRIVATE_DIRS for part in relative.parts)):
            raise ValueError('O pacote contém um arquivo que não pode ser compartilhado: '+relative.as_posix())
        with path.open('rb') as stream:
            if stream.read(16).startswith((b'SQLite format 3', b'APORTE-VAULT')):
                raise ValueError('Um banco de dados foi encontrado no pacote. Nada foi liberado.')
        files.append(path)
    if not (directory/'AporteBrasil'/'AporteBrasil.exe').is_file():
        raise ValueError('O executável do instalador não foi gerado.')
    return files


class Builder:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.mutex = threading.RLock()
        self.job = {'running':False, 'step':0, 'steps':6, 'detail':'Pronto para gerar.', 'error':None, 'artifact':None}

    def availability(self):
        if getattr(sys, 'frozen', False):
            return False, 'Gere novas versões pela pasta de código do projeto. Este aplicativo instalado já está compilado.'
        if os.name != 'nt': return False, 'O instalador Windows deve ser gerado no Windows.'
        if not (self.root/'app.py').is_file(): return False, 'Abra o aplicativo pela pasta de código completa.'
        try:
            if not all((self.root/'packaging'/name).is_file() for name in PACKAGING):
                return False, 'Esta distribuição não inclui todos os scripts de instalação revisados. Execute pela pasta de código Python.'
        except OSError:
            return False, 'Um script de instalação está indisponível para leitura. Execute pela pasta de código Python.'
        return True, 'Geração local, sem instalar nem substituir o aplicativo aberto.'

    def artifacts(self):
        directory = self.root/'release'
        if not directory.exists() or linked(directory): return []
        artifacts = []
        for manifest in sorted(directory.glob('AporteBrasil-Instalador-Windows-v*-*.zip.json'), reverse=True):
            try:
                if linked(manifest) or manifest.stat().st_size > 4096: continue
                item = json.loads(manifest.read_text(encoding='utf-8'))
                name = manifest.name[:-5]
                path = checked(self.root, 'release/'+name)
                if not NAME.fullmatch(name) or item.get('filename') != name: continue
                if not re.fullmatch('[a-f0-9]{64}', item.get('sha256','')) or item.get('size') != path.stat().st_size: continue
                artifacts.append({key:item[key] for key in ('filename','size','sha256','version','created_at')})
            except (OSError, ValueError, KeyError, TypeError): continue
            if len(artifacts) >= 5: break
        return artifacts

    def status(self):
        available, reason = self.availability()
        with self.mutex: job = dict(self.job)
        return {**job, 'available':available, 'reason':reason, 'artifacts':self.artifacts()}

    def update(self, **values):
        with self.mutex: self.job.update(values)

    def start(self):
        available, reason = self.availability()
        if not available: raise ValueError(reason)
        with self.mutex:
            if self.job['running']: return self.status()
            self.job = {'running':True, 'step':1, 'steps':6, 'detail':'Separando somente o código aprovado…',
                        'error':None, 'artifact':None}
            threading.Thread(target=self.build, daemon=True).start()
        return self.status()

    def download(self, name):
        if not NAME.fullmatch(name): raise ValueError('Arquivo de instalador inválido.')
        item = next((item for item in self.artifacts() if item['filename']==name), None)
        if not item: raise ValueError('Instalador não encontrado. Gere um novo pacote.')
        path = checked(self.root, 'release/'+name)
        with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != item['sha256']:
            raise ValueError('O pacote mudou depois da geração. Gere novamente antes de baixar.')
        return path

    def build(self):
        work = log = lease = archive = metadata = None
        success = False
        try:
            checked(self.root, 'build', directory=True)
            lease_path = self.root/'build'/'installer.lock'
            if lease_path.exists() and linked(lease_path): raise ValueError('O controle de geração contém um link inválido.')
            lease = lease_path.open('a+b')
            lease.seek(0); lease.write(b'0'); lease.flush(); lease.seek(0)
            import msvcrt
            try: msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError: raise ValueError('Já existe outra geração nesta pasta. Aguarde terminar.')
            identifier = datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)
            work = checked(self.root, 'build/installer-'+identifier, directory=True)
            log = self.root/'build'/('installer-'+identifier+'.log')
            source = work/'source'; source.mkdir()
            version, hashes = snapshot(self.root, source)
            self.update(step=2, detail='Conferindo os componentes do instalador…')
            checked(self.root, 'build-tools', directory=True)
            env = clean_environment(self.root, work)
            bundled = Path(os.environ.get('USERPROFILE', str(Path.home())))/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
            python = bundled if bundled.is_file() else Path(sys.executable)
            probe = work/'probe.py'
            probe.write_text('import cryptography, tzdata\n', encoding='utf-8')
            run([str(python), str(probe)], source, env, log, 45)
            if not (self.root/'build-tools/PyInstaller').is_dir():
                self.update(detail='Preparando o compilador público; requer internet na primeira geração…')
                run([str(python), '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
                     '--target', str(self.root/'build-tools'), 'pyinstaller==6.20.0'], source, env, log, 600)
            self.update(step=3, detail='Montando o aplicativo Windows. Esta etapa pode levar alguns minutos…')
            run(compiler_command(python, source, work), source, env, log)
            self.update(step=4, detail='Incluindo o instalador e conferindo os arquivos…')
            package_name = f'AporteBrasil-Windows-v{version}-{identifier}'
            package = work/package_name; package.mkdir()
            shutil.copytree(work/'dist/AporteBrasil', package/'AporteBrasil')
            for name in PACKAGING: shutil.copyfile(source/'packaging'/name, package/name)
            (package/'VERSAO.txt').write_text(f'Aporte Brasil v{version}\n', encoding='utf-8')
            (package/'MANIFESTO.json').write_text(json.dumps({'version':version, 'created_at':timestamp(),
                'source_sha256':hashes, 'optional_ml_bundled':False}, ensure_ascii=False, indent=2), encoding='utf-8')
            files = audit_payload(package)
            self.update(step=5, detail='Compactando o ZIP e verificando a integridade…')
            release = checked(self.root, 'release', directory=True)
            filename = f'AporteBrasil-Instalador-Windows-v{version}-{identifier}.zip'
            archive = release/filename
            # Exclusive creation prevents replacing an earlier artifact.
            with archive.open('xb') as output, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zipped:
                for path in files: zipped.write(path, package_name+'/'+path.relative_to(package).as_posix())
            with zipfile.ZipFile(archive) as zipped:
                if zipped.testzip() is not None: raise ValueError('A conferência do ZIP falhou. Tente gerar novamente.')
            with archive.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            artifact = {'filename':filename, 'size':archive.stat().st_size, 'sha256':digest,
                        'version':version, 'created_at':timestamp()}
            metadata = release/(filename+'.json')
            with metadata.open('x', encoding='utf-8') as output: json.dump(artifact, output)
            success = True
            self.update(step=6, detail='ZIP pronto e conferido. Sua carteira não faz parte do pacote.', artifact=artifact)
        except Exception as exc:
            if log:
                with log.open('a', encoding='utf-8') as output: output.write(traceback.format_exc())
            message = str(exc) if isinstance(exc, ValueError) else 'Não foi possível concluir. Confira o registro na pasta build e tente novamente.'
            self.update(error=message, detail='Geração interrompida; nenhum novo pacote foi liberado.')
        finally:
            try:
                if not success:
                    for path in (archive, metadata):
                        if path and path.is_file() and not linked(path): path.unlink()
                if lease: lease.close()
                if work and work.parent == self.root/'build' and not linked(work):
                    # rmtree is limited to this unique, controlled staging directory.
                    if all(not linked(path) for path in work.rglob('*')): shutil.rmtree(work)
            except OSError:
                # A busy antivirus may retain staging files; never lose the final job state.
                pass
            finally: self.update(running=False)
