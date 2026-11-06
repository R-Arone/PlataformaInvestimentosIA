"""Aporte Brasil: local portfolio research with encrypted private storage."""
from __future__ import annotations
import argparse
from contextlib import contextmanager, closing
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import statistics
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import hashlib
import time
import sys
from http.cookies import SimpleCookie
import private_storage
from market import (ASSET_TYPES, FIXED_TYPES, INSTITUTIONS, BASE_SECTORS, SOURCE_URLS,
                    normalize_catalog, fetch_catalog, fetch_fii, fetch_fii_vacancy, fetch_bitcoin, fetch_sentiment,
                    source_href, fx_projection)
import sector_analysis
import public_fundamentals
import tax_rules
import market_brief
import market_outlook
import market_ai
import extra_sources
import valuation
import research_exchange
import investment_exposure
import company_research
import factor_analysis
import fii_research
import international_market
import history_cache
import portfolio_strategy
import long_term
import investment_value
import investment_risk
import contrarian
import holdings
import portfolio_coupling
import market_signals
import model_comparison
import market_monitor
import stock_fundamentals
import market_news
import us_market
import lifecycle
import installer_builder
import tesouro

ROOT = Path(__file__).absolute().parent
DB_PATH = Path(os.environ.get('APORTE_DB', str(private_storage.data_dir() / 'carteira.sqlite3')))
VAULT = None  # Unit tests use temporary plain SQLite; main() always enables the vault.
APP_VERSION = 14
INSTALLER = installer_builder.Builder(ROOT)
INSTANCE_ID = secrets.token_hex(16)
CSRF = secrets.token_urlsafe(32)
REQUEST_LOCK = threading.RLock()
WRITE_LOCK = threading.RLock()
REFRESH_LOCK = threading.Lock()
PENDING_REFRESH = set()
JOB = {'running': False, 'progress': '', 'errors': [], 'finished_at': None}
CSV_PREVIEWS = {}
KINDS = ('quote', 'statistics', 'financial', 'history', 'us_quote', 'us_history', 'risk', 'public')+company_research.KINDS+fii_research.KINDS+international_market.KINDS+stock_fundamentals.KINDS+tuple('metric:'+k for k in sector_analysis.METRICS)
SNAPSHOT_FIELDS = {'quote': ('price', 'change'), 'statistics': ('pvp', 'pe', 'dy','nav','dividends_per_share','eps','bvps'),
                  'financial': ('roe', 'net_debt_ebitda', 'current_ratio', 'operating_margin',
                                'operating_cashflow', 'free_cashflow', 'debt_equity', 'net_debt_equity', 'roic', 'interest_coverage','eps','bvps','payout'),
                  'risk': tuple(sector_analysis.METRICS), 'public':tuple(sector_analysis.METRICS)}
SNAPSHOT_FIELDS.update({'metric:'+k:(k,) for k in sector_analysis.METRICS})
DEFAULTS = {'profile': 'Longo prazo · maior tolerância a oscilações', 'asset_limit': 20,
            'sector_limit': 40, 'equity_target': 60, 'risk_premium': 5,
            'sectors': [], 'auto_refresh': True, 'sector_rules': {},
            'allocation_targets':None,'allocation_overrides':{},'expensive_alert_percent':30,
            'model_average_enabled':False,'color_mode':'standard'}


def now():
    return datetime.now(timezone.utc).isoformat()


def today():
    # Brazilian dates, independent of the host's timezone.
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


@contextmanager
def connect():
    if VAULT is not None:
        with VAULT.connect() as c:yield c
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        with c:
            yield c
    finally:
        c.close()


def backup_db(c,stem):
    if VAULT is not None:return VAULT.backup(c,stem)
    target=DB_PATH.parent/(stem+'.sqlite3')
    with closing(sqlite3.connect(target)) as destination:c.backup(destination)
    return target


