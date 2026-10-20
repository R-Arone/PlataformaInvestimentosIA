"""Company business evidence gates factors; latest observations never become forecasts."""
import copy
import json
import unittest
from datetime import date
from unittest.mock import patch

import test_app as baseline
from test_factor_analysis import fixture, monthly_series, periods
import factor_analysis as model
import company_history
import company_research
import market_ai

app=baseline.app

def issuer(ticker='VALE3',mk='BR',description='',sector='Mineração'):
    a=dict(id=1,ticker=ticker,asset_type='stock' if mk=='BR' else 'foreign',sector=sector,name=ticker,snapshots={},company_research={})
    if description:
        a['snapshots']['issuer_profile']=dict(asof='2026-10-10',data=dict(symbol=ticker+('.SA' if mk=='BR' else ''),industry='',description=description,source_url='https://example.org/business'))
    return a

class FactorCriteriaTests(unittest.TestCase):
    asset=baseline.AppTests.asset
    def setUp(self):
        self.clock=patch.object(app,'today',return_value=date(2026,10,11));self.clock.start();baseline.AppTests.setUp(self)
    def tearDown(self):
        baseline.AppTests.tearDown(self);self.clock.stop()

    def test_macro_defaults_follow_market_and_do_not_infer_commodities_from_sector(self):
        a=issuer('ABCD3');s=model.scope(a)
        self.assertEqual([r['key'] for r in s['base']],list(model.CORE['BR']))
        self.assertFalse({'soy','iron','copper','gas'}&set(model.scope_keys(a)))
        us=issuer('TEST','US',sector='Tecnologia');self.assertEqual([r['key'] for r in model.scope(us)['base']],list(model.CORE['US']))
        self.assertNotIn('usd',model.scope_keys(us));self.assertNotIn('rates',model.scope_keys(us))

    def test_vale_products_with_issuer_source_never_soy_even_if_correlation_perfect(self):
        a=issuer();scope=model.scope(a);products={r['key']:r for r in scope['business']}
        self.assertTrue({'iron','copper','nickel'}<=products.keys());self.assertNotIn('soy',products)
        self.assertTrue(all(products[k]['role']=='output' and 'sec.gov' in products[k]['source_url'] for k in ('iron','copper','nickel')))
        d=fixture('VALE3.SA');d['factors']['soy']=copy.deepcopy(d['factors']['usd']);a['snapshots'][model.KINDS[0]]=dict(data=d)
        model.enrich(app,[a]);rows=a['company_research']['factor_analysis']['company']
        self.assertNotIn('soy',[r['key'] for r in rows]);self.assertEqual(next(r for r in rows if r['key']=='usd')['status'],'positive')

    def test_production_inputs_negation_and_description_take_precedence(self):
        s=model.scope(issuer('ABCD3',description='A empresa utiliza soja como insumo. Produz cobre. Não produz níquel.'))
        rows={r['key']:r for r in s['business']};self.assertEqual(rows['soy']['role'],'input');self.assertEqual(rows['copper']['role'],'output');self.assertNotIn('nickel',rows)
        a=issuer(description='A empresa produz minério de ferro.');self.assertIn('iron',model.scope_keys(a));self.assertNotIn('nickel',model.scope_keys(a))
        us=model.scope(issuer('TEST','US','The company produces soybeans and uses natural gas as a feedstock.','Alimentos'))
        self.assertEqual(next(r['role'] for r in us['business'] if r['key']=='gas'),'input')
        self.assertEqual(next(r['role'] for r in us['business'] if r['key']=='soy'),'output')

    def test_report_can_supply_missing_production_evidence(self):
        a=issuer('ABCD3');a['snapshots']['issuer_report']=dict(data=dict(title='Produtos',date='2026-09-01',url='https://example.org/report',text='A empresa produz soja e utiliza gás natural como insumo.'))
        self.assertIn('soy',model.scope_keys(a));self.assertFalse(model.scope(a)['needs_description']);self.assertIn('report',[f['id'] for f in model.ideas_context(a)[0]['facts']])
        self.assertEqual(next(r['role'] for r in model.scope(a)['business'] if r['key']=='soy'),'output')

    def test_manual_scope_validates_evidence_roles_duplicates_and_preserves_macro(self):
        a=issuer();payload=dict(symbol='VALE3.SA',market='BR',asof='2026-10-11',criteria=[dict(key='iron',role='output',evidence='Minério de ferro vendido',source_url='https://example.org')])
        a['snapshots'][model.KINDS[2]]=dict(data=model.validate_scope(app,payload));self.assertTrue(model.scope(a)['manual'])
        self.assertEqual(set(model.scope_keys(a)),set(model.CORE['BR'])|{'iron'})
        for change in ({'key':'usd'},{'role':'macro'},{'role':[]},{'evidence':''},{'key':'bad'}):
            bad=copy.deepcopy(payload);bad['criteria'][0].update(change)
            with self.assertRaises(ValueError):model.validate_scope(app,bad)
        bad=copy.deepcopy(payload);bad['criteria']*=2
        with self.assertRaises(ValueError):model.validate_scope(app,bad)

    def test_fixed_comparison_family_is_not_reduced_by_hiding_factors(self):
        d=fixture();y=model.changes(d['prices']['points']);m=model.changes(d['benchmark']['points'])
        selected=model.analyze_series(y,m,d['factors'],'BR',app.today(),['usd'])[0]
        all_rows=model.analyze_series(y,m,d['factors'],'BR',app.today());full=next(r for r in all_rows if r['key']=='usd')
        self.assertEqual(selected['interval'],full['interval']);self.assertEqual(selected['family_size'],19)
        legacy=model.fit([dict(month=t,y=y[t],x=model.changes(d['factors']['usd']['points'])[t],m=m[t]) for t in sorted(y)],family=6)
        self.assertGreater(selected['interval'][1]-selected['interval'][0],legacy['interval'][1]-legacy['interval'][0])

    def test_latest_open_month_is_context_not_an_extra_regression_observation(self):
        d=fixture();d['factors']['usd']['latest']=dict(date='2026-10-09',value=6,previous_date='2026-09-09',previous_value=5)
        d=model.validate_snapshot(app,d);row=next(r for r in model.analyze_series(model.changes(d['prices']['points']),model.changes(d['benchmark']['points']),d['factors'],'BR',app.today()) if r['key']=='usd')
        self.assertEqual(row['n'],59);self.assertEqual(row['end'],'2026-09');self.assertTrue(row['current']['partial']);self.assertTrue(row['current']['fresh']);self.assertAlmostEqual(row['current']['difference'],20)
        for change in ({'value':float('nan')},{'date':'2026-10-12'},{'previous_date':'2026-10-09'}):
            bad=copy.deepcopy(d);bad['factors']['usd']['latest'].update(change)
            with self.assertRaises(ValueError):model.validate_snapshot(app,bad)
        old=copy.deepcopy(d['factors']['usd']);old['latest']['date']='2026-08-09';old['latest']['previous_date']='2026-07-09'
        self.assertFalse(model.recent(old,model.FACTORS['usd'],app.today())['fresh'])

    def test_monthly_bcb_activity_and_negative_inflation(self):
        data=[dict(data='01/08/2026',valor='-0,2'),dict(data='01/09/2026',valor='-0,3')]
        with patch.object(app,'request_json',return_value=data):series=model.fetch_factor(app,'inflation',date(2026,8,1),app.today())
        self.assertEqual([r['value'] for r in series['points']],[-.2,-.3]);self.assertAlmostEqual(model.recent(series,model.FACTORS['inflation'],app.today())['difference'],-.1)
        with patch.object(app,'request_json',return_value=[dict(data='01/09/2026',valor='100')]) as request:
            self.assertEqual(len(model.fetch_factor(app,'activity',date(2026,8,1),app.today())['points']),1)
        self.assertIn('24364',request.call_args.args[0])

    def test_us_inflation_is_annual_change_not_index_and_missing_year_is_not_filled(self):
        months=periods(24);csv='observation_date,CPIAUCSL\n'+'\n'.join(m+'-01,'+str(100+i) for i,m in enumerate(months))
        with patch.object(model.company_insights,'request_text',return_value=csv):s=model.fetch_factor(app,'us_inflation',date(2022,10,1),app.today())
        self.assertAlmostEqual(s['points'][0]['value'],12);self.assertEqual(len(s['points']),12)
        missing=csv.replace('2021-11-01,101','2021-11-01,.')
        with patch.object(model.company_insights,'request_text',return_value=missing):s=model.fetch_factor(app,'us_inflation',date(2022,10,1),app.today())
        self.assertNotIn('2022-11',[p['month'] for p in s['points']])

    def ideas(self,a,key='iron'):
        ctx,digest=model.ideas_context(a);fact=next(f for f in ctx['facts'] if f['id']=='business')
        return dict(**ctx,asof='2026-10-11',model='mock-local',input_hash=digest,suggestions=[dict(criterion_id=key,role='output',why='Investigar preço e volume vendidos',source_id=fact['id'],quote='A Vale produz e vende minério de ferro e pelotas')])

    def test_ia_must_quote_real_company_product_and_cannot_invent_soy(self):
        valid=self.ideas(issuer());self.assertEqual(model.validate_ideas(app,valid)['suggestions'][0]['criterion_id'],'iron')
        for change in ({'criterion_id':'soy'},{'quote':'Produz soja'},{'source_id':'sector'},{'role':'macro'},{'role':[]}):
            bad=copy.deepcopy(valid);bad['suggestions'][0].update(change)
            with self.assertRaises(ValueError):model.validate_ideas(app,bad)
        bad=copy.deepcopy(valid);bad['facts'][0]['id']=[]
        with self.assertRaises(ValueError):model.validate_ideas(app,bad)
        bad=copy.deepcopy(valid);bad['facts'][1]['text']='A empresa não produz soja.';bad['suggestions'][0].update(criterion_id='soy',quote='produz soja')
        with self.assertRaises(ValueError):model.validate_ideas(app,bad)
        self.assertIn('iron',model.scope_keys(issuer(description='A empresa não produz soja.')))

    def test_ia_generation_persists_hypotheses_without_activating_factors(self):
        aid=self.asset();a=company_research.asset(app,aid)
        company_history.save(app,a,'issuer_profile',dict(symbol=company_history.symbol(a),name=a['name'],sector=a['sector'],industry='',description='A empresa utiliza gás natural como insumo.',cnpj='',website='',source_url='https://example.org/profile'),'Fixture')
        a=company_research.asset(app,aid)
        # A user previously chose no extra criteria; a suggestion must not change that choice.
        company_research.action(app,'/api/issuer/factor-scope',dict(asset_id=aid,criteria=[]))
        suggestion=dict(criterion_id='gas',role='input',why='Investigar custos contratados e hedge',source_id='profile',quote='A empresa utiliza gás natural como insumo')
        with patch.object(market_ai,'generate',return_value=({'suggestions':[suggestion]},'mock-local')):
            model.generate_ideas(app,dict(asset_id=aid))
        a=next(a for a in app.state()['assets'] if a['id']==aid);f=a['company_research']['factor_analysis']
        self.assertNotIn('gas',model.scope_keys(a));self.assertFalse(f['ideas']['stale'])
        a['snapshots']['issuer_profile']['data']['description']='A empresa mudou de atividade.';model.enrich(app,[a]);self.assertTrue(a['company_research']['factor_analysis']['ideas']['stale'])

    def test_missing_business_description_rejects_before_model_is_called(self):
        aid=self.asset()
        with patch.object(market_ai,'generate') as generate,self.assertRaisesRegex(ValueError,'descrição'):
            model.generate_ideas(app,dict(asset_id=aid))
        generate.assert_not_called()

    def test_reset_recomputes_automatic_scope_and_preserves_history(self):
        aid=self.asset();a=company_research.asset(app,aid)
        company_history.save(app,a,'issuer_profile',dict(symbol=company_history.symbol(a),name=a['name'],sector=a['sector'],industry='',description='A empresa utiliza gás natural como insumo.',cnpj='',website='',source_url='https://example.org/profile'),'Fixture')
        company_research.action(app,'/api/issuer/factor-scope',dict(asset_id=aid,criteria=[]))
        self.assertNotIn('gas',model.scope_keys(company_research.asset(app,aid)))
        company_research.action(app,'/api/issuer/factor-scope/reset',dict(asset_id=aid))
        a=company_research.asset(app,aid);self.assertIn('gas',model.scope_keys(a));self.assertFalse(model.scope(a)['manual'])
        with app.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM snapshots WHERE asset_id=? AND kind=?',(aid,model.KINDS[2])).fetchone()[0],2)

    def test_new_snapshots_backup_roundtrip_and_owner_isolation(self):
        aid=self.asset();a=company_research.asset(app,aid);symbol=company_history.symbol(a)
        company_research.action(app,'/api/issuer/factor-scope',dict(asset_id=aid,criteria=[dict(key='gas',role='input',evidence='Gás utilizado no forno',source_url='https://example.org')]))
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        self.assertIn('gas',model.scope_keys(next(a for a in app.state()['assets'] if a['ticker']==symbol[:-3])))
        bad=copy.deepcopy(backup)
        for s in bad['tables']['snapshots']:
            if s['kind']==model.KINDS[2]:
                d=json.loads(s['data']);d['symbol']='OTHER3.SA';s['data']=json.dumps(d)
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)

if __name__=='__main__':unittest.main()
