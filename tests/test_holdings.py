import copy,json,unittest
from datetime import timedelta
import test_app as baseline
import csv_import,b3_import
app=baseline.app

class HoldingTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def opening(self,**kw):
        return {'quantity':10,'average':25,'date':(app.today()-timedelta(days=10)).isoformat(),
                'institution':'Banco teste','confirmed':True,**kw}

    def fixed(self,**kw):
        return {'name':'Tesouro IPCA+ 2032','type':'Tesouro','institution':'Banco teste','balance':1200,
                'balance_date':self.day,'indexer':'IPCA+','rate':'','tax':'','fee':'',**kw}

    def test_new_stock_and_etf_with_opening_are_atomic_and_persist(self):
        for ticker,typ in [('ABCD3','stock'),('TEST11','etf')]:
            with app.connect() as c:c.execute('INSERT INTO catalog VALUES (?,?,?,?,?,?,?)',(ticker,ticker,typ,'Varejo',0,'Teste',app.now()))
            d={'ticker':ticker,'asset_type':typ,'opening':self.opening()}
            v=app.mutate('/api/assets',d);self.assertTrue(v['opening_added'])
            a=next(a for a in app.state()['assets'] if a['ticker']==ticker)
            self.assertEqual(a['asset_type'],typ);self.assertEqual(a['position']['quantity'],10);self.assertEqual(a['position']['average'],25)
            self.assertTrue(a['trades'][0]['opening']);self.assertEqual(a['trades'][0]['fees'],0)
        app.init_db();self.assertEqual(len(app.state()['assets']),2)
        with app.connect() as c:c.execute('INSERT INTO catalog VALUES (?,?,?,?,?,?,?)',('FAIL3','Fail','stock','Varejo',0,'Teste',app.now()))
        with self.assertRaises(ValueError):app.mutate('/api/assets',{'ticker':'FAIL3','opening':self.opening(average=0)})
        self.assertNotIn('FAIL3',[a['ticker'] for a in app.state()['assets']])

    def test_opening_duplicate_same_bank_rejected_but_other_bank_allowed(self):
        aid=self.asset();d={'asset_id':aid,'opening':self.opening()}
        app.mutate('/api/positions/opening',d)
        self.assertTrue(app.mutate('/api/positions/opening',d)['duplicate'])
        with self.assertRaises(ValueError):app.mutate('/api/positions/opening',{'asset_id':aid,'opening':self.opening(quantity=20)})
        app.mutate('/api/positions/opening',{'asset_id':aid,'opening':self.opening(institution='Outro banco',quantity=5,average=40)})
        a=app.state()['assets'][0];self.assertEqual(a['position']['quantity'],15);self.assertEqual(a['position']['average'],30)
        self.assertEqual(len(a['trades']),2)

    def test_invalid_date_confirmation_boolean_and_history_roll_back_asset_edit(self):
        aid=self.asset()
        for kw in ({'date':(app.today()+timedelta(days=1)).isoformat()},{'confirmed':False},{'quantity':True},{'average':False},{'institution':''}):
            with self.assertRaises(ValueError):app.mutate('/api/positions/opening',{'asset_id':aid,'opening':self.opening(**kw)})
        app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':3,'price':20,'date':self.day,'institution':'Banco teste'})
        with self.assertRaises(ValueError):app.mutate('/api/assets',{'id':aid,'ticker':'ABCD3','notes':'Não deve salvar','opening':self.opening()})
        a=app.state()['assets'][0];self.assertEqual(a['notes'],'');self.assertEqual(a['position']['quantity'],3)

    def test_later_sale_recalculates_and_old_operations_are_not_counted_twice(self):
        aid=self.asset();opening=self.opening();app.mutate('/api/positions/opening',{'asset_id':aid,'opening':opening})
        old={'asset_id':aid,'side':'buy','quantity':10,'price':25,'date':opening['date'],'institution':'Banco teste'}
        with self.assertRaises(ValueError):app.mutate('/api/trades',old)
        raw=f"ticker,side,quantity,price,institution,date\nABCD3,buy,10,25,Banco teste,{opening['date']}"
        p=csv_import.preview(app,{'kind':'trades','csv':raw});self.assertTrue(p['errors'])
        raw=f"Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\nCrédito;{opening['date']};Compra;ABCD3;Banco teste;10;25;250"
        p=b3_import.preview(app,{'csv':raw});self.assertTrue(p['errors'])
        app.mutate('/api/trades',{**old,'side':'sell','quantity':4,'price':30,'date':self.day})
        a=app.state()['assets'][0];self.assertEqual(a['position']['quantity'],6);self.assertEqual(a['position']['average'],25);self.assertEqual(a['position']['cost'],150)

    def test_opening_survives_backup_and_stays_deduplicated(self):
        aid=self.asset();d={'asset_id':aid,'opening':self.opening()};app.mutate('/api/positions/opening',d)
        with app.connect() as c:data=app.export_data(c)
        app.mutate('/api/import',data);self.assertTrue(app.mutate('/api/positions/opening',d)['duplicate'])
        self.assertTrue(app.state()['assets'][0]['trades'][0]['opening'])

    def test_ipca_and_prefixado_without_rate_keep_modality_and_unknown_status(self):
        for idx in ('IPCA+','Prefixado'):
            rid=app.mutate('/api/fixed-simple',self.fixed(name='Tesouro '+idx,indexer=idx))['id']
            f=next(f for f in app.state()['fixed'] if f['id']==rid)
            self.assertEqual(f['indexer'],idx);self.assertFalse(f['rate_known']);self.assertFalse(f['conditions_known']);self.assertEqual(f['balance'],1200)
            app.mutate('/api/fixed-simple',self.fixed(id=rid,name=f['name'],indexer=idx,balance=1250))
            f=next(f for f in app.state()['fixed'] if f['id']==rid);self.assertFalse(f['rate_known']);self.assertEqual(f['balance'],1250)

    def test_unknown_rate_can_be_completed_or_cleared_without_changing_statement(self):
        rid=app.mutate('/api/fixed-simple',self.fixed())['id']
        app.mutate('/api/fixed-simple',self.fixed(id=rid,rate=6.5,tax=15,fee=.2))
        f=app.state()['fixed'][0];self.assertTrue(f['rate_known']);self.assertTrue(f['conditions_known']);self.assertEqual(f['rate'],6.5)
        app.mutate('/api/fixed-simple',self.fixed(id=rid,rate=0,tax=15,fee=0))
        f=app.state()['fixed'][0];self.assertTrue(f['rate_known']);self.assertEqual(f['rate'],0)
        app.mutate('/api/fixed-simple',self.fixed(id=rid,rate='',tax=15,fee=0))
        f=app.state()['fixed'][0];self.assertFalse(f['rate_known']);self.assertFalse(f['conditions_known']);self.assertEqual(f['balance'],1200)

    def test_treasury_unknown_rate_marker_survives_backup(self):
        app.mutate('/api/fixed-simple',self.fixed())
        with app.connect() as c:data=app.export_data(c)
        app.mutate('/api/import',data);self.assertFalse(app.state()['fixed'][0]['rate_known']);self.assertEqual(app.state()['fixed'][0]['indexer'],'IPCA+')
        bad=copy.deepcopy(data);bad['tables']['fixed'][0]['metadata']=json.dumps({'contract_rate_known':'true'})
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)

if __name__=='__main__':unittest.main()
