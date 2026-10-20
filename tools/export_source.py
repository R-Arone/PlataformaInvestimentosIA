"""Copy only the approved source files; never copy a data directory."""
import argparse
from pathlib import Path
import shutil
import stat
from check_git_safety import allowed

root=Path(__file__).resolve().parents[1]
def approved_files():
    files=[p for p in root.iterdir() if allowed(p.name) and p.is_file()]
    for directory in ('static','tests','tools','packaging','.githooks'):
        files.extend(p for p in (root/directory).iterdir() if allowed(p.relative_to(root).as_posix()) and p.is_file())
    if any(p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))
           for source in files for p in (source,source.parent)):
        raise ValueError('A exportacao nao aceita links para outros arquivos ou pastas.')
    return sorted(files)
def export(target):
    target=Path(target).absolute()
    if target.exists() and any(target.iterdir()):raise ValueError('O destino deve estar vazio para nao misturar projetos ou dados.')
    target.mkdir(parents=True,exist_ok=True)
    files=approved_files()
    for source in files:
        dest=target/source.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    return len(files)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('target');args=parser.parse_args()
    print('Arquivos de codigo copiados:',export(args.target))
