"""Fictional pullbacks: dated evidence, actual cash, no portfolio transmission."""
import copy
from datetime import timedelta,datetime,timezone
import unittest
from unittest.mock import patch

from aporte_brasil.portfolio import contrarian
from aporte_brasil.portfolio import investment_exposure
from aporte_brasil.portfolio import long_term
from aporte_brasil.portfolio import portfolio_strategy
import test_recommendation_signals as examples
import test_long_term as base
import test_security as security


def snapshot(local,growth=-.004,count=160):
    points=[dict(date=(local.today()-timedelta(days=count-i)).isoformat(),close=100*(1+growth)**i) for i in range(count)]
    return dict(data={'prices':points,'currency':'BRL'},source='Synthetic benchmark',source_url='https://example.org/fictional-market',retrieved_at=local.now())


def portfolio(br=-.004,fx=-.003):
    local=examples.established()
    local.data['contribution_context']=contrarian.public_state(local,{'markets':{'brazil':snapshot(local,br),'usd':snapshot(local,fx)}})
    return local


def recommend(local,**opts):
    return long_term.recommend(local,dict(amount=5000,allocation_style='contrarian',max_assets=2,min_ticket=500,**opts))


class ContrarianTests(unittest.TestCase):
    def test_dips_use_multi_session_evidence_not_one_red_day(self):
        local=portfolio();markets={r['key']:r for r in local.data['contribution_context']['markets']}
        self.assertTrue(markets['brazil']['active']);self.assertTrue(markets['usd']['active'])
        self.assertLess(markets['brazil']['return21'],-5);self.assertLess(markets['usd']['return21'],-3)
        self.assertTrue(markets['brazil']['source_url']);self.assertIsNotNone(markets['brazil']['asof'])
        stable=snapshot(local,0);stable['data']['prices'][-1]['close']=99
        r=contrarian.pullback(local,stable,'brazil')
        self.assertAlmostEqual(r['return1'],-1);self.assertFalse(r['active'])

    def test_ancient_short_or_unfinished_series_never_becomes_a_signal(self):
        local=portfolio();short=snapshot(local,count=63)
        self.assertFalse(contrarian.pullback(local,short,'usd')['available'])
        old=snapshot(local);old['data']['prices']=old['data']['prices'][:-10]
        self.assertFalse(contrarian.pullback(local,old,'brazil')['available'])
        good=snapshot(local,0);good['data']['prices'].append(dict(date=local.today().isoformat(),close=1))
        good['data']['prices'].append(dict(date=(local.today()+timedelta(days=1)).isoformat(),close=1))
        self.assertFalse(contrarian.pullback(local,good,'brazil')['active'])

    def test_brazil_drop_selects_only_good_discounted_stocks_and_respects_cash_caps(self):
        local=portfolio();before=copy.deepcopy(local.data)
        plan=recommend(local)
        self.assertEqual(local.data,before);self.assertEqual(plan['invested']+plan['unassigned'],5000)
        self.assertEqual(plan['invested'],5000)
        self.assertTrue(all(r['contraflow']['market_active'] for r in plan['candidates']))
        self.assertTrue(all(r['after_issuer_weight']<=20 for r in plan['candidates'] if r['amount']))
        self.assertEqual(sum(r['budget'] for r in plan['classes']),5000)
        self.assertEqual(plan['comparisons'][0]['allocation_style'],'contrarian')
        for change in ('quality','expensive','missing_quote'):
            altered=portfolio();a=altered.data['assets'][0]
            if change=='quality':a['company_research']['study']['groups'][0]['checks'][0]['status']='fail'
            if change=='expensive':a['valuation']['suggestion']['ceiling']=5
            if change=='missing_quote':a['snapshots'].pop('quote')
            r=next(r for r in recommend(altered)['candidates'] if r['id']==a['id'])
            self.assertFalse(r['eligible']);self.assertEqual(r['amount'],0)

    def test_no_dip_means_no_forced_purchase_and_an_individual_dip_can_suffice(self):
        local=portfolio(.002,.002)
        p=recommend(local);self.assertEqual(p['invested'],0)
        self.assertEqual(p['unassigned'],5000)
        a=local.data['assets'][0];examples.history(local,a,-.004)
        p=recommend(local);r=next(r for r in p['candidates'] if r['id']==a['id'])
        self.assertTrue(r['eligible']);self.assertTrue(r['contraflow']['own_active']);self.assertFalse(r['contraflow']['market_active'])
        self.assertGreater(r['amount'],0)

    def test_zero_goal_and_no_goals_do_not_block_opportunities(self):
        local=portfolio();cfg=local.data['settings'];cfg['allocation_targets'].update(national=0,rf=100)
        local.data['allocation']=portfolio_strategy.allocation(local.data['assets'],local.data['fixed'],cfg,local.age)
        self.assertEqual(recommend(local)['invested'],5000)
        cfg['allocation_targets']=None
        local.data['allocation']=portfolio_strategy.allocation(local.data['assets'],local.data['fixed'],cfg,local.age)
        p=recommend(local);self.assertEqual(p['invested'],5000);self.assertFalse(p['has_targets']);self.assertIsNone(p['distance_after'])

    def etf(self,local,ticker='IVVB11',growth=-.004):
        a=local.data['assets'][0];a.update(asset_type='etf',ticker=ticker,sector='ETF · Ações exterior' if ticker=='IVVB11' else 'ETF · Ações Brasil')
        a.pop('company_research');a.pop('valuation');a['exposure']=investment_exposure.metadata(a,{})
        a['exposure']['asof']=local.today().isoformat()
        examples.history(local,a,growth)
        local.data['allocation']=portfolio_strategy.allocation(local.data['assets'],local.data['fixed'],local.data['settings'],local.age)
        return a

    def test_dollar_drop_links_to_existing_etf_without_inventing_company_score(self):
        local=portfolio(br=.002);a=self.etf(local)
        p=recommend(local,mode='context');r=next(r for r in p['candidates'] if r['id']==a['id'])
        self.assertTrue(r['eligible']);self.assertGreater(r['amount'],0);self.assertIsNone(r['quality']);self.assertFalse(r['ai']['applied'])
        self.assertEqual(r['contraflow']['area'],'usd');self.assertTrue(r['contraflow']['market_active'])
        idea=next(i for i in p['market_ideas'] if i['key']=='usd')
        self.assertIn('IVVB11',idea['related']);self.assertIn('IVVB11',idea['eligible']);self.assertGreater(idea['suggested'],0)

    def test_cheaper_dollar_does_not_make_rising_expensive_etf_a_contrarian_buy(self):
        local=portfolio(.002,-.003);a=self.etf(local,growth=.002)
        p=recommend(local);r=next(r for r in p['candidates'] if r['id']==a['id'])
        self.assertFalse(r['contraflow']['active']);self.assertFalse(r['eligible']);self.assertEqual(r['amount'],0)
        self.assertTrue(next(i for i in p['market_ideas'] if i['key']=='usd')['active'])

    def test_broad_brazil_etf_and_unknown_mixed_or_unverified_exposure(self):
        local=portfolio();a=self.etf(local,'BOVA11')
        r=next(r for r in recommend(local)['candidates'] if r['id']==a['id']);self.assertTrue(r['eligible']);self.assertIsNone(r['quality'])
        for ticker in ('ABTC11','DEBB11','UNKNOWN11'):
            local=portfolio();a=self.etf(local,ticker)
            r=next(r for r in recommend(local,accept_estimates=True)['candidates'] if r['id']==a['id']);self.assertFalse(r['eligible'])

    def test_ideas_do_not_add_products_or_allocate_to_a_missing_dollar_product(self):
        local=portfolio();p=recommend(local)
        idea=next(i for i in p['market_ideas'] if i['key']=='usd')
        self.assertTrue(idea['active']);self.assertFalse(idea['related']);self.assertEqual(idea['suggested'],0)
        self.assertEqual(len(p['candidates']),len(local.data['assets']))
        a=self.etf(local);a['position']['quantity']=0;a['value']=0
        local.data['allocation']=portfolio_strategy.allocation(local.data['assets'],local.data['fixed'],local.data['settings'],local.age)
        p=recommend(local,universe='held');self.assertNotIn('IVVB11',next(i for i in p['market_ideas'] if i['key']=='usd')['related'])

    def test_dollar_below_peak_can_be_rising_this_month_without_false_comparison(self):
        local=portfolio();fx=snapshot(local,0)
        for i,p in enumerate(fx['data']['prices']):p['close']=100 if i<100 else 85+(i-100)*.1
        reference=contrarian.pullback(local,fx,'usd')
        self.assertTrue(reference['active']);self.assertGreater(reference['return21'],0)
        local.data['contribution_context']['markets']=[reference]
        idea=recommend(local)['market_ideas'][0]
        self.assertIn('máximo recente',idea['explanation']);self.assertNotIn('referência anterior',idea['explanation'])

    def test_ia_reorders_but_cannot_approve_bad_fundamentals(self):
        local=portfolio();a,b=local.data['assets'][:2]
        local.data['signals']={'rows':[examples.forecast(local,a,-100),examples.forecast(local,b,100)]}
        p=recommend(local,mode='context');self.assertTrue(p['ai_effect']['allocation_changed'])
        a['company_research']['study']['groups'][0]['checks'][0]['status']='fail'
        local.data['signals']['rows'][0]=examples.forecast(local,a,100)
        r=next(r for r in recommend(local,mode='context')['candidates'] if r['id']==a['id'])
        self.assertFalse(r['eligible']);self.assertEqual(r['amount'],0)

    def test_public_sources_validate_identity_currency_and_dates(self):
        local=portfolio();snap=snapshot(local)
        dates=[int(datetime.fromisoformat(p['date']).replace(hour=20,tzinfo=timezone.utc).timestamp()) for p in snap['data']['prices']]
        response={'chart':{'result':[dict(meta=dict(symbol='^BVSP',currency='BRL',instrumentType='INDEX'),timestamp=dates,
                    indicators={'quote':[{'close':[p['close'] for p in snap['data']['prices']]}]})]}}
        good=contrarian.index_snapshot(lambda _:response,local.today(),local.now());self.assertTrue(contrarian.pullback(local,good,'brazil')['active'])
        response['chart']['result'][0]['meta']['symbol']='WRONG'
        with self.assertRaises(ValueError):contrarian.index_snapshot(lambda _:response,local.today(),local.now())
        rows=[dict(data=datetime.fromisoformat(p['date']).strftime('%d/%m/%Y'),valor=str(p['close'])) for p in snap['data']['prices']]
        rows.extend([dict(data=local.today().strftime('%d/%m/%Y'),valor='1'),dict(data='errada',valor='NaN')])
        fx=contrarian.fx_snapshot(lambda _:rows,local.today(),local.now())
        self.assertLess(fx['data']['prices'][-1]['date'],local.today().isoformat())
        self.assertEqual(len(fx['data']['prices']),160)


