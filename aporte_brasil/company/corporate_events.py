"""B3 corporate events: splits, groupings, bonus shares and fractions.

Quantities come from the B3 statement; nothing is estimated. Each event is stored
as a quantity change per institution, so later trades and sales stay consistent.
"""
from aporte_brasil.importers.csv_import import fingerprint

# Folded B3 'Movimentação' names -> internal kind.
KINDS = {'desdobro': 'split', 'desdobramento': 'split',
         'grupamento': 'grouping', 'agrupamento': 'grouping',
         'bonificacao em ativos': 'bonus', 'bonificacao em acoes': 'bonus',
         'fracao em ativos': 'fraction_out'}
LABELS = {'split': 'Desdobramento', 'grouping': 'Grupamento', 'bonus': 'Bonificação em ativos',
          'fraction_out': 'Fração retirada para leilão'}
# Inside the same day, quantity-changing events come before the removal of fractions.
ORDER = {'split': 0, 'grouping': 0, 'bonus': 0, 'fraction_out': 1}
NOT_AUTOMATIC = {'leilao de fracao': 'Leilão de fração: valor da venda das frações em leilão. A fração já sai da posição pelo evento "Fração em Ativos"; registre o valor recebido como venda se quiser apurar o ganho.',
                 'atualizacao': 'Atualização de código/ativo: revise manualmente; a troca de código não é aplicada automaticamente.',
                 'incorporacao': 'Incorporação: revise manualmente a conversão das ações; não há aplicação automática.',
                 'cisao': 'Cisão: revise manualmente o custo e as novas ações; não há aplicação automática.'}


def key(r):
    return '|'.join((r['ticker'], r['date'], r['institution'], r['event']))


def credit(direction):
    if direction in ('credito', 'entrada', 'c'): return True
    if direction in ('debito', 'saida', 'd'): return False
    return None


def raw_event(kind, direction, ticker, date, institution, quantity, price, amount, sheet, line):
    is_credit = credit(direction)
    if is_credit is None:
        raise ValueError(LABELS[kind]+': informe Entrada/Saída (crédito ou débito) para aplicar o evento.')
    if quantity is None or quantity <= 0:
        raise ValueError(LABELS[kind]+': quantidade ausente ou não positiva.')
    if kind in ('split', 'bonus') and not is_credit:
        raise ValueError(LABELS[kind]+' com débito: revise o extrato; o evento só acrescenta ações.')
    if kind == 'fraction_out' and is_credit:
        raise ValueError('Fração em ativos com crédito: revise o extrato; só a retirada da fração é aplicada.')
    unit = price if price and price > 0 else (amount/quantity if amount and amount > 0 else None)
    return {'event': kind, 'credit': is_credit, 'ticker': ticker, 'date': date, 'institution': institution,
            'quantity': quantity, 'unit_cost': unit, 'sheet': sheet, 'line': line}


def group(app, raw, inputs):
    """One event per asset/date/institution/kind. Returns (events, problems)."""
    if not isinstance(inputs, dict) or len(inputs) > 300:
        raise ValueError('Informações dos eventos corporativos inválidas.')
    grouped = {}
    for r in raw:
        g = grouped.setdefault(key(r), {'event': r['event'], 'ticker': r['ticker'], 'date': r['date'],
                                        'institution': r['institution'], 'b3_in': 0.0, 'b3_out': 0.0,
                                        'costs': [], 'sheet': r['sheet'], 'line': r['line']})
        g['b3_in' if r['credit'] else 'b3_out'] += r['quantity']
        if r['credit'] and r['unit_cost'] is not None: g['costs'].append((r['quantity'], r['unit_cost']))
    events, problems = [], []
    for k, g in grouped.items():
        data = {f: g[f] for f in ('ticker', 'event', 'date', 'institution', 'b3_in', 'b3_out')}
        given = inputs.get(k, {})
        if not isinstance(given, dict) or set(given) - {'unit_cost', 'after'}:
            raise ValueError('Informação inválida para o evento '+k+'.')
        if g['event'] == 'bonus':
            if given.get('unit_cost') not in (None, ''):
                if isinstance(given['unit_cost'], bool): raise ValueError('Custo atribuído precisa ser numérico.')
                data['unit_cost'] = app.number(given['unit_cost'], True, 0, 1e9); data['cost_source'] = 'informado por você'
            elif g['costs'] and sum(q for q, _ in g['costs']) >= g['b3_in'] - 1e-9:
                data['unit_cost'] = sum(q*u for q, u in g['costs'])/sum(q for q, _ in g['costs']); data['cost_source'] = 'extrato B3'
            else:
                problems.append({'key': k, 'need': 'unit_cost', 'sheet': g['sheet'], 'line': g['line'], **data,
                                 'reason': g['ticker']+' · '+g['date']+': informe o custo atribuído por ação da bonificação, divulgado no fato relevante/aviso aos acionistas. Ele entra no preço médio; não é estimado.'})
                continue
        if g['event'] in ('split', 'grouping') and given.get('after') not in (None, ''):
            if isinstance(given['after'], bool): raise ValueError('Quantidade após o evento precisa ser numérica.')
            data['after'] = app.number(given['after'], True, 0, 1e15)
        # Inputs and costs are kept out of the identity: a corrected cost cannot add the same event twice.
        fp = fingerprint('b3-corporate', {f: data[f] for f in ('ticker', 'event', 'date', 'institution', 'b3_in', 'b3_out')})
        events.append({'kind': 'event', 'sheet': g['sheet'], 'line': g['line'], 'data': data, 'fingerprint': fp})
    return events, problems


