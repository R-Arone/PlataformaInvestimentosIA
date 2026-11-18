import unittest
from aporte_brasil.importers import b3_import
from aporte_brasil.importers import pluggy_connector as pc
import test_app as baseline
app=baseline.app
CID='f8c9b8f0-b8e2-4f0f-b8e2-4f0f8e2f0f8e';ITEM='0d5a0de2-9c82-4ea2-af50-31643a632a33';INV='f77eccf4-7714-498e-92a9-1bebe70335d9'

class FakePluggy:
    def __init__(self):self.calls=[]
    def __call__(self,method,path,body,key):
        self.calls.append((method,path,key))
        if path=='/auth':
            if body['clientSecret']=='recusado123':raise ValueError('Credenciais da Pluggy recusadas. Confira clientId e clientSecret.')
            return {'apiKey':'KEY'}
        if path.startswith('/investments?'):
            return {'page':1,'total':2,'totalPages':1,'results':[
              {'id':INV,'name':'PETROBRAS PN','code':'PETR4','type':'EQUITY','subtype':'STOCK','quantity':100,'balance':3000,'date':'2026-11-10T00:00:00.000Z','institution':{'name':'XP'}},
              {'id':'cdb1','name':'CDB BANCO XYZ','type':'FIXED_INCOME','subtype':'CDB','balance':2500,'dueDate':'2028-03-01T00:00:00.000Z','issuer':'BANCO XYZ','rateType':'CDI','rate':110}]}
        if path.startswith(f'/investments/{INV}/transactions'):
            return {'page':1,'total':3,'totalPages':1,'results':[
              {'id':'t1','type':'BUY','quantity':100,'value':28.5,'amount':2850,'date':'2026-01-10','tradeDate':'2026-01-09','brokerageNumber':'123','expenses':{'brokerageFee':1.5,'stockExchangeFee':0.3,'incomeTax':9}},
              {'id':'t2','type':'TRANSFER','quantity':1,'value':1,'amount':1,'date':'2026-01-11'},
              {'id':'t3','type':'SELL','quantity':20,'value':30,'amount':600,'date':'2026-02-01'}]}
        raise AssertionError('chamada inesperada '+path)

class PluggyTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def read(self,fetch=None,**extra):
        return pc.read(app,{'consent':True,'client_id':CID,'client_secret':'segredo12345','item_ids':[ITEM],'institution':'XP',**extra},fetch or FakePluggy())

    def test_reads_positions_and_trades_and_feeds_the_reviewed_preview(self):
        self.asset('PETR4')
        fake=FakePluggy();r=self.read(fake)
        self.assertEqual([c[0] for c in fake.calls][:1],['POST']);self.assertTrue(all(c[2]=='KEY' for c in fake.calls[1:]))
        self.assertEqual(r['trade_count'],2);self.assertEqual(len(r['positions']),2)
        stock=next(p for p in r['positions'] if p['ticker']=='PETR4')
        self.assertEqual((stock['institution'],stock['quantity'],stock['local_quantity'],stock['status_check']),('XP',100,0,'different'))
        self.assertEqual(next(p for p in r['positions'] if p['type']=='FIXED_INCOME')['due_date'],'2028-03-01')
        self.assertEqual(r['csv'].splitlines()[1].split(';'),['09/01/2026','Compra','PETR4','XP','Mercado à Vista','100','28,5','2850','1,8'])  # income tax is not a cost
        p=b3_import.preview(app,{'csv':r['csv'],'filename':r['filename'],'mode':'trades','sheet':'__all','amount_basis':'reported'})
        self.assertEqual(p['errors'],[]);self.assertEqual(len(p['rows']),2)

    def test_consent_credentials_items_and_since_are_validated(self):
        with self.assertRaisesRegex(ValueError,'Confirme'):pc.read(app,{'client_id':CID,'client_secret':'segredo12345','item_ids':[ITEM]},FakePluggy())
        with self.assertRaisesRegex(ValueError,'clientId'):self.read(client_id='x')
        with self.assertRaisesRegex(ValueError,'itemIds'):self.read(item_ids=['nao-e-uuid'])
        with self.assertRaisesRegex(ValueError,'recusadas'):self.read(client_secret='recusado123')
        r=self.read(since='2026-01-31');self.assertEqual(r['trade_count'],1)

    def test_nothing_is_saved_and_secrets_never_reach_the_result(self):
        before=app.state()['assets'];r=self.read()
        self.assertEqual(app.state()['assets'],before)
        self.assertNotIn('segredo12345',repr(r));self.assertNotIn('KEY',repr(r))

if __name__=='__main__':unittest.main()
