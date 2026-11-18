"""Reader for SINACOR brokerage notes (nota de negociação), mainly for history before Nov/2019.

The notes are parsed locally and turned into a B3-style CSV that goes through the same reviewed
preview/commit flow as the B3 extracts (duplicates, balance checks, confirmation). Nothing is saved here.
Costs of each note are shared between its trades in proportion to their value; IRRF is not a cost.
"""
import base64
import csv
import io
import re
from aporte_brasil.importers.csv_import import key

B3_STARTS = '2019-11-01'
SUPPORTED = {'vista': 'Mercado à Vista', 'fracionario': 'Mercado Fracionário'}
NUM = r'\d{1,3}(?:\.\d{3})*,\d+|\d+,\d+'
TRADE = re.compile(r'^(?:\d+\s*-\s*)?(?:BOVESPA|BM&F BOVESPA|BMF)\s+(?P<cv>[CV])\s+(?P<rest>.+)$', re.I)
TAIL = re.compile(r'(?P<qty>\d{1,3}(?:\.\d{3})+|\d+)\s+(?P<price>(?:\d{1,3}(?:\.\d{3})*|\d+),\d{1,8})\s+(?P<value>(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2})\s+(?P<dc>[DC])\s*$')
MARKET = re.compile(r'^(?P<market>VISTA|FRACIONARIO|FRACIONÁRIO|OPCAO DE COMPRA|OPCAO DE VENDA|OPÇÃO DE COMPRA|OPÇÃO DE VENDA|TERMO|EXERCICIO[A-Z ]*|EXERCÍCIO[A-Z ]*|LEILAO|LEILÃO)\s*(?P<rest>.*)$', re.I)
TICKER = re.compile(r'^[A-Z]{4}\d{1,2}$')
VALUE = re.compile(r'(?P<label>[^\d]*?)\s*(?P<value>-?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2})\s*(?P<dc>[DC])?(?=\s|$)')
# Prefixes (folded) of cost lines. Totals, IRRF and net amounts are deliberately absent.
COSTS = ('taxa de liquidacao', 'taxa de registro', 'taxa de termo', 'taxa a.n.a', 'taxa ana', 'emolumentos', 'corretagem',
         'taxa operacional', 'execucao', 'taxa de custodia', 'iss', 'impostos', 'outras')


def number(text):
    return float(str(text).replace('.', '').replace(',', '.'))


def fold(text):
    return ' '.join(key(text).replace('\xa0', ' ').split())


