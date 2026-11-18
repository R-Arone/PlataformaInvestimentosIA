"""Six sourced FII criteria, with a strict user-defined P/VP discard rule."""
from datetime import date
import math
import re
import urllib.parse

from aporte_brasil.portfolio import sector_analysis

KIND = 'fii_quality_facts'
BOOL_FIELDS = ('prime_locations','new_properties','low_maintenance',
               'single_tenant_dependence','single_property_dependence')
FIELDS = (*BOOL_FIELDS,'dividend_record','peer_yield','pvp')


def validate_snapshot(app, data):
    if (not isinstance(data,dict) or set(data)!={'symbol','facts'}
            or not re.fullmatch(r'[A-Z0-9]{4}11',str(data.get('symbol','')))
            or not isinstance(data['facts'],dict) or set(data['facts'])-set(FIELDS)):
        raise ValueError('Evidências dos critérios do FII inválidas.')
    def past(value):
        ref=app.valid_date(value)
        if ref>app.today().isoformat():raise ValueError('Evidência do FII com data futura.')
        return ref
    facts={}
    for key,row in data['facts'].items():
        if not isinstance(row,dict) or set(row)!={'value','asof','source_url','note'}:
            raise ValueError('Informe resposta, data, fonte e fundamento do critério.')
        ref=past(row['asof']);source=app.validate_url(row['source_url']);parsed=urllib.parse.urlsplit(source)
        if not source or parsed.username or parsed.password:raise ValueError('Informe uma fonte pública sem credenciais.')
        value=row['value']
        if key in BOOL_FIELDS:
            if type(value) is not bool:raise ValueError('Use sim ou não; dado ausente continua pendente.')
        elif key=='pvp':
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
                raise ValueError('P/VP conferido deve ser positivo e finito.')
            value=app.number(value)
        elif key=='dividend_record':
            if (not isinstance(value,dict) or set(value)!={'since','through','frequency','consistent'}
                    or value['frequency']!='monthly' or type(value['consistent']) is not bool):
                raise ValueError('Histórico de rendimentos deve informar intervalo e consistência mensal.')
            start,end=past(value['since']),past(value['through'])
            if start>end or end>ref:raise ValueError('Intervalo dos rendimentos incompatível com a conferência.')
            value={**value,'since':start,'through':end}
        else:
            if (not isinstance(value,dict) or set(value)!={'fund_yield','mean_yield','peer_count','type','segment','window_months','basis'}
                    or value['type'] not in ('tijolo','papel','hibrido','fof')
                    or type(value['window_months']) is not int or value['window_months']!=12
                    or value['basis']!='paid_12m'
                    or type(value['peer_count']) is not int or not 1<=value['peer_count']<=10000):
                raise ValueError('Compare média aritmética de FIIs do mesmo tipo, na mesma janela de pagamentos de 12 meses.')
            value=dict(value)
            for field in ('fund_yield','mean_yield'):
                v=value[field]
                if type(v) not in (int,float) or not math.isfinite(v) or v<0:
                    raise ValueError('Yield anual deve ser um percentual não negativo.')
                value[field]=app.number(v)
            value['segment']=app.text_value(value['segment'],200,True)
        facts[key]=dict(value=value,asof=ref,source_url=source,note=app.text_value(row['note'],1500,True))
    return {'symbol':data['symbol'],'facts':facts}


def _segment(value):
    folded=sector_analysis.fold(value)
    return re.sub(r'[^a-z0-9]+',' ',re.sub(r'^fii\b','',folded)).strip()