class ContrarianPersistenceTests(unittest.TestCase):
    setUp=base.baseline.AppTests.setUp
    tearDown=base.baseline.AppTests.tearDown

    def test_failed_fetch_preserves_old_dates_and_does_not_send_the_portfolio(self):
        app=base.app;local=portfolio();old={'markets':{'usd':snapshot(local)},'retrieved_at':local.now()}
        with app.connect() as c:app.write_cache(c,contrarian.CACHE,old)
        calls=[]
        def request(url):calls.append(url);raise ValueError('Synthetic failure, no private content')
        with patch.object(app,'request_json',request):result=contrarian.refresh(app,{})
        self.assertEqual(len(calls),2)
        self.assertTrue(all('bcdata.sgs.1' in url or '%5EBVSP' in url for url in calls))
        self.assertEqual(len(result['errors']),2)
        with app.connect() as c:self.assertEqual(app.read_cache(c,contrarian.CACHE,{})['markets'],old['markets'])
        self.assertFalse(next(r for r in result['markets'] if r['key']=='usd')['available'])
        with self.assertRaises(ValueError):contrarian.refresh(app,{'tickers':['PRIVATE']})

    def test_generate_reads_cached_market_context_without_network_or_mutation(self):
        app=base.app
        with app.connect() as c:before=c.serialize()
        with patch.object(app,'request_json',side_effect=AssertionError('No network from recommendation')):
            plan=long_term.recommend(app,dict(amount=5000,allocation_style='contrarian'))
        self.assertEqual(plan['unassigned'],5000);self.assertEqual(len(plan['market_context']['markets']),2)
        with app.connect() as c:self.assertEqual(c.serialize(),before)


class ContrarianHTTPTests(unittest.TestCase):
    setUp=security.ProtectedAppTests.setUp
    tearDown=security.ProtectedAppTests.tearDown
    request=security.ProtectedAppTests.request

    def test_context_refresh_requires_session_and_csrf_before_network(self):
        app=base.app
        with patch.object(app,'request_json',side_effect=AssertionError('Unauthorized network')):
            self.assertEqual(self.request('/api/allocation/context',{})[0],401)
            self.assertEqual(self.request('/api/allocation/context',{},self.token,csrf=False)[0],403)
        with patch.object(app.contrarian,'refresh',return_value={'markets':[]}) as refresh:
            self.assertEqual(self.request('/api/allocation/context',{},self.token)[0],200)
            refresh.assert_called_once()


if __name__=='__main__':unittest.main()
