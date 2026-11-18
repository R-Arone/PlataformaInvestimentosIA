import base64
from datetime import timedelta
import io
import json
import unittest
import zipfile
from xml.sax.saxutils import escape
from aporte_brasil.importers import b3_import
from aporte_brasil.company import funds
import test_app as baseline
from unittest.mock import patch
app=baseline.app

def workbook(sheets,shared=False):
    """Minimal XLSX fixtures exercise the actual local XML parser, not a mock reader."""
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="'+b3_import.NS['s']+'" xmlns:r="'+b3_import.NS['r']+'"><sheets>'+''.join('<sheet name="'+escape(name)+'" sheetId="'+str(i)+'" r:id="r'+str(i)+'"/>' for i,(name,rows) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships>'+''.join('<Relationship Id="r'+str(i)+'" Target="worksheets/sheet'+str(i)+'.xml"/>' for i in range(1,len(sheets)+1))+'</Relationships>')
        for i,(name,rows) in enumerate(sheets,1):
            xml='<worksheet xmlns="'+b3_import.NS['s']+'"><sheetData>'
            for n,row in enumerate(rows,1):
                xml+='<row r="'+str(n)+'">'
                for k,value in enumerate(row):
                    ref=chr(65+k)+str(n)
                    xml+=('<c r="'+ref+'"><v>'+str(value)+'</v></c>') if isinstance(value,(int,float)) else '<c r="'+ref+'" t="inlineStr"><is><t>'+escape(str(value))+'</t></is></c>'
                xml+='</row>'
            z.writestr('xl/worksheets/sheet'+str(i)+'.xml',xml+'</sheetData></worksheet>')
    return out.getvalue()

class ResearchTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset
    complete=baseline.AppTests.complete
    def check(self,aid,key):
        a=next(a for a in app.state()['assets'] if a['id']==aid)
        return next(c for c in a['sector_analysis']['checks'] if c['metric']==key)
    def risk(self,aid,**values):
        app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','source':'Relatório de teste','asof':self.day,**values})

    def test_profiles_sector_limits_and_missing_are_not_healthy(self):
        bank=self.asset('ABCD3','Bancos',True);energy=self.asset('EFGH3','Energia elétrica');retail=self.asset('IJKL3','Varejo')
        for aid in (bank,energy,retail):self.complete(aid,debt=3.2)
        self.assertFalse(any(c['metric']=='net_debt_ebitda' for c in app.state()['assets'][0]['sector_analysis']['checks']))
        self.assertEqual(self.check(bank,'basel')['status'],'unknown')
        self.risk(bank,basel=13,capital_required=11,npl90=0,coverage=120)
        self.assertEqual(self.check(bank,'basel')['status'],'pass');self.assertEqual(self.check(bank,'npl90')['status'],'pass')
        self.assertEqual(self.check(energy,'net_debt_ebitda')['status'],'pass')
        self.assertEqual(self.check(retail,'net_debt_ebitda')['status'],'unknown')
        self.risk(retail,lease_consistent=1,net_debt_ebitda=3.2)
        self.assertEqual(self.check(retail,'net_debt_ebitda')['status'],'fail')
        app.mutate('/api/settings',{'sector_rules':{'retail':{'net_debt_ebitda':4}}})
        self.assertEqual(self.check(retail,'net_debt_ebitda')['status'],'pass')
        with self.assertRaises(ValueError):app.mutate('/api/settings',{'sector_rules':{'bank':{'net_debt_ebitda':4}}})

    def test_peer_count_share_classes_dates_and_invalid_denominators(self):
        ids=[self.asset(t,'Energia elétrica') for t in ('ABCD3','ABCD4','EFGH3','IJKL3')]
        for aid,pvp in zip(ids,[1,.5,2,4]):self.complete(aid,pvp=pvp)
        c=self.check(ids[0],'pvp');self.assertEqual(c['limit'],3);self.assertEqual(len(c['peers']),2);self.assertEqual(c['status'],'pass')
        self.risk(ids[0],pvp=-1,debt_equity=-1,roic=10,wacc=12)
        self.assertEqual(self.check(ids[0],'pvp')['status'],'unknown')
        self.assertEqual(self.check(ids[0],'debt_equity')['status'],'unknown')
        self.assertEqual(self.check(ids[0],'roic')['status'],'fail')
        old=(app.today()-timedelta(days=181)).isoformat()
        app.mutate('/api/manual',{'asset_id':ids[0],'kind':'risk','source':'Antigo','asof':old,'interest_coverage':10})
        self.assertEqual(self.check(ids[0],'interest_coverage')['status'],'unknown')

    def test_simple_fund_unknown_cost_and_preserved_fields(self):
        app.mutate('/api/fixed-simple',{'name':'Meu fundo','type':'Fundo multimercado','institution':'Itaú','balance':1000,'balance_date':self.day})
        f=app.state()['fixed'][0];self.assertEqual(f['invested_known'],0);self.assertEqual(f['indexer'],'Manual')
        app.mutate('/api/fixed-simple',{'id':f['id'],'name':f['name'],'type':f['type'],'institution':f['institution'],'balance':1050,'balance_date':self.day,'source_url':'https://example.com/fundo'})
        f=app.state()['fixed'][0];self.assertEqual(f['balance'],1050);self.assertEqual(f['source_url'],'https://example.com/fundo')
        self.assertEqual(f['invested_known'],0);self.assertEqual(f['conditions_known'],0)
        with self.assertRaises(ValueError):app.mutate('/api/fixed-simple',{'id':f['id'],'source_url':'javascript:alert(1)'})
        self.assertEqual(app.state()['fixed'][0]['balance'],1050)

    def b3_csv(self):
        return 'Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\nCrédito;'+self.day+';Compra;PETR4 - PETROBRAS;XP;10;30;300\nCrédito;'+self.day+';Dividendos;PETR4 - PETROBRAS;XP;10;1,25;12,50\nCrédito;'+self.day+';Bonificação;PETR4 - PETROBRAS;XP;1;0;0'

    def test_b3_preview_atomic_income_dedupe_and_acknowledgment(self):
        p=b3_import.preview(app,{'csv':self.b3_csv()})
        self.assertFalse(p['errors']);self.assertEqual(p['total'],2);self.assertEqual(p['ignored_count'],1)
        self.assertEqual(len(app.state()['income']),0);self.assertEqual(len(app.state()['assets']),0)
        with self.assertRaises(ValueError):b3_import.commit(app,{'confirm_records':True,'token':p['token']})
        b3_import.commit(app,{'confirm_records':True,'token':p['token'],'ack_ignored':True})
        s=app.state();self.assertEqual(s['income'][0]['amount'],12.5);self.assertEqual(s['assets'][0]['position']['quantity'],10)
        p=b3_import.preview(app,{'csv':self.b3_csv(),'amount_basis':'net'});self.assertEqual(p['skipped'],2)
        b3_import.commit(app,{'confirm_records':True,'token':p['token'],'ack_ignored':True});self.assertEqual(len(app.state()['income']),1)
        p=b3_import.preview(app,{'csv':self.b3_csv().replace('Compra','Venda').replace(';10;30;300',';100;30;3000')})
        self.assertTrue(p['errors']);self.assertIsNone(p['token']);self.assertEqual(app.state()['assets'][0]['position']['quantity'],10)

    def test_b3_xlsx_two_sheets_excel_dates_duplicate_multiplicity(self):
        serial=(app.today()-__import__('datetime').date(1899,12,30)).days
        h=['Data do Negócio','Tipo de Movimentação','Mercado','Instituição','Código de Negociação','Quantidade','Preço','Valor']
        trade=[serial,'Compra','Mercado à Vista','XP','PETR4F',2,30,60]
        ih=['Entrada/Saída','Data','Movimentação','Produto','Instituição','Quantidade','Preço unitário','Valor da Operação']
        income=['Crédito',serial,'Juros Sobre Capital Próprio','PETR4 - PETROBRAS','XP',4,1,4]
        data=workbook([('Negociação',[h,trade,trade]),('Movimentação',[ih,income])])
        p=b3_import.preview(app,{'xlsx':base64.b64encode(data).decode(),'amount_basis':'gross'})
        self.assertFalse(p['errors']);self.assertEqual(p['total'],3)
        b3_import.commit(app,{'confirm_records':True,'token':p['token']})
        self.assertEqual(app.state()['assets'][0]['position']['quantity'],4)
        self.assertEqual(app.state()['income'][0]['kind'],'JCP');self.assertEqual(app.state()['income'][0]['amount'],4)
        p=b3_import.preview(app,{'xlsx':base64.b64encode(data).decode()});self.assertEqual(p['skipped'],3)
        app.mutate('/api/income',{'ticker':'PETR4','kind':'Dividendos','amount':5,'date':self.day})
        with self.assertRaises(ValueError):b3_import.commit(app,{'confirm_records':True,'token':p['token']})

    def test_income_edit_persistence_backup_and_deduplication(self):
        p=b3_import.preview(app,{'csv':self.b3_csv()});b3_import.commit(app,{'confirm_records':True,'token':p['token'],'ack_ignored':True})
        income=app.state()['income'][0];app.mutate('/api/income',{**income,'amount_basis':'net'})
        self.assertEqual(len(app.state()['income']),1)
        aid=app.state()['assets'][0]['id'];self.risk(aid,roic=12,wacc=10,interest_coverage=4)
        app.init_db();self.assertEqual(app.state()['income'][0]['amount_basis'],'net')
        with app.connect() as c:export=app.export_data(c)
        app.mutate('/api/import',export)
        self.assertEqual(app.state()['assets'][0]['snapshots']['risk']['data']['roic'],12)
        p=b3_import.preview(app,{'csv':self.b3_csv()});self.assertEqual(p['skipped'],2)

    def test_xlsx_rejects_bombs_macros_and_uncalculated_values(self):
        with self.assertRaises(ValueError):b3_import.read_xlsx(base64.b64encode(b'bad zip').decode())
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('xl/vbaProject.bin',b'a')
        with self.assertRaises(ValueError):b3_import.read_xlsx(base64.b64encode(out.getvalue()).decode())
        with self.assertRaises(ValueError):b3_import.xml(b'<!DOCTYPE a [<!ENTITY x "bad">]><a>&x;</a>')

    def test_cvm_fund_class_parent_identity_and_cache_failure(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('registro_fundo.csv','ID_Registro_Fundo;CNPJ_Fundo;Denominacao_Social;Gestor;Administrador;Situacao\n1;00000000000191;FUNDO TESTE;Gestor X;Adm X;Em Funcionamento Normal')
            z.writestr('registro_classe.csv','ID_Registro_Fundo;ID_Registro_Classe;CNPJ_Classe;Denominacao_Social;Situacao;Classificacao\n1;2;00000000000272;CLASSE TESTE;Em Funcionamento Normal;Renda Fixa')
        rows=funds.parse_catalog(out.getvalue(),app.now());self.assertEqual(rows[1]['manager'],'Gestor X');self.assertEqual(rows[1]['entity'],'class')
        with patch.object(funds,'download',return_value=out.getvalue()):
            r=funds.search(app,{'query':'00000000000272'});self.assertEqual(r['total'],1)
        with patch.object(funds,'download',side_effect=ValueError('Sem rede')):
            r=funds.search(app,{'query':'TESTE','force':True});self.assertEqual(r['total'],2);self.assertIn('última consulta',r['warning'])

    def test_cvm_quote_subclasses_never_mix_and_future_is_filtered(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            header='TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;ID_SUBCLASSE;DT_COMPTC;VL_QUOTA;VL_PATRIM_LIQ;NR_COTST\n'
            rows='FIF;00000000000191;A;'+self.day+';1.5;10000;10\nFIF;00000000000191;B;'+self.day+';2.5;10000;10\n'
            future=(app.today()+timedelta(days=1)).isoformat()
            z.writestr('inf_diario_fi.csv',header+rows+'FIF;00000000000191;A;'+future+';99;10000;10')
        with patch.object(funds,'download',return_value=out.getvalue()):
            q=funds.quotes(app,{'cnpj':'00000000000191'})
            self.assertEqual(q['points'],[]);self.assertEqual(len(q['series']),2)
            q=funds.quotes(app,{'cnpj':'00000000000191','series':'A'})
            self.assertEqual(len(q['points']),1);self.assertEqual(q['points'][0]['value'],1.5)

if __name__=='__main__':unittest.main()
