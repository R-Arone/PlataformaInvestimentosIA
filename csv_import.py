"""Local CSV preview, normalization, duplicate tracking and atomic application."""
import csv
import hashlib
import io
import json
import time
import unicodedata
from datetime import datetime

FIELDS = {
 'positions': {'ticker':'Ticker', 'quantity':'Quantidade', 'price':'Preço médio', 'institution':'Instituição', 'date':'Data'},
 'trades': {'ticker':'Ticker','side':'Operação','quantity':'Quantidade','price':'Preço unitário','fees':'Custos','date':'Data','institution':'Instituição','external_id':'ID da operação (opcional)'},
 'fixed': {'name':'Nome','type':'Tipo','institution':'Instituição','invested':'Capital líquido aportado','balance':'Saldo','balance_date':'Data do saldo','indexer':'Indexador','rate':'Taxa contratada','tax':'IR do cenário','fee':'Custo anual do cenário','maturity':'Vencimento','liquidity':'Liquidez','issuer':'Emissor','cnpj':'CNPJ','notes':'Observações'},
 'watchlist': {'ticker':'Ticker','sector':'Setor (opcional)','notes':'Observações'}
}
ALIASES = {
 'ticker':['ticker','codigo','ativo','papel','symbol'], 'quantity':['quantidade','qtd','quantity'],
 'price':['preco','preco medio','preco unitario','price','custo medio'], 'institution':['instituicao','banco','corretora','custodia'],
 'date':['data','date','data operacao'], 'side':['operacao','tipo operacao','side','compra venda'],
 'fees':['custos','taxas','corretagem','fees'], 'external_id':['id operacao','external id','numero operacao'],
 'name':['nome','name','investimento','produto'], 'type':['tipo','type'], 'invested':['investido','capital aportado','aportes','invested'],
 'balance':['saldo','balance','valor atual'], 'balance_date':['data saldo','balance date','data'],
 'indexer':['indexador','indexer'], 'rate':['taxa','rentabilidade','rate'], 'tax':['ir','imposto','tax'],
 'fee':['taxa adm','custo anual','fee'], 'maturity':['vencimento','maturity'], 'liquidity':['liquidez','liquidity'],
 'issuer':['emissor','issuer'], 'cnpj':['cnpj'], 'notes':['observacoes','notas','notes'], 'sector':['setor','sector']
}

def key(v):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(v).strip().lower().replace('_',' ').replace('/',' ')) if not unicodedata.combining(c))

def decimal(v):
    s = str(v).strip().replace('R$', '').replace('%', '').replace(' ', '')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    return s

def day(v, fallback):
    s = str(v).strip()
    if not s:
        return fallback
    if '/' in s:
        try:
            return datetime.strptime(s, '%d/%m/%Y').date().isoformat()
        except ValueError:
            raise ValueError('Data inválida. Use DD/MM/AAAA ou AAAA-MM-DD.')
    return s

