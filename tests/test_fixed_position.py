import base64
import json
import unittest
from datetime import timedelta
from aporte_brasil.importers import b3_import
from aporte_brasil.portfolio import fixed_position
import test_app as baseline
from test_research import workbook
app=baseline.app
TREASURY=['Produto','Instituição','Código ISIN','Indexador','Vencimento','Quantidade','Valor Aplicado','Valor bruto','Valor líquido','Valor Atualizado']
FIXED=['Produto','Instituição','Emissor','Indexador','Tipo de regime','Data de Emissão','Vencimento','Quantidade','Quantidade Disponível','Preço Atualizado MTM','Valor Atualizado MTM','Preço Atualizado CURVA','Valor Atualizado CURVA']
CDB='CDB - CDB123ABCD - BANCO XYZ'
MOVEMENT='Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\n'

def ago(days):return (app.today()-timedelta(days=days)).isoformat()
def treasury(value,maturity='15/08/2032',quantity=1.5):return ['Tesouro IPCA+ 2032','XP','BRSTN','IPCA',maturity,quantity,1500,value,value-20,value]
def bank(curve,mtm,quantity=2):return [CDB,'XP','BANCO XYZ','PRE','Final','01/03/2025','01/03/2028',quantity,quantity,mtm/quantity,mtm,curve/quantity,curve]

class FixedPositionTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown

    def history(self):
        p=b3_import.preview(app,{'csv':MOVEMENT+f'Crédito;{ago(60)};COMPRA / VENDA;TESOURO IPCA+ 2032;XP;1,5;1000;1500\nCrédito;{ago(60)};Compra;{CDB};XP;2;1000;2000'})
        b3_import.commit(app,{'token':p['token'],'confirm_records':True})

    def preview(self,sheets,**extra):
        return fixed_position.preview(app,{'xlsx':base64.b64encode(workbook(sheets)).decode(),'filename':f'posicao-{ago(1)}-10-00-00.xlsx',**extra})

    def fixed(self,name):
        with app.connect() as c:
            return dict(c.execute('SELECT * FROM fixed WHERE upper(name)=?',(name.upper(),)).fetchone())

    def test_updates_balance_and_maturity_without_touching_cost_or_conditions(self):
        self.history()
        before=self.fixed('Tesouro IPCA+ 2032')
        p=self.preview([('Tesouro Direto',[TREASURY,treasury(1650)]),('Renda Fixa',[FIXED,bank(2300,2250)])])
        self.assertEqual(p['summary'],{'update':2,'new':0,'same':0,'older':0})
        self.assertEqual(self.fixed('Tesouro IPCA+ 2032'),before)  # preview is read-only
        rows={r['name']:r for r in p['rows']}
        self.assertEqual(rows[CDB]['b3_value'],2300)  # curve value is preferred over market value
        self.assertEqual(rows['TESOURO IPCA+ 2032']['maturity'],'2032-08-15')
        r=fixed_position.commit(app,{'token':p['token'],'confirm_records':True})
        self.assertEqual((r['updated'],r['created']),(2,0))
        after=self.fixed('Tesouro IPCA+ 2032')
        self.assertEqual((after['balance'],after['balance_date'],after['maturity']),(1650,ago(1),'2032-08-15'))
        for field in ('invested','indexer','rate','tax','fee','notes'):self.assertEqual(after[field],before[field])
        self.assertEqual(json.loads(after['metadata'])['treasury']['valuation'],'statement')
        self.assertEqual(self.fixed(CDB)['balance'],2300)
        again=self.preview([('Tesouro Direto',[TREASURY,treasury(1650)])])
        self.assertEqual(again['summary']['same'],1)

    def test_existing_maturity_and_newer_local_balance_are_kept(self):
        self.history()
        app.mutate('/api/fixed-simple',{'id':self.fixed('Tesouro IPCA+ 2032')['id'],'name':'Tesouro IPCA+ 2032','type':'Tesouro','institution':'XP','balance':1700,'balance_date':app.today().isoformat(),'maturity':'2031-01-01'})
        p=self.preview([('Tesouro Direto',[TREASURY,treasury(1650)])])
        self.assertEqual(p['rows'][0]['status'],'older')
        fixed_position.commit(app,{'token':p['token'],'confirm_records':True})
        kept=self.fixed('Tesouro IPCA+ 2032')
        self.assertEqual((kept['balance'],kept['maturity']),(1700,'2031-01-01'))

    def test_new_products_are_created_only_when_selected(self):
        p=self.preview([('Renda Fixa',[FIXED,bank(2300,2250)])])
        self.assertEqual((p['summary']['new'],p['rows'][0]['status']),(1,'new'))
        r=fixed_position.commit(app,{'token':p['token'],'confirm_records':True})
        self.assertEqual((r['created'],r['updated']),(0,0))
        p=self.preview([('Renda Fixa',[FIXED,bank(2300,2250)])])
        with self.assertRaisesRegex(ValueError,'fora da prévia'):
            fixed_position.commit(app,{'token':p['token'],'confirm_records':True,'create':['OUTRO|XP']})
        r=fixed_position.commit(app,{'token':p['token'],'confirm_records':True,'create':[CDB+'|XP']})
        self.assertEqual(r['created'],1)
        made=self.fixed(CDB)
        self.assertEqual((made['type'],made['balance'],made['invested_known'],made['conditions_known'],made['issuer']),('CDB',2300,0,0,'BANCO XYZ'))

    def test_guards_and_unrecognized_files(self):
        self.history()
        p=self.preview([('Tesouro Direto',[TREASURY,treasury(1650)])])
        with self.assertRaisesRegex(ValueError,'Confirme'):fixed_position.commit(app,{'token':p['token'],'confirm_records':False})
        app.mutate('/api/fixed-simple',{'id':self.fixed('Tesouro IPCA+ 2032')['id'],'name':'Tesouro IPCA+ 2032','type':'Tesouro','institution':'XP','balance':1000,'balance_date':ago(30)})
        with self.assertRaisesRegex(ValueError,'mudou'):fixed_position.commit(app,{'token':p['token'],'confirm_records':True})
        with self.assertRaisesRegex(ValueError,'Posição'):self.preview([('Acoes',[['Produto','Instituição','Quantidade'],['ABCD3','XP',1]])])
        unknown=self.preview([('Renda Fixa',[FIXED,['DEBENTURE XPTO','XP','EMPRESA','CDI','Final','01/01/2025','01/01/2030',1,1,1000,1000,1000,1000]])])
        self.assertEqual(unknown['unmatched_count'],1)
        self.assertEqual(unknown['rows'],[])

if __name__=='__main__':unittest.main()
