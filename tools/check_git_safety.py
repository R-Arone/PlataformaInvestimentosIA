"""Fail closed when private artifacts enter the Git index or reachable history."""
import argparse
from hashlib import sha256
from pathlib import PurePosixPath
import re
import subprocess
import sys

ROOT_FILES={'.gitignore','.gitattributes','README.md','SECURITY.md','requirements.txt','requirements-ai.txt','requirements-build.txt','Iniciar.ps1','Abrir Aporte Brasil.cmd','Reiniciar Aporte Brasil.cmd','Preparar Git.ps1'}
ROOT_FILES.add('Encerrar.ps1')
# Modulos de codigo publicaveis: app.py na raiz e o pacote aporte_brasil (um subpacote por area).
MODULES={
    'aporte_brasil/__init__.py',
    'aporte_brasil/ai/__init__.py',
    'aporte_brasil/ai/market_ai.py',
    'aporte_brasil/ai/model_comparison.py',
    'aporte_brasil/company/__init__.py',
    'aporte_brasil/company/business_drivers.py',
    'aporte_brasil/company/company_batch.py',
    'aporte_brasil/company/company_completion.py',
    'aporte_brasil/company/company_evidence.py',
    'aporte_brasil/company/company_history.py',
    'aporte_brasil/company/company_insights.py',
    'aporte_brasil/company/company_model.py',
    'aporte_brasil/company/company_quality.py',
    'aporte_brasil/company/company_registry.py',
    'aporte_brasil/company/company_research.py',
    'aporte_brasil/company/corporate_events.py',
    'aporte_brasil/company/factor_analysis.py',
    'aporte_brasil/company/fii_quality.py',
    'aporte_brasil/company/fii_research.py',
    'aporte_brasil/company/funds.py',
    'aporte_brasil/company/multiple_history.py',
    'aporte_brasil/company/public_fundamentals.py',
    'aporte_brasil/company/public_reports.py',
    'aporte_brasil/company/quality_evidence.py',
    'aporte_brasil/company/stock_fundamentals.py',
    'aporte_brasil/company/valuation.py',
    'aporte_brasil/company/valuation_history.py',
    'aporte_brasil/core/__init__.py',
    'aporte_brasil/core/desktop_notifications.py',
    'aporte_brasil/core/history_cache.py',
    'aporte_brasil/core/installer_builder.py',
    'aporte_brasil/core/lifecycle.py',
    'aporte_brasil/core/private_storage.py',
    'aporte_brasil/importers/__init__.py',
    'aporte_brasil/importers/b3_import.py',
    'aporte_brasil/importers/b3_position.py',
    'aporte_brasil/importers/brokerage_notes.py',
    'aporte_brasil/importers/csv_import.py',
    'aporte_brasil/importers/pluggy_connector.py',
    'aporte_brasil/importers/research_exchange.py',
    'aporte_brasil/importers/treasury_import.py',
    'aporte_brasil/market/__init__.py',
    'aporte_brasil/market/bayesian_signals.py',
    'aporte_brasil/market/benchmark_prices.py',
    'aporte_brasil/market/extra_sources.py',
    'aporte_brasil/market/international_market.py',
    'aporte_brasil/market/market.py',
    'aporte_brasil/market/market_brief.py',
    'aporte_brasil/market/market_monitor.py',
    'aporte_brasil/market/market_news.py',
    'aporte_brasil/market/market_outlook.py',
    'aporte_brasil/market/market_research.py',
    'aporte_brasil/market/market_signals.py',
    'aporte_brasil/market/price_context.py',
    'aporte_brasil/market/recommendation_signals.py',
    'aporte_brasil/market/us_market.py',
    'aporte_brasil/portfolio/__init__.py',
    'aporte_brasil/portfolio/asset_correlation.py',
    'aporte_brasil/portfolio/contrarian.py',
    'aporte_brasil/portfolio/contribution_context.py',
    'aporte_brasil/portfolio/fixed_income.py',
    'aporte_brasil/portfolio/fixed_position.py',
    'aporte_brasil/portfolio/holdings.py',
    'aporte_brasil/portfolio/investment_decision.py',
    'aporte_brasil/portfolio/investment_exposure.py',
    'aporte_brasil/portfolio/investment_risk.py',
    'aporte_brasil/portfolio/investment_value.py',
    'aporte_brasil/portfolio/long_term.py',
    'aporte_brasil/portfolio/portfolio_coupling.py',
    'aporte_brasil/portfolio/portfolio_review.py',
    'aporte_brasil/portfolio/portfolio_strategy.py',
    'aporte_brasil/portfolio/sector_analysis.py',
    'aporte_brasil/portfolio/tax_rules.py',
    'aporte_brasil/portfolio/tesouro.py',
    'app.py',
}

