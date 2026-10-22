"""Public market identities, source metadata and currency-cost calculations."""
from datetime import datetime, timezone
import json
import re
import urllib.parse

ASSET_TYPES = {'stock': 'Ação', 'fii': 'Fundo imobiliário', 'etf': 'ETF', 'crypto': 'Bitcoin', 'bdr':'BDR', 'foreign':'Stock dos EUA', 'global_stock':'Stock internacional', 'global_etf':'ETF internacional'}
FIXED_TYPES = ['Tesouro', 'CDB', 'LCI', 'LCA', 'CRI', 'CRA', 'Fundo de renda fixa',
               'Fundo de investimento', 'Fundo multimercado', 'Fundo de ações', 'Previdência', 'CDB/LCI/LCA', 'Outro']
INSTITUTIONS = ['Banco do Brasil', 'Itaú', 'Bradesco', 'Santander', 'Caixa', 'Nubank', 'Inter',
                'BTG Pactual', 'XP', 'Rico', 'Clear', 'Ágora', 'Genial', 'Modal', 'C6 Bank',
                'Sofisa', 'Daycoval', 'PagBank', 'Mercado Pago', 'Binance', 'Coinbase',
                'Mercado Bitcoin', 'Carteira própria', 'Não informada']
SECTOR_TRANSLATIONS = {'Retail Trade': 'Comércio varejista', 'Energy Minerals': 'Petróleo e gás',
    'Health Services': 'Serviços de saúde', 'Utilities': 'Energia e saneamento', 'Finance': 'Financeiro',
    'Consumer Services': 'Serviços ao consumidor', 'Consumer Non-Durables': 'Bens de consumo não duráveis',
    'Non-Energy Minerals': 'Mineração e siderurgia', 'Commercial Services': 'Serviços comerciais',
    'Distribution Services': 'Distribuição', 'Transportation': 'Transportes', 'Technology Services': 'Tecnologia',
    'Process Industries': 'Indústria de transformação', 'Communications': 'Telecomunicações',
    'Producer Manufacturing': 'Bens industriais', 'Miscellaneous': 'Diversos',
    'Electronic Technology': 'Tecnologia eletrônica', 'Industrial Services': 'Serviços industriais',
    'Health Technology': 'Tecnologia em saúde', 'Consumer Durables': 'Bens de consumo duráveis'}
BASE_SECTORS = ['Bancos', 'Seguradoras', 'Serviços financeiros', 'Petróleo e gás', 'Energia elétrica',
    'Água e saneamento', 'Mineração', 'Siderurgia', 'Papel e celulose', 'Alimentos', 'Varejo',
    'Construção e incorporação', 'Transportes', 'Telecomunicações', 'Tecnologia', 'Saúde', 'Educação',
    'Agronegócio', 'Bens industriais', 'FII · Papel', 'FII · Logística', 'FII · Shoppings',
    'FII · Lajes corporativas', 'FII · Híbrido', 'FII · A definir', 'ETF · Ações Brasil',
    'ETF · Renda fixa', 'ETF · Ações exterior', 'ETF · Cripto', 'ETF · A definir', 'Criptoativos', 'Não classificado']
SOURCE_URLS = {
    'catalog': 'https://brapi.dev/docs/openapi',
    'selic': 'https://dadosabertos.bcb.gov.br/dataset/432-taxa-de-juros---meta-selic-definida-pelo-copom',
    'cdi': 'https://www3.bcb.gov.br/sgspub/consultarvalores/consultarValoresSeries.do?method=consultarSeries&series=4389',
    'ipca': 'https://www3.bcb.gov.br/sgspub/consultarvalores/consultarValoresSeries.do?method=consultarSeries&series=13522',
    'usd': 'https://dadosabertos.bcb.gov.br/dataset/1-taxa-de-cambio---livre---dolar-americano-venda---diario',
    'bitcoin': 'https://docs.cdp.coinbase.com/coinbase-app/track-apis/prices',
    'sentiment': 'https://alternative.me/crypto/fear-and-greed-index/'}


