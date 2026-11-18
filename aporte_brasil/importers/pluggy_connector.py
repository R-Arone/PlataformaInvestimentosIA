"""Optional, read-only connector to Meu Pluggy (Open Finance). Off by default and never stores credentials.

The user brings the clientId/clientSecret of a Pluggy development application and the itemIds of the
connections made in Meu Pluggy. Only api.pluggy.ai is contacted. Trades go to the same reviewed B3 preview
(duplicates, balance checks, confirmation); positions are shown next to the local wallet, read-only.
"""
import csv
import io
import json
import re
import urllib.error
import urllib.request

API = 'https://api.pluggy.ai'
UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
TICKER = re.compile(r'^[A-Z]{4}\d{1,2}$')
LISTED = {'EQUITY': ('STOCK', 'BDR', 'REAL_ESTATE_FUND'), 'ETF': ('ETF',)}
MAX_PAGES = 20


def http(method, path, body=None, key=''):
    """Single place that touches the network; tests replace it."""
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'AporteBrasil/1.0'}
    if key: headers['X-API-KEY'] = key
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read(8_000_000))
    except urllib.error.HTTPError as exc:
        raise ValueError({401: 'Credenciais da Pluggy recusadas. Confira clientId e clientSecret.', 403: 'A Pluggy negou o acesso a este item.',
                          404: 'Item não encontrado na Pluggy. Confira o itemId.', 429: 'A Pluggy limitou as consultas; tente de novo mais tarde.'}
                         .get(exc.code, 'Pluggy indisponível (erro ' + str(exc.code) + ').'))
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('Sem conexão com a Pluggy.')


def pages(path, key, fetch, **params):
    out = []
    for page in range(1, MAX_PAGES + 1):
        query = '&'.join(f'{k}={v}' for k, v in {**params, 'pageSize': 500, 'page': page}.items())
        data = fetch('GET', path + ('&' if '?' in path else '?') + query, None, key)
        out.extend(data.get('results', []))
        if page >= int(data.get('totalPages') or 1): break
    return out


def listed_ticker(inv):
    for text in (inv.get('code'), inv.get('name')):
        for token in re.split(r'[\s/-]+', str(text or '').upper()):
            if TICKER.match(token): return token
    return None


