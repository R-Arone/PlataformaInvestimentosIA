"""Read-only comparison between the B3 'Posição' statement and the local wallet.

Nothing is saved. Differences come with the most likely cause to review; quantities
are never adjusted automatically.
"""
import json
import re
import b3_import
import treasury_import
from csv_import import key

# Sheet name (folded) -> category compared with the local wallet.
CATEGORIES = {'acoes': 'stock', 'acao': 'stock', 'bdr': 'bdr', 'bdrs': 'bdr', 'etf': 'etf', 'etfs': 'etf',
              'fundo de investimento': 'fii', 'fundos de investimento': 'fii', 'fundos imobiliarios': 'fii', 'fii': 'fii',
              'tesouro direto': 'treasury', 'renda fixa': 'bank_fixed'}
LABELS = {'stock': 'Ações', 'bdr': 'BDRs', 'etf': 'ETFs', 'fii': 'Fundos listados', 'treasury': 'Tesouro Direto', 'bank_fixed': 'Renda fixa'}
TYPE_CATEGORY = {'stock': 'stock', 'bdr': 'bdr', 'etf': 'etf', 'fii': 'fii'}
FIELDS = {'code': ['codigo de negociacao', 'codigo'], 'product': ['produto'], 'institution': ['instituicao'],
          'quantity': ['quantidade'], 'value': ['valor atualizado', 'valor atualizado mtm', 'valor liquido'],
          'price': ['preco de fechamento', 'preco atualizado mtm']}
DATE_HEADERS = {'data', 'data do negocio', 'data de negociacao', 'movimentacao'}


def header(sheet):
    for i, row in enumerate(sheet['rows'][:30]):
        names = [str(v).strip() for v in row['values']]
        folded = [key(h) for h in names]
        found = {f: next((names[j] for j, h in enumerate(folded) if h in aliases), '') for f, aliases in FIELDS.items()}
        if found['quantity'] and found['institution'] and (found['code'] or found['product']):
            if DATE_HEADERS & set(folded):
                return None, {}, True  # Negociação/Movimentação, not a position statement.
            return i, {f: names.index(h) if h else None for f, h in found.items()}, False
    return None, {}, False


def category(sheet_name, ticker):
    folded = key(sheet_name)
    for name, cat in CATEGORIES.items():
        if folded == name or folded.startswith(name+' '):
            return cat
    if treasury_import.product(ticker or ''): return 'treasury'
    return None


def identify(code, product):
    raw = ' '.join(str(product or '').upper().split())
    treasury = treasury_import.product(raw)
    if treasury: return treasury, 'treasury'
    bank = treasury_import.bank_product(raw)
    if bank: return bank['ticker'], 'bank_fixed'
    for text in (str(code or '').strip().upper(), raw):
        m = re.match(r'^([A-Z0-9]{3,8}\d{1,2})F?(?:\s|$|[-.])', text)
        if m: return m[1], None
    return None, None


def hint(b3, local, other_banks, other_b3=()):
    if local <= 0:
        if other_banks: return 'Mesmo ativo com saldo local em '+', '.join(other_banks)+'. Confira o nome da instituição (equivalência abaixo) ou uma transferência de custódia.'
        return 'Sem histórico local nessa instituição. Importe Negociação/Movimentação do período ou cadastre a posição que já tem.'
    if b3 <= 0:
        if other_b3: return 'A B3 mostra este ativo em '+', '.join(other_b3)+'. Confira o nome da instituição (equivalência abaixo) ou uma transferência de custódia.'
        return 'Saldo local sem posição na B3 nessa data. Confira vendas, transferências, resgates ou a data do extrato.'
    r = b3/local
    for big, text in ((r, 'Pode faltar um desdobramento ou bonificação. Importe a Movimentação do período.'),
                      (1/r, 'Pode faltar um grupamento. Importe a Movimentação do período.')):
        if big >= 1.99 and abs(big-round(big)) <= .01: return text
    if 0 < b3-local < 1 and abs(b3-round(b3)) > 1e-9 or 0 < local-b3 < 1:
        return 'Diferença menor que uma unidade: confira frações de bonificação/grupamento e leilão de frações.'
    if b3 > local: return 'B3 tem mais unidades: pode faltar compra, bonificação, subscrição ou transferência recebida.'
    return 'B3 tem menos unidades: pode faltar venda, grupamento, fração retirada ou transferência enviada.'


def local_positions(app, c, asof):
    result = {}
    for a in c.execute('SELECT id,ticker,asset_type FROM assets WHERE archived=0'):
        cat = TYPE_CATEGORY.get(a['asset_type'])
        if not cat: continue
        ledger = [t for t in app.asset_ledger(c, a['id']) if t['date'] <= asof]
        if not ledger: continue
        for pool in app.position(ledger)['institutions']:
            result[(a['ticker'], pool['institution'])] = {'quantity': pool['quantity'], 'category': cat, 'cost': pool['cost']}
    for f in c.execute('SELECT name,institution,metadata,balance FROM fixed WHERE archived=0'):
        metadata = json.loads(f['metadata'])
        ledger = treasury_import.ledger(metadata)
        cat = 'bank_fixed' if 'bank_fixed' in metadata else 'treasury' if 'treasury' in metadata else None
        if not cat: continue
        transactions = [t for t in ledger.get('transactions', []) if t['date'] <= asof]
        quantity = app.position(transactions)['quantity'] if transactions else 0
        result[(f['name'].upper(), f['institution'])] = {'quantity': quantity, 'category': cat, 'cost': None}
    return result