def normalize_sector(item, typ):
    sub = str(item.get('subsector') or '').strip()
    if typ == 'etf':
        from investment_exposure import etf_sector
        return etf_sector({'ticker':str(item.get('symbol') or '').upper(),'asset_type':'etf'})
    if typ == 'fii':
        return 'FII · ' + sub if sub and sub not in ('Fundos Imobiliários', 'Outros') else 'FII · A definir'
    aliases = {'Bancos Diversificados': 'Bancos', 'Exploração. Refino e Distribuição': 'Petróleo e gás',
               'Exploração, Refino e Distribuição': 'Petróleo e gás', 'Petróleo e Gás Integrado': 'Petróleo e gás',
               'Energia Elétrica': 'Energia elétrica', 'Água e Saneamento': 'Água e saneamento'}
    if sub:
        canonical = {s.casefold():s for s in BASE_SECTORS}
        canonical.update({s.casefold():v for s,v in aliases.items()})
        canonical.update({'aluguel de carros':'Aluguel de carros','açucar e alcool':'Açúcar e álcool',
            'açúcar e álcool':'Açúcar e álcool','mineração de minerais metálicos':'Mineração',
            'serv.méd.hospit..análises e diagnósticos':'Serviços de saúde',
            'máq. e equip. industriais':'Máquinas e equipamentos industriais',
            'máquinas e equipamentos industriais':'Máquinas e equipamentos industriais',
            'tecidos. vestuário e calçados':'Tecidos, vestuário e calçados',
            'tecidos, vestuário e calçados':'Tecidos, vestuário e calçados'})
        return canonical.get(sub.casefold(),sub)
    return SECTOR_TRANSLATIONS.get(item.get('sector'), 'Não classificado')


def normalize_catalog(payload, retrieved_at):
    result = []
    symbols = {str(r.get('symbol','')).upper() for r in payload.get('results', [])}
    for row in payload.get('results', []):
        typ = row.get('subType')
        if typ == 'unit':
            typ = 'stock'
        ticker = str(row.get('symbol', '')).upper()
        # Fractional-market aliases represent the same security, not a second holding.
        if ticker.endswith('F') and ticker[:-1] in symbols:
            continue
        if typ not in ('stock', 'fii', 'etf', 'bdr') or row.get('exchange') != 'B3' or not row.get('isActive'):
            continue
        if not re.fullmatch(r'[A-Z0-9]{4,12}', ticker):
            continue
        name = str(row.get('longName') or row.get('name') or ticker)[:150]
        sector = normalize_sector(row, typ)[:100]
        result.append({'ticker': ticker, 'name': name, 'asset_type': typ, 'sector': sector,
                       'financial': int(typ == 'stock' and (sector in ('Bancos', 'Seguradoras', 'Resseguradoras') or
                           any(w in sector.lower() for w in ('seguros', 'crédito', 'financiamento')))),
                       'source': 'brapi · catálogo B3', 'retrieved_at': retrieved_at})
    return result


def fetch_catalog(request_json, now):
    all_rows = []
    for page in range(1, 11):
        payload = request_json(f'https://brapi.dev/api/v2/tickers?limit=2000&page={page}&sortBy=symbol&sortOrder=asc')
        if not isinstance(payload.get('results'), list):
            raise ValueError('A fonte não retornou o catálogo esperado.')
        all_rows.extend(payload['results'])
        if not payload.get('pagination', {}).get('hasNextPage'):
            return normalize_catalog({'results': all_rows}, now())
    raise ValueError('Catálogo excedeu o limite de páginas; a lista anterior foi preservada.')


def source_href(asset, kind):
    if asset.get('asset_type') == 'crypto':
        return 'https://api.coinbase.com/v2/prices/BTC-BRL/spot'
    if asset.get('asset_type') == 'fii' and kind == 'statistics':
        return 'https://brapi.dev/api/v2/fii/indicators?symbols=' + urllib.parse.quote(asset['ticker'])
    if asset.get('asset_type') == 'fii' and kind == 'metric:vacancy':
        return 'https://brapi.dev/api/v2/fii/properties?symbols=' + urllib.parse.quote(asset['ticker'])
    ep = {'quote': 'quote', 'statistics': 'statistics', 'financial': 'financial-data', 'history': 'historical'}[kind]
    return 'https://brapi.dev/api/v2/stocks/' + ep + '?symbols=' + urllib.parse.quote(asset['ticker'])


