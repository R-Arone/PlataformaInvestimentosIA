"""Objective CVM registry facts, joined only through B3-confirmed CNPJ."""
import copy
import csv
from functools import lru_cache
import io
import urllib.request
from aporte_brasil.company import company_quality
from aporte_brasil.company import public_reports

URL='https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv'


@lru_cache(maxsize=1)
def catalog(day):
    req=urllib.request.Request(URL,headers={'User-Agent':'AporteBrasil/1.0'})
    with urllib.request.urlopen(req,timeout=25) as r:data=r.read(6_000_001)
    if len(data)>6_000_000:raise ValueError('Cadastro CVM excede o limite de consulta.')
    keys=('CNPJ_CIA','CD_CVM','DT_CONST','CONTROLE_ACIONARIO','SIT')
    return [{k:r.get(k,'') for k in keys} for r in csv.DictReader(io.StringIO(data.decode('latin1')),delimiter=';')]


def fill(app,a):
    from aporte_brasil.company import company_history
    profile=a.get('snapshots',{}).get('issuer_profile',{}).get('data',{})
    if a['asset_type']!='stock' or not a.get('verified') or len(public_reports.digits(profile.get('cnpj')))!=14:return []
    scope=str(app.DB_PATH);cnpj=public_reports.company_identity(app,a)
    if cnpj!=public_reports.digits(profile['cnpj']):raise ValueError('CNPJ do perfil difere da identidade confirmada na B3.')
    matches=[r for r in catalog(app.today().isoformat()) if public_reports.digits(r['CNPJ_CIA'])==cnpj and r['SIT']=='ATIVO']
    if len(matches)!=1:raise ValueError('Cadastro CVM ativo não identificado de forma única por CNPJ.')
    row=matches[0];facts={};today=app.today().isoformat()
    if row['DT_CONST']:
        value=app.valid_date(row['DT_CONST'])
        if value<=today:facts['founded']=dict(value=value,asof=today,source_url=URL,note='Data de constituição jurídica (DT_CONST) no cadastro CVM. Pode diferir da origem histórica da marca ou de uma empresa predecessora; edite se tiver evidência mais adequada.')
    control=row['CONTROLE_ACIONARIO']
    if control in ('ESTATAL','ESTATAL HOLDING','PRIVADO','PRIVADO HOLDING'):
        facts['state_controlled']=dict(value=control.startswith('ESTATAL'),asof=today,source_url=URL,note='CONTROLE_ACIONARIO: '+control+'. Esta classificação cadastral não responde sobre dependência de um cliente único.')
    with app.WRITE_LOCK,app.connect() as c:
        if str(app.DB_PATH)!=scope:raise ValueError('O banco mudou; preenchimento interrompido.')
        saved=copy.deepcopy(app.latest(c,a['id']).get(company_quality.KIND,{}).get('data',dict(symbol=company_history.symbol(a),facts={},annual_metrics=[])))
        added=[]
        for key,value in facts.items():
            if key in saved['facts'] or key=='founded' and 'founded_year' in saved['facts']:continue
            saved['facts'][key]=value;added.append(key)
        if added:
            payload=company_quality.validate_snapshot(app,saved)
            app.add_snapshot(c,a['id'],company_quality.KIND,payload,'Consulta pública · cadastro CVM por CNPJ confirmado',today)
    return added
