import base64
import unittest
from datetime import timedelta
from aporte_brasil.importers import b3_import
import test_app as baseline
from test_research import workbook
app=baseline.app

class BankImportTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset
    title='CDB - CDBTEST1234 - BANCO FICTICIO S/A'
    header='Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\n'

    def preview(self,lines,**options):
        return b3_import.preview(app,{'csv':self.header+'\n'.join(lines),**options})

    def row(self,event='Transferência - Liquidação',direction='Credito',quantity=1,price=572.661473,amount=572.66,bank='CORRETORA FICTICIA',date=None,title=None):
        return f'{direction};{date or self.day};{event};{title or self.title};{bank};{quantity};{price};{amount}'

    def save(self,plan,**extra):
        return b3_import.commit(app,{'token':plan['token'],'confirm_records':True,**extra})

    def test_credit_settlement_requires_choice_and_preserves_total_not_guessed_rate(self):
        p=self.preview([self.row()]);self.assertIsNone(p['token']);self.assertEqual(p['ignored_count'],1)
        p=self.preview([self.row()],include_settlements=True)
        self.assertFalse(p['errors']);self.assertEqual(p['rows'][0]['record_type'],'bank_fixed')
        self.assertEqual(p['rows'][0]['unit_price_reported'],572.661473)
        self.assertEqual(p['position_changes'][0]['after']['cost'],572.66)
        self.assertEqual(app.state()['fixed'],[])
        self.save(p);f=app.state()['fixed'][0]
        self.assertEqual(f['type'],'CDB');self.assertEqual(f['issuer'],'BANCO FICTICIO S/A')
        self.assertEqual(f['institution'],'CORRETORA FICTICIA');self.assertEqual(f['balance'],572.66)
        self.assertEqual(f['indexer'],'Manual');self.assertEqual(f['conditions_known'],0)
        self.assertEqual(f['maturity'],'');self.assertEqual(f['metadata']['bank_fixed']['product_code'],'CDBTEST1234')

    def test_buy_redemption_income_and_repeat_after_restore(self):
        lines=[self.row('Compra',quantity=2,price=100,amount=200),self.row('Resgate Antecipado','Debito',quantity=.5,price=110,amount=55),self.row('Pagamento de Juros',quantity=1,price=8,amount=8)]
        p=self.preview(lines);self.assertFalse(p['errors']);self.save(p)
        s=app.state();f=s['fixed'][0]
        self.assertEqual(f['balance'],150);self.assertEqual(f['metadata']['bank_fixed']['quantity'],1.5)
        self.assertEqual(f['metadata']['bank_fixed']['realized'],5);self.assertEqual(s['income'][0]['amount'],8)
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        p=self.preview(lines);self.assertEqual(p['skipped'],3);self.assertEqual(p['added'],0)
        self.save(p);self.assertEqual(app.state()['fixed'][0]['balance'],150)

    def test_missing_purchase_stays_atomic_and_can_use_proven_opening(self):
        self.asset();lines=[self.row('Resgate','Debito',quantity=.5,price=110,amount=55),f'Entrada;{self.day};Compra;ABCD3;XP;1;10;10']
        p=self.preview(lines);self.assertIsNone(p['token']);self.assertEqual(p['balance_issues'][0]['record_type'],'bank_fixed')
        self.assertEqual(app.state()['fixed'],[]);self.assertFalse(app.state()['assets'][0]['trades'])
        opening={'ticker':self.title,'record_type':'bank_fixed','institution':'CORRETORA FICTICIA','quantity':1,'average':100,'date':(app.today()-timedelta(days=1)).isoformat()}
        p=self.preview(lines,opening_positions=[opening]);self.assertIsNotNone(p['token'])
        self.save(p,confirm_openings=True);self.assertEqual(app.state()['fixed'][0]['balance'],50)
        p=self.preview(lines,opening_positions=[opening]);self.assertEqual(p['skipped'],3)

    def test_same_title_in_different_custodians_does_not_merge(self):
        p=self.preview([self.row('Compra',bank='Corretora A'),self.row('Compra',bank='Corretora B')]);self.save(p)
        self.assertEqual(len(app.state()['fixed']),2)
        p=self.preview([self.row('Resgate','Debito',quantity=2,price=600,amount=1200,bank='Corretora A')])
        self.assertIsNone(p['token']);self.assertEqual(p['balance_issues'][0]['institution'],'Corretora A')

    def test_new_import_keeps_statement_balance_and_updates_cost(self):
        self.save(self.preview([self.row('Compra',price=100,amount=100)]));f=app.state()['fixed'][0]
        app.mutate('/api/fixed-simple',{'id':f['id'],'balance':105,'balance_date':self.day})
        self.save(self.preview([self.row('Compra',quantity=2,price=100,amount=200)]))
        f=app.state()['fixed'][0];self.assertEqual(f['balance'],105);self.assertEqual(f['invested'],300)
        self.assertEqual(f['metadata']['bank_fixed']['valuation'],'statement')

    def test_manual_holding_is_not_silently_merged(self):
        app.mutate('/api/fixed-simple',{'name':self.title,'type':'CDB','institution':'CORRETORA FICTICIA','balance':700,'balance_date':self.day})
        p=self.preview([self.row('Compra')]);self.assertIsNone(p['token']);self.assertIn('já tem saldo',p['errors'][0])
        self.assertEqual(app.state()['fixed'][0]['balance'],700)

    def test_bank_settlement_is_kept_when_equity_negotiation_tab_exists(self):
        self.asset()
        hs=self.header.strip().split(';')
        movement=[hs,self.row().split(';')]
        negotiation=[['Data do Negócio','Tipo de Movimentação','Código de Negociação','Quantidade','Preço','Valor','Instituição'],[self.day,'Compra','ABCD3',1,10,10,'XP']]
        p=b3_import.preview(app,{'xlsx':base64.b64encode(workbook([('Movimentação',movement),('Negociação',negotiation)])).decode(),'include_settlements':True})
        self.assertFalse(p['errors']);self.assertEqual(p['total'],2);self.assertEqual(p['ignored_count'],0)
        self.save(p);self.assertEqual(len(app.state()['fixed']),1);self.assertEqual(app.state()['assets'][0]['position']['quantity'],1)

    def test_lci_lca_identity_and_partial_monetary_data(self):
        for typ in ('LCI','LCA'):
            title=f'{typ} - {typ}TEST123 - BANCO FICTICIO S/A'
            self.save(self.preview([self.row('Compra',title=title)]))
        self.assertEqual({f['type'] for f in app.state()['fixed']},{'LCI','LCA'})
        p=self.preview([self.row('Compra',amount='')]);self.assertFalse(p['errors'])
        self.assertAlmostEqual(p['position_changes'][0]['after']['cost'],572.661473)
        p=self.preview([self.row('Compra',price='',amount='')]);self.assertIsNone(p['token'])

if __name__=='__main__':unittest.main()
