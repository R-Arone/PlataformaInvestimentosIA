"""Public CVM fund/class identities. A quota quote never changes a user's balance."""
import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import threading
import urllib.error
import urllib.request
import zipfile
from sector_analysis import fold

CAT_URL='https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip'
CAT_SOURCE='https://dados.cvm.gov.br/dataset/fi-cad'
QUOTE_SOURCE='https://dados.cvm.gov.br/dataset/fi-doc-inf_diario'
LOCK=threading.Lock()

def validate_metadata(metadata,number,valid_date):
    if set(metadata)-{'identity','quotes','treasury','bank_fixed','contract_rate_known','tesouro_position'}: raise ValueError('Pesquisa de fundo com campos desconhecidos.')
    if 'contract_rate_known' in metadata and not isinstance(metadata['contract_rate_known'],bool):raise ValueError('Identificação da taxa inválida.')
    for name in ('treasury','bank_fixed'):
        if name not in metadata:continue
        import treasury_import
        treasury_import.validate(metadata[name],number,valid_date)
    identity=metadata.get('identity')
    if identity is not None:
        if not isinstance(identity,dict) or identity.get('entity') not in ('fund','class') or identity.get('source')!=CAT_SOURCE:
            raise ValueError('Identificação CVM inválida no backup.')
        if any(not isinstance(v,str) or len(v)>3000 for v in identity.values()): raise ValueError('Dados cadastrais de fundo inválidos.')
        if not re.fullmatch(r'\d{14}',identity.get('cnpj','')): raise ValueError('CNPJ CVM inválido no backup.')
    q=metadata.get('quotes')
    if q is not None:
        if not isinstance(q,dict) or q.get('source')!=QUOTE_SOURCE or not isinstance(q.get('points'),list) or len(q['points'])>100:
            raise ValueError('Histórico de cotas inválido no backup.')
        for p in q['points']:
            valid_date(p['date']); number(p['value'],True,.00000001)
        if not isinstance(q.get('retrieved_at'),str) or not isinstance(q.get('cnpj'),str): raise ValueError('Consulta de cotas inválida.')

def download(url,limit=18_000_000):
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'AporteBrasil/3.0','Accept':'application/zip'})
        with urllib.request.urlopen(req,timeout=35) as response:
            data=response.read(limit+1)
        if len(data)>limit: raise ValueError('Arquivo público excedeu o limite desta consulta.')
        return data
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise ValueError('CVM indisponível nesta consulta. Tente novamente; o cadastro e saldo locais foram preservados.') from exc

def zipped_rows(data,filename=None,limit=180_000_000):
    try:
        z=zipfile.ZipFile(io.BytesIO(data))
        if sum(i.file_size for i in z.infolist())>limit: raise ValueError('Arquivo CVM muito grande após descompactação.')
        for name in z.namelist():
            if name.endswith('.csv') and (filename is None or name==filename):
                with z.open(name) as source:
                    yield from csv.DictReader(io.TextIOWrapper(source,encoding='cp1252'),delimiter=';')
    except (zipfile.BadZipFile,UnicodeError) as exc: raise ValueError('Arquivo da CVM não reconhecido; dados locais preservados.') from exc

def parse_catalog(data,stamp):
    parents={r['ID_Registro_Fundo']:r for r in zipped_rows(data,'registro_fundo.csv')}
    result=[]
    def entry(r,typ,parent):
        cnpj=re.sub(r'\D','',r.get('CNPJ_Classe') or r.get('CNPJ_Fundo') or '')
        return {'key':typ+':'+(r.get('ID_Registro_Classe') if typ=='class' else r.get('ID_Registro_Fundo','')),
                'entity':typ,'cnpj':cnpj,'name':r.get('Denominacao_Social',''), 'status':r.get('Situacao',''),
                'category':r.get('Classificacao') or r.get('Tipo_Classe') or r.get('Tipo_Fundo',''),
                'anbima':r.get('Classificacao_Anbima',''),'benchmark':r.get('Indicador_Desempenho',''),
                'administrator':parent.get('Administrador',''),'manager':parent.get('Gestor',''),
                'audience':r.get('Publico_Alvo',''),'condominium':r.get('Forma_Condominio',''),
                'parent_cnpj':parent.get('CNPJ_Fundo',''),'parent_name':parent.get('Denominacao_Social',''),
                'nav':r.get('Patrimonio_Liquido',''),'nav_date':r.get('Data_Patrimonio_Liquido',''),
                'source':CAT_SOURCE,'retrieved_at':stamp}
    for r in parents.values(): result.append(entry(r,'fund',r))
    for r in zipped_rows(data,'registro_classe.csv'):
        result.append(entry(r,'class',parents.get(r.get('ID_Registro_Fundo'),{})))
    return result

def catalog(app,force=False):
    target=app.DB_PATH.parent/'cvm-fundos.json'
    with LOCK:
        cached=None
        if target.exists():
            try: cached=json.loads(target.read_text(encoding='utf-8'))
            except (OSError,ValueError): pass
        if cached and not force and cached['retrieved_at'][:10]==app.today().isoformat(): return cached
        try:
            stamp=app.now(); rows=parse_catalog(download(CAT_URL),stamp)
            if not rows: raise ValueError('CVM retornou catálogo vazio; versão anterior preservada.')
            cached={'retrieved_at':stamp,'items':rows,'warning':''}
            temporary=target.with_suffix('.tmp')
            temporary.write_text(json.dumps(cached,ensure_ascii=False),encoding='utf-8'); temporary.replace(target)
            with app.WRITE_LOCK,app.connect() as c:
                app.log_source(c,'cvm_catalog','Cadastro de fundos e classes · CVM',CAT_SOURCE,asof=app.today().isoformat())
            return cached
        except ValueError as exc:
            with app.WRITE_LOCK,app.connect() as c:
                app.log_source(c,'cvm_catalog','Cadastro de fundos e classes · CVM',CAT_SOURCE,'error',error=str(exc))
            if cached: return {**cached,'warning':str(exc)+' Exibindo catálogo da última consulta.'}
            raise

