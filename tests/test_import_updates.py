import unittest
import base64
from aporte_brasil.importers import b3_import
import test_app as baseline
from test_research import workbook
app=baseline.app

class ImportUpdatesTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def test_treasury_buy_coupon_sell_cost_and_restore(self):
        header='Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\n'
        rows=[f'Crédito;{self.day};COMPRA / VENDA;TESOURO IPCA+ 2032;XP;2;1000;2000',
              f'Crédito;{self.day};PAGAMENTO DE JUROS;TESOURO IPCA+ 2032;XP;2;50;100',
              f'Débito;{self.day};RESGATE ANTECIPADO;TESOURO IPCA+ 2032;XP;1;1100;1100']
        p=b3_import.preview(app,{'csv':header+'\n'.join(rows)})
        self.assertFalse(p['errors']);self.assertEqual(p['total'],3);self.assertEqual(p['ignored_count'],0)
        self.assertFalse(app.state()['fixed']);b3_import.commit(app,{'confirm_records':True,'token':p['token']})
        s=app.state();f=s['fixed'][0];self.assertEqual(f['balance'],1000);self.assertEqual(f['metadata']['treasury']['quantity'],1)
        self.assertEqual(s['income'][0]['amount'],100);self.assertEqual(f['conditions_known'],0)
        p=b3_import.preview(app,{'csv':header+'\n'.join(rows)});self.assertEqual(p['skipped'],3)
        app.mutate('/api/fixed/delete',{'id':f['id']})
        self.assertFalse(any(x['id']==f['id'] for x in app.state()['fixed']))
        app.mutate('/api/fixed/restore',{'id':f['id']})
        self.assertEqual(app.state()['fixed'][0]['metadata']['treasury']['quantity'],1)
        with app.connect() as c:data=app.export_data(c)
        app.mutate('/api/import',data)
        self.assertEqual(app.state()['fixed'][0]['balance'],1000)
        p=b3_import.preview(app,{'csv':header+'\n'.join(rows)});self.assertEqual(p['skipped'],3)
        f=app.state()['fixed'][0]
        app.mutate('/api/fixed-simple',{'id':f['id'],'name':f['name'],'type':f['type'],'institution':f['institution'],'balance':1200,'balance_date':self.day})
        f=app.state()['fixed'][0]
        self.assertEqual(f['metadata']['treasury']['valuation'],'statement')
        self.assertEqual(f['metadata']['treasury']['quantity'],1)
        self.assertEqual(f['invested'],1000)

    def test_unrecognized_fixed_does_not_block_supported_income(self):
        raw=f'Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\nCrédito;{self.day};Compra;CDB BANCO X;XP;1;100;100\nCrédito;{self.day};Dividendos;PETR4 - PETROBRAS;XP;1;1;1'
        p=b3_import.preview(app,{'csv':raw});self.assertFalse(p['errors']);self.assertEqual(p['total'],1);self.assertEqual(p['ignored_count'],1)
        self.assertIn('fora do importador',p['ignored'][0]['reason'])

    def test_settlement_opt_in_direction_negotiation_precedence(self):
        raw=f'Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\nCrédito;{self.day};Transferência - Liquidação;PETR4 - PETROBRAS;XP;3;30;90'
        p=b3_import.preview(app,{'csv':raw});self.assertEqual(p['total'],0)
        p=b3_import.preview(app,{'csv':raw,'include_settlements':True});self.assertFalse(p['errors']);self.assertEqual(p['total'],1)
        b3_import.commit(app,{'confirm_records':True,'token':p['token']});self.assertEqual(app.state()['assets'][0]['position']['quantity'],3)

    def test_negotiation_sheet_prevents_double_counting_settlement(self):
        trade_header=['Data do Negócio','Tipo de Movimentação','Código de Negociação','Quantidade','Preço','Valor','Instituição','Mercado']
        movement_header=['Entrada/Saída','Data','Movimentação','Produto','Instituição','Quantidade','Preço unitário','Valor da Operação']
        raw=workbook([('Negociação',[trade_header,[self.day,'Compra','PETR4',3,30,90,'XP','Mercado à Vista']]),
                      ('Movimentação',[movement_header,['Crédito',self.day,'Transferência - Liquidação','PETR4 - PETROBRAS','XP',3,30,90]])])
        p=b3_import.preview(app,{'xlsx':base64.b64encode(raw).decode(),'include_settlements':True})
        self.assertFalse(p['errors']);self.assertEqual(p['total'],1);self.assertEqual(p['ignored_count'],1)
        b3_import.commit(app,{'confirm_records':True,'token':p['token'],'ack_ignored':True})
        self.assertEqual(app.state()['assets'][0]['position']['quantity'],3)

    def test_archive_preserves_position_and_import_fingerprints(self):
        aid=self.asset();app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':4,'price':20,'date':self.day})
        app.mutate('/api/assets/delete',{'id':aid})
        s=app.state();self.assertFalse(s['assets']);self.assertEqual(s['archived_assets'][0]['id'],aid)
        with app.connect() as c:data=app.export_data(c)
        app.mutate('/api/import',data)
        self.assertFalse(app.state()['assets']);app.mutate('/api/assets/restore',{'id':aid})
        self.assertEqual(app.state()['assets'][0]['position']['quantity'],4)

if __name__=='__main__':unittest.main()