def check(app, d):
    if d.get('xlsx'): sheets = b3_import.read_xlsx(d['xlsx'])
    elif d.get('csv'): sheets = b3_import.read_csv(d['csv'])
    else: raise ValueError('Envie o Excel do extrato de Posição da B3.')
    filename = app.text_value(d.get('filename', 'Posição B3'), 200, True)
    found_date = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    asof = app.valid_date(d.get('asof') or (found_date[1] if found_date else app.today().isoformat()))
    if asof > app.today().isoformat(): raise ValueError('A data da posição não pode ser futura.')
    institution_map = d.get('institution_map', {})
    if not isinstance(institution_map, dict) or len(institution_map) > 200: raise ValueError('Nomes de instituições inválidos.')
    institution_map = {app.text_value(k, 150, True): app.text_value(v, 150, True) for k, v in institution_map.items()}
    b3, unmatched, used, skipped, wrong_file = {}, [], [], [], False
    for sh in sheets:
        start, cols, movement = header(sh)
        wrong_file = wrong_file or movement
        if start is None:
            skipped.append(sh['name']); continue
        get = lambda row, f: row['values'][cols[f]] if cols.get(f) is not None and cols[f] < len(row['values']) else ''
        used.append(sh['name'])
        for row in sh['rows'][start+1:]:
            if not any(str(v).strip() for v in row['values']): continue
            first = key(str(row['values'][0]) if row['values'] else '')
            if first.startswith('total') or key(str(get(row, 'institution'))).startswith('total'): continue
            ticker, kind = identify(get(row, 'code'), get(row, 'product'))
            label = str(get(row, 'product') or get(row, 'code'))[:150]
            try:
                quantity = b3_import.numeric(app, get(row, 'quantity'), 'Quantidade', True)
                value = b3_import.numeric(app, get(row, 'value'), 'Valor atualizado', True)
            except ValueError as exc:
                unmatched.append({'sheet': sh['name'], 'line': row['line'], 'product': label, 'reason': str(exc)}); continue
            if not ticker or quantity is None:
                unmatched.append({'sheet': sh['name'], 'line': row['line'], 'product': label,
                                  'reason': 'Produto sem código reconhecido; confira manualmente.' if not ticker else 'Quantidade ausente.'}); continue
            original = app.text_value(str(get(row, 'institution') or 'Não informada'), 150, True)
            bank = institution_map.get(original, original)
            cat = kind or category(sh['name'], ticker) or 'stock'
            item = b3.setdefault((ticker, bank), {'quantity': 0.0, 'value': 0.0, 'has_value': False, 'category': cat, 'sheet': sh['name'], 'product': label})
            item['quantity'] += quantity
            if value is not None: item['value'] += value; item['has_value'] = True
    if not used:
        raise ValueError('Este arquivo parece ser Negociação ou Movimentação. Baixe na B3 o extrato de Posição (Extratos → Posição) em Excel.' if wrong_file
                         else 'Não encontrei abas de posição com Produto, Instituição e Quantidade. Baixe na B3 o extrato de Posição em Excel.')
    with app.connect() as c:
        local = local_positions(app, c, asof)
    covered = {v['category'] for v in b3.values()}
    rows = []
    for ident in sorted(set(b3) | {k for k, v in local.items() if v['category'] in covered and v['quantity'] > 1e-9}):
        ticker, bank = ident
        theirs, mine = b3.get(ident), local.get(ident)
        q_b3 = theirs['quantity'] if theirs else 0.0
        q_local = mine['quantity'] if mine else 0.0
        diff = q_b3 - q_local
        status = 'ok' if abs(diff) <= max(1e-6, abs(q_b3)*1e-9) else 'only_b3' if q_local <= 1e-9 else 'only_local' if q_b3 <= 1e-9 else 'different'
        others = [b for (t, b), v in local.items() if t == ticker and b != bank and v['quantity'] > 1e-9 and (t, b) not in b3]
        others_b3 = [b for (t, b) in b3 if t == ticker and b != bank and (t, b) not in local]
        cat = (theirs or mine)['category']
        rows.append({'ticker': ticker, 'institution': bank, 'category': cat, 'category_label': LABELS[cat], 'status': status,
                     'b3_quantity': q_b3, 'local_quantity': q_local, 'difference': diff,
                     'b3_value': theirs['value'] if theirs and theirs['has_value'] else None,
                     'local_cost': mine['cost'] if mine else None,
                     'product': theirs['product'] if theirs else '', 'sheet': theirs['sheet'] if theirs else '',
                     'hint': '' if status == 'ok' else hint(q_b3, q_local, others, others_b3)})
    order = {'different': 0, 'only_b3': 1, 'only_local': 2, 'ok': 3}
    rows.sort(key=lambda r: (order[r['status']], r['category'], r['ticker'], r['institution']))
    summary = {s: sum(r['status'] == s for r in rows) for s in order}
    return {'asof': asof, 'filename': filename, 'sheets': used, 'skipped_sheets': skipped, 'categories': [LABELS[c] for c in sorted(covered)],
            'rows': rows, 'summary': summary, 'unmatched': unmatched[:100], 'unmatched_count': len(unmatched),
            'institutions': sorted({b for (_, b) in b3}),
            'notes': ['Somente leitura: nada foi salvo ou ajustado.',
                      'A carteira local é calculada até '+asof+', com compras, vendas e eventos corporativos registrados.',
                      'Só as classes presentes no arquivo são comparadas; ausência de uma aba não indica saldo zero.',
                      'Tesouro e renda fixa comparam quantidade de títulos; saldo financeiro e marcação a mercado ficam como referência.']}
