"""Reviewed update of fixed-income balances from the B3 'Posição' statement.

The preview never writes. Commit only updates balance, balance date and (when still empty)
maturity of products that already exist locally, plus products the user explicitly selects
to create. Rate, indexer and tax are never guessed from the statement.
"""
import base64
import hashlib
import json
import re
import secrets
import time
import b3_import
import b3_position
import treasury_import
from csv_import import key

FIELDS = {'product': ['produto'], 'institution': ['instituicao'], 'issuer': ['emissor'], 'maturity': ['vencimento', 'data de vencimento'],
          'quantity': ['quantidade'],
          'value': ['valor atualizado curva', 'valor atualizado mtm', 'valor atualizado', 'valor liquido', 'valor bruto']}
FIXED_SHEETS = ('tesouro direto', 'renda fixa')


def fixed_sheet(name):
    folded = key(name)
    return any(folded == n or folded.startswith(n + ' ') for n in FIXED_SHEETS)


def header(sheet):
    for i, row in enumerate(sheet['rows'][:30]):
        names = [str(v).strip() for v in row['values']]
        folded = [key(h) for h in names]
        found = {}
        for field, aliases in FIELDS.items():
            # Alias order is the order of preference (e.g. curve value before market value).
            found[field] = next((folded.index(a) for a in aliases if a in folded), None)
        if found['product'] is not None and found['institution'] is not None and found['quantity'] is not None and found['value'] is not None:
            column = names[found['value']]
            return i, found, column
    return None, {}, ''


def local_fixed(c):
    result = {}
    for f in c.execute('SELECT id,name,type,institution,balance,balance_date,maturity,metadata FROM fixed WHERE archived=0'):
        result[(f['name'].upper(), f['institution'])] = dict(f)
    return result


def revision(c):
    rows = [dict(r) for r in c.execute('SELECT id,name,institution,balance,balance_date,maturity,archived FROM fixed ORDER BY id')]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def parse(app, d):
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
    items, unmatched, used = {}, [], []
    for sh in sheets:
        if not fixed_sheet(sh['name']): continue
        start, cols, column = header(sh)
        if start is None: continue
        used.append(sh['name'])
        for row in sh['rows'][start + 1:]:
            values = row['values']
            if not any(str(v).strip() for v in values): continue
            get = lambda f: values[cols[f]] if cols.get(f) is not None and cols[f] < len(values) else ''
            if key(str(values[0]) if values else '').startswith('total') or key(str(get('institution'))).startswith('total'): continue
            label = ' '.join(str(get('product')).split())[:150]
            ticker, kind = b3_position.identify('', label)
            if kind not in ('treasury', 'bank_fixed'):
                unmatched.append({'sheet': sh['name'], 'line': row['line'], 'product': label,
                                  'reason': 'Produto de renda fixa sem formato reconhecido (Tesouro, CDB, LCI ou LCA). Cadastre manualmente.'}); continue
            try:
                quantity = b3_import.numeric(app, get('quantity'), 'Quantidade', True)
                value = b3_import.numeric(app, get('value'), column, True)
                maturity = '' if b3_import.missing(get('maturity')) else b3_import.date_value(get('maturity'), sh.get('date1904', False))
            except ValueError as exc:
                unmatched.append({'sheet': sh['name'], 'line': row['line'], 'product': label, 'reason': str(exc)}); continue
            if value is None:
                unmatched.append({'sheet': sh['name'], 'line': row['line'], 'product': label, 'reason': 'Valor atualizado ausente.'}); continue
            original = app.text_value(str(get('institution') or 'Não informada'), 150, True)
            bank = institution_map.get(original, original)
            item = items.setdefault((ticker, bank), {'name': ticker, 'institution': bank, 'kind': kind, 'value': 0.0, 'quantity': 0.0,
                                                     'maturity': maturity, 'issuer': ' '.join(str(get('issuer')).split())[:200], 'column': column, 'sheet': sh['name']})
            item['value'] += value
            item['quantity'] += quantity or 0.0
            if maturity and not item['maturity']: item['maturity'] = maturity
    if not used:
        raise ValueError('Não encontrei as abas Tesouro Direto ou Renda Fixa com Produto, Instituição, Quantidade e Valor. '
                         'Baixe na B3 o extrato de Posição (Extratos → Posição) em Excel.')
    return filename, asof, items, unmatched, used, sorted({b for (_, b) in items})


