"""Read-only XLSX extraction and reviewed, atomic B3 trades/income import."""
import base64
from collections import Counter
import csv
from datetime import datetime, timedelta
import io
import hashlib
import json
import posixpath
import re
import time
import zipfile
import treasury_import
from xml.etree import ElementTree as ET
from csv_import import key, decimal, fingerprint

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
FIELDS={'date':'Data da operação / pagamento','ticker':'Código de negociação / produto',
        'event':'Tipo de movimentação / provento','direction':'Entrada / saída',
        'quantity':'Quantidade','price':'Preço unitário','amount':'Valor da operação / provento',
        'institution':'Instituição','market':'Mercado','fees':'Custos (se houver)','external_id':'ID (se houver)'}
ALIASES={'date':['data','data do negocio','data de negociacao','data pagamento','data de pagamento','data operacao'],
 'ticker':['codigo de negociacao','codigo do ativo','ticker','produto','ativo'],
 'event':['tipo de movimentacao','movimentacao','operacao','tipo','tipo de provento','evento'],
 'direction':['entrada saida','entrada/saida','credito debito'],
 'quantity':['quantidade','qtd'], 'price':['preco','preco unitario'],
 'amount':['valor','valor da operacao','valor operacao','valor liquido','valor recebido'],
 'institution':['instituicao','corretora','banco'], 'market':['mercado'],
 'fees':['custos','taxas','corretagem'], 'external_id':['id','id operacao','numero operacao']}
INCOME_KINDS={'dividendo':'Dividendos','dividendos':'Dividendos',
 'juros sobre capital proprio':'JCP','juros sob capital proprio':'JCP','jcp':'JCP',
 'rendimento':'Rendimentos','rendimentos':'Rendimentos',
 'reembolso':'Reembolso','amortizacao':'Amortização','pagamento de juros':'Rendimentos','pagamento juros':'Rendimentos','juros':'Rendimentos'}

def missing(v):
    return v is None or str(v).strip().replace('R$','').strip() in ('','-','–','—','--','N/A','n/a')

def numeric(app,value,label,optional=False):
    if missing(value):
        if optional: return None
        raise ValueError(label+' não informado. Confira a coluna e o valor no extrato.')
    raw=str(value).replace('\u00a0',' ').replace('\u202f',' ').replace('−','-').strip()
    if raw.startswith('(') and raw.endswith(')'): raw='-'+raw[1:-1]
    try: return app.number(decimal(raw),True,0)
    except (ValueError,TypeError):
        raise ValueError(label+' inválido: '+repr(str(value)[:60])+'. Confira as colunas e o formato decimal; não foi convertido para zero.')

def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): raise ValueError('XML incompatível no Excel.')
    return ET.fromstring(data)

def read_xlsx(encoded):
    try:
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)>8_000_000: raise ValueError('Use um Excel de até 8 MB.')
        z=zipfile.ZipFile(io.BytesIO(raw))
        infos=z.infolist()
        if len(infos)>500 or sum(i.file_size for i in infos)>80_000_000 or any(i.file_size>35_000_000 for i in infos):
            raise ValueError('Excel muito grande após descompactação.')
        if any('vbaproject' in i.filename.lower() for i in infos): raise ValueError('Salve o arquivo como .xlsx sem macros.')
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            shared=[''.join(e.itertext()) for e in xml(z.read('xl/sharedStrings.xml')).findall('s:si',NS)]
        wb=xml(z.read('xl/workbook.xml'))
        props=wb.find('s:workbookPr',NS); date1904=props is not None and props.get('date1904') in ('1','true')
        relations={r.get('Id'):r for r in xml(z.read('xl/_rels/workbook.xml.rels'))}
        result=[]; count=0
        for sh in wb.findall('s:sheets/s:sheet',NS):
            rel=relations.get(sh.get('{'+NS['r']+'}id'))
            if rel is None or rel.get('TargetMode')=='External': continue
            target=rel.get('Target','')
            path=posixpath.normpath('xl/'+target) if not target.startswith('/') else target.lstrip('/')
            if not path.startswith('xl/worksheets/') or path not in z.namelist(): continue
            rows=[]
            for row in xml(z.read(path)).findall('s:sheetData/s:row',NS):
                out={}
                for cell in row.findall('s:c',NS):
                    ref=cell.get('r',''); letters=re.match('[A-Z]+',ref)
                    if not letters: continue
                    col=0
                    for ch in letters[0]: col=col*26+ord(ch)-64
                    if col>100: raise ValueError('Use no máximo 100 colunas.')
                    v=cell.find('s:v',NS); typ=cell.get('t',''); formula=cell.find('s:f',NS)
                    if typ=='inlineStr': value=''.join(cell.find('s:is',NS).itertext()) if cell.find('s:is',NS) is not None else ''
                    elif typ=='s': value=shared[int(v.text)] if v is not None and v.text else ''
                    elif typ in ('str','d'): value=v.text or '' if v is not None else ''
                    elif typ=='e' or formula is not None and (v is None or v.text is None): value='#VALOR_NAO_CALCULADO'
                    else: value=float(v.text) if v is not None and v.text else ''
                    out[col-1]=value
                if out:
                    count+=1
                    if count>15000: raise ValueError('Use até 15 mil linhas no Excel.')
                    rows.append({'line':int(row.get('r',len(rows)+1)), 'values':[out.get(i,'') for i in range(max(out)+1)]})
            result.append({'name':sh.get('name','Planilha'),'rows':rows,'date1904':date1904})
        if not result: raise ValueError('Nenhuma aba legível no Excel.')
        return result
    except (zipfile.BadZipFile,ET.ParseError,KeyError,IndexError,TypeError,OverflowError) as exc:
        raise ValueError('Excel inválido. Exporte novamente como .xlsx.') from exc

