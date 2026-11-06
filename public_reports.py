"""Bounded CVM archives, filtered by verified issuer identity, with original periods."""
import base64
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
import hashlib
import tempfile
import threading
import io
import json
import math
import re
import urllib.request
import zipfile

CVM = 'https://dados.cvm.gov.br/dados/'
_SHARED_ARCHIVES=None
_ARCHIVE_LOCK=threading.Lock()


@contextmanager
def shared_archives(directory):
    """A bounded, disposable cache of public ZIPs for one multi-company job."""
    global _SHARED_ARCHIVES
    with tempfile.TemporaryDirectory(prefix='tmp-public-cvm-',dir=directory) as folder:
        previous=_SHARED_ARCHIVES;_SHARED_ARCHIVES=Path(folder)
        try:yield
        finally:_SHARED_ARCHIVES=previous


def digits(v):
    return re.sub(r'\D', '', str(v or ''))


def numeric(v):
    if isinstance(v, bool) or v in (None, ''): return None
    try: n = float(v)
    except (TypeError, ValueError): return None
    return n if math.isfinite(n) and abs(n) <= 1e15 else None


@lru_cache(maxsize=6)
def archive(url, week):
    # Cache public compressed bytes only; never issuer/user holdings. Weekly revisions expire.
    cache=_SHARED_ARCHIVES/(hashlib.sha256((url+str(week)).encode()).hexdigest()+'.zip') if _SHARED_ARCHIVES else None
    if cache:
        try:
            data=cache.read_bytes()
            if len(data)<=35_000_000:return data
        except OSError:pass
    req = urllib.request.Request(url, headers={'User-Agent': 'AporteBrasil/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=25) as response: data = response.read(35_000_001)
        if len(data) > 35_000_000: raise ValueError('Arquivo público excede o limite de consulta.')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > 2_000_000_000: raise ValueError('Arquivo CVM excessivo após descompactação.')
        if cache:
            try:
                with _ARCHIVE_LOCK:
                    if sum(p.stat().st_size for p in cache.parent.glob('*.zip'))+len(data)<=640_000_000:cache.write_bytes(data)
            except OSError:pass
        return data
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError('Arquivo CVM indisponível; dados anteriores preservados.') from exc


def tables(url, day, names, cnpj=None):
    raw = archive(url, day.toordinal()//7)
    out = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for label, marker in names.items():
            matches = [n for n in z.namelist() if n.endswith('.csv') and marker in n]
            if len(matches) != 1: continue
            if z.getinfo(matches[0]).file_size>200_000_000:raise ValueError('Tabela CVM excessiva; consulta preserva os dados anteriores.')
            # CVM files are ISO-8859-1. The iterator closes each member before the next one.
            with z.open(matches[0]) as member:
                reader=csv.DictReader(io.TextIOWrapper(member, encoding='latin1'), delimiter=';')
                out[label] = [r for r in reader if cnpj is None or digits(r.get('CNPJ_CIA',r.get('CNPJ_Fundo_Classe')))==cnpj]
    return out


def fii_url(period, year):
    return CVM+f'FII/DOC/INF_{period.upper()}/DADOS/inf_{period}_fii_{year}.zip'


def fii_identity(a, rows, day):
    """B3 issuer code occurs in both ISIN and trading code; refuse ambiguous classes."""
    if not re.fullmatch(r'[A-Z0-9]{4}11', a['ticker']): raise ValueError('Identidade do FII precisa de conferência do código de negociação.')
    matches = [r for r in rows if str(r.get('Codigo_ISIN', '')).startswith('BR'+a['ticker'][:4]+'CTF')
               and r.get('Mercado_Negociacao_Bolsa') in ('S', 'Sim') and r.get('Data_Referencia', '') <= day.isoformat()]
    identities = {digits(r.get('CNPJ_Fundo_Classe')) for r in matches}
    if len(identities) != 1 or not all(len(c) == 14 for c in identities):
        raise ValueError('FII não identificado de forma única por emissor ISIN e CNPJ na CVM; nenhuma associação por nome foi feita.')
    cnpj = identities.pop()
    existing = a.get('snapshots', {}).get('fii_reports', {}).get('data', {}).get('profile', {})
    if existing.get('cnpj') and existing['cnpj'] != cnpj: raise ValueError('CNPJ do FII mudou; confira a identidade antes de substituir a série.')
    return cnpj, max(matches, key=lambda r: (r['Data_Referencia'], int(r.get('Versao') or 0)))


def selected(rows, cnpj, day):
    out = {}
    for r in rows:
        ref = r.get('Data_Referencia', '')
        if digits(r.get('CNPJ_Fundo_Classe')) != cnpj or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', ref) or ref > day.isoformat(): continue
        key = (ref, int(r.get('Versao') or 0))
        out.setdefault(key, []).append(r)
    versions = {ref: max(v for d, v in out if d == ref) for ref, _ in out}
    return {ref: out[(ref, version)] for ref, version in versions.items()}


def fetch_fii(a, day):
    current = tables(fii_url('mensal', day.year), day, {'general': '_geral_', 'monthly': '_complemento_', 'balance': '_ativo_passivo_'})
    cnpj, identity = fii_identity(a, current.get('general', []), day)
    payload = {'symbol': a['ticker'], 'profile': {'cnpj': cnpj, 'name': identity.get('Nome_Fundo_Classe', a['name']),
        'segment': identity.get('Segmento_Atuacao', ''), 'mandate': identity.get('Mandato', ''), 'management': identity.get('Tipo_Gestao', ''),
        'administrator': identity.get('Nome_Administrador', ''), 'isin': identity.get('Codigo_ISIN', ''),
        'started': identity.get('Data_Funcionamento') or None}, 'monthly': [], 'quarterly': [], 'source_url': fii_url('mensal', day.year)}
    warnings = []
    work = [('mensal', day.year-1), ('trimestral', day.year), ('trimestral', day.year-1)]
    loaded = {('mensal', day.year): current}
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [(p, y, pool.submit(tables, fii_url(p,y), day,
            {'monthly':'_complemento_','balance':'_ativo_passivo_'} if p=='mensal' else
            {'properties':f'inf_trimestral_fii_imovel_{y}.csv', 'portfolio':'_ativo_'+str(y), 'result':'_resultado_contabil_financeiro_', 'contracts':'_complemento_'})) for p,y in work]
        for p,y,task in tasks:
            try: loaded[p,y] = task.result()
            except ValueError as exc: warnings.append(f'CVM {p} {y}: {exc}')
    for (period, year), data in loaded.items():
        url = fii_url(period, year)
        if period == 'mensal':
            balance = selected(data.get('balance', []), cnpj, day)
            for ref, rows in selected(data.get('monthly', []), cnpj, day).items():
                r=rows[-1]; b=balance.get(ref, [{}])[-1]
                # Versions of the two files must agree before mixing balance inputs.
                if b.get('Versao') != r.get('Versao'): b={}
                payload['monthly'].append({'date': ref, 'nav': numeric(r.get('Valor_Patrimonial_Cotas')),
                    'equity': numeric(r.get('Patrimonio_Liquido')), 'shares': numeric(r.get('Cotas_Emitidas')),
                    'assets': numeric(r.get('Valor_Ativo')), 'yield_nav': numeric(r.get('Percentual_Dividend_Yield_Mes')),
                    'amortization': numeric(r.get('Percentual_Amortizacao_Cotas_Mes')),
                    'obligations': numeric(b.get('Obrigacoes_Aquisicao_Imoveis')), 'securitization': numeric(b.get('Obrigacoes_Securitizacao_Recebiveis')),
                    'cri': numeric(b.get('CRI') if b.get('CRI') not in (None,'') else b.get('CRI_CRA')),
                    'funds': numeric(b.get('FII')), 'property_assets': numeric(b.get('Direitos_Bens_Imoveis')), 'source_url':url})
        else:
            groups = {k:selected(v,cnpj,day) for k,v in data.items()}
            refs = set().union(*(set(v) for v in groups.values()))
            for ref in refs:
                result=groups.get('result',{}).get(ref,[{}])[-1]
                contract=groups.get('contracts',{}).get(ref,[{}])[-1]
                props=groups.get('properties',{}).get(ref,[])
                version=result.get('Versao') or contract.get('Versao') or (props[0].get('Versao') if props else None)
                if any(p.get('Versao')!=version for p in props): props=[]
                if contract.get('Versao')!=version:contract={}
                payload['quarterly'].append({'date':ref, 'cash_result':numeric(result.get('Resultado_Trimestral_Liquido_Financeiro')),
                    'cash_accumulated':numeric(result.get('Resultado_Financeiro_Liquido_Acumulado')),
                    'declared':numeric(result.get('Rendimentos_Declarados')),
                    'properties':[{'name':p.get('Nome_Imovel','')[:250],'area':numeric(p.get('Area')),
                        'vacancy':numeric(p.get('Percentual_Vacancia')),'delinquency':numeric(p.get('Percentual_Inadimplencia')),
                        'revenue_share':numeric(p.get('Percentual_Receitas_FII')),'class':p.get('Classe','')[:150]} for p in props],
                    'portfolio':[{'type':p.get('Tipo','')[:100],'issuer':p.get('Emissor','')[:250],
                        'issuer_cnpj':digits(p.get('CNPJ_Emissor')),'name':p.get('Nome_Ativo','')[:250],'value':numeric(p.get('Valor'))}
                        for p in groups.get('portfolio',{}).get(ref,[]) if p.get('Versao')==version],
                    'ipca_share':numeric(contract.get('Percentual_Indexador_Receita_FII_IPCA')),
                    'igpm_share':numeric(contract.get('Percentual_Indexador_Receita_FII_IGPM')),
                    'short_contracts':sum(numeric(contract[k]) for k in contract if k.startswith('Percentual_Vencimento_Receita_FII_Faixa_') and k.endswith(('Ate_3Meses','3a6Meses','6a9Meses','9a12Meses')))
                        if all(numeric(contract.get('Percentual_Vencimento_Receita_FII_Faixa_'+k)) is not None for k in ('Ate_3Meses','3a6Meses','6a9Meses','9a12Meses')) else None,
                    'source_url':url})
    payload['monthly'].sort(key=lambda r:r['date']);payload['quarterly'].sort(key=lambda r:r['date'])
    return payload, warnings


def company_identity(app, a, with_details=False):
    import company_insights as insights
    def read(route, **params):
        encoded=base64.b64encode(json.dumps({'language':'pt-br',**params},separators=(',',':')).encode()).decode()
        raw=app.request_json(insights.B3_API+route+'/'+encoded)
        return json.loads(raw) if isinstance(raw,str) else raw
    raw=read('GetInitialCompanies',pageNumber=1,pageSize=100,company=a['ticker'][:4])
    matches=[r for r in raw.get('results',[]) if r.get('issuingCompany')==a['ticker'][:4] and r.get('status')=='A']
    if len(matches)!=1: raise ValueError('Emissor não identificado de forma única na B3 para consultar a CVM.')
    d=read('GetDetail',codeCVM=matches[0]['codeCVM'])
    codes={r.get('code') for r in d.get('otherCodes',[])}|{d.get('code')}
    cnpj=digits(d.get('cnpj'))
    if a['ticker'] not in codes or len(cnpj)!=14 or d.get('issuingCompany')!=a['ticker'][:4]: raise ValueError('Classe/CNPJ da empresa não confirmados na B3.')
    return (cnpj,d) if with_details else cnpj


def parse_company(data, cnpj, day, nonfinancial=True):
    """Standardized CVM account codes, consolidated only. YTD cash is differenced."""
    import company_insights as insights
    fields={'DRE':{'3.11':'net_income'},'BPA':{'1.01':'current_assets','1.01.01':'cash','1.01.04':'inventory'},
            'BPP':{'2.01':'current_liabilities','2.03':'equity'},'DFC':{'6.01':'operating_cashflow','6.02':'_investing'}}
    if nonfinancial: fields['DRE'].update({'3.01':'revenue','3.02':'cost_of_revenue','3.03':'gross_profit','3.05':'ebit'})
    grouped={}; debts={}
    for label, rows in data.items():
        group=label.split('_')[0]
        for r in rows:
            ref=r.get('DT_FIM_EXERC','');code=r.get('CD_CONTA')
            if digits(r.get('CNPJ_CIA'))!=cnpj or r.get('ORDEM_EXERC')!='ÚLTIMO' or r.get('MOEDA')!='REAL' or ref>day.isoformat():continue
            unit={'MIL':1000,'UNIDADE':1}.get(r.get('ESCALA_MOEDA'))
            value=numeric(r.get('VL_CONTA'))
            if unit is None or value is None:continue
            start=r.get('DT_INI_EXERC') or ref; key=(start,ref); version=int(r.get('VERSAO') or 0)
            field=fields.get(group,{}).get(code)
            if group=='BPP' and code in ('2.01.04','2.02.01') and 'mpréstimos' in r.get('DS_CONTA',''):
                old=debts.setdefault(ref,{}).get(code)
                if old is None or version>=old[0]:debts[ref][code]=(version,value*unit)
                continue
            if field:
                old=grouped.setdefault(key,{}).get(field)
                if old is None or version>=old[0]: grouped[key][field]=(version,value*unit)
    for values in grouped.values():
        if 'operating_cashflow' in values and '_investing' in values:
            values['free_cashflow']=(max(values['operating_cashflow'][0],values['_investing'][0]),values['operating_cashflow'][1]+values['_investing'][1])
        values.pop('_investing',None)
    balances={end:{k:v[1] for k,v in vals.items()} for (start,end),vals in grouped.items() if start==end}
    for ref, vals in debts.items():
        if len(vals)==2: balances.setdefault(ref,{})['debt']=sum(v[1] for v in vals.values())
    annual={}; quarterly={}
    for (start,end),values in grouped.items():
        if start==end:continue
        duration=(date.fromisoformat(end)-date.fromisoformat(start)).days
        if not 70<=duration<=370:continue
        row={'date':end,**dict.fromkeys(insights.FIELDS),**balances.get(end,{})}
        for field,(_,value) in values.items():
            if duration>=330:row[field]=value
            elif duration<=100:row[field]=value
            else:
                previous=[(s,e,v) for (s,e),v in grouped.items() if s==start and e<end and field in v
                          and 70<=(date.fromisoformat(end)-date.fromisoformat(e)).days<=100]
                if previous: row[field]=value-max(previous,key=lambda p:p[1])[2][field][1]
        target=annual if duration>=330 else quarterly
        old=target.setdefault(end,{'date':end,**dict.fromkeys(insights.FIELDS),**balances.get(end,{})})
        old.update({k:v for k,v in row.items() if v is not None})
    for ref,row in annual.items():
        prior=(date.fromisoformat(ref).replace(month=9,day=30)).isoformat()
        # Q4 needs nine-month cumulative values, not the isolated Q3.
        ytd=grouped.get((ref[:4]+'-01-01',prior),{})
        if ref.endswith('-12-31') and ytd:
            q={'date':ref,**dict.fromkeys(insights.FIELDS),**balances.get(ref,{})}
            q.update({k:row[k]-v[1] for k,v in ytd.items() if row.get(k) is not None and k in insights.FLOW})
            quarterly[ref]=q
    return list(annual.values()),list(quarterly.values())


def fetch_company(app,a,full_history=True):
    import sector_analysis
    cnpj=company_identity(app,a); day=app.today(); errors=[]; data={}
    # Full financial history only when the primary provider leaves gaps. Public archives are shared.
    work=[('DFP',y) for y in range(day.year-(11 if full_history else 1),day.year)]+[('ITR',y) for y in range(day.year-(6 if full_history else 2),day.year+1)]
    def load(period,year):
        url=CVM+f'CIA_ABERTA/DOC/{period}/DADOS/{period.lower()}_cia_aberta_{year}.zip'
        names={k:k+'_con_' for k in ('DRE','BPA','BPP','DFC_MI','DFC_MD')}
        return tables(url,day,names,cnpj)
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks=[(p,y,pool.submit(load,p,y)) for p,y in work]
        for p,y,task in tasks:
            try:
                for k,rows in task.result().items():data.setdefault(k,[]).extend(r for r in rows if digits(r.get('CNPJ_CIA'))==cnpj)
            except ValueError as exc:errors.append(f'CVM {p} {y}: {exc}')
    annual,quarterly=parse_company(data,cnpj,day,sector_analysis.profile(a) in sector_analysis.NONFINANCIAL_PROFILES)
    if not annual and not quarterly:raise ValueError('Demonstrações consolidadas deste CNPJ não disponíveis na CVM.')
    url='https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr'
    return {'symbol':a['ticker']+'.SA','currency':'BRL','annual':sorted(annual,key=lambda r:r['date'])[-11:],
        'quarterly':sorted(quarterly,key=lambda r:r['date'])[-28:], 'source_url':url,
        'sources':{k:url for k in ('income-statement','balance-sheet','cash-flow')}},errors


def market_dividends(app,a):
    ticker=a['ticker']+'.SA'
    start=date(app.today().year-6,1,1);end=app.today()+timedelta(days=1)
    query=urllib.parse.urlencode({'period1':int(datetime.combine(start,datetime.min.time(),timezone.utc).timestamp()),
        'period2':int(datetime.combine(end,datetime.min.time(),timezone.utc).timestamp()),'interval':'1d','events':'div,splits'})
    raw=app.request_json('https://query1.finance.yahoo.com/v8/finance/chart/'+ticker+'?'+query)
    try:r=raw['chart']['result'][0]
    except (KeyError,TypeError,IndexError):raise ValueError('Yahoo sem histórico de proventos reconhecido.')
    if r.get('meta',{}).get('symbol')!=ticker or r['meta'].get('currency')!='BRL':raise ValueError('Ticker/moeda dos proventos não confirmados.')
    events={};splits=[]
    for event in (r.get('events',{}).get('dividends') or {}).values():
        ref=datetime.fromtimestamp(event['date'],timezone.utc).date().isoformat();amount=numeric(event.get('amount'))
        if ref>app.today().isoformat() or amount is None or amount<0:continue
        events[ref]=events.get(ref,0)+amount
    for event in (r.get('events',{}).get('splits') or {}).values():
        splits.append(datetime.fromtimestamp(event['date'],timezone.utc).date().isoformat())
    try:closes=r['indicators']['quote'][0]['close']
    except (KeyError,TypeError,IndexError):closes=[]
    prices={datetime.fromtimestamp(t,timezone.utc).date().isoformat():numeric(p) for t,p in zip(r.get('timestamp',[]),closes)
        if numeric(p) is not None and numeric(p)>0 and datetime.fromtimestamp(t,timezone.utc).date()<=app.today()}
    return events,prices,splits


def company_dividends(app,a):
    if a['asset_type']!='stock':raise ValueError('Esta série pública de proventos se aplica às ações da B3.')
    events,prices,splits=market_dividends(app,a);years=[]
    for year in range(app.today().year-5,app.today().year):
        rows=[(ref,p) for ref,p in prices.items() if int(ref[:4])==year]
        # Conservative: corporate actions require an explicit adjustment basis before combining sources.
        if len(rows)<180 or any(int(ref[:4])>=year for ref in splits):continue
        last,price=max(rows)
        if last[5:7]!='12':continue
        amount=sum(v for ref,v in events.items() if int(ref[:4])==year)
        years.append({'year':year,'dy':amount/price*100})
    if not years:raise ValueError('Sem anos completos de preço/proventos na mesma base; desdobramentos exigem conferência dos ajustes.')
    return {'symbol':a['ticker']+'.SA','years':years,'method':'Proventos em BRL da série Yahoo no ano ÷ fechamento disponível de dezembro × 100. Janela mínima de 180 pregões. Anos afetados por desdobramentos posteriores ficam pendentes. Cobertura de JCP e ajustes depende da fonte.',
        'source_url':'https://finance.yahoo.com/quote/'+a['ticker']+'.SA/history/'},events