def extract_pages(raw, password=''):
    """Text per page of a PDF. Uses pypdf, which is optional; the password is never stored."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        raise ValueError('Para ler PDFs instale o pypdf (pip install pypdf) ou cole o texto da nota. Os arquivos continuam sendo lidos neste computador.')
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted and not reader.decrypt(password or ''):
            raise ValueError('PDF protegido: informe a senha (normalmente os primeiros dígitos do CPF).')
        if len(reader.pages) > 80: raise ValueError('Use PDFs de até 80 páginas por arquivo.')
        pages = []
        for page in reader.pages:
            try: pages.append(page.extract_text(extraction_mode='layout') or '')
            except TypeError: pages.append(page.extract_text() or '')
    except ValueError: raise
    except (PdfReadError, Exception) as exc:
        raise ValueError('Não consegui ler este PDF: ' + str(exc)[:120])
    if not any(p.strip() for p in pages):
        raise ValueError('O PDF não tem texto (pode ser imagem escaneada). Cole o texto da nota ou use o extrato da B3 para períodos a partir de 11/2019.')
    return pages


def header_values(lines, folded):
    """Nota number and trading date, which sit on the line(s) below the 'Nr. nota ... Data pregão' labels."""
    label = next((i for i, l in enumerate(folded[:40]) if l.startswith('nr. nota') or l.startswith('nr nota')), None)
    number_text = date = ''
    if label is not None:
        for line in lines[label:label + 4]:
            found = re.search(r'\d{2}/\d{2}/\d{4}', line)
            if found and not date: date = found[0]
            digits = re.findall(r'\d+', re.sub(r'\d{2}/\d{2}/\d{4}', ' ', line))
            if digits and not number_text and line is not lines[label]: number_text = digits[0]
    if not date:
        found = re.search(r'\d{2}/\d{2}/\d{4}', '\n'.join(lines[:25]))
        date = found[0] if found else ''
    return number_text, date


def split_notes(pages):
    """Pages are grouped by (nota number, trading date); a note can span several pages."""
    notes = {}
    for index, text in enumerate(pages):
        lines = [' '.join(l.replace('\xa0', ' ').split()) for l in text.splitlines()]
        lines = [l for l in lines if l]
        folded = [fold(l) for l in lines]
        if not any('nota de negociacao' in l or l.startswith('nr. nota') for l in folded[:40]) and not any(TRADE.match(l) for l in lines): continue
        number_text, date = header_values(lines, folded)
        # Without a number, pages are never merged: two notes of the same day would be mixed up.
        ident = (number_text or f'sem número (pág. {index + 1})', date)
        entry = notes.setdefault(ident, {'number': ident[0], 'date': date, 'lines': [], 'pages': [], 'missing_number': not number_text})
        entry['lines'].extend(lines); entry['pages'].append(index + 1)
    return list(notes.values())


def parse_trade(line):
    m = TRADE.match(line)
    if not m: return None
    rest = m['rest']
    tail = TAIL.search(rest)
    if not tail: return {'error': 'Linha de negócio sem quantidade, preço e valor reconhecíveis.', 'line': line}
    head = rest[:tail.start()].strip()
    market = MARKET.match(head)
    if not market: return {'error': 'Mercado não reconhecido.', 'line': line}
    spec = re.sub(r'^\d{2}/\d{2}\s+', '', market['rest'].strip())  # prazo
    spec = re.sub(r'\s+[#@BCDEFHILPTXY]$', '', spec)  # Obs. (*) flag, a single character after the name
    qty, price, value = number(tail['qty']), number(tail['price']), number(tail['value'])
    return {'side': 'buy' if m['cv'].upper() == 'C' else 'sell', 'market': fold(market['market']).split()[0], 'market_text': market['market'],
            'spec': ' '.join(spec.upper().split()), 'quantity': qty, 'price': price, 'value': value, 'dc': tail['dc'], 'line': line}


def ticker_of(spec):
    for token in re.split(r'[\s/]+', spec):
        if TICKER.match(token): return token
    return None


def costs_of(lines):
    found, irrf, net = {}, 0.0, None
    for line in lines:
        folded = fold(line)
        if folded.startswith('liquido'):
            tail = re.search(r'(-?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2})\s*([DC])?\s*$', line)
            if tail: net = number(tail[1]) * (-1 if tail[2] == 'D' else 1)
            continue
        if 'i.r.r.f' in folded or 'irrf' in folded:
            amounts = re.findall(r'(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}', line)
            if len(amounts) >= 2: irrf = number(amounts[-1])
            continue
        for m in VALUE.finditer(line):
            label = fold(m['label'].strip(' .:-|'))
            if not label or label.startswith('total'): continue
            for prefix in COSTS:
                if label.startswith(prefix) and not label.startswith('total'):
                    found[prefix] = number(m['value'])
                    break
    return found, irrf, net


def spread(total, values):
    """Splits total in cents across values proportionally; the remainder goes to the largest value."""
    cents = round(total * 100)
    base = sum(values)
    parts = [int(cents * v / base) for v in values] if base > 0 else [0] * len(values)
    parts[max(range(len(values)), key=lambda i: values[i])] += cents - sum(parts)
    return [p / 100 for p in parts]


def read_note(entry):
    trades, problems, ignored = [], [], []
    for line in entry['lines']:
        t = parse_trade(line)
        if t is None: continue
        if 'error' in t:
            problems.append(t['error'] + ' ' + t['line'][:120]); continue
        if t['market'] not in SUPPORTED:
            ignored.append('Mercado não suportado (' + t['market_text'].strip().lower() + '): ' + t['spec'][:60]); continue
        if abs(t['quantity'] * t['price'] - t['value']) > max(.05, t['quantity'] * .011):
            problems.append('Quantidade × preço não confere com o valor: ' + t['line'][:120]); continue
        if (t['side'] == 'buy') != (t['dc'] == 'D'):
            problems.append('C/V e D/C não combinam: ' + t['line'][:120]); continue
        trades.append(t)
    components, irrf, net = costs_of(entry['lines'])
    total = round(sum(components.values()), 2)
    warnings = ['Não encontrei o número da nota; confira se este arquivo não repete outra nota do mesmo dia.'] if entry.get('missing_number') else []
    if ignored: warnings.append('Há negócios em mercados não suportados; os custos da nota foram divididos só entre os negócios lidos. Confira os valores.')
    if not components: warnings.append('Não encontrei as taxas e a corretagem desta nota; os custos ficam zerados. Confira o resumo financeiro.')
    if net is not None and trades:
        buys = sum(t['value'] for t in trades if t['side'] == 'buy'); sells = sum(t['value'] for t in trades if t['side'] == 'sell')
        expected = sells - buys - total - irrf
        if abs(expected - net) > .05 and not ignored:
            warnings.append(f'O líquido da nota ({net:.2f}) não bate com negócios, custos e IRRF ({expected:.2f}). Revise antes de salvar.')
    fees = spread(total, [t['value'] for t in trades]) if trades else []
    for t, fee in zip(trades, fees): t['fees'] = fee
    return {'number': entry['number'], 'date': entry['date'], 'pages': entry['pages'], 'trades': trades, 'costs': components,
            'total_costs': total, 'irrf': irrf, 'net': net, 'problems': problems, 'ignored': ignored, 'warnings': warnings}


def suggestions(app, spec):
    word = fold(spec.split()[0]) if spec.split() else ''
    if len(word) < 3: return []
    with app.connect() as c:
        rows = [(r['ticker'], r['name']) for r in c.execute('SELECT ticker,name FROM catalog UNION SELECT ticker,name FROM assets')]
    return [{'ticker': t, 'name': n} for t, n in sorted(rows) if fold(n).startswith(word)][:6]


def build(app, d):
    files = d.get('files')
    if not isinstance(files, list) or not files or len(files) > 40: raise ValueError('Envie de 1 a 40 arquivos de notas.')
    institution = app.text_value(d.get('institution', ''), 150, True)
    password = d.get('password', '')
    if not isinstance(password, str) or len(password) > 100: raise ValueError('Senha inválida.')
    ticker_map = d.get('ticker_map', {})
    if not isinstance(ticker_map, dict) or len(ticker_map) > 500: raise ValueError('Mapeamento de ativos inválido.')
    ticker_map = {' '.join(str(k).upper().split()): app.text_value(v, 12, True).upper() for k, v in ticker_map.items() if v}
    for value in ticker_map.values():
        if not re.fullmatch(r'[A-Z0-9]{3,8}\d{1,2}', value): raise ValueError('Ticker inválido: ' + value)
    until = app.valid_date(d['until'], True) if d.get('until') else ''
    pages, names = [], []
    for f in files:
        if not isinstance(f, dict): raise ValueError('Arquivo inválido.')
        name = app.text_value(f.get('name', 'nota'), 200, True)
        if f.get('pdf'):
            raw = base64.b64decode(f['pdf'], validate=True)
            if len(raw) > 12_000_000: raise ValueError(name + ': use PDFs de até 12 MB.')
            pages.extend(extract_pages(raw, password))
        elif isinstance(f.get('text'), str) and f['text'].strip():
            if len(f['text']) > 2_000_000: raise ValueError(name + ': texto muito grande.')
            pages.append(f['text'])
        else: raise ValueError(name + ': envie o PDF ou o texto da nota.')
        names.append(name)
    entries = split_notes(pages)
    if not entries: raise ValueError('Não encontrei notas de negociação (Nr. nota, Data pregão) neste conteúdo.')
    notes = [read_note(e) for e in entries]
    unresolved, rows, skipped_after, seen = {}, [], 0, set()
    for n in notes:
        if not n['date']: n['problems'].append('Data do pregão não encontrada.'); continue
        day, month, year = n['date'].split('/'); iso = f'{year}-{month}-{day}'
        n['iso'] = iso
        if (n['number'], n['date']) in seen: n['warnings'].append('Nota repetida neste envio; ignorei a cópia.'); continue
        seen.add((n['number'], n['date']))
        if until and iso > until:
            skipped_after += len(n['trades']); n['warnings'].append('Depois da data limite escolhida; não entra na importação.'); continue
        for t in n['trades']:
            ticker = ticker_of(t['spec']) or ticker_map.get(t['spec'])
            if not ticker:
                unresolved.setdefault(t['spec'], {'spec': t['spec'], 'count': 0, 'suggestions': suggestions(app, t['spec'])})['count'] += 1
                continue
            rows.append({'date': n['date'], 'side': t['side'], 'ticker': ticker, 'quantity': t['quantity'], 'price': t['price'], 'value': t['value'],
                         'fees': t['fees'], 'market': SUPPORTED[t['market']], 'note': n['number']})
    errors = [f"Nota {n['number']} ({n['date']}): {p}" for n in notes for p in n['problems']]
    warnings = [f"Nota {n['number']} ({n['date']}): {w}" for n in notes for w in n['warnings']]
    if any(n.get('iso', '') >= B3_STARTS for n in notes):
        warnings.append('Há notas a partir de 01/11/2019. A B3 já fornece esse período (Negociação); importar os dois pode duplicar operações se os nomes de instituição forem diferentes. Use a data limite 2019-10-31 para evitar.')
    out = io.StringIO(newline='')
    w = csv.writer(out, delimiter=';', lineterminator='\n')
    w.writerow(['Data', 'Movimentação', 'Produto', 'Instituição', 'Mercado', 'Quantidade', 'Preço unitário', 'Valor da Operação', 'Custos'])
    fmt = lambda v: (f'{v:.8f}'.rstrip('0').rstrip('.') if '.' in f'{v:.8f}' else f'{v}').replace('.', ',')
    for r in sorted(rows, key=lambda r: (r['date'][6:] + r['date'][3:5] + r['date'][:2], r['note'])):
        w.writerow([r['date'], 'Compra' if r['side'] == 'buy' else 'Venda', r['ticker'], institution, r['market'], fmt(r['quantity']),
                    fmt(r['price']), fmt(round(r['quantity'] * r['price'], 2)), fmt(r['fees'])])
    return {'notes': [{k: v for k, v in n.items() if k not in ('trades',)} | {'trade_count': len(n['trades'])} for n in notes],
            'rows': len(rows), 'unresolved': sorted(unresolved.values(), key=lambda u: u['spec']), 'errors': errors[:100], 'warnings': warnings[:100],
            'csv': out.getvalue() if rows and not unresolved and not errors else '', 'filename': 'Notas de corretagem · ' + ', '.join(names)[:150],
            'institution': institution, 'skipped_after_limit': skipped_after,
            'notes_info': ['Nada foi salvo. A próxima etapa é a prévia de importação, com confirmação.',
                           'Custos de cada nota (liquidação, registro, emolumentos, corretagem, ISS e outros) são divididos entre os negócios pelo valor. IRRF não entra no custo.',
                           'A senha do PDF é usada só para abrir o arquivo e não é guardada.']}
