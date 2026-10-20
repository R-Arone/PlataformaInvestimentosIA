"""Financial boundaries, reference identity, persistence and protected endpoints."""
import copy
from datetime import date,timedelta
import json
import unittest
from unittest.mock import patch
import tesouro
import test_app as baseline
import test_security as protected

app=baseline.app
HEADER='Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha\n'


def csv_row(label='Tesouro IPCA+',maturity='15/05/2035',day='06/10/2026',buy='6,00',sell='6,12',price='2.000,00'):
    return ';'.join((label,maturity,day,buy,sell,'2.005,00',price,price))+'\n'


class TreasuryTests(unittest.TestCase):
    def setUp(self):
        baseline.AppTests.setUp(self)
        # All reference tests are deterministic and do not access the network.
        current=patch.object(tesouro,'fetch_current',side_effect=ValueError('offline'))
        current.start();self.addCleanup(current.stop)
    tearDown=baseline.AppTests.tearDown

    def save(self,kind='ipca',**kw):
        d={'kind':kind,'maturity':'2035-05-15','conversion':'','institution':'Instituição fictícia',
           'invested':1000,'balance':1400,'balance_date':self.day,'balance_basis':'gross',
           'quantity':1,'purchase_date':(app.today()-timedelta(days=800)).isoformat(),
           'purchase_rate':6,'single_lot':True,'notes':'Dados de teste'}
        d.update(kw)
        if kind in ('prefixado','prefixado_cupom','igpm_cupom'):d['maturity']=kw.get('maturity','2035-01-01')
        if kind in ('renda','educa'):d.update(maturity='',conversion=kw.get('conversion','2035-01-15'))
        if kind=='reserva':d.update(maturity='',quantity='',purchase_rate='')
        return tesouro.save(app,d)['id']

    def simulate(self,fid,**kw):
        d={'id':fid,'valuation':'statement','market_rate':6,'inflation':4,'selic':10,'future_ir':15,
           'future_cost':20,'sale_cost':5,'alternative_rate':8,'shock':1,'horizon':'2035-01-01'}
        d.update(kw)
        return tesouro.action(app,'/api/tesouro/simulate',d)

    def test_every_product_roundtrip_and_simulation(self):
        for kind in tesouro.PRODUCTS:
            fid=self.save(kind)
            r=self.simulate(fid)
            self.assertEqual(r['kind'],kind)
            self.assertGreater(r['gross_payments'],0)
            self.assertTrue(r['comparison'])
            self.assertTrue(all(v['gross']>=0 for v in r['flows']))
            if kind in ('renda','educa'):self.assertEqual(r['flow_count'],tesouro.PRODUCTS[kind]['payments'])
            if kind=='reserva':self.assertEqual(r['stress'],[])
            else:self.assertGreater(r['stress'][0]['gross'],r['stress'][-1]['gross'])
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        self.assertEqual(len(app.state()['fixed']),len(tesouro.PRODUCTS))
        self.assertTrue(all(f['tesouro']['configured'] for f in app.state()['fixed']))

    def test_conversion_final_date_monthly_weights_and_remaining_payments(self):
        for kind,n in (('renda',240),('educa',60)):
            p=tesouro.validate_profile(app,{'kind':kind,'conversion':'2030-01-15'})
            flows=tesouro.schedule(p,date(2029,12,31))
            self.assertEqual(len(flows),n)
            self.assertAlmostEqual(sum(v['principal'] for v in flows),1,12)
            self.assertEqual(flows[-1]['date'],f'{2030+n//12-1}-12-15')
            self.assertEqual(len(tesouro.schedule(p,date(2030,1,15))),n-1)
            self.assertNotEqual(flows[0]['principal'],flows[-1]['principal'])
        fid=self.save('educa',conversion='2026-01-15')
        r=self.simulate(fid)
        self.assertLess(r['flow_count'],60)
        self.assertGreater(r['flow_count'],0)

    def test_coupon_rates_are_distinct_from_purchase_rate_and_prefixado_face(self):
        fid=self.save('prefixado_cupom',purchase_rate=13,quantity=2,balance=1800,invested=1500)
        r=self.simulate(fid,market_rate=14,future_ir=0,future_cost=0)
        self.assertAlmostEqual(r['flows'][0]['coupon'],2000*((1.1)**.5-1))
        self.assertAlmostEqual(r['flows'][-1]['principal'],2000)
        fid=self.save('prefixado',quantity=2,balance=1700)
        r=self.simulate(fid,market_rate=12)
        self.assertEqual(r['flows'][0]['gross'],2000)

    def test_regressive_ir_iof_no_gain_tax_and_net_override(self):
        f={'invested':1000,'invested_known':True};p={'kind':'ipca','single_lot':True,'purchase_date':'2026-01-01'}
        for days,rate in ((180,22.5),(181,20),(360,20),(361,17.5),(720,17.5),(721,15)):
            r=tesouro.sale_net(app,f,p,1200,date(2026,1,1)+timedelta(days=days),10)
            self.assertEqual(r['ir_rate'],rate)
            self.assertAlmostEqual(r['net'],1200-200*rate/100-10)
        r=tesouro.sale_net(app,f,p,900,date(2026,1,10),5)
        self.assertEqual(r['ir'],0);self.assertEqual(r['net'],895)
        r=tesouro.sale_net(app,f,p,1200,date(2026,1,2))
        self.assertAlmostEqual(r['iof'],192)
        self.assertAlmostEqual(r['ir'],8*.225)
        r=tesouro.sale_net(app,f,p,1200,date(2026,1,2),50,1190)
        self.assertEqual(r['net'],1190);self.assertIsNone(r['ir'])

    def test_missing_cost_multiple_lots_net_balance_and_cost_ledger(self):
        fid=self.save(single_lot=False,purchase_date='')
        r=self.simulate(fid)
        self.assertIsNone(r['sale']['net']);self.assertIsNone(r['comparison'])
        self.assertIsNotNone(self.simulate(fid,sale_net=1300)['comparison'])
        fid=self.save(invested='',single_lot=False,purchase_date='')
        self.assertIsNone(self.simulate(fid,sale_net=1300)['comparison'])
        fid=self.save(balance_basis='net')
        with self.assertRaisesRegex(ValueError,'saldo bruto'):self.simulate(fid)
        fid=self.save()
        with app.connect() as c:
            meta=json.loads(c.execute('SELECT metadata FROM fixed WHERE id=?',(fid,)).fetchone()[0])
            meta['treasury']={'valuation':'cost','transactions':[],'quantity':1}
            c.execute('UPDATE fixed SET metadata=? WHERE id=?',(json.dumps(meta),fid))
        with self.assertRaisesRegex(ValueError,'custo importado'):self.simulate(fid)

    def test_liquidity_and_stale_reference_do_not_become_recommendations(self):
        fid=self.save('educa',purchase_date=(app.today()-timedelta(days=10)).isoformat())
        r=self.simulate(fid,sale_net=1300)
        self.assertFalse(r['comparison']['eligible'])
        self.assertTrue(any('carência' in w for w in r['warnings']))
        with self.assertRaises(ValueError):self.simulate(fid,sale_net=1500)
        with self.assertRaises(ValueError):self.simulate(fid,alternative_rate=float('nan'))

    def test_unchanged_balances_and_common_horizon_break_even(self):
        fid=self.save('prefixado',quantity='',balance=800,invested=700,single_lot=False)
        before=copy.deepcopy(app.state()['fixed'][0])
        r=self.simulate(fid,market_rate=10,sale_net=800,future_ir=0,future_cost=0)
        self.assertAlmostEqual(r['comparison']['breakeven_net_rate'],10,6)
        self.assertEqual(app.state()['fixed'][0],before)
        self.assertEqual(r['asof'],self.day)
        self.assertEqual(r['end'],'2035-01-01')
        fid=self.save('ipca_cupom',single_lot=False)
        r=self.simulate(fid,sale_net=1300,future_ir=15)
        self.assertIsNotNone(r['comparison']['breakeven_net_rate'])

    def test_quote_identity_historical_reference_no_future_or_bad_prices(self):
        data=HEADER+csv_row()+csv_row(maturity='15/05/2045')+csv_row(day='05/10/2026',buy='6,40')+csv_row(day='08/10/2026',sell='99,00')+csv_row(maturity='15/05/2055',price='NaN')
        r=tesouro.parse_csv(data,date(2026,10,7),[('ipca|2035-05-15','2026-10-05')])
        self.assertEqual(len(r['quotes']),2)
        self.assertEqual(r['quotes'][0]['sell_price'],2000)
        self.assertEqual(r['quotes'][0]['sell_rate'],6.12)
        self.assertEqual(r['history']['ipca|2035-05-15|2026-10-05']['buy_rate'],6.4)
        with self.assertRaises(ValueError):tesouro.parse_csv('bad;columns\n',app.today())
        with self.assertRaises(ValueError):tesouro.parse_csv(HEADER+csv_row()+csv_row(sell='7,00'),date(2026,10,7))

    def test_update_failure_preserves_cache_and_never_posts_wallet(self):
        fid=self.save(purchase_date='2026-10-05',single_lot=True)
        fixture=HEADER+csv_row()+csv_row(day='05/10/2026',buy='6,40')
        with patch.object(tesouro,'fetch_csv',return_value=fixture.encode()):tesouro.update(app)
        f=app.state()['fixed'][0]
        self.assertEqual(f['tesouro']['market_value'],2000)
        self.assertEqual(f['tesouro']['historical']['buy_rate'],6.4)
        self.assertEqual(f['balance'],1400)
        r=self.simulate(fid,valuation='market',sale_net=1900)
        self.assertEqual(r['market_rate'],6.12)
        with app.connect() as c:before=app.read_cache(c,'tesouro_market',{})
        with patch.object(tesouro,'fetch_csv',side_effect=ValueError('falha')):
            with self.assertRaises(ValueError):tesouro.update(app)
        with app.connect() as c:self.assertEqual(app.read_cache(c,'tesouro_market',{}),before)

    def test_invalid_profile_and_backup_roll_back(self):
        fid=self.save()
        for kwargs in ({'kind':'inventado'},{'kind':[]},{'quantity':-1},{'quantity':True},{'single_lot':'true'},{'balance_basis':'unknown'},{'purchase_date':'2099-01-01'}):
            d={'kind':'ipca','maturity':'2035-05-15',**kwargs}
            with self.assertRaises(ValueError):tesouro.validate_profile(app,d)
        with self.assertRaises(ValueError):tesouro.validate_profile(app,{'kind':'renda','conversion':'2030-05-15'})
        with self.assertRaises(ValueError):tesouro.validate_profile(app,{'kind':'educa','conversion':'2030-01-15','maturity':'2030-01-15'})
        with app.connect() as c:backup=app.export_data(c)
        bad=copy.deepcopy(backup);m=json.loads(bad['tables']['fixed'][0]['metadata']);m['tesouro_position']['quantity']=-1
        bad['tables']['fixed'][0]['metadata']=json.dumps(m)
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)
        self.assertEqual(app.state()['fixed'][0]['id'],fid)

    def test_estimate_quantity_only_from_gross_balance_and_same_day_price(self):
        fid=self.save(quantity='',balance=1500,balance_date='2026-10-05',purchase_date='2026-10-01')
        fixture=HEADER+csv_row(day='05/10/2026',price='2.000,00')+csv_row(day='06/10/2026',price='2.200,00')
        with patch.object(tesouro,'fetch_csv',return_value=fixture.encode()):tesouro.update(app)
        t=app.state()['fixed'][0]['tesouro']
        self.assertEqual(t['quantity'],.75);self.assertEqual(t['market_value'],1650)
        self.assertIn('estimada',t['quantity_source'])
        r=self.simulate(fid,valuation='market')
        self.assertTrue(any('quantidade foi estimada' in w for w in r['warnings']))
        self.save(id=fid,quantity='',balance_basis='net',balance=1500,balance_date='2026-10-05',purchase_date='2026-10-01')
        self.assertIsNone(app.state()['fixed'][0]['tesouro']['quantity'])

    def test_import_product_names_cover_legacy_reserve_and_renda_brand(self):
        import treasury_import
        for name in ('TESOURO IGP-M+ COM JUROS SEMESTRAIS 2031','TESOURO RESERVA',
                     'TESOURO RENDA+ APOSENTADORIA EXTRA 2035','TESOURO EDUCA+ 2030'):
            self.assertEqual(treasury_import.product(name),name)
        self.assertIsNone(treasury_import.product('TESOURO SELIC COM JUROS SEMESTRAIS 2030'))

    def test_current_quotes_exact_identity_spread_timestamp_and_inactive_purchase(self):
        row={'treasuryBondName':'Tesouro Selic 2027','maturityDate':'2027-03-01T00:00',
             'lastMarketPricingDate':'2026-10-07T15:26:44.400',
             'unitaryRedemptionValue':20046.60,'unitaryInvestmentValue':0,
             'redemptionProfitabilityFeeIndexerName':'SELIC - 0,0164%',
             'investmentProfitabilityIndexerName':'SELIC'}
        reserve={**row,'treasuryBondName':'Tesouro Reserva 2036','maturityDate':'2036-01-01T00:00',
                 'redemptionProfitabilityFeeIndexerName':'SELIC','unitaryInvestmentValue':11.07,'unitaryRedemptionValue':11.07}
        data={'TesouroLegado':[row,{**row,'lastMarketPricingDate':'2026-10-08T10:00'},
                               {**row,'unitaryRedemptionValue':True},{**row,'treasuryBondName':{}}],
              'Tesouro24x7':[reserve]}
        parsed=tesouro.parse_current(json.dumps(data),date(2026,10,7))
        self.assertEqual(len(parsed),2)
        q=next(q for q in parsed if q['kind']=='selic')
        self.assertEqual(q['sell_rate'],-.0164);self.assertIsNone(q['buy_price']);self.assertIsNone(q['buy_rate'])
        self.assertTrue(q['asof_at'].endswith('-03:00'));self.assertIsNone(q['base_price'])
        self.assertEqual(next(q for q in parsed if q['kind']=='reserva')['sell_rate'],0)
        with self.assertRaises(ValueError):tesouro.parse_current({'unexpected':[]},date(2026,10,7))
        with self.assertRaises(ValueError):tesouro.parse_current({'TesouroLegado':[row,{**row,'unitaryRedemptionValue':999}]},date(2026,10,7))

    def test_live_price_precedes_daily_without_using_live_pu_to_infer_quantity(self):
        fid=self.save(balance_date='2026-10-06',quantity='')
        daily=tesouro.parse_csv(HEADER+csv_row(),app.today())
        q={**daily['quotes'][0],'asof':self.day,'asof_at':self.day+'T15:26:44-03:00',
           'reference':'current','source':tesouro.CURRENT_SOURCE,'sell_price':2100,'sell_rate':6.5,'base_price':None}
        with app.connect() as c:app.write_cache(c,'tesouro_market',{**daily,'live_quotes':[q]})
        f=app.state()['fixed'][0]
        self.assertEqual(f['tesouro']['quantity'],.7)
        self.assertEqual(f['tesouro']['market_value'],1470)
        r=self.simulate(fid,valuation='market',sale_net=1300)
        self.assertEqual(r['gross'],1470);self.assertEqual(r['market_rate'],6.5);self.assertEqual(r['asof_at'],q['asof_at'])
        self.save(id=fid,quantity='',balance_date=self.day)
        self.assertIsNone(app.state()['fixed'][0]['tesouro']['quantity'])
        r=self.simulate(fid,market_rate='')
        self.assertEqual(r['market_rate'],6.5)
        self.assertEqual(r['source'],tesouro.CURRENT_SOURCE)

    def test_partial_failures_and_older_live_download_preserve_references(self):
        fixture=HEADER+csv_row()
        q=tesouro.parse_csv(fixture,app.today())['quotes'][0]
        q.update(asof=self.day,asof_at=self.day+'T15:26:44-03:00',reference='current',base_price=None)
        with patch.object(tesouro,'parse_current',return_value=[q]),patch.object(tesouro,'fetch_current',return_value=b'{}'),patch.object(tesouro,'fetch_csv',return_value=fixture.encode()):
            r=tesouro.update(app)
        self.assertEqual(r['warnings'],[])
        older={**q,'asof_at':self.day+'T10:00:00-03:00','sell_price':999}
        with patch.object(tesouro,'parse_current',return_value=[older]),patch.object(tesouro,'fetch_current',return_value=b'{}'),patch.object(tesouro,'fetch_csv',side_effect=ValueError('offline')):
            r=tesouro.update(app)
        self.assertTrue(r['warnings']);self.assertEqual(app.state()['tesouro']['quotes'][0]['sell_price'],2000)
        with patch.object(tesouro,'fetch_csv',return_value=fixture.encode()):r=tesouro.update(app)
        self.assertTrue(r['warnings']);self.assertEqual(app.state()['tesouro']['quotes'][0]['asof_at'],q['asof_at'])

    def test_minimal_registration_and_optional_scenario_inputs(self):
        fid=tesouro.save(app,{'kind':'prefixado','maturity':'2035-01-01','balance':800})['id']
        f=app.state()['fixed'][0]
        self.assertEqual(f['balance_date'],self.day);self.assertFalse(f['invested_known'])
        self.assertIsNone(f['tesouro']['profile']['purchase_rate']);self.assertFalse(f['tesouro']['profile']['single_lot'])
        r=tesouro.action(app,'/api/tesouro/simulate',{'id':fid,'market_rate':10,'future_ir':'','future_cost':'','sale_cost':'','alternative_rate':'','shock':''})
        self.assertEqual(len(r['stress']),3);self.assertIsNone(r['comparison'])
        self.assertEqual(r['assumptions']['future_ir']['value'],15)
        fid=self.save('prefixado',quantity='',balance=800,invested=700)
        r=self.simulate(fid,alternative_rate='',future_ir=0,future_cost='',sale_cost='',sale_net=800,market_rate=10)
        self.assertIsNone(r['comparison']);self.assertAlmostEqual(r['breakeven_net_rate'],10,6)

    def test_optional_index_uses_macro_reference_or_returns_sensitivity_only(self):
        fid=self.save(quantity='')
        with app.connect() as c:c.execute("DELETE FROM macro WHERE key='ipca'")
        r=self.simulate(fid,inflation='')
        self.assertEqual(len(r['stress']),3);self.assertEqual(r['flows'],[]);self.assertIsNone(r['gross_payments'])
        with app.connect() as c:c.execute('INSERT INTO macro VALUES (?,?,?,?,?)',('ipca',4.25,self.day,'Teste BCB',app.now()))
        r=self.simulate(fid,inflation='')
        self.assertEqual(r['assumptions']['inflation']['value'],4.25)
        self.assertEqual(r['assumptions']['inflation']['asof'],self.day);self.assertTrue(r['comparison'])
        fid=self.save('igpm_cupom')
        self.assertEqual(self.simulate(fid,inflation='')['flows'],[])