def market_pvp(app,asset):
    """Manual current corrections, then current price/CVM VPA, then indicators."""
    snaps=asset.get('snapshots',{})
    def current(s,days):return bool(s.get('asof')) and 0<=app.age(s['asof'])<=days
    def numeric(v):return type(v) in (int,float) and math.isfinite(v)
    manual=snaps.get(KIND,{}).get('data',{}).get('facts',{}).get('pvp')
    if manual and current(manual,7):return manual['value'],manual,'P/VP conferido com fonte: '+manual['note']
    corrected=[s for k,s in snaps.items() if k in ('metric:pvp','risk') and 'pvp' in s.get('data',{}) and current(s,7)]
    if corrected:
        s=max(corrected,key=lambda r:(r['asof'],r.get('retrieved_at','')));v=s['data']['pvp']
        return (v if numeric(v) and v>0 else None),s,s.get('source','')
    report=snaps.get('fii_reports',{}).get('data',{});monthly=report.get('monthly',[])
    latest=monthly[-1] if monthly else {};quote=snaps.get('quote',{})
    if current(quote,7) and latest.get('date') and 0<=app.age(latest['date'])<=90:
        price=quote.get('data',{}).get('price');nav=latest.get('nav')
        if numeric(price) and numeric(nav):
            value=price/nav if price>0 and nav>0 else None
            return value,{'asof':quote['asof'],'source_url':latest.get('source_url','')},'Preço da cota / VPA CVM de '+latest['date']
    s=snaps.get('statistics',{});v=s.get('data',{}).get('pvp')
    fresh=current(s,7) and (not s.get('retrieved_at') or 0<=app.age(s['retrieved_at'])<=7)
    return (v if fresh and numeric(v) and v>0 else None),s,s.get('source','')