def preview(app, d):
    filename, asof, items, unmatched, used, institutions = parse(app, d)
    with app.connect() as c:
        local = local_fixed(c)
        rev = revision(c)
    rows = []
    for ident, item in sorted(items.items()):
        mine = local.get(ident)
        row = {'name': item['name'], 'institution': item['institution'], 'kind': item['kind'], 'b3_value': round(item['value'], 2),
               'b3_quantity': item['quantity'], 'maturity': item['maturity'], 'value_column': item['column'], 'issuer': item['issuer']}
        if not mine:
            row.update(status='new', local_balance=None, hint='Sem cadastro local. Marque para criar com o saldo da B3; o valor investido fica como desconhecido.')
        else:
            row['local_balance'] = mine['balance']
            row['local_date'] = mine['balance_date']
            changes = []
            if abs(mine['balance'] - item['value']) > 0.005 or mine['balance_date'] != asof: changes.append('saldo')
            if item['maturity'] and not mine['maturity']: changes.append('vencimento')
            row['status'] = 'update' if changes else 'same'
            row['changes'] = changes
            row['hint'] = 'Atualiza ' + ' e '.join(changes) + '.' if changes else 'Já está igual ao extrato.'
            if mine['balance_date'] > asof: row.update(status='older', hint='O saldo local é de ' + mine['balance_date'] + ', mais recente que este extrato. Não será alterado.')
        rows.append(row)
    in_b3 = set(items)
    local_only = [{'name': k[0], 'institution': k[1], 'balance': v['balance']} for k, v in sorted(local.items())
                  if k not in in_b3 and v['type'] in ('Tesouro', 'CDB', 'LCI', 'LCA') and ('bank_fixed' in v['metadata'] or 'treasury' in v['metadata'])]
    token = secrets.token_urlsafe(24)
    for k in list(app.CSV_PREVIEWS):
        if app.CSV_PREVIEWS[k]['expires'] < time.time(): del app.CSV_PREVIEWS[k]
    if len(app.CSV_PREVIEWS) > 30: app.CSV_PREVIEWS.pop(next(iter(app.CSV_PREVIEWS)))
    app.CSV_PREVIEWS[token] = {'kind': 'b3_fixed', 'items': {f'{k[0]}|{k[1]}': v for k, v in items.items()}, 'asof': asof, 'revision': rev,
                               'expires': time.time() + 900, 'filename': filename,
                               'file_hash': hashlib.sha256(json.dumps(sorted((k, v['value']) for k, v in items.items()), default=str).encode()).hexdigest()}
    summary = {s: sum(r['status'] == s for r in rows) for s in ('update', 'new', 'same', 'older')}
    return {'token': token, 'asof': asof, 'filename': filename, 'sheets': used, 'rows': rows, 'summary': summary,
            'local_only': local_only[:100], 'unmatched': unmatched[:100], 'unmatched_count': len(unmatched), 'institutions': institutions,
            'notes': ['Nada foi salvo. Ao confirmar, só saldo, data do saldo e vencimento (se estiver vazio) são atualizados.',
                      'Taxa, indexador e imposto não vêm deste extrato; continuam como você cadastrou.',
                      'Coluna de valor usada: ' + (', '.join(sorted({r['value_column'] for r in rows})) or '—') + '.',
                      'Produtos só no cadastro local não são alterados: podem ter vencido, sido resgatados ou estar em outra instituição.']}


def commit(app, d):
    with app.WRITE_LOCK, app.connect() as c:
        plan = app.CSV_PREVIEWS.get(d.get('token'))
        if not plan or plan['kind'] != 'b3_fixed' or plan['expires'] < time.time(): raise ValueError('Prévia expirou; confira novamente.')
        if revision(c) != plan['revision']: raise ValueError('A carteira mudou; refaça a prévia.')
        if d.get('confirm_records') is not True: raise ValueError('Confirme os saldos antes de salvar.')
        create = d.get('create', [])
        if not isinstance(create, list) or len(create) > 500 or any(not isinstance(k, str) for k in create): raise ValueError('Seleção inválida.')
        unknown = [k for k in create if k not in plan['items']]
        if unknown: raise ValueError('Produto fora da prévia: ' + unknown[0][:80])
        local = local_fixed(c)
        updated = created = 0
        for ident, item in plan['items'].items():
            mine = local.get((item['name'], item['institution']))
            if mine:
                if mine['balance_date'] > plan['asof']: continue
                changed = abs(mine['balance'] - item['value']) > 0.005 or mine['balance_date'] != plan['asof']
                maturity = item['maturity'] if item['maturity'] and not mine['maturity'] else mine['maturity']
                if not changed and maturity == mine['maturity']: continue
                metadata = json.loads(mine['metadata'])
                ledger = metadata.get('bank_fixed') or metadata.get('treasury')
                if ledger and changed:
                    ledger['valuation'] = 'statement'
                c.execute('UPDATE fixed SET balance=?,balance_date=?,maturity=?,metadata=? WHERE id=?',
                          (round(item['value'], 2), plan['asof'], maturity, json.dumps(metadata, ensure_ascii=False), mine['id']))
                updated += 1
            elif ident in create:
                typ = 'Tesouro' if item['kind'] == 'treasury' else item['name'].split(' - ')[0]
                note = 'Criado pelo extrato de Posição da B3: valor investido e condições (taxa, imposto) não constam do extrato. Complete pelo comprovante.'
                c.execute("INSERT INTO fixed(name,type,invested,balance,balance_date,indexer,rate,tax,fee,maturity,liquidity,notes,institution,issuer,invested_known,conditions_known) VALUES (?,?,0,?,?,'Manual',0,0,0,?,'',?,?,?,0,0)",
                          (item['name'], typ, round(item['value'], 2), plan['asof'], item['maturity'], note, item['institution'], item['issuer']))
                created += 1
        receipt = {'file_hash': plan['file_hash'], 'filename': plan['filename'], 'saved_at': app.now(), 'added': created, 'skipped': 0, 'ignored': 0, 'updated': updated}
        receipts = app.read_cache(c, 'import_receipts', []); receipts.append(receipt)
        app.write_cache(c, 'import_receipts', receipts[-500:])
        app.CSV_PREVIEWS.pop(d['token'], None)
    return {'updated': updated, 'created': created, 'receipt': receipt}