def read_csv(raw):
    if not isinstance(raw,str) or len(raw)>4_000_000: raise ValueError('Use um CSV de até 4 MB.')
    try: dialect=csv.Sniffer().sniff(raw[:10000],delimiters=';,\t')
    except csv.Error: dialect=csv.excel; dialect.delimiter=';' if ';' in raw[:500] else ','
    rows=[{'line':i,'values':r} for i,r in enumerate(csv.reader(io.StringIO(raw.lstrip('\ufeff')),dialect),1)]
    if len(rows)>15000: raise ValueError('Use até 15 mil linhas.')
    return [{'name':'CSV','rows':rows,'date1904':False}]

def date_value(v,date1904=False):
    if isinstance(v,(int,float)):
        if not 1<=v<=100000: raise ValueError('Data numérica inválida.')
        return ((datetime(1904,1,1) if date1904 else datetime(1899,12,30))+timedelta(days=v)).date().isoformat()
    v=str(v).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}T',v):
        try: return datetime.fromisoformat(v.replace('Z','+00:00')).date().isoformat()
        except ValueError: pass
    for fmt in ('%d/%m/%Y','%Y-%m-%d','%d/%m/%Y %H:%M:%S','%Y-%m-%dT%H:%M:%S'):
        try: return datetime.strptime(v,fmt).date().isoformat()
        except ValueError: pass
    raise ValueError('Data não reconhecida: '+v[:40])

def find_header(sheet):
    for i,row in enumerate(sheet['rows'][:30]):
        headers=[str(v).strip() for v in row['values']]
        matches={f:next((h for h in headers if key(h) in [key(x) for x in names]),'') for f,names in ALIASES.items()}
        if matches['date'] and matches['ticker'] and matches['event']:
            if len(headers)!=len(set(headers)): raise ValueError('Cabeçalhos repetidos na aba '+sheet['name'])
            return i,headers,matches
    return None,[],{}