class TreasuryHTTPTests(unittest.TestCase):
    setUp=protected.ProtectedAppTests.setUp
    tearDown=protected.ProtectedAppTests.tearDown
    request=protected.ProtectedAppTests.request

    def test_endpoints_require_session_and_csrf_and_preserve_encrypted_backup(self):
        for route in ('save','update','simulate'):
            path='/api/tesouro/'+route
            self.assertEqual(self.request(path,{})[0],401)
            self.assertEqual(self.request(path,{},self.token,csrf=False)[0],403)
        d={'kind':'prefixado','maturity':'2035-01-01','institution':'Banco de teste','invested':1000,
           'balance':1200,'balance_date':self.day,'single_lot':True,
           'purchase_date':(app.today()-timedelta(days=800)).isoformat()}
        status,_,body=self.request('/api/tesouro/save',d,self.token)
        self.assertEqual(status,200);fid=json.loads(body)['id']
        status,_,body=self.request('/api/tesouro/simulate',{'id':fid,'market_rate':10,'alternative_rate':8,
            'future_ir':15,'future_cost':0,'sale_cost':0,'shock':1},self.token)
        self.assertEqual(status,200);self.assertIsNotNone(json.loads(body)['comparison'])
        status,_,body=self.request('/api/export',token=self.token)
        self.assertEqual(status,200);self.assertNotIn(b'tesouro_position',body)
        self.assertEqual(self.request('/tesouro.js')[0],200)


if __name__=='__main__':unittest.main()