def fetch_fii(asset, request_json, token, valid_date, clean, today):
    p = request_json(source_href(asset, 'statistics'), token)
    rows = [r for r in p.get('fiis', []) if isinstance(r,dict) and r.get('symbol') == asset['ticker']]
    if len(rows)!=1:
        raise ValueError('Indicadores de FII não disponíveis no plano.')
    r=rows[0]
    ref = valid_date(str(r.get('asOfDate') or '')[:10])
    if ref > today().isoformat():
        raise ValueError('FII com referência futura.')
    dy = clean(r.get('dividendYield12m'))
    if isinstance(r.get('dividendYield12m'),bool) or dy is not None and dy<0:
        dy=None
    return 'statistics', {'pvp': clean(r.get('priceToNav')), 'pe': None,
        'dy': dy*100 if dy is not None else None, 'nav': clean(r.get('navPerShare'))}, ref


def fetch_fii_vacancy(asset, request_json, token, valid_date, clean, today):
    """Only complete, area-weighted physical vacancy; missing disclosure is not zero."""
    p = request_json(source_href(asset, 'metric:vacancy'), token)
    rows = [r for r in p.get('fiis', []) if isinstance(r, dict) and r.get('symbol') == asset['ticker']]
    if len(rows) != 1:
        raise ValueError('Imóveis do FII indisponíveis nesta fonte ou plano.')
    r = rows[0]
    ref = valid_date(str(r.get('referenceDate') or '')[:10])
    if ref > today().isoformat():
        raise ValueError('Vacância com referência futura.')
    s = r.get('summary') or {}
    value = clean(s.get('vacancyRate'))
    count = s.get('count')
    if (value is None or not 0 <= value <= 1 or isinstance(s.get('vacancyRate'), bool)
            or not isinstance(count, int) or isinstance(count, bool) or count <= 0
            or isinstance(s.get('propertiesWithVacancy'),bool) or s.get('propertiesWithVacancy') != count
            or isinstance(s.get('totalArea'),bool) or (clean(s.get('totalArea')) or 0) <= 0):
        raise ValueError('Vacância física ponderada sem cobertura completa de imóveis e áreas; confira o relatório gerencial.')
    return 'metric:vacancy', {'vacancy': value*100}, ref


def fetch_bitcoin(request_json, number, now, today):
    p = request_json('https://api.coinbase.com/v2/prices/BTC-BRL/spot')
    d = p.get('data', {})
    if d.get('base') != 'BTC' or d.get('currency') != 'BRL':
        raise ValueError('Cotação de Bitcoin retornou moeda inesperada.')
    return {'price': number(d.get('amount'), True, .00000001), 'observed_at': now()}, today().isoformat()


def fetch_sentiment(request_json, number, today):
    p = request_json('https://api.alternative.me/fng/?limit=90&format=json')
    points = []
    for r in p.get('data', []):
        ref = datetime.fromtimestamp(int(r['timestamp']), timezone.utc).date().isoformat()
        if ref <= today().isoformat():
            points.append({'date': ref, 'value': number(r['value'], True, 0, 100),
                           'classification': str(r.get('value_classification', ''))[:50]})
    if not points:
        raise ValueError('Índice de sentimento sem observações até hoje.')
    return sorted(points, key=lambda p: p['date'])


def fx_projection(d, number):
    budget = number(d.get('budget'), True, .01, 1e12)
    base = number(d.get('exchange'), True, .00001, 10000)
    spread = number(d.get('spread'), True, 0, 100)
    percent_fee = number(d.get('percent_fee'), True, 0, 100)
    fixed_fee = number(d.get('fixed_fee'), True, 0, 1e12)
    iof = number(d.get('iof'), True, 0, 100)
    mode = d.get('mode', 'budget')
    if mode not in ('budget', 'dollars'):
        raise ValueError('Modo de câmbio inválido.')
    quoted = base * (1 + spread / 100)
    factor = 1 + (percent_fee + iof) / 100
    if mode == 'budget':
        if budget <= fixed_fee:
            raise ValueError('O orçamento deve superar a tarifa fixa.')
        converted = (budget - fixed_fee) / factor
        usd = converted / quoted
        total = budget
    else:
        usd = budget
        converted = usd * quoted
        total = converted * factor + fixed_fee
    spread_brl = usd * (quoted - base)
    tax = converted * iof / 100
    fee = fixed_fee + converted * percent_fee / 100
    no_cost = usd * base
    return {'usd': usd, 'total': total, 'quoted_rate': quoted, 'effective_rate': total/usd,
            'spread_cost': spread_brl, 'tax_cost': tax, 'fee_cost': fee,
            'total_cost': total-no_cost, 'cost_percent': (total/no_cost-1)*100,
            'base_cost': no_cost}
