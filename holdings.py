"""Explicit opening balances, separated from new market purchases."""
import hashlib,json

def rate_known(f):
    metadata=f.get('metadata',{})
    if isinstance(metadata,str):metadata=json.loads(metadata)
    return f['indexer']!='Manual' and bool(f.get('conditions_known') or metadata.get('contract_rate_known') or f.get('rate',0)!=0)

def ensure_after_opening(c,aid,institution,day):
    cutoff=c.execute("SELECT MAX(t.date) FROM trades t JOIN imported_rows i ON i.record_id=t.id AND i.kind='positions' WHERE t.asset_id=? AND t.institution=?",(aid,institution)).fetchone()[0]
    if cutoff and day<=cutoff:
        raise ValueError('Há uma posição inicial em '+cutoff+' nesta instituição. Não some operações já cobertas por ela; revise o saldo inicial antes de registrar/importar esse período.')

def add_opening(app,c,aid,d):
    if not isinstance(d,dict) or set(d)!={'quantity','average','date','institution','confirmed'} or d['confirmed'] is not True:
        raise ValueError('Confira quantidade, preço médio, instituição e data da posição inicial.')
    asset=c.execute('SELECT ticker FROM assets WHERE id=? AND archived=0',(aid,)).fetchone()
    if not asset:raise ValueError('Ativo não encontrado ou removido.')
    if isinstance(d['quantity'],bool) or isinstance(d['average'],bool):raise ValueError('Quantidade e preço médio precisam ser números.')
    q=app.number(d['quantity'],True,.00000001,1e12);average=app.number(d['average'],True,.00000001,1e12)
    app.number(q*average,True,0,1e18)
    day=app.valid_date(d['date'])
    if day>app.today().isoformat():raise ValueError('A posição não pode ter data futura.')
    bank=app.text_value(d['institution'],150,True)
    record={'ticker':asset['ticker'],'quantity':q,'average':average,'date':day,'institution':bank}
    fp=hashlib.sha256(('manual-opening-v1:'+json.dumps(record,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()
    if c.execute('SELECT 1 FROM imported_rows WHERE fingerprint=?',(fp,)).fetchone():return {'opening_added':False,'duplicate':True}
    if c.execute('SELECT 1 FROM trades WHERE asset_id=? AND institution=?',(aid,bank)).fetchone():
        raise ValueError('Este ativo já tem operações nesta instituição. Confira o histórico; uma posição inicial adicional duplicaria o saldo. Use o saldo anterior da prévia B3 para conciliar um extrato incompleto.')
    rid=c.execute("INSERT INTO trades(asset_id,side,quantity,price,fees,date,institution) VALUES (?,'buy',?,?,0,?,?)",(aid,q,average,day,bank)).lastrowid
    c.execute("INSERT INTO imported_rows VALUES (?,'positions',?,?)",(fp,rid,app.now()))
    app.position(app.asset_ledger(c,aid))
    return {'opening_added':True,'quantity':q,'average':average,'cost':q*average}