def assess(app,asset,profile):
    snaps=asset.get('snapshots',{});saved=snaps.get(KIND,{}).get('data',{});facts=saved.get('facts',{})
    reports=snaps.get('fii_reports',{}).get('data',{})
    physical=profile in ('tijolo','hibrido');not_physical=profile in ('papel','fof')
    checks=[]
    def fact(key,days=180):
        row=facts.get(key)
        return row if row and 0<=app.age(row['asof'])<=days else None
    def add(key,label,status,detail,rows=(),scope='quality'):
        refs=sorted({(r.get('asof') or r.get('date') or '',r.get('source_url') or r.get('url') or '') for r in rows if r})
        checks.append(dict(key='fii_quality_'+key,label=label,status=status,detail=detail,scope=scope,
            edit_action='fii-quality',edit_key=key,
            asof=min((d for d,_ in refs if d),default=None),source_url=next((u for _,u in refs if u),''),
            references=[{'asof':d,'url':u} for d,u in refs if u]))
    def physical_status(status):return 'na' if not_physical else status if physical else 'unknown'
    applicability=' Para papel e fundos de fundos, confira devedores, garantias e fundos investidos nos critérios próprios; imóveis das garantias não equivalem a imóveis próprios.'
    location=fact('prime_locations')
    add('location','Os imóveis ficam em regiões nobres?',physical_status('unknown' if not location else 'pass' if location['value'] else 'fail'),
        'Exige avaliação documentada da localização dos imóveis da carteira, cobertura e critérios de atratividade. Nome da cidade, classe do imóvel e baixa vacância não comprovam região nobre. '+
        (location or {}).get('note','')+applicability,[location])
    new,maintenance=fact('new_properties'),fact('low_maintenance')
    values=[r['value'] if r else None for r in (new,maintenance)]
    status='fail' if False in values else 'pass' if all(v is True for v in values) else 'unknown'
    add('properties','As propriedades são novas e não exigem manutenção excessiva?',physical_status(status),
        'Os dois pontos precisam ser confirmados: imóveis novos E manutenção sem consumo excessivo. Não é inferido um limite universal de idade ou despesa. '+
        ' '.join(r['note'] for r in (new,maintenance) if r)+applicability,[new,maintenance])
    pvp,ref,source=market_pvp(app,asset)
    discard=pvp is not None and pvp>1.5
    screen='discard' if discard else 'discount' if pvp is not None and pvp<1 else 'no_discount' if pvp is not None else 'unknown'
    detail=(f'P/VP: {pvp:.4f}×. ' if pvp is not None else 'Falta P/VP positivo com referência de preço recente. ')+\
        'Seu corte: abaixo de 1× atende ao desconto; de 1× até 1,5× não atende; acima de 1,5× aciona descarte obrigatório na triagem. Exatamente 1,5× não é acima de 1,5×. '+source
    add('pvp','O FII está abaixo de P/VP 1? Acima de 1,5: descartar.',
        'unknown' if pvp is None else 'pass' if pvp<1 else 'fail',detail,[ref],scope='price')
    # Forty-nine complete months distinguish >4 years from exactly 48 months.
    expected=app.today().year*12+app.today().month-1
    wanted={f'{n//12:04d}-{n%12+1:02d}' for n in range(expected-49,expected)}
    dividends=snaps.get('fii_dividends',{}).get('data',{})
    months={r['date'][:7] for r in dividends.get('items',[]) if r['type']=='RENDIMENTO' and not r['estimated'] and r['amount']>0 and r['date']<=app.today().isoformat()}
    record=fact('dividend_record');reviewed=False;rejected=False
    if record:
        value=record['value'];today=app.today()
        cutoff=(today.year-4,today.month,today.day)
        since=date.fromisoformat(value['since'])
        long=(since.year,since.month,since.day)<cutoff
        last_month=f'{(expected-1)//12:04d}-{(expected-1)%12+1:02d}'
        covers_latest=value['through'][:7]>=last_month
        reviewed=long and covers_latest and value['consistent']
        rejected=covers_latest and not value['consistent']
    status='fail' if rejected else 'pass' if wanted<=months or reviewed else 'unknown'
    add('dividends','Distribui rendimentos consistentemente há mais de 4 anos?',status,
        f'{len(wanted & months)} de 49 meses completos com pagamentos positivos confirmados. '+
        'Convenção de consistência: mensal. Amortizações, datas ex e eventos estimados não contam. Falha de coleta não significa falta de pagamento. '+
        ('Conferência documental: '+record['value']['since']+' a '+record['value']['through']+'. '+record['note'] if record else 'Também é possível registrar uma conferência documental do intervalo e da consistência.'),
        [record,{'source_url':dividends.get('source_url','')}])
    tenant,prop=fact('single_tenant_dependence'),fact('single_property_dependence')
    single_tenant=tenant['value'] if tenant else None;single_property=prop['value'] if prop else None
    quarters=reports.get('quarterly',[]);q=quarters[-1] if quarters else {}
    # A 100% revenue property can disprove diversification; several buildings
    # never prove that tenants are different or that cash flows are independent.
    mono=bool(q) and 0<=app.age(q['date'])<=180 and any(
        p.get('revenue_share') is not None and p['revenue_share']>=1 for p in q.get('properties',[]))
    # A documented subsequent portfolio change may supersede the old quarter.
    if mono and prop and prop['value'] is False and prop['asof']>q['date']:
        mono=False
    status='fail' if single_tenant is True or single_property is True or mono else 'pass' if single_tenant is False and single_property is False else 'unknown'
    add('dependence','Não depende de um único inquilino nem de um único imóvel?',physical_status(status),
        'Confira separadamente inquilinos/grupos econômicos e imóveis. Ter vários imóveis não comprova diversidade de inquilinos. Não foi inventado um percentual mínimo de diversificação. '+
        ('O informe atribui 100% da receita a um imóvel. ' if mono else '')+applicability,[tenant,prop,q if mono else None])
    benchmark=fact('peer_yield',31);value=benchmark['value'] if benchmark else {}
    segment=reports.get('profile',{}).get('segment') or asset.get('sector','')
    comparable=bool(benchmark and profile!='unknown' and value['type']==profile and _segment(value['segment'])==_segment(segment) and value['peer_count']>=2)
    status=('pass' if value['fund_yield']>=value['mean_yield'] else 'fail') if comparable else 'unknown'
    add('yield','O yield está dentro ou acima da média de FIIs do mesmo tipo?',status,
        ('DY do fundo: '+f'{value["fund_yield"]:.4f}% · média aritmética: {value["mean_yield"]:.4f}% · {value["peer_count"]} outros FIIs. ' if benchmark else '')+
        '“Dentro da média” significa igual à média; acima também atende. Exige mesmo tipo E segmento, mesma data-base e pagamentos de 12 meses, com ao menos dois pares. '
        'A referência é a amostra ou média publicada identificada pela fonte, sem usar automaticamente sua lista pessoal como média do mercado. DY patrimonial mensal não substitui DY de mercado anual. '+
        (benchmark['note'] if benchmark else ''),[benchmark],scope='price')
    return {'checks':checks,'facts':saved,'screening':{'status':screen,'pvp':pvp,'discard':discard,'detail':detail}}