def ratio_label(before, after):
    if before <= 0 or after <= 0: return '', ''
    r = after/before
    big = r if r >= 1 else 1/r
    clean = abs(big - round(big)) <= max(.005, big*.002)
    label = ('1 para '+format(round(big) if clean else big, '.6g')) if r >= 1 else (format(round(big) if clean else big, '.6g')+' para 1')
    return label, '' if clean else 'Proporção aproximada; confira o fato relevante (frações costumam sair em seguida).'


def resolve(app, c, aid, r):
    """Quantity change at the institution on the event date, from the B3 quantities."""
    day, bank, kind = r['date'], r['institution'], r['event']
    entries = [t for t in app.asset_ledger(c, aid) if (t['date'] <= day if 'quantity_delta' in t else t['date'] < day)]
    pool = next((p for p in app.position(entries)['institutions'] if p['institution'] == bank), None)
    before = pool['quantity'] if pool else 0.0
    where = r['ticker']+' · '+bank+' · '+day+': '
    if before <= 1e-12:
        raise ValueError(where+LABELS[kind]+' sem posição anterior nessa instituição. Importe as compras anteriores, confira o nome da instituição ou exclua os eventos corporativos desta prévia.')
    if kind == 'split':
        delta = (r['after'] - before) if r.get('after') is not None else r['b3_in'] - r['b3_out']
        if delta <= 0: raise ValueError(where+'desdobramento sem aumento da quantidade; confira a quantidade após o evento.')
    elif kind == 'bonus':
        if r['b3_out']: raise ValueError(where+'bonificação com débito; revise o extrato.')
        delta = r['b3_in']
    elif kind == 'fraction_out':
        delta = -r['b3_out']
        if -delta > before + 1e-9: raise ValueError(where+'fração retirada maior que a posição nessa data.')
    else:
        if r.get('after') is not None: after = r['after']
        elif r['b3_in'] and r['b3_out']: after = before - r['b3_out'] + r['b3_in']
        elif r['b3_in']: after = r['b3_in']  # B3 credits the resulting quantity of a grouping.
        else: after = before - r['b3_out']
        if after < -1e-9 or after >= before - 1e-12:
            raise ValueError(where+'grupamento sem redução da quantidade ('+format(before, '.8g')+' → '+format(after, '.8g')+'). Confira se já foi lançado manualmente ou informe a quantidade após o grupamento.')
        delta = after - before
    if abs(delta) < 1e-12:
        raise ValueError(where+LABELS[kind]+' sem mudança de quantidade; confira se o evento já foi lançado manualmente.')
    after = before + delta
    label, warning = ratio_label(before, after) if kind in ('split', 'grouping') else ('', '')
    if kind == 'bonus' and before > 0:
        label = format(delta/before*100, '.4g')+'% sobre '+format(before, '.8g')
    return {'before': before, 'after': after, 'delta': delta, 'ratio': label, 'warning': warning}


def apply(app, c, aid, item):
    r = item['data']
    change = resolve(app, c, aid, r)
    unit = r.get('unit_cost', 0) if r['event'] == 'bonus' else 0
    b3_quantity = r['b3_in'] if r['b3_in'] else r['b3_out']
    notes = {'split': 'Desdobramento: ações creditadas sem custo; o preço médio é diluído.',
             'grouping': 'Grupamento: quantidade reduzida sem alterar o custo total.',
             'bonus': 'Bonificação: custo atribuído de '+format(unit, '.10g')+' por ação ('+r.get('cost_source', '')+').',
             'fraction_out': 'Fração retirada para leilão: custo proporcional retirado pelo preço médio.'}[r['event']]
    rid = c.execute('INSERT INTO corporate_events(asset_id,kind,date,institution,quantity_delta,unit_cost,b3_quantity,notes,source) VALUES (?,?,?,?,?,?,?,?,?)',
                    (aid, r['event'], r['date'], r['institution'], change['delta'], unit, b3_quantity, notes, 'B3 · Movimentação importada')).lastrowid
    return rid, {'ticker': r['ticker'], 'institution': r['institution'], 'date': r['date'], 'event': r['event'],
                 'label': LABELS[r['event']], 'b3_quantity': b3_quantity, 'unit_cost': unit, 'sheet': item['sheet'], 'line': item['line'], **change}