def search(app,d):
    q=app.text_value(d.get('query',''),200,True)
    if len(q)<3: raise ValueError('Informe ao menos 3 letras do nome ou o CNPJ.')
    data=catalog(app,d.get('force') is True); digits=re.sub(r'\D','',q); text=fold(q)
    exact=[r for r in data['items'] if len(digits)==14 and r['cnpj']==digits]
    hits=exact or [r for r in data['items'] if text in fold(r['name']) or len(digits)>=6 and digits in r['cnpj']]
    hits.sort(key=lambda r:(r['status']!='Em Funcionamento Normal',r['entity']!='class',r['name']))
    return {'items':hits[:30],'total':len(hits),'retrieved_at':data['retrieved_at'],'warning':data.get('warning',''),
            'note':'Confirme o CNPJ e se sua aplicação é no fundo, classe ou subclasse. Subclasses sem CNPJ próprio não são diferenciadas por esta busca.'}

def detail(app,d):
    data=catalog(app); item=next((r for r in data['items'] if r['key']==d.get('key')),None)
    if not item: raise ValueError('Fundo/classe não encontrado. Refazer busca na CVM.')
    return item

def quotes(app,d):
    cnpj=re.sub(r'\D','',app.text_value(d.get('cnpj',''),25,True))
    if len(cnpj)!=14: raise ValueError('Informe o CNPJ de 14 dígitos da classe ou fundo.')
    grouped={}; errors=[]; consulted=[]
    first=app.today().replace(day=1); previous=(first-timedelta(days=1)).replace(day=1)
    for month in (previous,first):
        url='https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_'+month.strftime('%Y%m')+'.zip'
        path=app.DB_PATH.parent/('cvm-informe-'+month.strftime('%Y%m')+'.zip')
        try:
            fresh=path.exists() and datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).date()==app.today()
            if fresh: data=path.read_bytes()
            else:
                data=download(url,25_000_000)
                # Validate the archive before caching it.
                z=zipfile.ZipFile(io.BytesIO(data))
                if sum(i.file_size for i in z.infolist())>220_000_000: raise ValueError('Informe mensal muito grande para esta consulta.')
                path.write_bytes(data)
            consulted.append(url)
            for row in zipped_rows(data,limit=220_000_000):
                code=re.sub(r'\D','',row.get('CNPJ_FUNDO_CLASSE') or row.get('CNPJ_FUNDO') or '')
                if code!=cnpj: continue
                date=app.valid_date(row['DT_COMPTC']); value=app.clean(row.get('VL_QUOTA'))
                if date<=app.today().isoformat() and value is not None and value>0:
                    sid=row.get('ID_SUBCLASSE','').strip()
                    grouped.setdefault(sid,[]).append({'date':date,'value':value,'nav':app.clean(row.get('VL_PATRIM_LIQ')),'holders':app.clean(row.get('NR_COTST'))})
        except (ValueError,zipfile.BadZipFile) as exc: errors.append(str(exc))
    series=[{'id':sid,'label':'Subclasse '+sid if sid else 'Sem subclasse identificada no informe','count':len(items)} for sid,items in sorted(grouped.items())]
    selected=d.get('series')
    if selected is None and len(series)==1: selected=series[0]['id']
    chosen=grouped.get(selected,[]) if selected is not None else []
    by_date={}; conflict=False
    for point in chosen:
        if point['date'] in by_date and abs(point['value']-by_date[point['date']]['value'])>1e-9: conflict=True
        by_date[point['date']]=point
    points=sorted(by_date.values(),key=lambda p:p['date'])
    if conflict: points=[]; errors.append('Há cotas diferentes para a mesma série e data; consulte o administrador antes de usar.')
    result={'cnpj':cnpj,'points':points,'source':QUOTE_SOURCE,'files':consulted,'retrieved_at':app.now(),
            'series':series,'selected_series':selected,
            'errors':errors,'note':'Cotas publicadas para este CNPJ nos dois meses consultados. Não identifica automaticamente subclasses; confirme sua série de cotas. Não altera seu saldo, nem desconta taxas ou impostos do investidor.'}
    if len(series)>1 and selected is None:
        result['note']='Há mais de uma subclasse para este CNPJ. Escolha a série do seu extrato; as cotas não foram misturadas.'
    elif not points: result['note']='Nenhuma cota encontrada nos dois meses consultados. Confira o CNPJ da classe, a cobertura e os prazos de divulgação. '+result['note']
    with app.WRITE_LOCK,app.connect() as c:
        app.log_source(c,'cvm_quotes','Cotas de fundos · CVM',QUOTE_SOURCE,'ok' if points and not errors else 'error',
                       asof=points[-1]['date'] if points else '',error='; '.join(errors) or ('' if points else 'Sem cota para o CNPJ consultado.'))
    return result
