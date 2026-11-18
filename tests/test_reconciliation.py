import copy,json,unittest
from datetime import timedelta
from aporte_brasil.importers import b3_import
import test_app as baseline
app=baseline.app

class ReconciliationTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def data(self,rows):
        return {'csv':'Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\n'+'\n'.join(rows)}

    def opening(self,ticker='ABCD3',institution='XP',quantity=10,average=20,kind='trades',days=1):
        return {'ticker':ticker,'institution':institution,'record_type':kind,'quantity':quantity,'average':average,'date':(app.today()-timedelta(days=days)).isoformat()}

    def test_missing_stock_identified_and_preview_is_atomic_for_all_assets(self):
        self.asset();self.asset('EFGH3')
        d=self.data([f'Saída;{self.day};Venda;ABCD3;XP;3;25;75',f'Saída;{self.day};Venda;EFGH3;Itaú;7;10;70'])
        p=b3_import.preview(app,d)
        self.assertIsNone(p['token']);self.assertEqual(len(p['balance_issues']),2)
        issue=next(r for r in p['balance_issues'] if r['ticker']=='ABCD3')
        self.assertEqual(issue['institution'],'XP');self.assertEqual(issue['line'],2);self.assertEqual(issue['available'],0)
        self.assertEqual(issue['sold'],3);self.assertEqual(issue['required_quantity'],3)
        self.assertIn('ABCD3',p['errors'][0]);self.assertTrue(all(not a['trades'] for a in app.state()['assets']))

    def test_opening_cost_sale_and_explicit_final_confirmation(self):
        self.asset();d=self.data([f'Saída;{self.day};Venda;ABCD3;XP;3;25;75'])
        opening=self.opening();p=b3_import.preview(app,{**d,'opening_positions':[opening]})
        self.assertIsNotNone(p['token']);self.assertEqual(p['added'],2)
        self.assertEqual(p['position_changes'][0]['after']['quantity'],7)
        self.assertEqual(p['position_changes'][0]['after']['average'],20)
        self.assertEqual(p['position_changes'][0]['after']['realized'],15)
        self.assertTrue(p['rows'][0]['opening']);self.assertEqual(len(p['opening_rows']),1)
        self.assertFalse(app.state()['assets'][0]['trades'])
        with self.assertRaisesRegex(ValueError,'saldos anteriores'):b3_import.commit(app,{'token':p['token'],'confirm_records':True})
        b3_import.commit(app,{'token':p['token'],'confirm_records':True,'confirm_openings':True})
        a=app.state()['assets'][0];self.assertEqual(a['position']['quantity'],7);self.assertEqual(len(a['trades']),2)

    def test_repeated_opening_dedupes_after_backup_and_changed_cost_rejected(self):
        self.asset();d=self.data([f'Saída;{self.day};Venda;ABCD3;XP;3;25;75']);opening=self.opening()
        p=b3_import.preview(app,{**d,'opening_positions':[opening]});b3_import.commit(app,{'token':p['token'],'confirm_records':True,'confirm_openings':True})
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        p=b3_import.preview(app,{**d,'opening_positions':[opening]});self.assertEqual(p['skipped'],2);self.assertEqual(p['added'],0)
        b3_import.commit(app,{'token':p['token'],'confirm_records':True,'confirm_openings':True})
        self.assertEqual(app.state()['assets'][0]['position']['quantity'],7)
        p=b3_import.preview(app,{**d,'opening_positions':[{**opening,'average':22}]})
        self.assertIsNone(p['token']);self.assertIn('outros valores',p['errors'][0])

    def test_minimum_opening_uses_worst_deficit_but_does_not_auto_fill(self):
        self.asset();earlier=(app.today()-timedelta(days=2)).isoformat()
        d=self.data([f'Saída;{earlier};Venda;ABCD3;XP;3;25;75',f'Entrada;{self.day};Compra;ABCD3;XP;2;20;40',f'Saída;{self.day};Venda;ABCD3;XP;5;25;125'])
        p=b3_import.preview(app,d);self.assertEqual(p['balance_issues'][0]['required_quantity'],6);self.assertEqual(p['opening_rows'],[])
        p=b3_import.preview(app,{**d,'opening_positions':[self.opening(quantity=3,days=3)]})
        self.assertIsNone(p['token']);self.assertTrue(p['balance_issues'])
        self.assertFalse(app.state()['assets'][0]['trades'])

    def test_bad_opening_dates_missing_cost_wrong_bank_and_boolean_rejected(self):
        self.asset();d=self.data([f'Saída;{self.day};Venda;ABCD3;XP;3;25;75']);o=self.opening()
        for bad in ({**o,'date':self.day},{**o,'average':0},{**o,'average':True},{**o,'institution':'Outra'},{**o,'quantity':0}):
            p=b3_import.preview(app,{**d,'opening_positions':[bad]});self.assertIsNone(p['token']);self.assertTrue(p['errors'])
        self.assertFalse(app.state()['assets'][0]['trades'])

    def test_institution_alias_explicitly_resolves_without_fake_opening(self):
        aid=self.asset();old=(app.today()-timedelta(days=1)).isoformat()
        app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':10,'price':20,'fees':0,'date':old,'institution':'XP'})
        d=self.data([f'Saída;{self.day};Venda;ABCD3;XP INVESTIMENTOS;3;25;75'])
        p=b3_import.preview(app,d);self.assertEqual(p['balance_issues'][0]['other_institutions'][0]['institution'],'XP')
        p=b3_import.preview(app,{**d,'institution_map':{'XP INVESTIMENTOS':'XP'}})
        self.assertIsNotNone(p['token']);self.assertEqual(p['added'],1);self.assertEqual(p['opening_rows'],[])
        b3_import.commit(app,{'token':p['token'],'confirm_records':True})
        self.assertEqual(app.state()['assets'][0]['position']['quantity'],7)
        p=b3_import.preview(app,{**d,'institution_map':{'XP INVESTIMENTOS':'XP'}});self.assertEqual(p['skipped'],1)

    def test_old_purchases_cannot_double_count_saved_opening(self):
        self.asset();d=self.data([f'Saída;{self.day};Venda;ABCD3;XP;3;25;75']);opening=self.opening()
        p=b3_import.preview(app,{**d,'opening_positions':[opening]});b3_import.commit(app,{'token':p['token'],'confirm_records':True,'confirm_openings':True})
        older=(app.today()-timedelta(days=2)).isoformat()
        p=b3_import.preview(app,self.data([f'Entrada;{older};Compra;ABCD3;XP;10;20;200']))
        self.assertIsNone(p['token']);self.assertIn('saldo inicial',p['errors'][0])
        self.assertEqual(app.state()['assets'][0]['position']['quantity'],7)

    def test_new_date_cannot_duplicate_an_existing_opening(self):
        self.asset()
        cases=[('ABCD3','trades','Venda',3,25,75),('TESOURO SELIC 2031','treasury','Resgate Antecipado',.3,1000,300)]
        for ticker,kind,event,quantity,price,amount in cases:
            d=self.data([f'Saída;{self.day};{event};{ticker};XP;{quantity};{price};{amount}'])
            opening=self.opening(ticker=ticker,kind=kind)
            p=b3_import.preview(app,{**d,'opening_positions':[opening]})
            b3_import.commit(app,{'token':p['token'],'confirm_records':True,'confirm_openings':True})
            earlier=self.opening(ticker=ticker,kind=kind,days=2)
            p=b3_import.preview(app,{**d,'opening_positions':[earlier]})
            self.assertIsNone(p['token']);self.assertIn('já existe um saldo inicial',p['errors'][0])
        state=app.state();self.assertEqual(state['assets'][0]['position']['quantity'],7)
        self.assertEqual(len(state['fixed'][0]['metadata']['treasury']['transactions']),2)

    def test_treasury_missing_balance_opening_remainder_and_repeat(self):
        ticker='TESOURO SELIC 2031';d=self.data([f'Saída;{self.day};Resgate Antecipado;{ticker};XP;0,3;1000;300'])
        p=b3_import.preview(app,d);self.assertEqual(p['balance_issues'][0]['ticker'],ticker);self.assertEqual(p['balance_issues'][0]['record_type'],'treasury')
        opening=self.opening(ticker=ticker,quantity=1,average=900,kind='treasury')
        p=b3_import.preview(app,{**d,'opening_positions':[opening]});self.assertIsNotNone(p['token'])
        self.assertAlmostEqual(p['position_changes'][0]['after']['quantity'],.7);self.assertAlmostEqual(p['position_changes'][0]['after']['cost'],630)
        self.assertEqual(app.state()['fixed'],[])
        b3_import.commit(app,{'token':p['token'],'confirm_records':True,'confirm_openings':True})
        p=b3_import.preview(app,{**d,'opening_positions':[opening]});self.assertEqual(p['skipped'],2)
        self.assertAlmostEqual(app.state()['fixed'][0]['balance'],630)
        older=(app.today()-timedelta(days=2)).isoformat()
        p=b3_import.preview(app,self.data([f'Entrada;{older};Compra;{ticker};XP;1;900;900']))
        self.assertIsNone(p['token']);self.assertIn('saldo inicial',p['errors'][0])

if __name__=='__main__':unittest.main()