def read(app, d, fetch=None):
    fetch = fetch or http
    if d.get('consent') is not True: raise ValueError('Confirme que entende que seus dados passam pela Pluggy.')
    client_id, secret = str(d.get('client_id', '')).strip(), str(d.get('client_secret', '')).strip()
    if not UUID.match(client_id) or not 8 <= len(secret) <= 200: raise ValueError('Informe o clientId (UUID) e o clientSecret da sua aplicação Pluggy.')
    items = d.get('item_ids')
    if not isinstance(items, list) or not 1 <= len(items) <= 10 or not all(isinstance(i, str) and UUID.match(i.strip()) for i in items):
        raise ValueError('Informe de 1 a 10 itemIds (UUID) das conexões feitas no Meu Pluggy.')
    institution = app.text_value(d.get('institution', ''), 150, True)
    since = app.valid_date(d['since'], True) if d.get('since') else ''
    key = fetch('POST', '/auth', {'clientId': client_id, 'clientSecret': secret}, '').get('apiKey')
    if not key: raise ValueError('A Pluggy não devolveu a chave de acesso.')
    positions, trades, warnings, skipped = [], [], [], 0
    for item in [i.strip() for i in items]:
        for inv in pages('/investments', key, fetch, itemId=item):
            kind, sub = inv.get('type'), inv.get('subtype')
            bank = ((inv.get('institution') or {}).get('name') or institution)[:150]
            ticker = listed_ticker(inv) if sub in LISTED.get(kind, ()) else None
            positions.append({'item': item, 'name': str(inv.get('name', ''))[:150], 'type': kind, 'subtype': sub, 'ticker': ticker, 'institution': bank,
                              'quantity': inv.get('quantity'), 'balance': inv.get('balance'), 'date': (inv.get('date') or '')[:10],
                              'due_date': (inv.get('dueDate') or '')[:10], 'issuer': str(inv.get('issuer') or '')[:150],
                              'rate_type': inv.get('rateType'), 'rate': inv.get('rate'), 'status': inv.get('status')})
            if not ticker: continue
            for t in pages(f"/investments/{inv['id']}/transactions", key, fetch):
                side = {'BUY': 'buy', 'SELL': 'sell'}.get(str(t.get('type')).upper())
                day = str(t.get('tradeDate') or t.get('date') or '')[:10]
                try: quantity = float(t.get('quantity')); amount = float(t.get('amount') if t.get('amount') is not None else t.get('value') * quantity)
                except (TypeError, ValueError): side = None
                if not side or not day or since and day < since: skipped += 1; continue
                quantity, amount = abs(quantity), abs(amount)
                if quantity <= 0 or amount <= 0: skipped += 1; continue
                costs = t.get('expenses') if isinstance(t.get('expenses'), dict) else {}
                fees = sum(abs(float(v)) for k, v in costs.items() if isinstance(v, (int, float)) and 'tax' not in k.lower() or k.lower() in ('brokeragefee', 'custodyfee', 'stockexchangefee'))
                trades.append({'date': day, 'side': side, 'ticker': ticker, 'quantity': quantity, 'price': amount / quantity, 'amount': amount, 'fees': round(fees, 2),
                               'institution': bank or 'Não informada', 'note': t.get('brokerageNumber') or ''})
    with app.connect() as c:
        local = {}
        for a in c.execute('SELECT id,ticker FROM assets WHERE archived=0'):
            local[a['ticker']] = app.position(app.asset_ledger(c, a['id']))['quantity']
    for p in positions:
        if p['ticker']:
            mine = local.get(p['ticker'], 0.0)
            p['local_quantity'] = mine
            p['status_check'] = 'ok' if p['quantity'] is not None and abs(float(p['quantity']) - mine) < 1e-6 else 'different'
    if skipped: warnings.append(f'{skipped} movimentação(ões) sem tipo BUY/SELL, data ou valores utilizáveis foram ignoradas.')
    if any(not t['institution'] or t['institution'] == 'Não informada' for t in trades): warnings.append('Algumas operações vieram sem corretora; informe uma corretora padrão.')
    warnings.append('A qualidade dos dados do Open Finance varia por instituição: confira quantidades e datas na prévia. Custos ausentes ficam zerados.')
    out = io.StringIO(newline=''); w = csv.writer(out, delimiter=';', lineterminator='\n')
    w.writerow(['Data', 'Movimentação', 'Produto', 'Instituição', 'Mercado', 'Quantidade', 'Preço unitário', 'Valor da Operação', 'Custos'])
    fmt = lambda v: f'{v:.8f}'.rstrip('0').rstrip('.').replace('.', ',') or '0'
    for t in sorted(trades, key=lambda t: (t['date'], t['ticker'])):
        w.writerow([t['date'][8:] + '/' + t['date'][5:7] + '/' + t['date'][:4], 'Compra' if t['side'] == 'buy' else 'Venda', t['ticker'], t['institution'],
                    'Mercado à Vista', fmt(t['quantity']), fmt(t['price']), fmt(round(t['amount'], 2)), fmt(t['fees'])])
    return {'positions': positions, 'trade_count': len(trades), 'csv': out.getvalue() if trades else '', 'filename': 'Meu Pluggy · ' + str(len(items)) + ' conexão(ões)',
            'warnings': warnings, 'notes': ['Somente leitura: nada foi salvo e as credenciais não são guardadas pelo app.',
                                            'Posições de renda fixa e fundos aparecem só como referência; cadastre-as na tela de renda fixa ou use o extrato da B3.']}
