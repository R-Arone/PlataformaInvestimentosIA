"""B3 fixed income ledgers; remaining cost is separate from a statement balance."""
import json
import re

def product(name):
    name=' '.join(name.upper().split())
    pattern=r'TESOURO (SELIC|PREFIXADO( COM JUROS SEMESTRAIS)?|IPCA\+( COM JUROS SEMESTRAIS)?|RENDA\+( APOSENTADORIA EXTRA)?|EDUCA\+|(IGP-M|IGPM)\s*\+ COM JUROS SEMESTRAIS) \d{4}'
    return name if re.fullmatch(pattern,name) or re.fullmatch(r'TESOURO RESERVA( \d{4})?',name) else None

def bank_product(name):
    name=' '.join(name.upper().split())
    match=re.fullmatch(r'(CDB|LCI|LCA)\s*-\s*([A-Z0-9]{5,40})\s*-\s*(.{1,100})',name)
    if not match:return None
    typ,code,issuer=match.groups()
    if not code.startswith(typ):return None
    return {'ticker':f'{typ} - {code} - {issuer}','fixed_type':typ,'issuer':issuer,'product_code':code}

def ledger_key(row):
    return 'bank_fixed' if row.get('fixed_type') in ('CDB','LCI','LCA') else 'treasury'

def ledger(metadata):
    return metadata.get('bank_fixed') or metadata.get('treasury') or {}

def apply(app,c,row,fp,defer=False,opening=False):
    name=row['ticker']; institution=row['institution']; key=ledger_key(row)
    found=c.execute('SELECT * FROM fixed WHERE upper(name)=? AND institution=?',(name,institution)).fetchone()
    if found:
        metadata=json.loads(found['metadata']); ledger=metadata.get(key)
        if not ledger:
            raise ValueError(name+' já tem saldo cadastrado nessa instituição. Use outro nome para o histórico importado ou revise o cadastro antes de mesclar.')
        fid=found['id']
    else:
        metadata={}; ledger={'transactions':[],'valuation':'cost','quantity':0,'realized':0}
        if key=='bank_fixed':ledger.update(product_code=row['product_code'],issuer=row['issuer'])
        fid=c.execute("INSERT INTO fixed(name,type,invested,balance,balance_date,indexer,rate,tax,fee,institution,issuer,invested_known,conditions_known,notes) VALUES (?,?,0,0,?,'Manual',0,0,0,?,?,1,0,?)",(name,row.get('fixed_type','Tesouro'),row['date'],institution,row.get('issuer',''),'B3: custo remanescente do histórico, sem atualização pela taxa ou desconto de IR. Taxa, vencimento e liquidez não constam desta movimentação. Atualize o saldo e as condições pelo extrato ou nota do produto.')).lastrowid
    if not opening and any(t.get('opening') and row['date']<=t['date'] for t in ledger['transactions']):
        raise ValueError(name+' · '+institution+': há um saldo inicial posterior a essa operação. Revise o histórico inicial antes de importar períodos mais antigos.')
    transaction={k:row[k] for k in ('side','quantity','price','fees','date','institution')}
    for field in ('unit_price_reported','amount_reported'):
        if field in row:transaction[field]=row[field]
    if opening:transaction['opening']=True
    transaction['fingerprint']=fp; transaction['id']=len(ledger['transactions'])+1
    ledger['transactions'].append(transaction)
    metadata[key]=ledger
    c.execute('UPDATE fixed SET metadata=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),fid))
    if not defer:recalculate(app,c,fid)
    return fid

def recalculate(app,c,fid):
    found=c.execute('SELECT name,metadata,balance,balance_date FROM fixed WHERE id=?',(fid,)).fetchone()
    name=found['name'];metadata=json.loads(found['metadata']);key='bank_fixed' if 'bank_fixed' in metadata else 'treasury';ledger=metadata[key]
    try: position=app.position(ledger['transactions'])
    except ValueError:
        raise ValueError(name+': resgate/venda excede as compras disponíveis. O extrato precisa incluir a aquisição/posição anterior deste título.')
    statement=ledger.get('valuation')=='statement'
    ledger.update(quantity=position['quantity'],realized=position['realized'],valuation='statement' if statement else 'cost')
    metadata[key]=ledger
    latest=max(t['date'] for t in ledger['transactions'])
    c.execute('UPDATE fixed SET metadata=?,invested=?,balance=?,balance_date=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),position['cost'],found['balance'] if statement else position['cost'],found['balance_date'] if statement else latest,fid))
    return position

def validate(ledger,number,valid_date):
    if not isinstance(ledger,dict) or not isinstance(ledger.get('transactions'),list) or len(ledger['transactions'])>15000:
        raise ValueError('Histórico de Tesouro inválido.')
    for t in ledger['transactions']:
        if t.get('side') not in ('buy','sell'): raise ValueError('Operação de Tesouro inválida.')
        number(t['quantity'],True,.00000001);number(t['price'],True,.00000001);number(t['fees'],True,0);valid_date(t['date'])
        if not isinstance(t.get('institution'),str) or not re.fullmatch('[a-f0-9]{64}',t.get('fingerprint','')): raise ValueError('Registro de Tesouro inválido.')