def revision(c):
    import hashlib,json
    return hashlib.sha256(json.dumps({t:[dict(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY id')] for t in ('assets','trades','fixed','income')},sort_keys=True).encode()).hexdigest()

class ReconciliationError(ValueError):
    def __init__(self,issues):
        self.issues=issues
        first=issues[0]
        super().__init__(first['ticker']+' · '+first['institution']+' · '+first['date']+
            ': venda/resgate de '+format(first['sold'],'.8g')+' excede a posição disponível ('+format(max(0,first['available']),'.8g')+'). '+
            'Confira compras anteriores, linhas excluídas e nomes de instituições. Nada foi salvo.')

def balance_issues(trades,ticker,kind,locations=None):
    """Diagnose the missing opening quantity; never infer its cost or add it."""
    locations=locations or {};pools={};issues={};ordered=sorted(trades,key=lambda t:(t['date'],t['id']))
    for t in ordered:
        bank=t.get('institution') or 'Não informada';q=pools.get(bank,0)
        after=q+(t['quantity'] if t['side']=='buy' else -t['quantity'])
        if after < -1e-12:
            if bank not in issues:
                issues[bank]={'ticker':ticker,'record_type':kind,'institution':bank,'date':t['date'],
                    'sold':t['quantity'],'available':q,'required_quantity':-after,
                    'first_date':min(x['date'] for x in ordered if (x.get('institution') or 'Não informada')==bank),
                    'other_institutions':[{'institution':b,'quantity':v} for b,v in pools.items() if b!=bank and v>0],
                    **locations.get(t['id'],{'sheet':'Histórico já salvo','line':None})}
            issues[bank]['required_quantity']=max(issues[bank]['required_quantity'],-after)
        pools[bank]=after
    return list(issues.values())

def opening_rows(app,c,request,rows):
    values=request.get('opening_positions',[])
    if not isinstance(values,list) or len(values)>200:raise ValueError('Saldos anteriores inválidos.')
    result=[];seen=set()
    for v in values:
        fields={'ticker','record_type','institution','quantity','average','date'}
        if not isinstance(v,dict) or set(v)!=fields or v['record_type'] not in ('trades','treasury','bank_fixed'):raise ValueError('Saldo anterior incompleto.')
        ticker=app.text_value(v['ticker'],150,True);bank=app.text_value(v['institution'],150,True);kind=v['record_type']
        ident=(kind,ticker,bank)
        if ident in seen:raise ValueError('Informe somente um saldo anterior por ativo e instituição.')
        seen.add(ident)
        related=[r for r in rows if (r['kind'],r['data']['ticker'],r['data']['institution'])==ident]
        if not related:raise ValueError('Saldo anterior não corresponde às operações desta prévia.')
        date=app.valid_date(v['date'])
        fp=fingerprint('b3-opening',{'kind':kind,'ticker':ticker,'institution':bank,'date':date})
        existing=c.execute('SELECT kind,record_id FROM imported_rows WHERE fingerprint=?',(fp,)).fetchone()
        dates=[r['data']['date'] for r in related]
        if kind=='trades':
            initial=c.execute("SELECT i.fingerprint FROM trades t JOIN imported_rows i ON i.record_id=t.id AND i.kind='positions' WHERE t.institution=? AND t.asset_id IN (SELECT id FROM assets WHERE ticker=?)",(bank,ticker)).fetchall()
            if any(r['fingerprint']!=fp for r in initial):raise ValueError(ticker+' · '+bank+': já existe um saldo inicial. Revise esse registro antes de informar outro, mesmo com uma data diferente.')
            dates += [r['date'] for r in c.execute('SELECT id,date FROM trades WHERE institution=? AND asset_id IN (SELECT id FROM assets WHERE ticker=?)',(bank,ticker)) if not existing or r['id']!=existing['record_id']]
        else:
            f=c.execute('SELECT metadata FROM fixed WHERE upper(name)=? AND institution=?',(ticker,bank)).fetchone()
            transactions=treasury_import.ledger(json.loads(f['metadata'])).get('transactions',[]) if f else []
            if any(t.get('opening') and t['fingerprint']!=fp for t in transactions):raise ValueError(ticker+' · '+bank+': já existe um saldo inicial. Revise esse registro antes de informar outro, mesmo com uma data diferente.')
            dates += [t['date'] for t in transactions if t['fingerprint']!=fp]
        if date>=min(dates):raise ValueError(ticker+': a data do saldo anterior deve ser antes de '+min(dates)+'.')
        for k in ('quantity','average'):
            if isinstance(v[k],bool):raise ValueError('Saldo anterior requer quantidade e preço médio numéricos.')
        quantity=app.number(v['quantity'],True,.00000001);average=app.number(v['average'],True,.00000001)
        data={'ticker':ticker,'institution':bank,'date':date,'side':'buy','quantity':quantity,'price':average,'fees':0}
        if kind=='bank_fixed':
            for field in ('fixed_type','issuer','product_code'):data[field]=related[0]['data'][field]
        # Stable identity protects against adding the same opening twice, even after editing its inputs.
        if existing:
            if kind=='trades':old=c.execute('SELECT quantity,price FROM trades WHERE id=?',(existing['record_id'],)).fetchone()
            else:
                f=c.execute('SELECT metadata FROM fixed WHERE id=?',(existing['record_id'],)).fetchone()
                old=next((t for t in treasury_import.ledger(json.loads(f['metadata'])).get('transactions',[]) if t['fingerprint']==fp),None) if f else None
            if not old or old['quantity']!=quantity or old['price']!=average:raise ValueError(ticker+': esse saldo anterior já foi salvo com outros valores. Revise o histórico antes de alterar.')
        result.append({'kind':kind,'sheet':'Saldo anterior informado por você','line':0,'data':data,
            'fingerprint':fp,'historical':related[0].get('historical'),'opening':True})
    return result

def apply(app,c,rows):
    added=skipped=0; changed=set(); previous={}; fixed_previous={}; fixed_changed=set();locations={};fixed_locations={}
    # B3 does not provide execution times in these layouts; purchases are ordered first on the same day.
    for item in sorted(rows,key=lambda r:(r['data']['date'],r['data'].get('side')=='sell',r['line'])):
        r=item['data']; fp=item['fingerprint']; typ=item['kind']
        if c.execute('SELECT 1 FROM imported_rows WHERE fingerprint=?',(fp,)).fetchone(): skipped+=1; continue
        if typ=='trades':
            found=c.execute('SELECT id FROM assets WHERE ticker=?',(r['ticker'],)).fetchone()
            if found: aid=found['id']
            else:
                if item.get('historical'):
                    values=app.validate_asset({'ticker':r['ticker'],**item['historical']}); verified=0
                else: values,verified=app.asset_values_from_catalog(c,{'ticker':r['ticker']})
                aid=c.execute('INSERT INTO assets(ticker,name,sector,financial,notes,asset_type,verified) VALUES (?,?,?,?,?,?,?)',(*values,verified)).lastrowid
            if not item.get('opening'):
                cutoff=c.execute("SELECT MAX(t.date) AS date FROM trades t JOIN imported_rows i ON i.record_id=t.id AND i.kind='positions' WHERE t.asset_id=? AND t.institution=?",(aid,r['institution'])).fetchone()['date']
                if cutoff and r['date']<=cutoff:raise ValueError(r['ticker']+' · '+r['institution']+': já existe saldo inicial em '+cutoff+'. Não some operações anteriores a esse saldo; revise o histórico inicial primeiro.')
            if aid not in previous: previous[aid]=app.position([dict(t) for t in c.execute('SELECT * FROM trades WHERE asset_id=?',(aid,))])
            rid=c.execute('INSERT INTO trades(asset_id,side,quantity,price,fees,date,institution) VALUES (?,?,?,?,?,?,?)',
                          (aid,r['side'],r['quantity'],r['price'],r['fees'],r['date'],r['institution'])).lastrowid
            locations[rid]={'sheet':item['sheet'],'line':item['line']}
            changed.add(aid)
        elif typ in ('treasury','bank_fixed'):
            ident=(r['ticker'],r['institution'])
            if ident not in fixed_previous:
                f=c.execute('SELECT metadata FROM fixed WHERE upper(name)=? AND institution=?',ident).fetchone()
                ledger=treasury_import.ledger(json.loads(f['metadata'])) if f else {}
                fixed_previous[ident]=app.position(ledger.get('transactions',[]))
            rid=treasury_import.apply(app,c,r,fp,defer=True,opening=bool(item.get('opening')))
            ledger=treasury_import.ledger(json.loads(c.execute('SELECT metadata FROM fixed WHERE id=?',(rid,)).fetchone()['metadata']))
            fixed_locations.setdefault(ident,{})[ledger['transactions'][-1]['id']]={'sheet':item['sheet'],'line':item['line']}
            fixed_changed.add(ident)
        else:
            cols=list(r)
            rid=c.execute('INSERT INTO income('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',tuple(r.values())).lastrowid
        record_kind='positions' if typ=='trades' and item.get('opening') else {'trades':'b3_trades','treasury':'b3_fixed','bank_fixed':'b3_fixed','income':'income'}[typ]
        c.execute('INSERT INTO imported_rows VALUES (?,?,?,?)',(fp,record_kind,rid,app.now())); added+=1
    issues=[]
    for aid in sorted(changed):
        ticker=c.execute('SELECT ticker FROM assets WHERE id=?',(aid,)).fetchone()['ticker']
        trades=[dict(r) for r in c.execute('SELECT * FROM trades WHERE asset_id=?',(aid,))]
        issues+=balance_issues(trades,ticker,'trades',locations)
    for ident in sorted(fixed_changed):
        f=c.execute('SELECT metadata FROM fixed WHERE upper(name)=? AND institution=?',ident).fetchone()
        metadata=json.loads(f['metadata']);kind='bank_fixed' if 'bank_fixed' in metadata else 'treasury'
        issues+=balance_issues(treasury_import.ledger(metadata)['transactions'],ident[0],kind,fixed_locations.get(ident))
    if issues:raise ReconciliationError(issues)
    positions=[]
    for aid in sorted(changed):
        try:
            pos=app.position([dict(r) for r in c.execute('SELECT * FROM trades WHERE asset_id=?',(aid,))])
            positions.append({'ticker':c.execute('SELECT ticker FROM assets WHERE id=?',(aid,)).fetchone()['ticker'],'before':previous[aid], 'after':pos})
        except ValueError as exc:
            raise ValueError(str(exc)+' O Excel pode não incluir compras antigas ou pode conter transferências. Cadastre a posição anterior na mesma instituição, ou revise o período do extrato.')
    for ident in sorted(fixed_changed):
        f=c.execute('SELECT id FROM fixed WHERE upper(name)=? AND institution=?',ident).fetchone()
        pos=treasury_import.recalculate(app,c,f['id'])
        positions.append({'ticker':ident[0], 'institution':ident[1], 'before':fixed_previous[ident],'after':pos})
    return {'added':added,'updated':0,'skipped':skipped,'position_changes':positions}

def preview(app,d):
    sheets=read_xlsx(d.get('xlsx','')) if d.get('xlsx') else read_csv(d.get('csv',''))
    selection=d.get('sheet','__all'); chosen=[s for s in sheets if selection=='__all' or s['name']==selection]
    if not chosen: raise ValueError('Aba não encontrada.')
    mode=d.get('mode','auto'); basis=d.get('amount_basis','reported')
    settlements=d.get('include_settlements',False)
    if not isinstance(settlements,bool): raise ValueError('Opção de liquidação inválida.')
    has_negotiation=any(key(s['name']) in ('negociacao','negociacoes') or any(key(h)=='data do negocio' for h in find_header(s)[1]) for s in chosen)
    if mode not in ('auto','trades','income') or basis not in ('reported','net','gross'): raise ValueError('Modo de importação inválido.')
    resolutions=d.get('historical_assets',{})
    if not isinstance(resolutions,dict) or len(resolutions)>200: raise ValueError('Identificação de ativos inválida.')
    historical={}
    for ticker,v in resolutions.items():
        if not isinstance(v,dict) or set(v)-{'name','asset_type','sector','financial'} or v.get('asset_type') not in ('stock','fii','etf','bdr'): raise ValueError('Escolha o tipo do ativo histórico.')
        values=app.validate_asset({'ticker':ticker,**v})
        historical[ticker]={'name':values[1],'sector':values[2],'financial':values[3],'notes':'Cadastro histórico confirmado na importação B3. Código original mantido; sem conversão ou verificação automática.','asset_type':values[5]}
    if not isinstance(d.get('skip_unknown',False),bool): raise ValueError('Opção de exclusão inválida.')
    if not isinstance(d.get('skip_invalid',False),bool): raise ValueError('Opção de exclusão inválida.')
    institution_map=d.get('institution_map',{})
    if not isinstance(institution_map,dict) or len(institution_map)>200:raise ValueError('Nomes de instituições inválidos.')
    institution_map={app.text_value(k,150,True):app.text_value(v,150,True) for k,v in institution_map.items()}
    raw=base64.b64decode(d['xlsx']) if d.get('xlsx') else d.get('csv','').encode('utf-8')
    file_hash=hashlib.sha256(raw).hexdigest()
    filename=app.text_value(d.get('filename','Arquivo B3'),200,True)
    rows=[]; errors=[]; error_details=[]; ignored=[]; mappings=[]; headers_out=[]; unknown={};institutions=Counter();balance_problems=[]
    with app.connect() as c:
        tickers={r['ticker'] for r in c.execute('SELECT ticker FROM catalog')}|{r['ticker'] for r in c.execute('SELECT ticker FROM assets')}
        previous=[r for r in app.read_cache(c,'import_receipts',[]) if r['file_hash']==file_hash]
    for sh in chosen:
        start,headers,mapping=find_header(sh)
        if start is None:
            ignored.append({'sheet':sh['name'],'line':0,'reason':'Aba sem cabeçalho de negociação/movimentação reconhecido.'}); continue
        if d.get('mapping') and selection!='__all': mapping={f:d['mapping'].get(f,'') for f in FIELDS}
        mappings.append({'sheet':sh['name'],'mapping':mapping}); headers_out=headers
        occurrences=Counter()
        for row in sh['rows'][start+1:]:
            if not any(v!='' for v in row['values']): continue
            values={h:row['values'][i] if i<len(row['values']) else '' for i,h in enumerate(headers)}
            get=lambda f:values.get(mapping.get(f,''),'')
            event=' '.join(key(get('event')).split()); direction=' '.join(key(get('direction')).split()); location=sh['name']+' · linha '+str(row['line'])
            product=' '.join(str(get('ticker')).strip().upper().split())
            treasury=treasury_import.product(product)
            bank_product=treasury_import.bank_product(product)
            income_kind=INCOME_KINDS.get(event)
            trade_side='buy' if event in ('compra','c') else 'sell' if event in ('venda','v') else None
            if event in ('transferencia - liquidacao','transferencia liquidacao','liquidacao'):
                if has_negotiation and not bank_product:
                    ignored.append({'sheet':sh['name'],'line':row['line'],'reason':'Liquidação: a aba Negociação tem prioridade para evitar contar a operação duas vezes. Use só Movimentação se quiser importar por liquidação.'}); continue
                if not settlements:
                    ignored.append({'sheet':sh['name'],'line':row['line'],'reason':'Liquidação: habilite a opção de usar liquidação como compra/venda somente após confirmar o significado no extrato. Transferência de custódia não deve ser tratada como aporte.'}); continue
                trade_side='buy' if direction in ('entrada','credito','c') else 'sell' if direction in ('saida','debito','d') else None
            if event in ('compra venda','compra / venda'):
                trade_side='buy' if direction in ('entrada','credito','c') else 'sell' if direction in ('saida','debito','d') else None
            if (treasury or bank_product) and event in ('resgate antecipado','vencimento/resgate saldo em conta','vencimento resgate saldo em conta','vencimento','resgate'):
                trade_side='sell'
            if mode=='income' and not income_kind or mode=='trades' and not trade_side or not (income_kind or trade_side):
                ignored.append({'sheet':sh['name'],'line':row['line'],'reason':str(get('event'))[:150]+' · evento fora do tipo escolhido ou sem tratamento automático.'}); continue
            if income_kind and direction not in ('','credito','entrada','c'):
                ignored.append({'sheet':sh['name'],'line':row['line'],'reason':'Provento sem entrada/crédito positivo; revisar estorno ou débito.'}); continue
            market=key(get('market'))
            if trade_side and not bank_product and market and market not in ('mercado a vista','a vista','fracionario','mercado fracionario','vista'):
                ignored.append({'sheet':sh['name'],'line':row['line'],'reason':'Mercado não suportado: '+str(get('market'))[:80]}); continue
            try:
                m=re.match(r'^([A-Z0-9]{3,8}\d{1,2}F?)(?:\s|$|[-.])',product)
                if not m and not treasury and not bank_product:
                    ignored.append({'sheet':sh['name'],'line':row['line'],'reason':'Produto fora do importador automático: '+product[:100]+'. Cadastre o saldo na tela Fundos / renda fixa; a linha não bloqueia os demais produtos.'}); continue
                ticker=treasury or (bank_product['ticker'] if bank_product else m[1])
                if ticker.endswith('F') and ticker[:-1] in tickers: ticker=ticker[:-1]
                date=app.valid_date(date_value(get('date'),sh['date1904']))
                if date>app.today().isoformat(): raise ValueError('Data futura; use proventos já pagos.')
                original_bank=app.text_value(str(get('institution') or 'Não informada'),150,True)
                bank=institution_map.get(original_bank,original_bank);institutions[original_bank]+=1
                external_id=app.text_value(str(get('external_id') or ''),150)
                if trade_side:
                    if not treasury and not bank_product and ticker not in tickers and ticker not in historical:
                        unknown.setdefault(ticker,{'ticker':ticker,'product':product,'lines':[]})['lines'].append(location)
                        if d.get('skip_unknown'):
                            ignored.append({'sheet':sh['name'],'line':row['line'],'reason':ticker+' · ativo não identificado, excluído por opção explícita. A posição deste ativo não será conciliada.'}); continue
                        raise ValueError('Ativo '+ticker+' fora do catálogo atual: '+product[:100]+'. Atualize o catálogo ou confirme o cadastro histórico na prévia.')
                    if (treasury or bank_product) and (missing(get('quantity')) or missing(get('price')) and missing(get('amount'))):
                        ignored.append({'sheet':sh['name'],'line':row['line'],'reason':product+' · sem quantidade/preço ou valor suficientes para separar resgate do principal e rendimento. Revise o saldo pelo extrato.'}); continue
                    q=numeric(app,get('quantity'),'Quantidade')
                    amount=numeric(app,get('amount'),'Valor da operação',True)
                    p=numeric(app,get('price'),'Preço unitário',True)
                    if p is None: p=amount/q if amount is not None and q>0 else 0
                    if q<=0 or p<=0: raise ValueError('Quantidade e preço precisam ser positivos.')
                    if amount is not None and abs(amount-q*p)>max(.05,q*.011):
                        raise ValueError('Quantidade × preço não confere com o valor; reveja as colunas e custos.')
                    r={'ticker':ticker,'side':trade_side,'quantity':q,'price':p,'fees':numeric(app,get('fees'),'Custos',True) or 0,'date':date,'institution':bank}
                    if bank_product:
                        r.update(bank_product)
                        # B3 monetary total is rounded to cents; keep the reported PU for inspection.
                        if amount is not None:
                            if amount<=0:raise ValueError('Valor da operação precisa ser positivo.')
                            r.update(price=amount/q,unit_price_reported=p,amount_reported=amount)
                    kind='bank_fixed' if bank_product else 'treasury' if treasury else 'trades'
                else:
                    amount=numeric(app,get('amount'),'Valor do provento')
                    if amount<=0: raise ValueError('Valor de provento precisa ser positivo.')
                    r={'ticker':ticker,'kind':income_kind,'amount':amount,'date':date,'institution':bank,
                       'amount_basis':basis,'notes':'Valor preservado do extrato; sem desconto de IR automático.','source':'B3 · Excel/CSV importado'}
                    kind='income'
                semantic={k:v for k,v in r.items() if k not in ('amount_basis','notes','source','fees','unit_price_reported','amount_reported','fixed_type','issuer','product_code')}
                identity={'record':semantic,'external_id':external_id}
                base=fingerprint('b3-'+kind,identity); occurrences[base]+=1
                # The same event in multiple sheets/files is deduplicated; repeated identical events within a sheet retain multiplicity.
                fp=fingerprint('b3-event',{'base':base,'occurrence':occurrences[base]})
                rows.append({'kind':kind,'line':row['line'],'sheet':sh['name'],'data':r,'fingerprint':fp,'historical':historical.get(ticker)})
            except (ValueError,TypeError) as exc:
                detail={'sheet':sh['name'],'line':row['line'],'reason':str(exc),'product':product[:150]}
                if d.get('skip_invalid'):
                    ignored.append({**detail,'reason':'Excluída por sua escolha: '+str(exc)})
                else:
                    errors.append(location+': '+str(exc));error_details.append(detail)
    stats={'added':0,'updated':0,'skipped':0,'position_changes':[]}; token=None
    with app.WRITE_LOCK, app.connect() as c:
        rev=revision(c)
        if rows and not errors:
            try:rows=opening_rows(app,c,d,rows)+rows
            except ValueError as exc:errors.append(str(exc))
        if rows and not errors:
            c.execute('SAVEPOINT b3_preview')
            try: stats=apply(app,c,rows)
            except (ValueError,KeyError) as exc:
                errors.append(str(exc))
                if isinstance(exc,ReconciliationError):balance_problems=exc.issues
            finally: c.execute('ROLLBACK TO b3_preview'); c.execute('RELEASE b3_preview')
        if not rows and not errors: errors.append('Nenhuma compra, venda ou provento reconhecido; confira a aba e as colunas.')
        if not errors:
            for k in list(app.CSV_PREVIEWS):
                if app.CSV_PREVIEWS[k]['expires']<time.time(): del app.CSV_PREVIEWS[k]
            if len(app.CSV_PREVIEWS)>30: app.CSV_PREVIEWS.pop(next(iter(app.CSV_PREVIEWS)))
            token=app.secrets.token_urlsafe(24)
            app.CSV_PREVIEWS[token]={'kind':'b3','rows':rows,'revision':rev,'expires':time.time()+900,'has_ignored':bool(ignored),'has_openings':any(r.get('opening') for r in rows),'file_hash':file_hash,'filename':filename,'ignored_count':len(ignored)}
    return {'sheets':[s['name'] for s in sheets],'selected_sheet':selection,'headers':headers_out,
            'mapping':mappings[0]['mapping'] if len(mappings)==1 else {},'mappings':mappings,'fields':FIELDS,
            'rows':[{'sheet':r['sheet'],'line':r['line'],'record_type':r['kind'],'opening':bool(r.get('opening')),**r['data']} for r in rows[:100]],
            'opening_rows':[r['data'] for r in rows if r.get('opening')],
            'balance_issues':balance_problems,'institutions':[{'original':bank,'resolved':institution_map.get(bank,bank),'count':count} for bank,count in institutions.items()],
            'total':len(rows),'errors':errors[:100],'error_count':len(errors),'error_details':error_details[:100], 'previous_imports':previous[-5:],'unknown_assets':list(unknown.values()),'ignored':ignored[:100],'ignored_count':len(ignored),'token':token,**stats,
            'notes':['Custos ausentes no Excel ficam em zero; podem ser acrescentados ao registrar operações.',
                     'Tesouro: compras e resgates com quantidade/valor formam um histórico próprio por título e instituição. Saldo calculado pelo custo remanescente, não pelo preço de mercado; cupons ficam em proventos.',
                     'CDB, LCI e LCA: código e emissor são separados da instituição de custódia. O custo usa o valor monetário da operação; taxa, vencimento e liquidez permanecem desconhecidos. Rendimentos recebidos ficam em Proventos.',
                     'Liquidação só vira compra/venda com opção confirmada. A aba Negociação tem prioridade nos ativos de bolsa; títulos bancários vêm de Movimentação. Confira duplicidade com lançamentos manuais ou outros extratos.',
                     'Sem horário de execução: compras antes das vendas no mesmo dia. A apuração tributária intradia exige a nota de corretagem.',
                     'Não substitui posição anterior: importe todo o histórico ou registre o saldo anterior com seu custo.',
                     'Dividendos, JCP e rendimentos são separados das posições. Valor da operação é mantido conforme a base escolhida; não há IR presumido.']}

def commit(app,d):
    with app.WRITE_LOCK,app.connect() as c:
        plan=app.CSV_PREVIEWS.get(d.get('token'))
        if not plan or plan['kind']!='b3' or plan['expires']<time.time(): raise ValueError('Prévia expirou; confira novamente.')
        if revision(c)!=plan['revision']: raise ValueError('A carteira mudou; refaça a prévia.')
        if d.get('confirm_records') is not True: raise ValueError('Confirme as operações e posições antes de salvar.')
        if plan.get('has_openings') and d.get('confirm_openings') is not True:raise ValueError('Confirme que os saldos anteriores vieram do seu histórico e não de uma estimativa automática.')
        if plan['has_ignored'] and d.get('ack_ignored') is not True: raise ValueError('Confirme a revisão dos eventos excluídos antes de salvar.')
        result=apply(app,c,plan['rows'])
        receipt={'file_hash':plan['file_hash'],'filename':plan['filename'],'saved_at':app.now(),'added':result['added'],'skipped':result['skipped'],'ignored':plan['ignored_count']}
        receipts=app.read_cache(c,'import_receipts',[]);receipts.append(receipt)
        app.write_cache(c,'import_receipts',receipts[-500:]);result['receipt']=receipt
        app.CSV_PREVIEWS.pop(d['token'],None)
    return result