ROOT_FILES.add('LONGO_PRAZO.md')

ANDROID_FILES={
    'android/settings.gradle.kts',
    'android/build.gradle.kts',
    'android/gradle.properties',
    'android/gradlew.bat',
    'android/prepare-wrapper.ps1',
    'android/gradle/wrapper/gradle-wrapper.properties',
    'android/app/build.gradle.kts',
    'android/app/src/main/AndroidManifest.xml',
    'android/app/src/main/java/br/aporte/app/MainActivity.kt',
    'android/app/src/main/python/android_entry.py',
    'android/app/src/main/res/values/styles.xml',
    'android/app/src/main/res/values-night/styles.xml',
    'android/app/src/main/res/xml/network_security_config.xml',
}

# The shortcut icons are binary. Match their reviewed bytes at the exact paths.
# Keep previous digests when replacing an icon so existing history still passes.
SHORTCUT_ICONS={
    'packaging/abrir-aporte.ico': {'e89ff946df0115cacd642f2544b780b132e4dd1ed251f7e9acb8ec1e51686f48'},
    'packaging/reiniciar-aporte.ico': {'836861556b930290efaacba8599457a26b4067f04c03f0b373fcb86fdbaaf7b8'},
}

# Layout anterior (modulos soltos na raiz): so e aceito ao auditar o historico ja publicado.
LEGACY_ROOT_MODULES={n.rsplit('/',1)[1] for n in MODULES if n.count('/')==2 and not n.endswith('__init__.py')}

# Ensaios dependentes de bases locais ou de ferramentas offline nao publicadas.
LOCAL_TESTS={'test_installer.py','test_model_comparison.py','test_company_history.py',
             'test_long_term_models.py','test_model_agreement.py','test_replay_models.py'}

def allowed(name,history=False):
    path=PurePosixPath(name)
    if name in ROOT_FILES|MODULES|ANDROID_FILES or name in SHORTCUT_ICONS or history and name in LEGACY_ROOT_MODULES:return True
    if '..' in path.parts or len(path.parts)!=2:return False
    parent,base=path.parts
    return (parent=='static' and path.suffix in ('.html','.css','.js','.svg')
        or parent=='tests' and base.startswith('test_') and not base.endswith('_live.py') and base not in LOCAL_TESTS and path.suffix=='.py'
        or parent=='tools' and base in ('check_git_safety.py','export_source.py','build_windows.ps1','runtime_probe.py','prepare_runtime.py','build_installer.py','create_desktop_shortcuts.ps1')
        or parent=='packaging' and base in ('Instalar.cmd','Uninstall.ps1','LEIA-ME.txt')
        or parent=='.githooks' and base in ('pre-commit','pre-push'))

def run(*args):return subprocess.check_output(['git',*args])

# Only report the location/type of a finding, never its secret value.
SENSITIVE=(
    ('credencial', re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')),
    ('caminho pessoal', re.compile(rb'(?i)(?:[A-Z]:[/\\]Users[/\\]|/Users/|/home/)[A-Za-z0-9_.-]+[/\\]')),
    ('email pessoal', re.compile(rb'(?i)[A-Za-z0-9_.+-]+@(?:gmail|hotmail|outlook|yahoo|icloud|protonmail)\.[A-Za-z.]+')),
)

def content_problem(data,name=''):
    if name in SHORTCUT_ICONS:
        return None if sha256(data).hexdigest() in SHORTCUT_ICONS[name] else 'icone diferente dos arquivos revisados'
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
        problem=problem or ('fora da lista de arquivos de codigo permitidos' if not allowed(name,history) else content_problem(data,name))
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