def digest(c):
    rows = {t:[dict(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY id')] for t in ('assets','trades','fixed')}
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def fingerprint(kind, row):
    return hashlib.sha256(json.dumps([kind,row], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def template(kind):
    names = {'ticker':'ticker','quantity':'quantidade','price':'preco_medio' if kind=='positions' else 'preco','institution':'instituicao','date':'data','side':'operacao','fees':'custos','external_id':'id_operacao','name':'nome','type':'tipo','invested':'investido','balance':'saldo','balance_date':'data_saldo','indexer':'indexador','rate':'taxa','tax':'ir','fee':'taxa_adm','maturity':'vencimento','liquidity':'liquidez','issuer':'emissor','cnpj':'cnpj','notes':'observacoes','sector':'setor'}
    if kind not in FIELDS:
        raise ValueError('Modelo desconhecido.')
    return '\ufeff' + ';'.join(names[f] for f in FIELDS[kind]) + '\r\n'

def normalize(app, kind, row):
    if kind in ('positions','trades','watchlist'):
        row['ticker'] = str(row.get('ticker','')).strip().upper()
        if not row['ticker']:
            raise ValueError('Ticker obrigatório.')
        if row['ticker'].endswith('F'):
            with app.connect() as c:
                if c.execute('SELECT 1 FROM catalog WHERE ticker=?',(row['ticker'][:-1],)).fetchone():
                    row['ticker'] = row['ticker'][:-1]
    if kind == 'watchlist':
        return {f:row.get(f,'').strip() for f in FIELDS[kind]}
    if kind in ('positions','trades'):
        side = key(row.get('side',''))
        side = 'buy' if kind=='positions' or side in ('c','compra','buy','entrada') else 'sell' if side in ('v','venda','sell','saida') else ''
        if not side:
            raise ValueError('Operação deve ser compra ou venda.')
        dt = app.valid_date(day(row.get('date',''), app.today().isoformat() if kind=='positions' else ''))
        if dt > app.today().isoformat():
            raise ValueError('Data futura.')
        return {'ticker':row['ticker'],'side':side,'quantity':app.number(decimal(row.get('quantity','')),True,.00000001),
            'price':app.number(decimal(row.get('price','')),True,.00000001),'fees':app.number(decimal(row.get('fees') or 0),True,0),
            'institution':app.text_value(row.get('institution') or 'Não informada',150,True),'date':dt,
            'external_id':app.text_value(row.get('external_id',''),150)}
    types = {key(v):v for v in app.FIXED_TYPES}
    idxs = {key(v):v for v in ['CDI','Selic','IPCA+','Prefixado','Manual']}
    typ = types.get(key(row.get('type','')))
    idx = idxs.get(key(row.get('indexer') or 'Manual'))
    d = {f:row.get(f,'').strip() for f in FIELDS[kind]}
    d.update(type=typ,indexer=idx,balance_date=day(d['balance_date'],app.today().isoformat()),maturity=day(d['maturity'],''))
    for f in ('invested','balance','rate','tax','fee'):
        default = 100 if f=='rate' and idx=='CDI' else 0
        d[f] = decimal(d[f] or (default if f not in ('invested','balance') else ''))
    vals = app.validate_fixed(d)
    columns = 'name,type,invested,balance,balance_date,indexer,rate,tax,fee,maturity,liquidity,notes,institution,issuer,cnpj'.split(',')
    result = dict(zip(columns,vals))
    result.update(invested_known=1,conditions_known=int(all(row.get(k,'').strip() for k in ('rate','tax','fee'))))
    return result

def apply_rows(app, c, kind, rows):
    added = updated = skipped = 0
    changed_assets = set()
    for item in rows:
        r, fp, line = item['data'], item['fingerprint'], item['line']
        try:
            if c.execute('SELECT 1 FROM imported_rows WHERE fingerprint=?',(fp,)).fetchone():
                skipped += 1; continue
            if kind == 'fixed':
                found = c.execute('SELECT id FROM fixed WHERE name=? AND institution=?',(r['name'],r['institution'])).fetchall()
                if len(found)>1:
                    raise ValueError('Há mais de um investimento com esse nome e instituição; use nomes distintos.')
                cols = list(r)
                if found:
                    rid = found[0]['id']
                    old_cnpj=c.execute('SELECT cnpj FROM fixed WHERE id=?',(rid,)).fetchone()['cnpj']
                    c.execute('UPDATE fixed SET '+','.join(f+'=?' for f in cols)+' WHERE id=?', (*r.values(),rid)); updated+=1
                    c.execute('DELETE FROM imported_rows WHERE kind="fixed" AND record_id=?',(rid,))
                    if old_cnpj!=r['cnpj']: c.execute("UPDATE fixed SET metadata='{}' WHERE id=?",(rid,))
                else:
                    rid = c.execute('INSERT INTO fixed('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',tuple(r.values())).lastrowid; added+=1
            else:
                asset = c.execute('SELECT * FROM assets WHERE ticker=?',(r['ticker'],)).fetchone()
                if not asset:
                    vals, verified = app.asset_values_from_catalog(c,r)
                    aid = c.execute('INSERT INTO assets(ticker,name,sector,financial,notes,asset_type,verified) VALUES (?,?,?,?,?,?,?)',(*vals,verified)).lastrowid
                else:
                    aid = asset['id']
                if kind=='watchlist':
                    rid=aid
                    if asset: skipped+=1
                    else: added+=1
                else:
                    if kind=='positions' and c.execute('SELECT 1 FROM trades WHERE asset_id=? AND institution=?',(aid,r['institution'])).fetchone():
                        raise ValueError('Posição inicial já tem operações nessa instituição. Importe operações para acrescentar movimentações.')
                    if kind=='trades':
                        import holdings
                        holdings.ensure_after_opening(c,aid,r['institution'],r['date'])
                    rid = c.execute('INSERT INTO trades(asset_id,side,quantity,price,fees,date,institution) VALUES (?,?,?,?,?,?,?)',
                        (aid,r['side'],r['quantity'],r['price'],r['fees'],r['date'],r['institution'])).lastrowid
                    changed_assets.add(aid); added+=1
            c.execute('INSERT INTO imported_rows VALUES (?,?,?,?)',(fp,kind,rid,app.now()))
        except (ValueError, KeyError) as exc:
            raise ValueError(f'Linha {line}: {exc}')
    for aid in changed_assets:
        app.position([dict(t) for t in c.execute('SELECT * FROM trades WHERE asset_id=?',(aid,))])
    return {'added':added,'updated':updated,'skipped':skipped}

def preview(app, d):
    kind = d.get('kind')
    if kind not in FIELDS:
        raise ValueError('Tipo de importação inválido.')
    raw = d.get('csv','')
    if not isinstance(raw,str) or len(raw)>4_000_000 or not raw.strip():
        raise ValueError('Selecione um CSV de até 4 MB.')
    try:
        dialect = csv.Sniffer().sniff(raw[:10000],delimiters=';,\t')
    except csv.Error:
        dialect = csv.excel; dialect.delimiter=';' if ';' in raw.splitlines()[0] else ','
    reader = csv.DictReader(io.StringIO(raw.lstrip('\ufeff')),dialect=dialect)
    headers = reader.fieldnames or []
    if len(headers)!=len(set(headers)) or len(headers)>100:
        raise ValueError('Cabeçalhos repetidos ou excesso de colunas.')
    mapping = d.get('mapping') or {}
    selected = {f:mapping[f] if f in mapping else next((h for h in headers if key(h) in ALIASES[f]+[key(f)]),'') for f in FIELDS[kind]}
    errors, rows = [], []
    try:
        for n, rawrow in enumerate(reader,2):
            if n>10002:
                raise ValueError('Use até 10 mil linhas por arquivo.')
            if not any(v for v in rawrow.values()): continue
            try:
                if None in rawrow: raise ValueError('Quantidade de colunas diferente do cabeçalho.')
                r = normalize(app,kind,{f:(rawrow.get(h) or '') for f,h in selected.items()})
                rows.append({'line':n,'data':r,'fingerprint':fingerprint(kind,r)})
            except (ValueError,TypeError) as exc:
                errors.append(f'Linha {n}: {exc}')
    except csv.Error:
        errors.append('CSV com aspas ou colunas inválidas.')
    stats = {'added':0,'updated':0,'skipped':0}
    token = None
    with app.WRITE_LOCK, app.connect() as c:
        revision = digest(c)
        if not errors and rows:
            c.execute('SAVEPOINT csv_preview')
            try:
                stats = apply_rows(app,c,kind,rows)
            except Exception as exc:
                errors.append(str(exc) if isinstance(exc,ValueError) else 'Arquivo incompatível com os registros da carteira.')
            finally:
                c.execute('ROLLBACK TO csv_preview'); c.execute('RELEASE csv_preview')
        if not rows and not errors: errors.append('Arquivo sem registros. Preencha as linhas abaixo do cabeçalho.')
        if not errors:
            for k in list(app.CSV_PREVIEWS):
                if app.CSV_PREVIEWS[k]['expires'] < time.time(): del app.CSV_PREVIEWS[k]
            token = app.secrets.token_urlsafe(24)
            app.CSV_PREVIEWS[token] = {'kind':kind,'rows':rows,'revision':revision,'expires':time.time()+900}
    return {'headers':headers,'mapping':selected,'fields':FIELDS[kind],'rows':[{'line':r['line'],**{k:v for k,v in r['data'].items() if k not in ('invested_known','conditions_known')}} for r in rows[:100]],
            'total':len(rows),'errors':errors[:100],'token':token,**stats}

def commit(app, d):
    token = d.get('token','')
    with app.WRITE_LOCK, app.connect() as c:
        plan = app.CSV_PREVIEWS.get(token)
        if not plan or plan['expires']<time.time():
            raise ValueError('Prévia expirou. Confira o arquivo novamente.')
        if digest(c)!=plan['revision']:
            raise ValueError('A carteira mudou desde a prévia. Confira novamente antes de salvar.')
        result = apply_rows(app,c,plan['kind'],plan['rows'])
    app.CSV_PREVIEWS.pop(token,None)
    return result
