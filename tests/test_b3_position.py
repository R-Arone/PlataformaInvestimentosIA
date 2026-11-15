import base64
import unittest
from datetime import timedelta
import b3_import
import b3_position
import test_app as baseline
from test_research import workbook
app=baseline.app
STOCK=['Produto','Instituição','Conta','Código de Negociação','CNPJ da Empresa','Código ISIN / Distribuição','Tipo','Escriturador','Quantidade','Quantidade Disponível','Quantidade Indisponível','Motivo','Preço de Fechamento','Valor Atualizado']

def ago(days):return (app.today()-timedelta(days=days)).isoformat()
def stock(code,bank,quantity,price=10):return [code+' - EMPRESA',bank,'123',code,'00.000.000/0001-00','BR0000000000','ON','BANCO',quantity,quantity,0,'',price,quantity*price]

class PositionCheckTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def check(self,sheets,**extra):
        return b3_position.check(app,{'xlsx':base64.b64encode(workbook(sheets)).decode(),'filename':f'posicao-{ago(1)}-10-00-00.xlsx',**extra})

    def test_matches_differences_hints_and_nothing_saved(self):
        a=self.asset();b=self.asset('EFGH3');c=self.asset('IJKL3')
        app.mutate('/api/trades',{'asset_id':a,'side':'buy','quantity':100,'price':20,'date':ago(30),'institution':'XP'})
        app.mutate('/api/trades',{'asset_id':b,'side':'buy','quantity':50,'price':20,'date':ago(30),'institution':'XP'})
        app.mutate('/api/trades',{'asset_id':c,'side':'buy','quantity':7,'price':20,'date':ago(30),'institution':'Itaú'})
        app.mutate('/api/trades',{'asset_id':a,'side':'buy','quantity':5,'price':20,'date':app.today().isoformat(),'institution':'XP'})
        before=app.state()['assets']
        r=self.check([('Acoes',[STOCK,stock('ABCD3','XP',100),stock('EFGH3','XP',100),stock('MNOP3','XP',3),['Total','','','','','','','','','','','','',0]])])
        self.assertEqual(r['asof'],ago(1));self.assertEqual(r['sheets'],['Acoes'])
        rows={(x['ticker'],x['institution']):x for x in r['rows']}
        self.assertEqual(rows[('ABCD3','XP')]['status'],'ok')  # today's purchase is after the statement date
        self.assertEqual(rows[('EFGH3','XP')]['status'],'different');self.assertIn('desdobramento',rows[('EFGH3','XP')]['hint'])
        self.assertEqual(rows[('MNOP3','XP')]['status'],'only_b3')
        self.assertEqual(rows[('IJKL3','Itaú')]['status'],'only_local')
        self.assertEqual(r['summary'],{'different':1,'only_b3':1,'only_local':1,'ok':1})
        self.assertEqual(r['rows'][0]['ticker'],'EFGH3');self.assertEqual(rows[('ABCD3','XP')]['b3_value'],1000)
        self.assertEqual(app.state()['assets'],before)

    def test_institution_names_corporate_events_and_uncovered_classes(self):
        a=self.asset()
        app.mutate('/api/trades',{'asset_id':a,'side':'buy','quantity':100,'price':20,'date':ago(30),'institution':'XP'})
        p=b3_import.preview(app,{'csv':f'Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\nCrédito;{ago(10)};Desdobro;ABCD3;XP;100;-;-'})
        b3_import.commit(app,{'token':p['token'],'confirm_records':True,'confirm_events':True})
        app.mutate('/api/fixed-simple',{'name':'Tesouro Selic 2029','type':'Tesouro','institution':'XP','balance':1000,'balance_date':ago(5)})
        r=self.check([('Acoes',[STOCK,stock('ABCD3','XP INVESTIMENTOS CCTVM S/A',200)])])
        rows={(x['ticker'],x['institution']):x for x in r['rows']}
        self.assertEqual(rows[('ABCD3','XP INVESTIMENTOS CCTVM S/A')]['status'],'only_b3')
        self.assertIn('XP',rows[('ABCD3','XP INVESTIMENTOS CCTVM S/A')]['hint'])
        self.assertFalse(any(x['category']=='treasury' for x in r['rows']))
        r=self.check([('Acoes',[STOCK,stock('ABCD3','XP INVESTIMENTOS CCTVM S/A',200)])],institution_map={'XP INVESTIMENTOS CCTVM S/A':'XP'})
        self.assertEqual([x['status'] for x in r['rows']],['ok'])

    def test_treasury_quantity_and_wrong_file(self):
        header='Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\n'
        p=b3_import.preview(app,{'csv':header+f'Crédito;{ago(20)};COMPRA / VENDA;TESOURO IPCA+ 2032;XP;2;1000;2000'})
        b3_import.commit(app,{'token':p['token'],'confirm_records':True})
        treasury=['Produto','Instituição','Código ISIN','Indexador','Vencimento','Quantidade','Valor Aplicado','Valor bruto','Valor líquido','Valor Atualizado']
        r=self.check([('Tesouro Direto',[treasury,['Tesouro IPCA+ 2032','XP','BRSTN','IPCA','15/08/2032',1.5,1500,1600,1580,1600]])])
        row=r['rows'][0];self.assertEqual((row['ticker'],row['status'],row['category']),('TESOURO IPCA+ 2032','different','treasury'))
        self.assertEqual(row['difference'],-.5)
        movement=['Entrada/Saída','Data','Movimentação','Produto','Instituição','Quantidade','Preço unitário','Valor da Operação']
        with self.assertRaisesRegex(ValueError,'Extratos → Posição'):
            self.check([('Movimentação',[movement,['Crédito',ago(2),'Compra','ABCD3','XP',1,1,1]])])
        with self.assertRaisesRegex(ValueError,'futura'):
            self.check([('Acoes',[STOCK])],asof=(app.today()+timedelta(days=1)).isoformat())

if __name__=='__main__':unittest.main()