def init_db():
    global CSRF
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
          CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY, ticker TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, sector TEXT NOT NULL DEFAULT 'Não classificado',
            financial INTEGER NOT NULL DEFAULT 0 CHECK(financial IN (0,1)),
            notes TEXT NOT NULL DEFAULT '');
          CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL REFERENCES assets(id),
            side TEXT NOT NULL CHECK(side IN ('buy','sell')),
            quantity REAL NOT NULL CHECK(quantity>0), price REAL NOT NULL CHECK(price>0),
            fees REAL NOT NULL DEFAULT 0 CHECK(fees>=0), date TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS idx_trades_asset ON trades(asset_id, date, id);
          CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, data TEXT NOT NULL, source TEXT NOT NULL,
            asof TEXT NOT NULL, retrieved_at TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS idx_snapshots_asset_kind ON snapshots(asset_id,kind,id DESC);
          CREATE TABLE IF NOT EXISTS fixed (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
            invested REAL NOT NULL CHECK(invested>=0), balance REAL NOT NULL CHECK(balance>=0),
            balance_date TEXT NOT NULL, indexer TEXT NOT NULL, rate REAL NOT NULL,
            tax REAL NOT NULL CHECK(tax BETWEEN 0 AND 100), fee REAL NOT NULL CHECK(fee>=0),
            maturity TEXT NOT NULL DEFAULT '', liquidity TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '');
          CREATE TABLE IF NOT EXISTS macro (
            key TEXT PRIMARY KEY, value REAL NOT NULL, asof TEXT NOT NULL,
            source TEXT NOT NULL, retrieved_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS runtime (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS catalog (
            ticker TEXT PRIMARY KEY, name TEXT NOT NULL, asset_type TEXT NOT NULL,
            sector TEXT NOT NULL, financial INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL, retrieved_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS source_log (
            key TEXT PRIMARY KEY, label TEXT NOT NULL, url TEXT NOT NULL, status TEXT NOT NULL,
            asof TEXT NOT NULL, retrieved_at TEXT NOT NULL, error TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sentiment (
            date TEXT PRIMARY KEY, value REAL NOT NULL CHECK(value BETWEEN 0 AND 100),
            classification TEXT NOT NULL, retrieved_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS imported_rows (
            fingerprint TEXT PRIMARY KEY, kind TEXT NOT NULL, record_id INTEGER NOT NULL,
            created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, kind TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount>0), date TEXT NOT NULL, institution TEXT NOT NULL,
            amount_basis TEXT NOT NULL CHECK(amount_basis IN ('reported','net','gross')),
            notes TEXT NOT NULL DEFAULT '', source TEXT NOT NULL);
        ''')
        additions = {'assets': {'asset_type': "TEXT NOT NULL DEFAULT 'stock'", 'verified': 'INTEGER NOT NULL DEFAULT 0',
                               'research_profile': "TEXT NOT NULL DEFAULT 'auto'", 'archived':'INTEGER NOT NULL DEFAULT 0',
                               'auto_sector':'INTEGER NOT NULL DEFAULT 0 CHECK(auto_sector IN (0,1))'},
                     'trades': {'institution': "TEXT NOT NULL DEFAULT 'Não informada'"},
                     'fixed': {'institution': "TEXT NOT NULL DEFAULT 'Não informada'",
                               'issuer': "TEXT NOT NULL DEFAULT ''", 'cnpj': "TEXT NOT NULL DEFAULT ''",
                               'source_url': "TEXT NOT NULL DEFAULT ''", 'metadata': "TEXT NOT NULL DEFAULT '{}'",
                               'invested_known': 'INTEGER NOT NULL DEFAULT 1', 'conditions_known': 'INTEGER NOT NULL DEFAULT 1', 'archived':'INTEGER NOT NULL DEFAULT 0'}}
        old_schema = {r['name'] for r in c.execute('PRAGMA table_info(assets)')}
        if 'archived' not in old_schema and (c.execute('SELECT 1 FROM assets LIMIT 1').fetchone() or c.execute('SELECT 1 FROM fixed LIMIT 1').fetchone()):
            backup_db(c,'antes-atualizacao-v4-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        if 'research_profile' not in old_schema and (c.execute('SELECT 1 FROM assets LIMIT 1').fetchone() or c.execute('SELECT 1 FROM fixed LIMIT 1').fetchone()):
            backup_db(c,'antes-atualizacao-v3-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        if 'asset_type' not in old_schema and (c.execute('SELECT 1 FROM assets LIMIT 1').fetchone() or c.execute('SELECT 1 FROM fixed LIMIT 1').fetchone()):
            backup_db(c,'antes-atualizacao-v2-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        for table, fields in additions.items():
            present = {r['name'] for r in c.execute('PRAGMA table_info('+table+')')}
            for name, declaration in fields.items():
                if name not in present:
                    c.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+declaration)
        bootstrap = ROOT / 'data' / 'catalog-bootstrap.json'
        if not c.execute('SELECT 1 FROM catalog LIMIT 1').fetchone() and bootstrap.exists():
            try:
                seed = json.loads(bootstrap.read_text(encoding='utf-8'))
                store_catalog(c, normalize_catalog(seed['payload'], seed['retrieved_at']))
            except (ValueError, KeyError, OSError):
                pass
        for k, v in DEFAULTS.items():
            c.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (k, json.dumps(v)))
        # Keep the local form nonce across restarts; it is never included in exports.
        nonce = c.execute("SELECT value FROM runtime WHERE key='form_nonce'").fetchone()
        if nonce:
            CSRF = nonce['value']
        else:
            c.execute("INSERT INTO runtime VALUES ('form_nonce',?)", (CSRF,))
        c.execute('PRAGMA optimize')
        last_attempt = c.execute("SELECT value FROM runtime WHERE key='last_market_attempt'").fetchone()
        if last_attempt and not JOB['finished_at']:
            JOB['finished_at'] = last_attempt['value']
            last_errors = c.execute("SELECT value FROM runtime WHERE key='last_market_errors'").fetchone()
            if last_errors:
                try:
                    JOB['errors'] = json.loads(last_errors['value'])
                except ValueError:
                    JOB['errors'] = []


def number(v, required=False, low=None, high=None):
    if v in (None, ''):
        if required:
            raise ValueError('Preencha os campos numéricos obrigatórios.')
        return None
    try:
        n = float(v)
    except (ValueError, TypeError):
        raise ValueError('Número inválido. Use o campo numérico, sem símbolos.')
    if not math.isfinite(n) or abs(n) > 1e15:
        raise ValueError('Número fora do intervalo permitido.')
    if low is not None and n < low or high is not None and n > high:
        raise ValueError('Número fora do intervalo permitido.')
    return n


def text_value(v, limit=300, required=False):
    if not isinstance(v, str) or len(v) > limit:
        raise ValueError('Texto inválido ou muito longo.')
    v = v.strip()
    if required and not v:
        raise ValueError('Preencha os campos obrigatórios.')
    return v


def valid_date(v, optional=False):
    if optional and not v:
        return ''
    if not isinstance(v, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', v):
        raise ValueError('Data inválida.')
    d = date.fromisoformat(v)
    return d.isoformat()


def age(v):
    try:
        return max(0, (today() - date.fromisoformat(v[:10])).days)
    except (ValueError, TypeError):
        return 99999


def settings(c):
    return {r['key']: json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}


def position(trades):
    pools = {}
    for t in sorted(trades, key=lambda x: (x['date'], x['id'])):
        bank = t.get('institution') or 'Não informada'
        pool = pools.setdefault(bank, {'institution': bank, 'quantity': 0.0, 'cost': 0.0, 'realized': 0.0})
        qty, cost, realized = pool['quantity'], pool['cost'], pool['realized']
        q, p, f = t['quantity'], t['price'], t['fees']
        if t['side'] == 'buy':
            qty += q
            cost += q * p + f
        else:
            if q > qty + 1e-12:
                raise ValueError('A venda excede a posição disponível nessa data.')
            avg = cost / qty if qty else 0
            realized += q * (p - avg) - f
            qty -= q
            cost -= q * avg
            if qty < 1e-12:
                qty = cost = 0.0
        pool.update(quantity=qty, cost=cost, realized=realized, average=cost/qty if qty else 0)
    qty = sum(p['quantity'] for p in pools.values())
    cost = sum(p['cost'] for p in pools.values())
    return {'quantity': qty, 'cost': cost, 'average': cost/qty if qty else 0,
            'realized': sum(p['realized'] for p in pools.values()), 'institutions': list(pools.values())}


def latest(c, asset_id):
    result = {}
    for k in KINDS:
        r = c.execute('SELECT * FROM snapshots WHERE asset_id=? AND kind=? ORDER BY id DESC LIMIT 1',
                      (asset_id, k)).fetchone()
        if r:
            result[k] = {**dict(r), 'data': json.loads(r['data'])}
    return result


def trend(history):
    pts = sorted(history.get('prices', []), key=lambda p: p['date'])
    prices = [p['close'] for p in pts if p.get('close', 0) > 0]
    result = {'count': len(prices), 'label': 'Histórico insuficiente', 'score': None,
              'ma50': None, 'ma200': None, 'return63': None, 'volatility': None}
    if len(prices) >= 64:
        result['return63'] = (prices[-1] / prices[-64] - 1) * 100
        rr = [math.log(b / a) for a, b in zip(prices, prices[1:])]
        result['volatility'] = statistics.stdev(rr[-252:]) * math.sqrt(252) * 100
    if len(prices) >= 200:
        m50, m200 = statistics.mean(prices[-50:]), statistics.mean(prices[-200:])
        result.update(ma50=m50, ma200=m200)
        result['score'] = (50 if prices[-1] > m200 else 0) + (50 if m50 > m200 else 0)
        result['label'] = {0: 'Baixa', 50: 'Mista', 100: 'Alta'}[result['score']]
    return result


def analysis(assets, cfg, macros):
    total = sum(a['value'] for a in assets if a['position']['quantity'] > 0)
    sector_totals = {}
    for a in assets:
        sector_totals[a['sector']] = sector_totals.get(a['sector'], 0) + a['value']
    for a in assets:
        s = a['metrics']
        research_profile = sector_analysis.profile(a)
        f = research_profile in ('bank','insurance','financial_services')
        debt_limit = cfg.get('sector_rules',{}).get(research_profile,{}).get('net_debt_ebitda',sector_analysis.PROFILES[research_profile]['limits'].get('net_debt_ebitda',3))
        typ = a.get('asset_type', 'stock')
        if typ != 'stock':
            a.update(peer_pvp=None, peer_pe=None, peer_count=0, weight=a['value']/total*100 if total else 0,
                     sector_weight=sector_totals.get(a['sector'], 0)/total*100 if total else 0,
                     earnings_yield=None, yield_spread=None)
            reason = {'etf': 'ETF: avaliar índice, custo, liquidez e diversificação; P/L e ROE da empresa não se aplicam.',
                      'fii': 'FII: comparar P/VP e DY com fundos do mesmo segmento; revisar vacância, renda e carteira.',
                      'crypto': 'Bitcoin: observar risco e sentimento; não possui balanço nem múltiplos fundamentalistas.',
                      'bdr':'BDR: suporte básico em reais; comparar moeda, custos, custódia e tributação. Integração de fundamentos será posterior.',
                      'global_stock':'Stock internacional: use critérios do setor, balanços na moeda informada e cotação nativa. Não recebe o ranking brasileiro.',
                      'global_etf':'ETF internacional: conferir área, índice, custo, domicílio, moeda e composição; não recebe critérios de lucro e dívida de empresas.',
                      'foreign':'Stocks dos EUA têm comparação própria em USD; consulte a página Stocks dos EUA. O ranking brasileiro e seus juros não são aplicados a elas.'}[typ]
            a['analysis'] = {'score': None, 'problems': [reason], 'reasons': [reason],
                             'action': 'Análise por tipo de ativo'}
            continue
        problems, reasons = [], []
        pvp, pe, roe, debt = (s.get(k) for k in ('pvp', 'pe', 'roe', 'net_debt_ebitda'))
        peers = [b for b in assets if b['sector'].casefold() == a['sector'].casefold()
                 and b.get('asset_type', 'stock') == 'stock'
                 and b['ticker'][:4] != a['ticker'][:4] and b['metrics'].get('pvp', 0) is not None
                 and (b['metrics'].get('pvp') or 0) > 0 and (b['metrics'].get('pe') or 0) > 0
                 and age(b['snapshots'].get('statistics', {}).get('asof', '')) <= 180]
        # One share class per issuer, so multiple tickers do not inflate the peer sample.
        peers = list({b['ticker'][:4]: b for b in peers}.values())
        med_pvp = statistics.median([b['metrics']['pvp'] for b in peers]) if peers else None
        med_pe = statistics.median([b['metrics']['pe'] for b in peers]) if peers else None
        a['peer_pvp'], a['peer_pe'], a['peer_count'] = med_pvp, med_pe, len(peers)
        if pvp is None or pvp <= 0:
            problems.append('P/VP ausente ou patrimônio não positivo')
        if pe is None or pe <= 0:
            problems.append('P/L ausente ou lucro não positivo')
        if roe is None or roe <= 0:
            problems.append('ROE ausente ou não positivo')
        if not f and debt is None:
            problems.append('Dívida líquida/EBITDA ausente')
        if not f and debt is not None and debt > debt_limit:
            problems.append(f'Alavancagem acima do limite de estudo deste perfil ({debt_limit:g}×) exige revisão')
        if f:
            problems.append('Instituição financeira: revisar capital, inadimplência e provisões')
        if not peers or a['sector'] == 'Não classificado':
            problems.append('Adicione ao menos outra empresa comparável do mesmo setor')
        if age(a['snapshots'].get('quote', {}).get('asof', '')) > 7:
            problems.append('Cotação ausente ou com mais de 7 dias')
        for kind in ('statistics', 'financial'):
            if age(a['snapshots'].get(kind, {}).get('asof', '')) > 180:
                problems.append('Indicadores ausentes ou com mais de 180 dias')
        if a['trend']['score'] is None or age(a['snapshots'].get('history', {}).get('asof', '')) > 7:
            problems.append('Tendência requer 200 pregões e histórico recente')
        if pvp and pvp > 0 and med_pvp:
            reasons.append(f'P/VP {pvp:.2f}× vs. mediana dos pares {med_pvp:.2f}×')
        if pe and pe > 0 and med_pe:
            reasons.append(f'P/L {pe:.2f}× vs. mediana dos pares {med_pe:.2f}×')
        if roe is not None:
            reasons.append(f'ROE {roe:.1f}%')
        if debt is not None and not f:
            reasons.append(f'Dívida líquida/EBITDA {debt:.2f}×')
        a['weight'] = a['value'] / total * 100 if total else 0
        a['sector_weight'] = sector_totals.get(a['sector'], 0) / total * 100 if total else 0
        if a['position']['quantity'] and a['weight'] >= cfg['asset_limit']:
            problems.append('Posição já alcançou o limite por ação dentro da renda variável')
        if a['sector_weight'] >= cfg['sector_limit']:
            problems.append('Setor já alcançou o limite dentro da renda variável')
        a['earnings_yield'] = 100 / pe if pe and pe > 0 else None
        selic = macros.get('selic', {}).get('value')
        a['yield_spread'] = a['earnings_yield'] - selic if a['earnings_yield'] is not None and selic is not None else None
        if a['yield_spread'] is not None and a['yield_spread'] < cfg['risk_premium']:
            reasons.append('Lucro/preço abaixo de Selic + prêmio configurado; investigar crescimento e ciclo')
        score = None
        # This is a research ordering, not an expected-return model.
        if not problems:
            valuation = 50 * min(1, med_pvp / pvp) + 50 * min(1, med_pe / pe)
            quality = 60 * min(1, roe / 20) + 40 * max(0, min(1, (debt_limit - debt) / (debt_limit or 1)))
            score = round(.45 * valuation + .35 * quality + .20 * a['trend']['score'], 1)
        a['analysis'] = {'score': score, 'problems': list(dict.fromkeys(problems)), 'reasons': reasons,
                         'action': 'Estudar reforço' if a['position']['quantity'] else 'Estudar entrada'}
    return assets


def state():
    with connect() as c:
        cfg = settings(c)
        macros = {r['key']: dict(r) for r in c.execute('SELECT * FROM macro')}
        assets = []
        for r in c.execute('SELECT * FROM assets WHERE archived=0 ORDER BY ticker'):
            a = dict(r)
            a['trades'] = [dict(t) for t in c.execute('SELECT * FROM trades WHERE asset_id=? ORDER BY date,id', (a['id'],))]
            openings={r['record_id'] for r in c.execute("SELECT record_id FROM imported_rows WHERE kind='positions'")}
            for t in a['trades']:
                if t['id'] in openings:t['opening']=True
            a['position'] = position(a['trades'])
            a['provider_references']=read_cache(c,'provider_references',{}).get(str(a['id']),[])
            a['snapshots'] = latest(c, a['id'])
            us_market.enrich(sys.modules[__name__],c,a)
            international_market.enrich(a)
            stock_fundamentals.enrich(a,age)
            a['history_info']=history_cache.info(a['snapshots'].get('history'))
            a['fundamental_history']=history_cache.observations(__import__(__name__),c,a['id'])
            for kind, snapshot in a['snapshots'].items():
                if kind in company_research.KINDS+fii_research.KINDS:
                    snapshot['url'] = snapshot['data'].get('source_url') or snapshot['data'].get('url') or ''
                elif kind in stock_fundamentals.KINDS:
                    snapshot['url']=snapshot['data']['source_url']
                elif a['asset_type'] in international_market.TYPES and (kind in international_market.KINDS or snapshot['source'].startswith('Yahoo Finance')):
                    snapshot['url']=a['international']['composition_url'] if kind=='international_listing' else 'https://finance.yahoo.com/quote/'+(snapshot['data'].get('symbol',a['ticker']))+'/'
                else:
                    snapshot['url'] = source_href(a, kind) if snapshot['source'].startswith(('brapi', 'Coinbase')) else extra_sources.source_url(snapshot['source'],a['ticker'])
            metrics = {}
            for k in ('quote', 'statistics', 'financial'):
                metrics.update(a['snapshots'].get(k, {}).get('data', {}))
            a['metrics'] = metrics
            a['sector_metrics']={}
            for key in sector_analysis.METRICS:
                v,snapshot,reason=sector_analysis.metric(a,key,age)
                if snapshot:
                    a['sector_metrics'][key]={'value':v,'asof':snapshot['asof'],'source':snapshot['source'],'retrieved_at':snapshot['retrieved_at'],'reason':reason,'currency':snapshot.get('data',{}).get('currency')}
                if v is not None:
                    metrics[key]=v
            a['trend'] = trend(a['snapshots'].get('history', {}).get('data', {}))
            a['value_at_cost'] = metrics.get('price') is None
            a['value'] = a['position']['cost'] if a['value_at_cost'] else a['position']['quantity'] * metrics['price']
            a['gain'] = None if a['value_at_cost'] else a['value'] - a['position']['cost']
            for p in a['position']['institutions']:
                p['value'] = p['cost'] if a['value_at_cost'] else p['quantity']*metrics['price']
            a['quote_history'] = [{'date': r['asof'], 'price': json.loads(r['data']).get('price'),
                                   'retrieved_at': r['retrieved_at']}
                for r in c.execute("SELECT asof,data,retrieved_at FROM snapshots WHERE asset_id=? AND kind='quote' ORDER BY id DESC LIMIT 90", (a['id'],))][::-1]
            assets.append(a)
        saved_exposures=read_cache(c,'investment_exposures',{})
        for a in assets:
            a['exposure']=investment_exposure.metadata(a,saved_exposures)
            if a['asset_type']=='etf' and a['exposure'].get('asset_class')!='unknown' and (a['sector'] in ('ETF','Não classificado') or a['sector'].startswith('ETF ·')):
                a['sector']=investment_exposure.etf_sector(a)
        public_cfg = {k: v for k, v in cfg.items() if k != 'brapi_token'}
        public_cfg['has_token'] = bool(cfg.get('brapi_token') or os.getenv('BRAPI_TOKEN'))
        sector_options = sorted(set(BASE_SECTORS + [r['sector'] for r in c.execute('SELECT DISTINCT sector FROM catalog')] + [a['sector'] for a in assets] + cfg['sectors']))
        catalog_count = c.execute('SELECT COUNT(*) AS n FROM catalog').fetchone()['n']
        catalog_date = c.execute('SELECT MAX(retrieved_at) AS t FROM catalog').fetchone()['t']
        assets = sector_analysis.analyze(analysis(assets, public_cfg, macros), public_cfg, macros, age)
        for a in assets:
            critical = [r for r in a['sector_analysis']['checks'] if r['status']=='fail' and r['metric'] in ('net_debt_ebitda','debt_equity','interest_coverage','current_ratio','operating_cashflow','basel','solvency')]
            if a['sector_analysis']['profile']=='retail':
                critical += [r for r in a['sector_analysis']['checks'] if r['metric']=='lease_consistent' and r['status']!='pass']
            if critical:
                a['analysis']['score']=None
                a['analysis']['problems'] += ['Revisar critério por setor: '+r['label'] for r in critical]
            if a['asset_type']=='stock':
                a['valuation']=valuation.for_asset(a,read_cache(c,'valuation_cases',{}).get(a['ticker'],{}),number,age)
                a['valuation_alert']=valuation.alert(a,cfg['expensive_alert_percent'])
            a['indicator_coverage']=sector_analysis.coverage(a,age)
            company_research.enrich(sys.modules[__name__],a)
            fii_research.enrich(sys.modules[__name__],a,c)
            a['value_reading']=investment_value.reference(sys.modules[__name__],a,read_cache(c,'valuation_cases',{}))
            a['sector_rating']=investment_risk.rating(a)
            a['risk_group']=investment_risk.group(a)
            a.pop('_statement_metrics', None)
            a.pop('_fii_metrics', None)
        factor_analysis.enrich(sys.modules[__name__], assets)
        fixed = [dict(r) for r in c.execute('SELECT * FROM fixed WHERE archived=0 ORDER BY name')]
        tesouro_market = read_cache(c,'tesouro_market',{})
        for f in fixed:
            f['metadata'] = json.loads(f['metadata'])
            f['rate_known']=holdings.rate_known(f)
            tesouro.enrich(f,tesouro_market,today())
        signal_state=market_signals.public_state(sys.modules[__name__],c,assets)
        us_state=us_market.public_state(sys.modules[__name__],c,assets)
        us_state['candidates']={str(h):us_market.rank(assets,signal_state,h) for h in market_signals.HORIZONS}
        ai_state=market_ai.public_state(sys.modules[__name__],c,assets,fixed)
        news_feeds=read_cache(c,'news_reports',{})
        for a in assets:
            if a.get('company_research'):
                a['company_research']['news_context']=company_research.company_history.company_insights.news_context(
                    sys.modules[__name__],a,news_feeds,ai_state['sentiment'])
            if a.get('fii_research'):
                a['fii_research']['news_context']=company_research.company_history.company_insights.news_context(
                    sys.modules[__name__],a,news_feeds,ai_state['sentiment'])
        return {'assets': assets,
                'contribution_context':contrarian.public_state(sys.modules[__name__],read_cache(c,contrarian.CACHE,{})),
                'market_research':read_cache(c,'market_batch',None),
                'exposure_areas':investment_exposure.areas(assets,fixed,saved_exposures,age),
                'exposure_themes':investment_exposure.THEMES,
                'issuer_auto':read_cache(c,'issuer_auto',True),
                'coupling':portfolio_coupling.analyze(assets,fixed,today(),now()),
                'signals':signal_state,
                'us_market':us_state,
                'allocation':portfolio_strategy.allocation(assets,fixed,public_cfg,age),
                'allocation_classes':portfolio_strategy.CLASSES,
                'import_receipts':read_cache(c,'import_receipts',[])[-50:][::-1],
                'history_storage_bytes':c.execute("SELECT COALESCE(SUM(LENGTH(CAST(data AS BLOB))),0) FROM snapshots WHERE kind='history'").fetchone()[0],
                'archived_assets':[dict(r) for r in c.execute('SELECT id,ticker,name,sector,asset_type FROM assets WHERE archived=1 ORDER BY ticker')],
                'fixed': fixed, 'tesouro': tesouro.public_state(tesouro_market),
                'archived_fixed':[dict(r) for r in c.execute('SELECT id,name,type,institution FROM fixed WHERE archived=1 ORDER BY name')],
                'income': [dict(r) for r in c.execute('SELECT * FROM income ORDER BY date DESC,id DESC')],
                'research': {'profiles': sector_analysis.PROFILES, 'metrics': sector_analysis.METRICS, 'indicator_info':sector_analysis.INDICATOR_INFO,
                             'references': sector_analysis.REFERENCES,
                             'company_profiles':sector_analysis.COMPANY_PROFILES,
                             'nonfinancial_profiles':sector_analysis.NONFINANCIAL_PROFILES},
                'health_guide':sector_analysis.health_guide(public_cfg),
                'research_reports':read_cache(c,'research_reports',[]),
                'valuation_cases':read_cache(c,'valuation_cases',{}),
                'tax_references':tax_rules.references(),
                'brazil_benchmarks':read_cache(c,'brazil_benchmarks',{}),
                'news_scenarios':read_cache(c,'news_scenarios',{}),
                'ai':ai_state,
                'monitor':market_monitor.public_state(sys.modules[__name__],c),
                'market_overview':market_monitor.status()['market'] or market_news.overview(
                    read_cache(c,'news_reports',{}).get('general',{}),read_cache(c,'ai_sentiment',{}).get('general'),datetime.now(timezone.utc)),
                'news_reports':{k:market_brief.brief(v,assets,macros,public_cfg,today()) for k,v in news_records(c).items()},
                'macro': macros, 'settings': public_cfg, 'job': dict(JOB), 'csrf': CSRF, 'today': today().isoformat(),
                'security': {'encrypted':VAULT is not None,'version':APP_VERSION,'idle_minutes':private_storage.IDLE_SECONDS//60,
                             'legacy_files':len(VAULT.old_files()) if VAULT is not None else 0},
                'sectors': sector_options, 'asset_types': ASSET_TYPES, 'international_market':international_market.public_state(), 'fixed_types': FIXED_TYPES,
                'institutions': sorted(set(INSTITUTIONS+[r['institution'] for r in c.execute('SELECT DISTINCT institution FROM trades')]+[r['institution'] for r in c.execute('SELECT DISTINCT institution FROM fixed')])),
                'catalog': {'count': catalog_count, 'retrieved_at': catalog_date},
                'sentiment': [dict(r) for r in c.execute('SELECT * FROM sentiment ORDER BY date DESC LIMIT 90')][::-1],
                'sources': [dict(r) for r in c.execute('SELECT * FROM source_log ORDER BY label')]}


def add_snapshot(c, asset_id, kind, data, source, asof):
    encoded=json.dumps(data, ensure_ascii=False, allow_nan=False)
    # Repeated public queries update the consultation date, not the stored series.
    automatic=source.startswith(('brapi','Yahoo Finance','Fundamentus','Coinbase','Status Invest','Investidor10'))
    if automatic:
        old=c.execute('SELECT * FROM snapshots WHERE asset_id=? AND kind=? AND source=? ORDER BY id DESC LIMIT 1',(asset_id,kind,source)).fetchone()
        newest=c.execute('SELECT MAX(id) FROM snapshots WHERE asset_id=? AND kind=?',(asset_id,kind)).fetchone()[0]
        if old and old['id']==newest and old['data']==encoded and old['asof']==asof:
            c.execute('UPDATE snapshots SET retrieved_at=? WHERE id=?',(now(),old['id']));return
        if kind in ('history','us_history'):
            # One complete adjusted window replaces the previous window from this source.
            # Do not stitch adjusted and unadjusted vintages across corporate actions.
            c.execute('DELETE FROM snapshots WHERE asset_id=? AND kind=? AND source=?',(asset_id,kind,source))
        elif old and old['asof']==asof and old['retrieved_at'][:10]==now()[:10]:
            c.execute('UPDATE snapshots SET data=?,asof=?,retrieved_at=? WHERE id=?',(encoded,asof,now(),old['id']));return
    c.execute('INSERT INTO snapshots(asset_id,kind,data,source,asof,retrieved_at) VALUES (?,?,?,?,?,?)',
              (asset_id, kind, encoded, source, asof, now()))

def read_cache(c,key,default):
    row=c.execute('SELECT value FROM runtime WHERE key=?',(key,)).fetchone()
    try: return json.loads(row['value']) if row else default
    except ValueError: return default

def write_cache(c,key,value):
    c.execute('INSERT OR REPLACE INTO runtime VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False,allow_nan=False)))

def brazil_benchmarks():
    """Observation from a liquid, catalog-matched sample, never recommended cut-offs."""
    with connect() as c:
        cached=read_cache(c,'brazil_benchmarks',{})
        if cached and cached.get('method_version')==2 and age(cached.get('retrieved_at'))<1: return cached
        catalog={r['ticker']:dict(r) for r in c.execute("SELECT * FROM catalog WHERE asset_type='stock'")}
    rows=public_fundamentals.parse_universe(public_fundamentals.fetch_html(public_fundamentals.BASE+'resultado.php'))
    selected={}
    for row in rows:
        a=catalog.get(row['ticker'])
        if not a: continue
        if sector_analysis.profile(a) in ('bank','insurance','financial_services'):
            for k in ('net_debt_equity','current_ratio','roic','operating_margin'): row[k]=None
        issuer=row['ticker'][:4]
        if issuer not in selected or row['liquidity']>selected[issuer]['liquidity']:
            selected[issuer]={**row,'sector':a['sector']}
    groups={}
    for a in selected.values(): groups.setdefault(a['sector'],[]).append(a)
    def quantile(values,f):
        pos=(len(values)-1)*f; i=int(pos); return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(pos-i)
    result={}
    for sector,peers in groups.items():
        metrics={}
        for key in ('pvp','pe','roe','net_debt_equity','current_ratio','roic','operating_margin'):
            vals=sorted(a[key] for a in peers if a[key] is not None and (key not in ('pvp','pe') or a[key]>0))
            metrics[key]={'count':len(vals),'median':statistics.median(vals) if len(vals)>=3 else None,
                          'p25':quantile(vals,.25) if len(vals)>=3 else None,'p75':quantile(vals,.75) if len(vals)>=3 else None}
        result[sector]={'metrics':metrics,'peers':[a['ticker'] for a in peers],'count':len(peers)}
    payload={'method_version':2,'retrieved_at':now(),'source':'Fundamentus · tabela pública + catálogo B3/brapi',
       'url':public_fundamentals.BASE+'resultado.php','sectors':result,
       'method':'Ações do catálogo atual com negociação observada; uma classe por emissor, escolhida pela maior liquidez. Exclui múltiplos não positivos. Dívida/PL, liquidez corrente, ROIC e margem operacional desta tabela não são usados para instituições financeiras. Mediana e faixa de 25% a 75% exigem 3 empresas. A tabela não informa a data do balanço/cotação de cada linha; consulta recente não comprova balanço recente. Referência descritiva, não corte recomendado ou valor justo. Dívida líquida/PL não é dívida líquida/EBITDA.'}
    with WRITE_LOCK,connect() as c:
        write_cache(c,'brazil_benchmarks',payload)
        log_source(c,'brazil_benchmarks','Referência setorial Brasil · Fundamentus',payload['url'],asof=today().isoformat())
    return payload

def news_records(c):
    reports=read_cache(c,'news_reports',{});scenarios=read_cache(c,'news_scenarios',{});context=read_cache(c,'news_macro_context',{})
    return {k:{**reports.get(k,{'profile':k,'retrieved_at':None,'headlines':[],'sources':[],'errors':[],
                              'method':'Hipóteses locais. Notícias ainda não consultadas.'}),
               'macro_context':context,'scenario':scenarios.get(k,market_outlook.DEFAULT)} for k in reports.keys()|scenarios.keys()|set(read_cache(c,'news_context_profiles',[]))}

def update_news_context(force=False):
    with connect() as c:previous=read_cache(c,'news_macro_context',{})
    if not force and previous.get('consulted_date')==today().isoformat():return
    current=market_outlook.fetch_context(request_json,today(),now())
    current['consulted_date']=today().isoformat()
    # Preserve source dates when a query fails; a new retrieval never makes old data recent.
    current['observations']={**previous.get('observations',{}),**current['observations']}
    with WRITE_LOCK,connect() as c:
        write_cache(c,'news_macro_context',current)
        for key,obs in current['observations'].items():
            log_source(c,'news_context_'+key,'Cenário · '+market_outlook.FACTORS[key],obs['source_url'],asof=obs['asof'],error='; '.join(current['errors']))

def news_action(path,d):
    ident=d.get('profile','general')
    if not isinstance(ident,str) or ident not in sector_analysis.PROFILES: raise ValueError('Perfil setorial inválido.')
    if path=='/api/news/update':
        record=market_brief.fetch(ident,datetime.now(timezone.utc))
        with WRITE_LOCK,connect() as c:
            reports=read_cache(c,'news_reports',{}); reports[ident]=record; write_cache(c,'news_reports',reports)
            log_source(c,'news_'+ident,'Notícias · '+sector_analysis.PROFILES[ident]['label'],market_brief.AGENCIA,asof=today().isoformat(),error='; '.join(record['errors']))
        update_news_context()
    elif path=='/api/news/context':
        update_news_context(force=True)
        with WRITE_LOCK,connect() as c:
            profiles=read_cache(c,'news_context_profiles',[]);write_cache(c,'news_context_profiles',sorted(set(profiles)|{ident}))
    elif path=='/api/news/scenario':
        scenario=market_outlook.validate_scenario(sys.modules[__name__],{k:v for k,v in d.items() if k!='profile'})
        with WRITE_LOCK,connect() as c:
            scenarios=read_cache(c,'news_scenarios',{});scenarios[ident]=scenario;write_cache(c,'news_scenarios',scenarios)
    elif path not in ('/api/news/brief','/api/news/prompt'): raise ValueError('Consulta de notícias inválida.')
    s=state()
    if ident not in s['news_reports']:
        if path=='/api/news/context':return {'updated':True}
        raise ValueError('Consulte as notícias ou salve uma hipótese deste setor primeiro.')
    args=(s['news_reports'][ident],s['assets'],s['macro'],s['settings'],today())
    return {'prompt':market_brief.prompt(*args)} if path=='/api/news/prompt' else market_brief.brief(*args)


def log_source(c, key, label, url, status='ok', asof='', error=''):
    c.execute('INSERT OR REPLACE INTO source_log VALUES (?,?,?,?,?,?,?)',
              (key, label, url, status, asof, now(), error))


def store_catalog(c, rows):
    if not rows:
        raise ValueError('Catálogo vazio; a lista anterior foi preservada.')
    c.execute('DELETE FROM catalog')
    for r in rows:
        c.execute('INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?)',
                  tuple(r[k] for k in ('ticker', 'name', 'asset_type', 'sector', 'financial', 'source', 'retrieved_at')))
    c.execute('UPDATE assets SET verified=0 WHERE asset_type != ?', ('crypto',))
    for r in rows:
        c.execute('UPDATE assets SET asset_type=?,verified=1 WHERE ticker=?', (r['asset_type'], r['ticker']))
    log_source(c, 'catalog', 'Catálogo de ativos da B3 · brapi', SOURCE_URLS['catalog'], asof=rows[0]['retrieved_at'][:10])


def update_catalog():
    try:
        rows = fetch_catalog(request_json, now)
        with WRITE_LOCK, connect() as c:
            store_catalog(c, rows)
        return {'count': len(rows), 'retrieved_at': now()}
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Não foi possível atualizar o catálogo.'
        with WRITE_LOCK, connect() as c:
            log_source(c, 'catalog', 'Catálogo de ativos da B3 · brapi', SOURCE_URLS['catalog'], 'error', error=message)
        raise ValueError(message)


def catalog_state():
    with connect() as c:
        rows = [dict(r) for r in c.execute('SELECT * FROM catalog ORDER BY ticker')]
    return {'items': rows, 'retrieved_at': max((r['retrieved_at'] for r in rows), default=None)}


def asset_values_from_catalog(c, d):
    ticker = text_value(d.get('ticker', ''), 15, True).upper()
    if d.get('asset_type') in ('foreign','bdr',*international_market.TYPES):
        if d['asset_type']=='bdr' and not re.fullmatch(r'[A-Z][A-Z0-9]{3}\d{2}',ticker):
            raise ValueError('BDR: informe o ticker negociado na B3, como AAPL34.')
        listing=c.execute('SELECT * FROM catalog WHERE ticker=?',(ticker,)).fetchone()
        if listing and listing['asset_type']!=d['asset_type']:
            raise ValueError('Ticker já classificado como outro produto no catálogo.')
        return validate_asset(d),int(bool(listing))
    if ticker.endswith('F') and c.execute('SELECT 1 FROM catalog WHERE ticker=?',(ticker[:-1],)).fetchone():
        ticker = ticker[:-1]
    if ticker == 'BTC':
        return validate_asset({**d, 'ticker': 'BTC', 'asset_type': 'crypto', 'name': 'Bitcoin', 'sector': 'Criptoativos', 'financial': False}), 1
    listing = c.execute('SELECT * FROM catalog WHERE ticker=?', (ticker,)).fetchone()
    if not listing:
        if d.get('id') and c.execute('SELECT 1 FROM assets WHERE id=? AND ticker=?', (d['id'], ticker)).fetchone():
            return validate_asset(d), 0
        raise ValueError('Ativo não encontrado no catálogo atual da B3. Atualize o catálogo e escolha na lista.')
    typ = listing['asset_type']
    if d.get('asset_type') and d['asset_type'] != typ:
        raise ValueError('O tipo informado não corresponde ao catálogo da B3.')
    return validate_asset({**d, 'ticker': ticker, 'name': d.get('name') or listing['name'],
        'sector': d.get('sector') or listing['sector'], 'financial': d.get('financial', bool(listing['financial'])),
        'asset_type': typ}), 1


def validate_asset(d):
    ticker = text_value(d.get('ticker', ''), 15, True).upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}' if d.get('asset_type') in ('foreign',*international_market.TYPES) else r'[A-Z0-9]{3,12}', ticker):
        raise ValueError('Escolha um ativo do catálogo da B3 ou Bitcoin.')
    typ = d.get('asset_type', 'stock')
    if typ not in ASSET_TYPES or (typ == 'crypto') != (ticker == 'BTC'):
        raise ValueError('Tipo de ativo inválido.')
    financial = d.get('financial', False)
    if not isinstance(financial, (bool, int)) or financial not in (0, 1):
        raise ValueError('Classificação financeira inválida.')
    return (ticker, text_value(d.get('name', ticker), 150, True),
            text_value(d.get('sector', 'Não classificado'), 100, True), int(financial),
            text_value(d.get('notes', ''), 5000), typ)


def validate_fixed(d):
    typ, idx = d.get('type'), d.get('indexer')
    if typ not in FIXED_TYPES or idx not in ('CDI', 'Selic', 'IPCA+', 'Prefixado', 'Manual'):
        raise ValueError('Tipo ou indexador inválido.')
    balance_date = valid_date(d.get('balance_date'))
    if balance_date > today().isoformat():
        raise ValueError('O saldo informado não pode ter data futura.')
    return (text_value(d.get('name', ''), 200, True), typ,
            number(d.get('invested'), True, 0), number(d.get('balance'), True, 0), balance_date, idx,
            number(d.get('rate'), True, -50, 1000), number(d.get('tax'), True, 0, 100),
            number(d.get('fee'), True, 0, 100), valid_date(d.get('maturity'), True),
            text_value(d.get('liquidity', ''), 200), text_value(d.get('notes', ''), 5000),
            text_value(d.get('institution') or 'Não informada', 150, True),
            text_value(d.get('issuer', ''), 200), text_value(d.get('cnpj', ''), 25))


def request_json(url, token='', timeout=8):
    headers = {'Accept': 'application/json', 'User-Agent': 'AporteBrasil/1.0'}
    if url.startswith('https://query1.finance.yahoo.com/'):
        headers['User-Agent']='Mozilla/5.0 AporteBrasil/1.0'
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
            return json.loads(response.read(8_000_000))
    except urllib.error.HTTPError as exc:
        if 'api.bcb.gov.br/' in url:
            raise ValueError({400: 'Consulta de série rejeitada pelo Banco Central',
                              429: 'Banco Central limitou as consultas'}.get(exc.code, 'Banco Central indisponível'))
        raise ValueError({401: 'Chave ausente ou inválida', 403: 'Indicador não incluído no plano',
                          429: 'Limite de consultas atingido', 404: 'Ativo ou dado não encontrado',
                          400: 'Consulta não suportada pelo plano'}.get(exc.code, 'Provedor indisponível'))
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('Sem conexão com a fonte; dados anteriores preservados')


def clean(v):
    if isinstance(v, dict):
        v = v.get('raw')
    try:
        return number(v)
    except ValueError:
        return None


def fetch_stock(asset, endpoint, token):
    params = {'symbols': asset['ticker']}
    if endpoint == 'historical':
        params.update(range='1y', interval='1d', sortOrder='asc')
    url = 'https://brapi.dev/api/v2/stocks/' + endpoint + '?' + urllib.parse.urlencode(params)
    payload = request_json(url, token)
    match = next((r for r in payload.get('results', []) if r.get('requestedSymbol', r.get('symbol')) == asset['ticker']), None)
    if not match or not isinstance(match.get('data'), dict):
        raise ValueError('Resposta da fonte sem os dados solicitados')
    if match.get('symbol') != asset['ticker']:
        raise ValueError('Ticker mudou: revise a conversão antes de atualizar a posição')
    d = match['data']
    asof = today().isoformat()
    if endpoint == 'quote':
        data = {'price': clean(d.get('regularMarketPrice')), 'change': clean(d.get('regularMarketChangePercent'))}
        market_date = d.get('regularMarketTime')
        if isinstance(market_date, (int, float)):
            market_date = datetime.fromtimestamp(market_date, timezone.utc).date().isoformat()
        if not market_date:
            raise ValueError('Cotação sem data de referência')
        asof = valid_date(str(market_date)[:10])
        if asof > today().isoformat():
            raise ValueError('Fonte retornou cotação futura; dados anteriores preservados')
        if data['price'] is None or data['price'] <= 0:
            raise ValueError('Cotação não disponível')
        kind = 'quote'
    elif endpoint == 'statistics':
        data = {'pvp': clean(d.get('priceToBook')), 'pe': clean(d.get('trailingPE')),
                'dy': clean(d.get('dividendYield')), 'eps':clean(d.get('trailingEps')),
                'bvps':clean(d.get('bookValue'))}
        if data['dy'] is not None:
            data['dy'] *= 100
        period = d.get('mostRecentQuarter')
        # Require a disclosed accounting date, not merely the request date.
        if not period:
            raise ValueError('Múltiplos sem data de balanço; informe manualmente a referência')
        asof, kind = valid_date(str(period)[:10]), 'statistics'
        if asof > today().isoformat():
            raise ValueError('Fonte retornou balanço com data futura')
    elif endpoint == 'financial-data':
        data = {'roe': clean(d.get('returnOnEquity')), 'net_debt_ebitda': None}
        if data['roe'] is not None:
            data['roe'] *= 100
        data.update(current_ratio=clean(d.get('currentRatio')),
                    # v2 documents debtToEquity as a ratio, unlike legacy percentage feeds.
                    debt_equity=clean(d.get('debtToEquity')),
                    operating_margin=clean(d.get('operatingMargins')),
                    operating_cashflow=clean(d.get('operatingCashflow')),
                    free_cashflow=clean(d.get('freeCashflow')))
        if data['operating_margin'] is not None:
            data['operating_margin'] *= 100
        if d.get('financialCurrency') != 'BRL':
            data['operating_cashflow'] = data['free_cashflow'] = None
        debt, cash, ebitda = (clean(d.get(k)) for k in ('totalDebt', 'totalCash', 'ebitda'))
        if debt is not None and cash is not None and ebitda is not None and ebitda > 0:
            data['net_debt_ebitda'] = (debt - cash) / ebitda
        # Financial endpoint may not expose period; statistics date is used only if fetched in this refresh.
        asof = str(d.get('mostRecentQuarter') or d.get('endDate') or '')[:10]
        kind = 'financial'
    else:
        pts = []
        for p in d.get('historicalDataPrice', []):
            v = clean(p.get('adjustedClose'))
            # Avoid silently mixing adjusted and unadjusted time series.
            if v is None or v <= 0:
                continue
            pd = p.get('date')
            pd = datetime.fromtimestamp(pd, timezone.utc).date().isoformat() if isinstance(pd, (int, float)) else str(pd)[:10]
            if valid_date(pd) <= today().isoformat():
                pts.append({'date': pd, 'close': v})
        pts = list({p['date']: p for p in pts}.values())
        if not pts:
            raise ValueError('Histórico ajustado indisponível no plano')
        data, kind = {'prices': sorted(pts, key=lambda p: p['date'])}, 'history'
        asof = data['prices'][-1]['date']
    if not any(v is not None for v in data.values()):
        raise ValueError('Indicadores não disponíveis')
    return kind, data, asof


def refresh_worker(asset_id=None):
    errors = []
    def pull_bdr(a):
        JOB['progress'] = a['ticker']+' · cotação do BDR em reais'
        try:
            investment_exposure.refresh_bdr(sys.modules[__name__], a)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else 'Cotação do BDR indisponível; anterior preservada.'
            errors.append(a['ticker']+': '+message)
            with WRITE_LOCK, connect() as c:
                log_source(c,'bdr_'+str(a['id']),a['ticker']+' · BDR','https://finance.yahoo.com/quote/'+a['ticker']+'.SA/','error',error=message)
    try:
        with connect() as c:
            cfg = settings(c)
            assets = [dict(r) for r in c.execute('SELECT * FROM assets WHERE archived=0' + (' AND id=?' if asset_id else ''), (asset_id,) if asset_id else ())]
        if asset_id and len(assets) == 1 and assets[0]['asset_type'] == 'bdr':
            pull_bdr(assets[0])
            return
        token = os.getenv('BRAPI_TOKEN') or cfg.get('brapi_token', '')
        with connect() as c:
            cat_date = c.execute('SELECT MAX(retrieved_at) AS t FROM catalog').fetchone()['t']
        if age(cat_date or '') >= 7:
            JOB['progress'] = 'Atualizando catálogo da B3'
            try:
                update_catalog()
            except ValueError as exc:
                errors.append('Catálogo: '+str(exc))
        with connect() as c:
            assets = [dict(r) for r in c.execute('SELECT * FROM assets WHERE archived=0' + (' AND id=?' if asset_id else ''), (asset_id,) if asset_id else ())]
        with ThreadPoolExecutor(max_workers=4) as macro_pool:
            macro_futures={macro_pool.submit(request_json,macro_url(code)):(key,code) for key,code in (('selic',432),('cdi',4389),('ipca',13522),('usd',1))}
            for future in as_completed(macro_futures):
                key,code=macro_futures[future]
                JOB['progress'] = 'Atualizando juros, inflação e dólar'
                try:
                    rows = future.result()
                    eligible = [(datetime.strptime(r['data'], '%d/%m/%Y').date(), r) for r in rows]
                    eligible = [(d, r) for d, r in eligible if d <= today()]
                    if not eligible:
                        raise ValueError('Fonte sem observações até a data de hoje')
                    last = max(eligible, key=lambda x: x[0])[1]
                    value = number(str(last['valor']).replace(',', '.'), True, -99, 1000)
                    ref = datetime.strptime(last['data'], '%d/%m/%Y').date().isoformat()
                    with WRITE_LOCK, connect() as c:
                        c.execute('INSERT OR REPLACE INTO macro VALUES (?,?,?,?,?)', (key, value, ref, f'BCB/SGS {code}', now()))
                        log_source(c, key, {'selic':'Selic meta', 'cdi':'CDI anualizado', 'ipca':'IPCA em 12 meses', 'usd':'Dólar PTAX venda'}[key]+' · Banco Central', SOURCE_URLS[key], asof=ref)
                except Exception as exc:
                    message = str(exc) if isinstance(exc, ValueError) else 'Falha ao ler a fonte'
                    errors.append(key.upper() + ': ' + message)
                    with WRITE_LOCK, connect() as c:
                        log_source(c, key, key.upper()+' · Banco Central', SOURCE_URLS[key], 'error', error=message)
        JOB['progress'] = 'Atualizando Bitcoin e medo/ganância'
        try:
            sentiment = fetch_sentiment(request_json, number, today)
            with WRITE_LOCK, connect() as c:
                for row in sentiment:
                    c.execute('INSERT OR REPLACE INTO sentiment VALUES (?,?,?,?)', (row['date'], row['value'], row['classification'], now()))
                log_source(c, 'sentiment', 'Medo e ganância · Alternative.me', SOURCE_URLS['sentiment'], asof=sentiment[-1]['date'])
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else 'Índice de sentimento indisponível'
            errors.append('Medo/ganância: '+message)
            with WRITE_LOCK, connect() as c:
                log_source(c, 'sentiment', 'Medo e ganância · Alternative.me', SOURCE_URLS['sentiment'], 'error', error=message)
        try:
            btc_data, btc_date = fetch_bitcoin(request_json, number, now, today)
            with WRITE_LOCK, connect() as c:
                c.execute('INSERT OR REPLACE INTO macro VALUES (?,?,?,?,?)', ('btc', btc_data['price'], btc_date, 'Coinbase · BTC/BRL spot', now()))
                log_source(c, 'bitcoin', 'Bitcoin em reais · Coinbase', SOURCE_URLS['bitcoin'], asof=btc_date)
                for a in c.execute("SELECT * FROM assets WHERE asset_type='crypto'"):
                    add_snapshot(c, a['id'], 'quote', btc_data, 'Coinbase · BTC/BRL spot', btc_date)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else 'Cotação de Bitcoin indisponível'
            errors.append('Bitcoin: '+message)
            with WRITE_LOCK, connect() as c:
                log_source(c, 'bitcoin', 'Bitcoin em reais · Coinbase', SOURCE_URLS['bitcoin'], 'error', error=message)
        for i, a in enumerate(assets):
            if a.get('asset_type')=='fii' and a.get('verified'):
                with connect() as c: attempt=read_cache(c,'fii_attempt_'+str(a['id']),{})
                if age(attempt.get('at',''))>=7:
                    JOB['progress']=a['ticker']+' · informes e carteira do FII'
                    errors.extend(a['ticker']+': '+w for w in fii_research.refresh(sys.modules[__name__],a)['warnings'])
            if a.get('asset_type') in ('foreign','global_stock') or a.get('asset_type')=='stock' and a.get('verified'):
                with connect() as c: annual = latest(c,a['id']).get('issuer_financials')
                if not annual or age(annual.get('retrieved_at','')) >= 90:
                    try:
                        company_research.refresh_annual(sys.modules[__name__],a)
                    except ValueError as exc:
                        with WRITE_LOCK,connect() as c:
                            log_source(c,'issuer_'+str(a['id']),a['ticker']+' · resultados anuais','https://finance.yahoo.com/quote/'+company_research.annual_symbol(a)+'/financials/','error',error=str(exc))
                with connect() as c: dossier = latest(c, a['id'])
                profile = dossier.get('issuer_profile')
                statements = dossier.get('issuer_statements')
                if not profile or age(profile.get('retrieved_at', '')) >= 90 or a['asset_type']=='stock' and (not statements or age(statements.get('retrieved_at','')) >= 30):
                    JOB['progress'] = a['ticker'] + ' · ficha e histórico da empresa'
                    company_research.company_history.refresh(sys.modules[__name__], a)
            if a.get('asset_type') in international_market.TYPES:
                JOB['progress']=a['ticker']+' · cotação internacional'
                try: errors.extend(a['ticker']+': '+w for w in international_market.refresh_asset(sys.modules[__name__],a))
                except Exception as exc:
                    errors.append(a['ticker']+': '+(str(exc) if isinstance(exc,ValueError) else 'Consulta internacional indisponível; dados anteriores preservados.'))
                if a.get('asset_type')=='global_stock':
                    JOB['progress']=a['ticker']+' · setor e indicadores'
                    try: errors.extend(a['ticker']+': '+w for w in stock_fundamentals.refresh_asset(sys.modules[__name__],a))
                    except Exception:errors.append(a['ticker']+': pesquisa de indicadores indisponível; anteriores preservados.')
                continue
            if a.get('asset_type') == 'bdr':
                pull_bdr(a)
                continue
            if a.get('asset_type') == 'foreign':
                JOB['progress'] = a['ticker']+' · dados americanos em USD'
                try:
                    with connect() as c: previous_us=latest(c,a['id']).get('us_history',{})
                    warnings=us_market.refresh_asset(sys.modules[__name__],a,previous_us.get('data',{}).get('years',1))
                    errors.extend(a['ticker']+': '+w for w in warnings)
                except Exception as exc:
                    message=str(exc) if isinstance(exc,ValueError) else 'Dados americanos indisponíveis; anteriores preservados.'
                    errors.append(a['ticker']+': '+message)
                    with WRITE_LOCK,connect() as c: log_source(c,'us_'+str(a['id']),a['ticker']+' · EUA','https://finance.yahoo.com/','error',error=message)
                JOB['progress']=a['ticker']+' · setor e indicadores'
                try: errors.extend(a['ticker']+': '+w for w in stock_fundamentals.refresh_asset(sys.modules[__name__],a))
                except Exception:errors.append(a['ticker']+': pesquisa de indicadores indisponível; anteriores preservados.')
                continue
            if a.get('asset_type') == 'crypto' or not a.get('verified'):
                continue
            JOB['progress'] = f"{a['ticker']} · {i+1} de {len(assets)}"
            received = {}; endpoint_errors=[]; alternatives={}; refs=[]
            with connect() as c: old_history=latest(c,a['id']).get('history')
            history_years=old_history['data'].get('years',1) if old_history else 1
            need_history=not history_cache.fresh(old_history,history_years)
            with ThreadPoolExecutor(max_workers=8) as pool:
                endpoints = ('quote', 'historical') if a.get('asset_type') in ('etf', 'fii') else ('quote', 'statistics', 'financial-data', 'historical')
                if not need_history or history_years>1:endpoints=tuple(ep for ep in endpoints if ep!='historical')
                futures = {pool.submit(fetch_stock, a, ep, token): ep for ep in endpoints}
                futures[pool.submit(extra_sources.yahoo,a['ticker'],request_json,today,need_history,history_years)]='yahoo'
                if a.get('asset_type') == 'fii':
                    futures[pool.submit(fetch_fii, a, request_json, token, valid_date, clean, today)] = 'fii/indicators'
                    futures[pool.submit(fetch_fii_vacancy, a, request_json, token, valid_date, clean, today)] = 'fii/properties'
                if a.get('asset_type','stock')=='stock':
                    futures[pool.submit(public_fundamentals.fetch_detail,a['ticker'],today)]='fundamentus'
                    for name in extra_sources.SITES: futures[pool.submit(extra_sources.fetch_page,name,a['ticker'],today)]=name
                for fu in as_completed(futures):
                    ep=futures[fu]
                    try:
                        result=fu.result()
                        if ep in ('fundamentus','yahoo','status','investidor'): alternatives[ep]=result
                        else:
                            kind,data,ref=result; received[kind]=(data,ref,'brapi · fii/properties') if ep=='fii/properties' else (data,ref)
                    except Exception as exc:
                        endpoint_errors.append((ep,str(exc) if isinstance(exc,ValueError) else 'Falha ao ler a fonte'))
            if 'financial' in received and received['financial'][1] and received['financial'][1]>today().isoformat():
                received.pop('financial');endpoint_errors.append(('financial-data','Financeiros com data futura; dados anteriores preservados'))
            if 'financial' in received and not received['financial'][1]:
                if 'statistics' in received:received['financial']=(received['financial'][0],received['statistics'][1])
                else:received.pop('financial');endpoint_errors.append(('financial-data','Financeiros sem data contábil verificável'))
            supplemental={};public=alternatives.get('fundamentus')
            if public:
                for kind,(data,ref) in public.items():
                    if kind not in received: received[kind]=(data,ref,'Fundamentus · detalhes/'+a['ticker'])
                supplemental={k:v for k,v in public['financial'][0].items() if k in ('debt_equity','net_debt_equity','roic') and v is not None}
                for kind in ('statistics','financial'):
                    for key,value in public[kind][0].items():
                        if key in sector_analysis.METRICS and value is not None and received[kind][0].get(key) is None:supplemental[key]=value
                public_ref=public['financial'][1]
            for name in ('investidor','yahoo','status'):
                found=alternatives.get(name)
                if not found:continue
                groups=found if name=='yahoo' else found['groups']
                for kind,result in groups.items():
                    if kind not in received or kind=='quote' and result[1]>received[kind][1]:received[kind]=result
                if name!='yahoo':refs.append({**found['reference'],'retrieved_at':now()})
            with WRITE_LOCK, connect() as c:
                if c.execute('SELECT 1 FROM assets WHERE id=?', (a['id'],)).fetchone():
                    for kind, result in received.items():
                        data,ref=result[:2]
                        source=result[2] if len(result)>2 else 'brapi · '+('fii/indicators' if a.get('asset_type')=='fii' and kind=='statistics' else 'stocks/'+{'quote':'quote','statistics':'statistics','financial':'financial-data','history':'historical'}[kind])
                        add_snapshot(c,a['id'],kind,data,source,ref)
                        log_source(c,'asset_'+str(a['id'])+'_'+kind,a['ticker']+' · '+kind,public_fundamentals.BASE+'detalhes.php?papel='+a['ticker'] if source.startswith('Fundamentus') else extra_sources.source_url(source,a['ticker']) or SOURCE_URLS['catalog'],asof=ref)
                    if supplemental:
                        # Do not overwrite user-authored risk entries; dated provider fields remain separate.
                        add_snapshot(c,a['id'],'public',supplemental,'Fundamentus · detalhes/'+a['ticker'],public_ref)
                    if refs:
                        references=read_cache(c,'provider_references',{});references[str(a['id'])]=refs;write_cache(c,'provider_references',references)
                    for name in alternatives:
                        url=extra_sources.SITES[name][1]+a['ticker'].lower() if name in extra_sources.SITES else 'https://finance.yahoo.com/quote/'+a['ticker']+'.SA/' if name=='yahoo' else public_fundamentals.BASE+'detalhes.php?papel='+a['ticker']
                        log_source(c,'provider_'+str(a['id'])+'_'+name,a['ticker']+' · '+name,url)
                    for ep,message in endpoint_errors:
                        kind={'statistics':'statistics','financial-data':'financial','historical':'history','quote':'quote','fii/indicators':'statistics','fii/properties':'metric:vacancy'}.get(ep,ep)
                        if ep in ('fundamentus','yahoo','status','investidor'):
                            log_source(c,'provider_'+str(a['id'])+'_'+ep,a['ticker']+' · '+ep,extra_sources.SITES[ep][1]+a['ticker'].lower() if ep in extra_sources.SITES else 'https://finance.yahoo.com/' if ep=='yahoo' else public_fundamentals.BASE,'error',error=message)
                        elif kind not in received:
                            errors.append(a['ticker']+' / '+ep+': '+message)
                            log_source(c,'asset_'+str(a['id'])+'_'+kind,a['ticker']+' · '+kind,SOURCE_URLS['catalog'],'error',error=message)
                        elif ep!='fundamentus':
                            log_source(c,'provider_'+str(a['id'])+'_'+ep,a['ticker']+' · brapi/'+ep,SOURCE_URLS['catalog'],'error',error=message+'; grupo disponível pela fonte alternativa.')
    finally:
        JOB.update(running=False, progress='Atualização concluída', errors=errors, finished_at=now())
        try:
            with WRITE_LOCK, connect() as c:
                c.execute("INSERT OR REPLACE INTO runtime VALUES ('last_market_attempt',?)", (JOB['finished_at'],))
                c.execute("INSERT OR REPLACE INTO runtime VALUES ('last_market_errors',?)", (json.dumps(errors,ensure_ascii=False),))
                tickers = [r['ticker'] for r in c.execute("SELECT ticker FROM assets WHERE asset_type!='crypto'")]
                relevant = [e for e in errors if any(e.startswith(t+' /') or e.startswith(t+':') for t in tickers)]
                if tickers:
                    log_source(c,'quotes','Cotações e indicadores · brapi',SOURCE_URLS['catalog'],
                               'error' if relevant else 'ok',error='; '.join(relevant)[:1800])
        except sqlite3.Error:
            pass
        REFRESH_LOCK.release()
        with WRITE_LOCK:
            pending=bool(PENDING_REFRESH); PENDING_REFRESH.clear()
        if pending: start_refresh()
        else:
            company_research.start_initial(sys.modules[__name__])
            try:
                with connect() as c: enabled = bool(read_cache(c,'market_signal_models',{}))
                if enabled and not market_signals.job_state()['running']:
                    market_signals.start(sys.modules[__name__],{'pretrained':True})
            except Exception:
                pass  # Locked wallets and a concurrent model job do not invalidate market data.


def start_refresh(asset_id=None):
    if REFRESH_LOCK.acquire(blocking=False):
        JOB.update(running=True, progress='Consultando fontes', errors=[])
        threading.Thread(target=refresh_worker, args=(asset_id,), daemon=True).start()
    elif asset_id:
        with WRITE_LOCK: PENDING_REFRESH.add(asset_id)
    return dict(JOB)


def macro_url(code):
    base = f'https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados'
    if code == 13522:
        # Monthly observations; the public endpoint permits at most 20 latest values.
        return base + '/ultimos/12?formato=json'
    # Daily series are bounded to a short window and to the current Brazilian date.
    start = (today()-timedelta(days=14)).strftime('%d/%m/%Y')
    end = today().strftime('%d/%m/%Y')
    return base + f'?formato=json&dataInicial={start}&dataFinal={end}'


def projection(d):
    principal = number(d.get('principal'), True, 0, 1e12)
    months = number(d.get('months'), True, 1, 600)
    days=tax_rules.horizon_days(today(),months)
    tax_ref=tax_rules.reference(d.get('product','CDB'),days)
    if d.get('tax_mode')=='auto' and not tax_ref['automatic']:
        raise ValueError('Selecione um regime tributário confirmado ou informe o IR personalizado.')
    tax = tax_ref['rate'] if d.get('tax_mode')=='auto' else number(d.get('tax'), True, 0, 100)
    fee = number(d.get('fee', 0), True, 0, 100)
    cdi, selic, ipca = [number(d.get(k), False, -99, 1000) for k in ('cdi', 'selic', 'ipca')]
    rate = number(d.get('rate'), True, -50, 1000)
    idx = d.get('indexer')
    if idx == 'CDI':
        if cdi is None:
            raise ValueError('Informe o CDI no cenário.')
        daily = (1 + cdi / 100) ** (1 / 252) - 1
        annual = (1 + daily * rate / 100) ** 252 - 1
    elif idx == 'Selic':
        if selic is None:
            raise ValueError('Informe a Selic no cenário.')
        annual = (1 + selic / 100) * (1 + rate / 100) - 1
    elif idx == 'IPCA+':
        if ipca is None:
            raise ValueError('Informe a inflação no cenário.')
        annual = (1 + ipca / 100) * (1 + rate / 100) - 1
    elif idx == 'Prefixado':
        annual = rate / 100
    else:
        raise ValueError('Saldo manual não permite estimar a rentabilidade futura.')
    after_fee = (1 + annual) / (1 + fee / 100) - 1
    gross = principal * (1 + after_fee) ** (months / 12)
    gain = gross - principal
    net = gross - max(0, gain) * tax / 100
    real = net / ((1 + ipca / 100) ** (months / 12)) if ipca is not None else None
    benchmark = principal * (1 + cdi / 100) ** (months / 12) if cdi is not None else None
    benchmark_tax=tax_rules.regressive(days) if d.get('tax_mode')=='auto' else tax
    bnet = benchmark - max(0, benchmark-principal) * benchmark_tax / 100 if benchmark is not None else None
    points = []
    for m in range(0, int(months)+1, max(1, int(months)//60)):
        g = principal * (1 + after_fee) ** (m / 12)
        points.append({'month': m, 'value': g - max(0, g-principal) * tax / 100})
    return {'annual': annual*100, 'gross': gross, 'net': net, 'real': real,'tax':tax,'benchmark_tax':benchmark_tax,'tax_reference':tax_ref,
            'benchmark': bnet, 'points': points}


def export_data(c):
    tables = {t: [dict(r) for r in c.execute('SELECT * FROM ' + t)] for t in ('assets', 'trades', 'snapshots', 'fixed', 'macro', 'imported_rows', 'income')}
    tables['settings'] = [dict(r) for r in c.execute("SELECT * FROM settings WHERE key != 'brapi_token'")]
    tables['sentiment'] = [dict(r) for r in c.execute('SELECT * FROM sentiment')]
    entities={'asset:'+a['ticker'] for a in tables['assets']}|{'fund:'+str(f['id']) for f in tables['fixed'] if investment_exposure.is_fund(f)}
    exposures={k:v for k,v in read_cache(c,'investment_exposures',{}).items() if k in entities}
    return {'format': 'aporte-brasil-v6', 'exported_at': now(), 'tables': tables,'research_reports':read_cache(c,'research_reports',[]),'valuation_cases':read_cache(c,'valuation_cases',{}),'import_receipts':read_cache(c,'import_receipts',[]),'news_scenarios':read_cache(c,'news_scenarios',{}),'ai_scenarios':read_cache(c,'ai_scenarios',[]),'investment_exposures':exposures}


def restore(c, d):
    if JOB['running'] or market_ai.job_state()['running'] or market_signals.job_state()['running']:
        raise ValueError('Aguarde a atualização de mercado e a análise de IA antes de restaurar.')
    if d.get('format') not in ('aporte-brasil-v1', 'aporte-brasil-v2', 'aporte-brasil-v3', 'aporte-brasil-v4','aporte-brasil-v5','aporte-brasil-v6') or not isinstance(d.get('tables'), dict):
        raise ValueError('Use um backup exportado por este aplicativo.')
    tables = d['tables']
    for a in tables.get('assets', []):
        a.setdefault('asset_type', 'stock'); a.setdefault('verified', 0)
        a.setdefault('research_profile', 'auto')
        a.setdefault('archived',0)
        a.setdefault('auto_sector',0)
        if type(a['auto_sector']) is not int or a['auto_sector'] not in (0,1) or a['auto_sector'] and a['asset_type'] not in ('foreign','global_stock'):
            raise ValueError('Preferência de setor automático inválida.')
        if a['archived'] not in (0,1): raise ValueError('Situação de ativo inválida.')
    for t in tables.get('trades', []):
        t.setdefault('institution', 'Não informada')
    for f in tables.get('fixed', []):
        f.setdefault('institution', 'Não informada'); f.setdefault('issuer', ''); f.setdefault('cnpj', '')
        f.setdefault('source_url', ''); f.setdefault('metadata', '{}')
        f.setdefault('invested_known', 1); f.setdefault('conditions_known', 1)
        f.setdefault('archived',0)
        validate_url(f['source_url'])
        if not isinstance(json.loads(f['metadata']),dict) or len(f['metadata'])>5_000_000:
            raise ValueError('Pesquisa de fundo inválida no backup.')
        import funds
        funds.validate_metadata(json.loads(f['metadata']), number, valid_date)
        if 'tesouro_position' in json.loads(f['metadata']):
            if f['type']!='Tesouro':raise ValueError('Posição de Tesouro em investimento incompatível.')
            tesouro.validate_profile(sys.modules[__name__],json.loads(f['metadata'])['tesouro_position'])
        marker=json.loads(f['metadata']).get('contract_rate_known',False)
        if not isinstance(marker,bool):raise ValueError('Identificação da taxa inválida no backup.')
        for flag in ('invested_known','conditions_known','archived'):
            if f[flag] not in (0,1): raise ValueError('Campo de investimento inválido.')
    tables.setdefault('income', [])
    expected = ('assets', 'trades', 'snapshots', 'fixed', 'macro', 'settings', 'income')
    for t in expected:
        if not isinstance(tables.get(t), list) or len(tables[t]) > 100000:
            raise ValueError('Backup inválido ou muito grande.')
    for a in tables['assets']:
        validate_asset(a)
        if a['research_profile'] not in ('auto', *sector_analysis.PROFILES):
            raise ValueError('Perfil de pesquisa inválido no backup.')
    for r in tables['income']:
        validate_income(r)
    for f in tables['fixed']:
        validate_fixed(f)
    for t in tables['trades']:
        number(t['quantity'], True, .00000001)
        number(t['price'], True, .00000001)
        number(t['fees'], True, 0)
        if valid_date(t['date']) > today().isoformat():
            raise ValueError('Operação com data futura.')
    for s in tables['snapshots']:
        payload = json.loads(s['data'], parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Número inválido no backup')))
        if s['kind'] not in KINDS or not isinstance(payload, dict):
            raise ValueError('Indicadores inválidos no backup.')
        if valid_date(s['asof']) > today().isoformat():
            raise ValueError('Backup contém referência futura.')
        text_value(s['source'], 400, True)
        if s['kind'] in ('us_quote','us_history'):
            payload=us_market.validate_snapshot(sys.modules[__name__],s['kind'],payload)
        elif s['kind'] in stock_fundamentals.KINDS:
            payload=stock_fundamentals.validate_snapshot(sys.modules[__name__],s['kind'],payload)
            owner=next((a for a in tables['assets'] if a['id']==s['asset_id']),None)
            if not owner or owner['asset_type'] not in ('foreign','global_stock') or payload['symbol']!=stock_fundamentals.symbol(owner['ticker'],payload['market']):
                raise ValueError('Pesquisa de stock não corresponde ao ativo do backup.')
            if owner['asset_type']=='foreign' and payload['market']!='US':raise ValueError('Pesquisa americana em bolsa incompatível.')
        elif s['kind'] in international_market.KINDS:
            payload=international_market.validate_snapshot(sys.modules[__name__],s['kind'],payload)
            owner=next((a for a in tables['assets'] if a['id']==s['asset_id']),None)
            if not owner or owner['asset_type'] not in international_market.TYPES or s['kind']!='international_fx' and payload['symbol']!=owner['ticker']:
                raise ValueError('Listagem internacional não corresponde ao ativo do backup.')
            if s['kind']=='international_quote' and payload['instrument_type']!=('ETF' if owner['asset_type']=='global_etf' else 'EQUITY'):
                raise ValueError('Tipo de cotação internacional não corresponde ao cadastro.')
        elif s['kind'] in fii_research.KINDS:
            payload=fii_research.validate_snapshot(sys.modules[__name__],s['kind'],payload)
            owner=next((a for a in tables['assets'] if a['id']==s['asset_id']),None)
            if not owner or owner['asset_type']!='fii' or payload['symbol']!=owner['ticker']:
                raise ValueError('Pesquisa do FII não corresponde ao ativo do backup.')
        elif s['kind'] in company_research.KINDS:
            payload=company_research.validate_snapshot(sys.modules[__name__],s['kind'],payload)
            issuer=next((a for a in tables['assets'] if a['id']==s['asset_id']),None)
            if not issuer or issuer['asset_type'] not in ('stock','foreign','global_stock') or 'symbol' in payload and payload['symbol']!=company_research.annual_symbol(issuer):
                raise ValueError('Pesquisa financeira não corresponde à empresa do backup.')
            if s['kind'] in factor_analysis.KINDS and payload['market'] != factor_analysis.market(issuer):
                raise ValueError('Mercado do histórico de fatores não corresponde à empresa do backup.')
        elif s['kind'] == 'history':
            points = payload.get('prices')
            if not isinstance(points, list) or not 1 <= len(points) <= 10000:
                raise ValueError('Histórico inválido no backup.')
            normalized = []
            for point in points:
                pd = valid_date(point['date'])
                if pd > today().isoformat():
                    raise ValueError('Histórico futuro no backup.')
                normalized.append({'date': pd, 'close': number(point['close'], True, .00000001)})
            if len({p['date'] for p in normalized}) != len(normalized):
                raise ValueError('Histórico duplicado no backup.')
            years=payload.get('years',1)
            if isinstance(years,bool) or years not in (1,5):raise ValueError('Janela histórica inválida.')
            payload = {'prices': sorted(normalized,key=lambda p:p['date']),'years':years}
        else:
            keys = SNAPSHOT_FIELDS[s['kind']]
            currency=payload.get('currency')
            quote_owner=next((a for a in tables['assets'] if a['id']==s['asset_id']),None)
            conversion=international_market.brl_conversion(sys.modules[__name__],payload) if s['kind']=='quote' and quote_owner and quote_owner['asset_type'] in international_market.TYPES else {}
            payload = {k: number(payload.get(k)) for k in keys}
            payload.update(conversion)
            if conversion and s['asof']!=min(conversion['native_asof'],conversion['fx_asof']): raise ValueError('Data da conversão BRL incompatível no backup.')
            if currency is not None:
                if currency not in stock_fundamentals.CURRENCIES or s['kind']=='quote': raise ValueError('Moeda de indicadores inválida.')
                payload['currency']=currency
            if s['kind'] == 'quote' and (payload['price'] is None or payload['price'] <= 0):
                raise ValueError('Cotação inválida no backup.')
        s['data'] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    for owner in tables['assets']:
        if owner['asset_type'] not in international_market.TYPES: continue
        rows=[s for s in tables['snapshots'] if s['asset_id']==owner['id']]
        listings=[s for s in rows if s['kind']=='international_listing']
        if not listings: raise ValueError('Ativo internacional sem listagem no backup.')
        l=json.loads(max(listings,key=lambda s:s['id'])['data'])
        for snapshot in rows:
            p=json.loads(snapshot['data'])
            if snapshot['kind'] in stock_fundamentals.KINDS and p['market']!=l['market']:
                raise ValueError('Pesquisa diverge da bolsa cadastrada no backup.')
            if snapshot['kind']=='international_quote' and (p['market']!=l['market'] or p['currency']!=l['currency']):
                raise ValueError('Cotação diverge da bolsa ou moeda cadastrada no backup.')
            if snapshot['kind']=='quote' and p.get('native_currency',l['currency'])!=l['currency']:
                raise ValueError('Conversão BRL diverge da moeda da listagem.')
            if snapshot['kind']=='international_fx' and p['currency']!=l['currency']:
                raise ValueError('Câmbio diverge da moeda de negociação do backup.')
    for s in tables['settings']:
        if s['key'] not in DEFAULTS:
            raise ValueError('Configuração desconhecida no backup.')
        normalized = validate_settings({s['key']: json.loads(s['value'])})
        s['value'] = json.dumps(normalized[s['key']], ensure_ascii=False)
    for m in tables['macro']:
        if m['key'] not in ('selic', 'cdi', 'ipca', 'usd', 'btc'):
            raise ValueError('Índice desconhecido no backup.')
        number(m['value'], True, .00000001 if m['key'] in ('usd', 'btc') else -99, 1e12)
        if valid_date(m['asof']) > today().isoformat():
            raise ValueError('Taxa futura no backup.')
    scenarios=d.get('news_scenarios',{})
    if not isinstance(scenarios,dict) or len(scenarios)>len(sector_analysis.PROFILES):raise ValueError('Cenários de notícias inválidos no backup.')
    for profile,scenario in scenarios.items():
        if profile not in sector_analysis.PROFILES:raise ValueError('Perfil de notícias inválido no backup.')
        scenarios[profile]=market_outlook.validate_scenario(sys.modules[__name__],scenario)
    reports=d.get('research_reports',[]);cases=d.get('valuation_cases',{})
    receipts=d.get('import_receipts',[])
    if not isinstance(receipts,list) or len(receipts)>500:raise ValueError('Histórico de importação inválido.')
    for r in receipts:
        if set(r)!={'file_hash','filename','saved_at','added','skipped','ignored'} or not re.fullmatch('[a-f0-9]{64}',r['file_hash']):raise ValueError('Comprovante de importação inválido.')
        text_value(r['filename'],200,True);text_value(r['saved_at'],100,True)
        for k in ('added','skipped','ignored'):
            if isinstance(r[k],bool) or not isinstance(r[k],int) or r[k]<0:raise ValueError('Contagem de importação inválida.')
    if not isinstance(reports,list) or len(reports)>100 or not isinstance(cases,dict) or len(cases)>1000:raise ValueError('Pesquisa/cenários inválidos no backup.')
    backup_tickers={a['ticker'] for a in tables['assets']}
    ai_scenarios=market_ai.validate_saved(sys.modules[__name__],d.get('ai_scenarios',[]),backup_tickers)
    entities={'asset:'+a['ticker'] for a in tables['assets']}|{'fund:'+str(f['id']) for f in tables['fixed'] if investment_exposure.is_fund(f)}
    exposures=investment_exposure.validate_saved(sys.modules[__name__],d.get('investment_exposures',{}),entities)
    for r in reports:
        if set(r)!={'id','saved_at','record','indicators_applied'} or not re.fullmatch('[a-f0-9]{64}',r['id']) or not isinstance(r['indicators_applied'],bool):raise ValueError('Registro de pesquisa inválido.')
        research_exchange.validate(__import__(__name__),r['record'],backup_tickers);text_value(r['saved_at'],100,True)
    for ticker,case in cases.items():
        if ticker not in backup_tickers or set(case)!={'inputs','saved_at'}:raise ValueError('Cenário não corresponde ao backup.')
        valuation.calculate(case['inputs'],number);text_value(case['saved_at'],100,True)
    # Retain a real SQLite backup before replacing the portfolio.
    backup_db(c,'antes-restauracao-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    for t in ('trades', 'snapshots', 'assets', 'fixed', 'macro', 'income'):
        c.execute('DELETE FROM ' + t)
    c.execute('DELETE FROM imported_rows')
    c.execute('DELETE FROM sentiment')
    for p in tables.get('sentiment', []):
        ref = valid_date(p['date'])
        if ref > today().isoformat():
            raise ValueError('Sentimento com data futura.')
        c.execute('INSERT INTO sentiment VALUES (?,?,?,?)', (ref, number(p['value'], True, 0, 100), text_value(p['classification'], 50), text_value(p['retrieved_at'], 100)))
    c.execute("DELETE FROM settings WHERE key != 'brapi_token'")
    for table in expected:
        columns = [r['name'] for r in c.execute('PRAGMA table_info(' + table + ')')]
        for row in tables[table]:
            if set(row) != set(columns):
                raise ValueError('Estrutura do backup não compatível.')
            c.execute('INSERT INTO ' + table + ' (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
                      [row[col] for col in columns])
    write_cache(c,'research_reports',reports);write_cache(c,'valuation_cases',cases);write_cache(c,'import_receipts',receipts)
    write_cache(c,'news_scenarios',scenarios)
    write_cache(c,'ai_scenarios',ai_scenarios)
    write_cache(c,'investment_exposures',exposures)
    write_cache(c,'investment_quotes',{})
    write_cache(c,'investment_quote_errors',[])
    write_cache(c,'issuer_initial',{})
    # Public observations can be fetched again; do not retain the replaced wallet's feeds.
    for key,empty in (('news_reports',{}),('news_macro_context',{}),('news_context_profiles',[]),('ai_sentiment',{}),('us_news',{}),('market_signal_models',{}),('market_signal_results',{})):
        write_cache(c,key,empty)
    for a in tables['assets']:
        position([t for t in tables['trades'] if t['asset_id'] == a['id']])
    c.execute('UPDATE assets SET verified=CASE WHEN ticker="BTC" OR ticker IN (SELECT ticker FROM catalog) THEN 1 ELSE 0 END')
    c.execute('UPDATE assets SET asset_type=(SELECT asset_type FROM catalog WHERE catalog.ticker=assets.ticker) WHERE ticker IN (SELECT ticker FROM catalog)')
    for r in tables.get('imported_rows', []):
        if r.get('kind') not in ('positions','trades','fixed','watchlist','b3_trades','b3_fixed','income') or not re.fullmatch('[a-f0-9]{64}',r.get('fingerprint','')):
            raise ValueError('Registro de importação inválido no backup.')
        rid = int(r['record_id'])
        target = {'positions':'trades','trades':'trades','fixed':'fixed','watchlist':'assets','b3_trades':'trades','b3_fixed':'fixed','income':'income'}[r['kind']]
        if c.execute('SELECT 1 FROM '+target+' WHERE id=?',(rid,)).fetchone():
            c.execute('INSERT INTO imported_rows VALUES (?,?,?,?)',(r['fingerprint'],r['kind'],rid,text_value(r['created_at'],100)))
    for k, v in DEFAULTS.items():
        c.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (k, json.dumps(v)))


def validate_settings(d):
    result = {}
    for k, v in d.items():
        if k=='color_mode':
            if not isinstance(v,str) or v not in ('standard','accessible'):raise ValueError('Escolha cores padrão ou modo daltônico.')
            result[k]=v
        elif k=='allocation_targets':result[k]=portfolio_strategy.targets(v,number)
        elif k=='allocation_overrides':result[k]=portfolio_strategy.overrides(v)
        elif k in ('asset_limit', 'sector_limit', 'equity_target'):
            result[k] = number(v, True, 1 if k != 'equity_target' else 0, 100)
        elif k == 'risk_premium':
            result[k] = number(v, True, 0, 30)
        elif k == 'expensive_alert_percent':
            if isinstance(v,bool):raise ValueError('Informe o percentual do alerta de preço.')
            result[k]=number(v,True,1,1000)
        elif k == 'sectors':
            if not isinstance(v, list) or len(v) > 50:
                raise ValueError('Lista de setores inválida.')
            result[k] = [text_value(x, 100, True) for x in v]
        elif k == 'sector_rules':
            result[k] = sector_analysis.validate_rules(v, number)
        elif k in ('auto_refresh', 'model_average_enabled'):
            if not isinstance(v, bool):
                raise ValueError('Configuração inválida.')
            result[k] = v
        elif k == 'profile':
            result[k] = text_value(v, 200, True)
        elif k == 'brapi_token':
            result[k] = text_value(v, 500)
    return result


def mutate(path, d):
    with WRITE_LOCK, connect() as c:
        if path == '/api/assets':
            values, verified = asset_values_from_catalog(c, d)
            if 'auto_sector' in d and (type(d['auto_sector']) is not bool or d['auto_sector'] and values[-1] not in ('foreign','global_stock')):
                raise ValueError('Setor automático disponível apenas para stocks.')
            if d.get('id'):
                if not c.execute('SELECT 1 FROM assets WHERE id=?', (d['id'],)).fetchone():
                    raise ValueError('Ativo não encontrado.')
                original_row = c.execute('SELECT ticker,asset_type FROM assets WHERE id=?', (d['id'],)).fetchone()
                original=original_row['ticker']
                if (original_row['asset_type'] in international_market.TYPES or values[-1] in international_market.TYPES) and original_row['asset_type']!=values[-1]:
                    raise ValueError('Cadastre outro produto separadamente para alterar o tipo internacional.')
                if original != values[0]:
                    raise ValueError('Cadastre o novo ticker separadamente para revisar a conversão.')
                c.execute('UPDATE assets SET ticker=?,name=?,sector=?,financial=?,notes=?,asset_type=?,verified=? WHERE id=?', (*values, verified, d['id']))
                aid=int(d['id'])
            else:
                cur = c.execute('INSERT INTO assets(ticker,name,sector,financial,notes,asset_type,verified) VALUES (?,?,?,?,?,?,?)', (*values, verified))
                aid=cur.lastrowid
            if 'auto_sector' in d:c.execute('UPDATE assets SET auto_sector=? WHERE id=?',(int(d['auto_sector']),aid))
            if values[-1] in international_market.TYPES:
                old_listing=latest(c,aid).get('international_listing')
                candidate=d.get('listing') or (old_listing or {}).get('data')
                listing=international_market.listing(sys.modules[__name__],values[0],candidate)
                if values[-1]=='global_etf' and listing['distribution']=='not_applicable' or values[-1]=='global_stock' and (listing['distribution']!='not_applicable' or values[0] in international_market.PRESETS):
                    raise ValueError('Confira o produto e a política de distribuição: ETF pode acumular, distribuir ou ficar a conferir.')
                if old_listing and any(old_listing['data'][k]!=listing[k] for k in ('symbol','market','currency')):
                    raise ValueError('Cadastre outra listagem separadamente para alterar bolsa ou moeda.')
                add_snapshot(c,aid,'international_listing',listing,'Cadastro internacional · fonte conferida pelo usuário',listing['asof'])
                if not d.get('id') and values[-1]=='global_etf' and values[0] in international_market.PRESETS:
                    is_vanguard=values[0]!='CSPX.L'
                    add_snapshot(c,aid,'metric:expense_ratio',{'expense_ratio':.14 if is_vanguard else .07},
                        'Emissor · '+international_market.PRESETS[values[0]]['source_url'], '2026-10-06')
                    if is_vanguard:
                        add_snapshot(c,aid,'metric:tracking_error',{'tracking_error':.07},
                            'Vanguard · tracking error anualizado 1 ano · '+international_market.VANGUARD,'2026-08-31')
            opening=holdings.add_opening(sys.modules[__name__],c,aid,d['opening']) if d.get('opening') is not None else {}
            if not d.get('id'): company_research.queue_initial(sys.modules[__name__],c,aid)
            return {'id':aid,**opening}
        elif path=='/api/positions/opening':
            return holdings.add_opening(sys.modules[__name__],c,int(d['asset_id']),d.get('opening'))
        elif path == '/api/assets/delete':
            aid = int(d['id'])
            c.execute('UPDATE assets SET archived=1 WHERE id=?',(aid,))
        elif path=='/api/assets/restore':
            c.execute('UPDATE assets SET archived=0 WHERE id=?',(int(d['id']),))
        elif path == '/api/trades':
            aid, side = int(d['asset_id']), d.get('side')
            if side not in ('buy', 'sell'):
                raise ValueError('Operação inválida.')
            q, p, fee = number(d.get('quantity'), True, .00000001), number(d.get('price'), True, .00000001), number(d.get('fees', 0), True, 0)
            dt = valid_date(d.get('date'))
            if dt > today().isoformat():
                raise ValueError('A operação não pode ter data futura.')
            institution = text_value(d.get('institution') or 'Não informada', 150, True)
            holdings.ensure_after_opening(c,aid,institution,dt)
            c.execute('INSERT INTO trades(asset_id,side,quantity,price,fees,date,institution) VALUES (?,?,?,?,?,?,?)', (aid, side, q, p, fee, dt, institution))
            position([dict(t) for t in c.execute('SELECT * FROM trades WHERE asset_id=?', (aid,))])
        elif path == '/api/trades/delete':
            r = c.execute('SELECT asset_id FROM trades WHERE id=?', (int(d['id']),)).fetchone()
            if not r:
                raise ValueError('Operação não encontrada.')
            c.execute('DELETE FROM trades WHERE id=?', (int(d['id']),))
            c.execute('DELETE FROM imported_rows WHERE kind IN ("trades","positions","b3_trades") AND record_id=?', (int(d['id']),))
            position([dict(t) for t in c.execute('SELECT * FROM trades WHERE asset_id=?', (r['asset_id'],))])
        elif path == '/api/manual':
            aid = int(d['asset_id'])
            ref = valid_date(d.get('asof'))
            if ref > today().isoformat():
                raise ValueError('Indicadores não podem ter data futura.')
            source = text_value(d.get('source', ''), 300, True)
            group = d.get('kind')
            keys = SNAPSHOT_FIELDS
            if group not in keys:
                raise ValueError('Grupo de indicadores inválido.')
            metrics = {k: number(d.get(k)) for k in keys[group]}
            if d.get('currency') is not None:
                if d['currency'] not in stock_fundamentals.CURRENCIES or group=='quote': raise ValueError('Moeda de indicadores inválida.')
                metrics['currency']=d['currency']
            if group == 'quote' and (metrics['price'] is None or metrics['price'] <= 0):
                raise ValueError('Informe uma cotação positiva.')
            add_snapshot(c, aid, group, metrics, 'Manual · ' + source, ref)
            company_research.queue_initial(sys.modules[__name__],c,aid)
        elif path=='/api/stocks/metrics':
            if set(d)!={'asset_id','values','currency','asof','source'} or not isinstance(d['values'],dict) or not d['values'] or set(d['values'])-set(sector_analysis.METRICS):
                raise ValueError('Indicadores de stock inválidos.')
            if isinstance(d['asset_id'],bool):raise ValueError('Stock inválido.')
            aid=int(number(d['asset_id'],True,1));owner=c.execute('SELECT asset_type FROM assets WHERE id=? AND archived=0',(aid,)).fetchone()
            if not owner or owner['asset_type'] not in ('foreign','global_stock'):raise ValueError('Escolha um stock cadastrado.')
            ref=valid_date(d['asof']);source=text_value(d['source'],300,True)
            if ref>today().isoformat() or d['currency'] not in stock_fundamentals.CURRENCIES:raise ValueError('Data ou moeda inválida.')
            values={}
            for key,value in d['values'].items():
                if isinstance(value,bool):raise ValueError('Indicador numérico inválido.')
                values[key]=number(value,True)
            for key,value in values.items():add_snapshot(c,aid,'metric:'+key,{key:value,'currency':d['currency']},'Manual · '+source,ref)
            company_research.queue_initial(sys.modules[__name__],c,aid)
        elif path == '/api/research-profile':
            profile = d.get('profile')
            if profile not in ('auto',*sector_analysis.COMPANY_PROFILES):
                raise ValueError('Perfil de empresa inválido.')
            issuer=c.execute('SELECT asset_type FROM assets WHERE id=?',(int(d['id']),)).fetchone()
            if not issuer or issuer['asset_type'] not in ('stock','foreign','global_stock'): raise ValueError('Perfil de empresa disponível apenas para ações e stocks.')
            c.execute('UPDATE assets SET research_profile=? WHERE id=?', (profile,int(d['id'])))
        elif path == '/api/income':
            values = validate_income(d)
            cols = list(values)
            if d.get('id'):
                if not c.execute('SELECT 1 FROM income WHERE id=?',(int(d['id']),)).fetchone(): raise ValueError('Recebimento não encontrado.')
                c.execute('UPDATE income SET '+','.join(k+'=?' for k in cols)+' WHERE id=?',(*values.values(),int(d['id'])))
            else:
                c.execute('INSERT INTO income('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')', tuple(values.values()))
        elif path == '/api/income/delete':
            c.execute('DELETE FROM income WHERE id=?', (int(d['id']),))
            c.execute('DELETE FROM imported_rows WHERE kind="income" AND record_id=?', (int(d['id']),))
        elif path == '/api/history':
            aid = int(d['asset_id'])
            source = text_value(d.get('source', ''), 300, True)
            rows = d.get('prices')
            if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
                raise ValueError('Envie até 10 mil preços ajustados.')
            prices = []
            for row in rows:
                dt = valid_date(row['date'])
                if dt > today().isoformat():
                    raise ValueError('Histórico com data futura.')
                prices.append({'date': dt, 'close': number(row['close'], True, .00000001)})
            if len({r['date'] for r in prices}) != len(prices):
                raise ValueError('Histórico com datas duplicadas.')
            prices.sort(key=lambda p: p['date'])
            add_snapshot(c, aid, 'history', {'prices': prices}, 'Manual · ' + source, prices[-1]['date'])
        elif path == '/api/fixed-simple':
            original = c.execute('SELECT * FROM fixed WHERE id=?',(int(d['id']),)).fetchone() if d.get('id') else None
            if d.get('id') and not original: raise ValueError('Investimento não encontrado.')
            payload = dict(original) if original else {'indexer':'Manual','rate':0,'tax':0,'fee':0,'maturity':'','liquidity':'','notes':'','issuer':'','cnpj':''}
            payload.update(d)
            invested_known = d['invested'] not in (None,'') if 'invested' in d else bool(original['invested_known']) if original else False
            payload['invested'] = payload.get('invested') or 0
            conditions_known = all(payload.get(k) not in (None,'') for k in ('rate','tax','fee')) if any(k in d for k in ('rate','tax','fee')) else bool(original['conditions_known']) if original else False
            rate_known=payload['indexer']!='Manual' and (d['rate'] not in (None,'') if 'rate' in d else holdings.rate_known(dict(original)) if original else False)
            conditions_known=conditions_known and rate_known
            for k in ('rate','tax','fee'): payload[k] = payload.get(k) or 0
            values = validate_fixed(payload)
            url = validate_url(d.get('source_url',payload.get('source_url','')))
            columns = 'name,type,invested,balance,balance_date,indexer,rate,tax,fee,maturity,liquidity,notes,institution,issuer,cnpj,source_url,invested_known,conditions_known'.split(',')
            values = (*values,url,int(invested_known),int(conditions_known))
            if original:
                rid=original['id']
                c.execute('UPDATE fixed SET '+','.join(k+'=?' for k in columns)+' WHERE id=?',(*values,original['id']))
                metadata=json.loads(original['metadata'])
                ledger=metadata.get('bank_fixed') or metadata.get('treasury')
                if ledger and (number(payload['balance'])!=original['balance'] or payload['balance_date']!=original['balance_date']):
                    ledger['valuation']='statement'
                    c.execute('UPDATE fixed SET metadata=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),original['id']))
                if re.sub(r'\D','',original['cnpj']) != re.sub(r'\D','',payload['cnpj']):
                    metadata={k:v for k,v in metadata.items() if k in ('treasury','bank_fixed')}
            else:
                rid=c.execute('INSERT INTO fixed('+','.join(columns)+') VALUES ('+','.join('?' for _ in values)+')',values).lastrowid
                metadata={}
            metadata['contract_rate_known']=bool(rate_known)
            if 'tesouro_profile' in d:
                if payload['type']!='Tesouro':raise ValueError('Dados de Tesouro em tipo incompatível.')
                metadata['tesouro_position']=tesouro.validate_profile(sys.modules[__name__],d['tesouro_profile'])
                ledger=metadata.get('treasury')
                if ledger:ledger['valuation']='statement'
            elif payload['type']!='Tesouro':
                metadata.pop('tesouro_position',None)
            c.execute('UPDATE fixed SET metadata=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),rid))
            return {'id':rid}
        elif path == '/api/fixed':
            v = validate_fixed(d)
            columns = 'name,type,invested,balance,balance_date,indexer,rate,tax,fee,maturity,liquidity,notes,institution,issuer,cnpj'.split(',')
            if d.get('id'):
                c.execute('UPDATE fixed SET ' + ','.join(k+'=?' for k in columns) + ' WHERE id=?', (*v, int(d['id'])))
            else:
                c.execute('INSERT INTO fixed(' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in v) + ')', v)
        elif path == '/api/fixed/delete':
            c.execute('UPDATE fixed SET archived=1 WHERE id=?',(int(d['id']),))
        elif path=='/api/fixed/restore':
            c.execute('UPDATE fixed SET archived=0 WHERE id=?',(int(d['id']),))
        elif path == '/api/settings':
            for k, v in validate_settings(d).items():
                if k=='allocation_overrides':
                    for ident in v:
                        typ,rid=ident.split(':');table='assets' if typ=='asset' else 'fixed'
                        if not c.execute('SELECT 1 FROM '+table+' WHERE id=?',(int(rid),)).fetchone():raise ValueError('Investimento da classificação não encontrado.')
                c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (k, json.dumps(v, ensure_ascii=False)))
        elif path == '/api/macro/manual':
            ref = valid_date(d.get('asof'))
            if ref > today().isoformat():
                raise ValueError('Taxa com data futura.')
            source = text_value(d.get('source', ''), 300, True)
            for key in ('selic', 'cdi', 'ipca'):
                v = number(d.get(key), False, -99, 1000)
                if v is not None:
                    c.execute('INSERT OR REPLACE INTO macro VALUES (?,?,?,?,?)', (key, v, ref, 'Manual · '+source, now()))
        elif path == '/api/import':
            restore(c, d)
        else:
            raise ValueError('Ação não encontrada.')
    if path == '/api/import':
        for token, plan in list(CSV_PREVIEWS.items()):
            if plan.get('kind') == 'ai_import':
                CSV_PREVIEWS.pop(token, None)
    return {'ok': True}


def validate_url(v):
    v=text_value(v,1500)
    if not v: return ''
    parsed=urllib.parse.urlparse(v)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use um link http ou https sem credenciais.')
    return v


def validate_income(d):
    import treasury_import
    ticker=text_value(d.get('ticker',''),200,True).upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}',ticker) and not re.fullmatch(r'TESOURO [A-Z0-9+ ÁÉÍÓÚÇÃÕ\-]{1,180}',ticker) and not treasury_import.bank_product(ticker): raise ValueError('Código do ativo / título inválido.')
    if d.get('kind') not in ('Dividendos','JCP','Rendimentos','Reembolso','Amortização'): raise ValueError('Tipo de provento inválido.')
    ref=valid_date(d.get('date'))
    if ref>today().isoformat(): raise ValueError('Registre apenas proventos recebidos, sem data futura.')
    basis=d.get('amount_basis','reported')
    if basis not in ('reported','net','gross'): raise ValueError('Base do valor inválida.')
    return {'ticker':ticker,'kind':d['kind'],'amount':number(d.get('amount'),True,.00000001),'date':ref,
            'institution':text_value(d.get('institution') or 'Não informada',150,True), 'amount_basis':basis,
            'notes':text_value(d.get('notes',''),5000), 'source':text_value(d.get('source') or 'Manual · extrato',400,True)}


def fund_action(path,d):
    import funds
    app=__import__(__name__)
    if path=='/api/funds/search': return funds.search(app,d)
    if path=='/api/funds/link':
        info=funds.detail(app,d)
        with WRITE_LOCK,connect() as c:
            current=c.execute('SELECT * FROM fixed WHERE id=?',(int(d['id']),)).fetchone()
            if not current: raise ValueError('Investimento não encontrado.')
            typ=current['type']
            if typ.startswith('Fundo') and info['entity']=='class':
                typ={'renda fixa':'Fundo de renda fixa','multimercado':'Fundo multimercado','acoes':'Fundo de ações'}.get(sector_analysis.fold(info['category']),typ)
            c.execute('UPDATE fixed SET metadata=?,cnpj=?,issuer=?,type=? WHERE id=?',
                      (json.dumps({'identity':info},ensure_ascii=False),info['cnpj'],info['manager'] or info['administrator'],typ,int(d['id'])))
        return info
    if path=='/api/funds/quotes':
        with connect() as c:
            f=c.execute('SELECT * FROM fixed WHERE id=?',(int(d['id']),)).fetchone()
            if not f: raise ValueError('Investimento não encontrado.')
            f=dict(f)
        result=funds.quotes(app,{'cnpj':f['cnpj'],**({'series':d['series']} if 'series' in d else {})})
        if result['points']:
            with WRITE_LOCK,connect() as c:
                current=c.execute('SELECT * FROM fixed WHERE id=?',(f['id'],)).fetchone()
                if current and current['cnpj']==f['cnpj']:
                    metadata=json.loads(current['metadata'])
                    old=metadata.get('quotes',{})
                    if old.get('cnpj')==result['cnpj'] and old.get('selected_series')==result.get('selected_series') and result['errors']:
                        observed={p['date']:p for p in old.get('points',[])}
                        observed.update({p['date']:p for p in result['points']})
                        result['points']=sorted(observed.values(),key=lambda p:p['date'])[-90:]
                        result['note']+=' Consulta parcial: observações anteriores desta série foram preservadas.'
                    metadata['quotes']=result
                    c.execute('UPDATE fixed SET metadata=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),f['id']))
        return result
    raise ValueError('Consulta de fundo não encontrada.')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def safe_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def session_token(self):
        try:
            cookie=SimpleCookie(self.headers.get('Cookie',''))
            return cookie['aporte_session'].value if 'aporte_session' in cookie else None
        except Exception:return None

    def authenticated(self):
        return VAULT is None or VAULT.authorized(self.session_token())

    def reject_post(self,data,status):
        # Drain bounded input before closing HTTP/1.0. Otherwise Windows clients
        # may see a TCP reset instead of the intended authentication error.
        try:
            length=int(self.headers.get('Content-Length',0))
            if 0<length<=20_000_000:
                self.connection.settimeout(2)
                self.rfile.read(length)
        except (ValueError,OSError):pass
        return self.respond(data,status)

    def respond(self, data, status=200, content_type='application/json; charset=utf-8', download=False,session=None):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if download:
            extension='aporteb' if download=='encrypted' else 'json'
            self.send_header('Content-Disposition', f'attachment; filename="aporte-brasil-{today()}.{extension}"')
        if session is not None:
            self.send_header('Set-Cookie','aporte_session='+session+'; HttpOnly; SameSite=Strict; Path=/'+('; Max-Age=0' if not session else ''))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:return self.get_route()
        except private_storage.LockedError:return self.respond({'error':'A carteira foi bloqueada. Abra-a novamente com sua senha.','code':'locked'},401)

    def get_route(self):
        if not self.safe_host():
            return self.respond({'error': 'Host inválido'}, 403)
        path = urllib.parse.urlparse(self.path).path
        if path=='/api/health':return self.respond({'app':'aporte-brasil','version':APP_VERSION,'instance':INSTANCE_ID})
        if path=='/api/security/status':
            status=VAULT.status(self.session_token()) if VAULT is not None else {'initialized':True,'authenticated':True,'encrypted':False}
            return self.respond({**status,'csrf':CSRF,'version':APP_VERSION})
        if path.startswith('/api/') and not self.authenticated():return self.respond({'error':'Desbloqueie sua carteira com a senha local.','code':'locked'},401)
        if path == '/api/state':
            return self.respond(state())
        if path == '/api/ai/job':
            return self.respond(market_ai.job_state())
        if path == '/api/signals/job':
            return self.respond(market_signals.job_state())
        if path == '/api/models/comparison':
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query, keep_blank_values=True)
            try:
                if any(len(values) != 1 for values in query.values()):
                    raise ValueError('Escolha uma única opção em cada campo.')
                with connect() as c:
                    enabled = settings(c).get('model_average_enabled', False)
                return self.respond(model_comparison.public_state(ROOT, {k: v[0] for k, v in query.items()}, enabled))
            except (ValueError, KeyError, TypeError) as exc:
                return self.respond({'error': str(exc) if isinstance(exc, ValueError) else 'Comparativo histórico indisponível.'}, 400)
        if path == '/api/monitor/status':
            return self.respond(market_monitor.status())
        if path == '/api/installer/status':
            return self.respond(INSTALLER.status())
        if path == '/api/installer/download':
            name = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('file',[''])[0]
            try: package = INSTALLER.download(name)
            except ValueError as exc: return self.respond({'error':str(exc)},400)
            with package.open('rb') as stream:
                self.send_response(200)
                self.send_header('Content-Type','application/zip')
                self.send_header('Content-Length',str(os.fstat(stream.fileno()).st_size))
                self.send_header('Content-Disposition',f'attachment; filename="{package.name}"')
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers()
                try:
                    while chunk := stream.read(1024*1024): self.wfile.write(chunk)
                except (BrokenPipeError,ConnectionResetError): pass
            return
        if path == '/api/catalog':
            return self.respond(catalog_state())
        if path == '/api/stocks/lookup':
            query=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:return self.respond(stock_fundamentals.lookup(sys.modules[__name__],query.get('ticker',[''])[0].strip().upper(),query.get('market',['US'])[0]))
            except (ValueError,KeyError,TypeError):return self.respond({'error':'Empresa ou setor não identificado. Confira ticker e bolsa; você pode preencher o setor manualmente.'},400)
        if path == '/api/csv/template':
            from csv_import import template
            kind = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('kind',['positions'])[0]
            try:
                return self.respond(template(kind).encode('utf-8'), content_type='text/csv; charset=utf-8')
            except ValueError as exc:
                return self.respond({'error':str(exc)},400)
        if path == '/api/export':
            if VAULT is not None:return self.respond(VAULT.export(),content_type='application/octet-stream',download='encrypted')
            with connect() as c:
                return self.respond(export_data(c), download=True)
        files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'application/javascript'),
                 '/expanded.js': ('expanded.js', 'application/javascript'),
                 '/research.js': ('research.js', 'application/javascript'),
                 '/insights.js': ('insights.js', 'application/javascript'),
                 '/developments.js': ('developments.js', 'application/javascript'),
                 '/planning.js': ('planning.js', 'application/javascript'),
                 '/decisions.js': ('decisions.js', 'application/javascript'),
                 '/context.js': ('context.js', 'application/javascript'),
                 '/ai.js': ('ai.js', 'application/javascript'),
                 '/exposures.js': ('exposures.js', 'application/javascript'),
                 '/quality.js': ('quality.js', 'application/javascript'),
                 '/company-model.js': ('company-model.js', 'application/javascript'),
                 '/factor-analysis.js': ('factor-analysis.js', 'application/javascript'),
                 '/international.js': ('international.js', 'application/javascript'),
                 '/stocks.js': ('stocks.js', 'application/javascript'),
                 '/buy-hold.js': ('buy-hold.js', 'application/javascript'),
                 '/fii-research.js': ('fii-research.js', 'application/javascript'),
                 '/intelligence.js': ('intelligence.js', 'application/javascript'),
                 '/tesouro.js': ('tesouro.js', 'application/javascript'),
                 '/long-term.js': ('long-term.js', 'application/javascript'),
                 '/navigation.js': ('navigation.js', 'application/javascript'),
                 '/research-dashboard.js': ('research-dashboard.js', 'application/javascript'),
                 '/accessibility.js': ('accessibility.js', 'application/javascript'),
                 '/positions.js': ('positions.js', 'application/javascript'),
                 '/signals.js': ('signals.js', 'application/javascript'),
                 '/models.js': ('models.js', 'application/javascript'),
                 '/us.js': ('us.js', 'application/javascript'),
                 '/security.js': ('security.js', 'application/javascript'),
                 '/installer.js': ('installer.js', 'application/javascript'),
                 '/style.css': ('style.css', 'text/css'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
        if path in files:
            fn, typ = files[path]
            return self.respond((ROOT / 'static' / fn).read_bytes(), content_type=typ+'; charset=utf-8')
        self.respond({'error': 'Não encontrado'}, 404)

    def do_POST(self):
        # Drain an in-flight write before maintenance, and reject new writes once stopping.
        with REQUEST_LOCK:
            return self.post_route()

    def post_route(self):
        if not self.safe_host() or self.headers.get('X-CSRF-Token') != CSRF:
            return self.reject_post({'error': 'Acesso inválido; recarregue a página.'}, 403)
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            return self.reject_post({'error': 'Origem inválida'}, 403)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reject_post({'error': 'Formato inválido'}, 415)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length < 1 or length > 20_000_000:
                raise ValueError('Conteúdo vazio ou muito grande.')
            d = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Número inválido')))
            if not isinstance(d, dict):
                raise ValueError('Conteúdo inválido.')
            path = urllib.parse.urlparse(self.path).path
            if getattr(self.server,'stopping',False):return self.respond({'error':'O aplicativo está encerrando ou reiniciando. Aguarde.'},503)
            if path in ('/api/security/exit','/api/security/restart'):
                if INSTALLER.status()['running']:raise ValueError('Aguarde a geração do instalador terminar antes de encerrar ou reiniciar.')
                if JOB['running'] or market_ai.job_state()['running'] or market_signals.job_state()['running']:raise ValueError('Aguarde a atualização e a análise de IA terminarem antes de encerrar ou reiniciar.')
                self.server.restart_requested=path.endswith('/restart')
                self.server.stopping=True
                self.respond({'ok':True,'previous_instance':INSTANCE_ID},session='')
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            if path in ('/api/security/create','/api/security/unlock','/api/security/fresh-start'):
                if VAULT is None:raise ValueError('Proteção não configurada neste processo de teste.')
                if path.endswith('/create'):
                    token=VAULT.create(d.get('password'),d.get('confirmation'),d.get('confirm_migration',False))
                elif path.endswith('/fresh-start'):
                    token,_=VAULT.fresh_start(d.get('password'),d.get('confirmation'),d.get('confirmed',False))
                    CSV_PREVIEWS.clear()
                else:token=VAULT.unlock(d.get('password'))
                try:init_db()
                except Exception:VAULT.lock();raise
                return self.respond({'ok':True},session=token)
            if not self.authenticated():return self.respond({'error':'Desbloqueie sua carteira com a senha local.','code':'locked'},401)
            if path=='/api/installer/build':
                if d: raise ValueError('A geração usa somente os arquivos desta pasta; não aceita caminhos ou comandos externos.')
                return self.respond(INSTALLER.start())
            if path=='/api/security/ping':return self.respond({'ok':True})
            if path=='/api/security/lock':
                if JOB['running'] or market_ai.job_state()['running']:raise ValueError('Aguarde a atualização de mercado e a análise de IA terminarem antes de bloquear.')
                VAULT.lock();CSV_PREVIEWS.clear()
                return self.respond({'ok':True},session='')
            if path=='/api/security/change':
                VAULT.change_password(d.get('current'),d.get('password'),d.get('confirmation'))
                return self.respond({'ok':True,'note':'Cópias de segurança anteriores continuam usando a senha da época em que foram criadas.'})
            if path=='/api/security/cleanup':
                if d.get('confirmed') is not True:raise ValueError('Confirme a migração das cópias antigas.')
                private_storage.decrypt_password(VAULT.path.read_bytes(),d.get('password'))
                with WRITE_LOCK,VAULT.mutex:VAULT.protect_legacy()
                return self.respond({'ok':True})
            if path=='/api/security/restore':
                import base64
                payload=base64.b64decode(d.get('file',''),validate=True)
                image,_,_=private_storage.decrypt_password(payload,d.get('password'))
                with closing(private_storage.memory_db(image)) as source:backup=export_data(source)
                mutate('/api/import',backup)
                return self.respond({'ok':True})
            if path == '/api/refresh':
                return self.respond(start_refresh(int(d['asset_id']) if d.get('asset_id') else None))
            if path.startswith('/api/monitor/'):
                return self.respond(market_monitor.action(sys.modules[__name__],path,d))
            if path=='/api/benchmarks/update': return self.respond(brazil_benchmarks())
            if path.startswith('/api/news/'): return self.respond(news_action(path,d))
            if path.startswith('/api/ai/'): return self.respond(market_ai.action(sys.modules[__name__],path,d))
            if path.startswith('/api/issuer/'): return self.respond(company_research.action(sys.modules[__name__],path,d))
            if path.startswith('/api/fii/'): return self.respond(fii_research.action(sys.modules[__name__],path,d))
            if path in ('/api/research/template','/api/research/preview','/api/research/commit'):return self.respond(research_exchange.action(__import__(__name__),path,d))
            if path=='/api/valuation':
                result=valuation.calculate(d,number)
                selected=next((a for a in state()['assets'] if a['id']==d.get('asset_id')),None)
                if selected:
                    if selected['asset_type']!='stock':raise ValueError('Escolha uma ação de empresa para avaliar.')
                    valuation.apply_policy(result,valuation.policy(selected,result['inputs']))
                if d.get('save'):
                    with WRITE_LOCK,connect() as c:
                        asset=c.execute('SELECT ticker FROM assets WHERE id=? AND archived=0',(d.get('asset_id'),)).fetchone()
                        if not asset:raise ValueError('Ativo não encontrado.')
                        cases=read_cache(c,'valuation_cases',{});cases[asset['ticker']]={'inputs':result['inputs'],'saved_at':now()};write_cache(c,'valuation_cases',cases)
                return self.respond(result)
            if path=='/api/tax/reference':
                days=number(d.get('days',365),True,1,30000)
                return self.respond(tax_rules.reference(d.get('product','CDB'),days))
            if path.startswith('/api/tesouro/'):
                return self.respond(tesouro.action(sys.modules[__name__],path,d))
            if path == '/api/project':
                return self.respond(projection(d))
            if path == '/api/fx':
                return self.respond(fx_projection(d, number))
            if path == '/api/catalog/refresh':
                return self.respond(update_catalog())
            if path == '/api/csv/preview':
                import csv_import
                return self.respond(csv_import.preview(__import__(__name__), d))
            if path == '/api/csv/commit':
                import csv_import
                return self.respond(csv_import.commit(__import__(__name__), d))
            if path == '/api/b3/preview':
                import b3_import
                return self.respond(b3_import.preview(__import__(__name__), d))
            if path == '/api/signals/analyze':return self.respond(market_signals.start(__import__(__name__),d))
            if path == '/api/allocation/plan':return self.respond(portfolio_strategy.plan(__import__(__name__),d))
            if path == '/api/allocation/recommend':return self.respond(long_term.recommend(__import__(__name__),d))
            if path == '/api/allocation/context':return self.respond(contrarian.refresh(__import__(__name__),d))
            if path == '/api/history/fetch':return self.respond(history_cache.fetch(__import__(__name__),d))
            if path == '/api/b3/commit':
                import b3_import
                result=b3_import.commit(__import__(__name__), d)
                if result['added']: result['refresh']=start_refresh()
                return self.respond(result)
            if path.startswith('/api/funds/'):
                return self.respond(fund_action(path,d))
            result=mutate(path,d)
            if path=='/api/assets' and result.get('id') and d.get('asset_type','stock') != 'foreign':
                result['refresh']=start_refresh(result['id'])
            if path in ('/api/manual','/api/assets','/api/stocks/metrics'):
                company_research.start_initial(sys.modules[__name__])
            return self.respond(result)
        except private_storage.LockedError:
            self.respond({'error':'A carteira foi bloqueada. Abra-a novamente com sua senha.','code':'locked'},401)
        except sqlite3.IntegrityError:
            self.respond({'error': 'Ativo já cadastrado ou operação incompatível com os dados.'}, 400)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            self.respond({'error': str(exc) if isinstance(exc, ValueError) else 'Dados incompletos ou inválidos.'}, 400)
        except Exception:
            self.respond({'error': 'Não foi possível salvar. Seus dados anteriores foram preservados.'}, 500)


def main():
    global VAULT,DB_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--restart', action='store_true', help='Encerra a instância local anterior e carrega os arquivos atuais.')
    args = parser.parse_args()
    if args.restart:
        try:
            if lifecycle.stop_existing(args.port):print('Versão anterior encerrada. Carregando o código atual…')
        except (ValueError,OSError) as exc:
            print(str(exc));return 1
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/health', timeout=2) as response:
                existing = json.load(response)
            if existing.get('app') == 'aporte-brasil':
                if not args.no_browser:
                    webbrowser.open(f'http://127.0.0.1:{args.port}')
                print('O aplicativo já está aberto.')
                return
        except Exception:
            pass
        print(f'A porta {args.port} já está em uso. Abra http://127.0.0.1:{args.port} se o aplicativo já estiver iniciado, ou use --port 8766.')
        return 1
    directory=private_storage.data_dir()
    legacy=Path(os.environ.get('APORTE_DB',str(ROOT/'data/carteira.sqlite3')))
    VAULT=private_storage.Vault(directory,legacy_primary=legacy,legacy_dirs=[legacy.parent])
    deadline=time.monotonic()+5 if args.restart else 0
    while True:
        try:VAULT.acquire_instance();break
        except ValueError as exc:
            if time.monotonic()>=deadline:
                print(str(exc));server.server_close();return 1
            time.sleep(.1)
    DB_PATH=directory/'carteira.sqlite3'
    stop_security=threading.Event()
    def expire_sessions():
        while not stop_security.wait(5):VAULT.authorized(None,touch=False)
    threading.Thread(target=expire_sessions,daemon=True).start()
    market_monitor.start_worker(sys.modules[__name__],stop_security,args.port)
    print(f'Aporte Brasil aberto em http://127.0.0.1:{args.port}')
    if not args.no_browser:
        threading.Timer(.5, lambda: webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_security.set()
        server.server_close()
        VAULT.close()
    if getattr(server,'restart_requested',False):
        try:lifecycle.replace_process(ROOT,args.port)
        except OSError:
            print('Não foi possível reabrir automaticamente. Use Reiniciar Aporte Brasil.cmd nesta pasta.');return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
