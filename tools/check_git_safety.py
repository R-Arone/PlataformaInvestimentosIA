"""Fail closed when private artifacts enter the Git index or reachable history."""
import argparse
from pathlib import PurePosixPath
import re
import subprocess
import sys

ROOT_FILES={'.gitignore','.gitattributes','README.md','SECURITY.md','requirements.txt','requirements-ai.txt','requirements-build.txt','Iniciar.ps1','Abrir Aporte Brasil.cmd','Reiniciar Aporte Brasil.cmd','Preparar Git.ps1'}
ROOT_FILES.add('Encerrar.ps1')
MODULES={'app.py','b3_import.py','bayesian_signals.py','csv_import.py','extra_sources.py','funds.py','history_cache.py','holdings.py','installer_builder.py','lifecycle.py','market.py','market_brief.py','market_outlook.py','market_ai.py','market_signals.py','portfolio_coupling.py','us_market.py','portfolio_strategy.py','public_fundamentals.py','research_exchange.py','sector_analysis.py','tax_rules.py','treasury_import.py','valuation.py','private_storage.py'}

MODULES.add('investment_exposure.py')
MODULES.add('company_research.py')
MODULES.add('company_history.py')
MODULES.add('company_insights.py')
MODULES.update(('fii_research.py','public_reports.py'))
MODULES.add('international_market.py')
MODULES.update(('market_monitor.py','market_news.py','desktop_notifications.py'))
MODULES.add('stock_fundamentals.py')
MODULES.add('tesouro.py')
MODULES.add('model_comparison.py')
MODULES.add('company_model.py')
MODULES.add('factor_analysis.py')
MODULES.add('company_evidence.py')
MODULES.add('company_batch.py')
MODULES.add('company_quality.py')
MODULES.add('fii_quality.py')

# Ensaios dependentes de bases locais ou de ferramentas offline nao publicadas.
LOCAL_TESTS={'test_installer.py','test_model_comparison.py','test_company_history.py',
             'test_long_term_models.py','test_model_agreement.py','test_replay_models.py'}

def allowed(name):
    path=PurePosixPath(name)
    if name in ROOT_FILES|MODULES:return True
    if '..' in path.parts or len(path.parts)!=2:return False
    parent,base=path.parts
    return (parent=='static' and path.suffix in ('.html','.css','.js','.svg')
        or parent=='tests' and base.startswith('test_') and not base.endswith('_live.py') and base not in LOCAL_TESTS and path.suffix=='.py'
        or parent=='tools' and base in ('check_git_safety.py','export_source.py','build_windows.ps1','runtime_probe.py','prepare_runtime.py','build_installer.py')
        or parent=='packaging' and base in ('Instalar.cmd','Uninstall.ps1','LEIA-ME.txt')
        or parent=='.githooks' and base in ('pre-commit','pre-push'))

def run(*args):return subprocess.check_output(['git',*args])

# Only report the location/type of a finding, never its secret value.
SENSITIVE=(
    ('credencial', re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')),
    ('caminho pessoal', re.compile(rb'(?i)(?:[A-Z]:[/\\]Users[/\\]|/Users/|/home/)[A-Za-z0-9_.-]+[/\\]')),
    ('email pessoal', re.compile(rb'(?i)[A-Za-z0-9_.+-]+@(?:gmail|hotmail|outlook|yahoo|icloud|protonmail)\.[A-Za-z.]+')),
)

def content_problem(data):
    if b'SQLite format 3\x00' in data[:32] or data.startswith(b'APORTE-VAULT\x00'):
        return 'conteudo de banco de dados'
    if data.startswith((b'PK\x03\x04',b'MZ',b'\x1f\x8b',b'\x89PNG',b'\xff\xd8\xff',b'%PDF')):
        return 'arquivo binario/compactado disfarçado'
    try:data.decode('utf-8-sig')
    except UnicodeDecodeError:return 'conteudo nao textual'
    for label,pattern in SENSITIVE:
        if pattern.search(data):return label
    return None

def audit(history=False,staged=False,refs=()):
    if history:
        entries=[]
        # Inspect every path in every published tree, including deleted files
        # and identical blobs placed under different names. Cache blob reads.
        blobs={};seen=set()
        for commit in run('rev-list',*(refs or ('--all',))).decode().splitlines():
            for entry in run('ls-tree','-r','-z',commit).split(b'\0'):
                if not entry:continue
                metadata,raw_name=entry.split(b'\t',1)
                mode,kind,oid=metadata.split();name=raw_name.decode('utf-8')
                identity=(mode,oid,name)
                if identity in seen:continue
                seen.add(identity)
                if mode not in (b'100644',b'100755') or kind!=b'blob':
                    entries.append((name,b'','link/submodulo nao permitido'));continue
                if oid not in blobs:blobs[oid]=run('cat-file','blob',oid.decode())
                entries.append((name,blobs[oid],None))
    else:
        names=run('diff','--cached','--name-only','--diff-filter=ACMR','-z') if staged else run('ls-files','-z')
        entries=[]
        for name in names.decode().split('\0'):
            if not name:continue
            mode=run('ls-files','--stage','--',name).split(b' ',1)[0]
            entries.append((name,run('show',':'+name),None if mode in (b'100644',b'100755') else 'link/submodulo nao permitido'))
    violations=[]
    for name,data,problem in entries:
        problem=problem or ('fora da lista de arquivos de codigo permitidos' if not allowed(name) else content_problem(data))
        if problem:violations.append(name+' ('+problem+')')
    if violations:
        print('Publicacao bloqueada: arquivos possivelmente privados:',file=sys.stderr)
        for item in sorted(set(violations)):print(' - '+item,file=sys.stderr)
        return 1
    print('Conferencia Git: apenas codigo/documentacao ('+str(len(entries))+' verificacoes).')
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--staged',action='store_true');parser.add_argument('--history',action='store_true')
    parser.add_argument('--ref',action='append',default=[]);parser.add_argument('--push',action='store_true')
    args=parser.parse_args()
    if args.push:
        refs=[]
        for line in sys.stdin:
            local_ref,local_oid,remote_ref,remote_oid=line.split()
            if set(local_oid)!={'0'}:refs.append(local_oid)
        sys.exit(audit(history=True,refs=refs) if refs else 0)
    sys.exit(audit(args.history,args.staged,args.ref))
