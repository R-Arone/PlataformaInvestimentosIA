"""Independent financial identities and dated climate predictors; fictional inputs only."""
import random
import unittest
from datetime import date

import test_app as baseline
from aporte_brasil.company import valuation as v
from aporte_brasil.company import factor_analysis as f
from test_factor_analysis import monthly_series, fixture

app=baseline.app

class FinancialIdentities(unittest.TestCase):
    def calculate(self,**kw):return v.calculate(kw,app.number)
    def values(self,**kw):return {m['method']:m['value'] for m in self.calculate(**kw)['methods']}

    def test_fcff_to_equity_subtracts_claims_once_and_accepts_net_cash(self):
        for debt in (10,-10,0):
            rows=self.values(fcff_per_share=4,fcff_growth=2,terminal_growth=2,wacc=10,
                forecast_years=7,net_debt_per_share=debt,other_claims_per_share=3)
            self.assertAlmostEqual(rows[v.FCFF],4*1.02/.08-debt-3)

    def test_unknown_debt_or_claims_is_not_zero(self):
        for missing in ('net_debt_per_share','other_claims_per_share'):
            inputs=dict(fcff_per_share=4,fcff_growth=2,terminal_growth=2,wacc=10,
                net_debt_per_share=0,other_claims_per_share=0)
            inputs.pop(missing)
            self.assertIsNone(self.values(**inputs)[v.FCFF])

    def test_multistage_ddm_equals_perpetuity_when_growth_is_constant(self):
        rows=self.values(dividends_per_share=2,dividend_growth=3,terminal_growth=3,required_return=12,growth=3)
        self.assertAlmostEqual(rows[v.DDM],2*1.03/.09)
        self.assertAlmostEqual(rows[v.DDM],rows['Gordon'])

    def test_residual_income_book_at_cost_and_equivalence_to_stable_model(self):
        rows=self.values(bvps=20,normalized_roe=12,terminal_roe=12,payout_ratio=75,required_return=12,terminal_growth=3)
        self.assertAlmostEqual(rows[v.RI],20)
        rows=self.values(bvps=20,normalized_roe=15,terminal_roe=15,payout_ratio=80,required_return=12,terminal_growth=3,growth=3)
        self.assertAlmostEqual(rows[v.RI],rows[v.PB])

    def test_turnaround_uses_explicit_negative_flows_before_positive_terminal(self):
        rows=self.values(fcfe_forecast='-2; -1; 4',required_return=12,terminal_growth=2)
        expected=-2/1.12-1/1.12**2+4/1.12**3+(4*1.02/.10)/1.12**3
        self.assertAlmostEqual(rows[v.FCFE],expected)
        self.assertIsNone(self.values(fcfe_forecast=[-2,-1],required_return=12,terminal_growth=2)[v.FCFE])

    def test_valuation_normalization_is_roundtrip_safe(self):
        r=self.calculate(price=20,fcfe_forecast=[-1,3],required_return=12,terminal_growth=2)
        self.assertEqual(r['inputs'],v.calculate(r['inputs'],app.number)['inputs'])
        empty=self.calculate()
        self.assertEqual(empty['inputs'],v.calculate(empty['inputs'],app.number)['inputs'])

    def test_expiring_concession_can_have_zero_terminal_value(self):
        rows=self.values(fcff_forecast=[5,4,-1],wacc=10,fcff_terminal_value=0,net_debt_per_share=1,other_claims_per_share=0)
        self.assertAlmostEqual(rows[v.FCFF],5/1.1+4/1.1**2-1/1.1**3-1)
        rows=self.values(fcfe_forecast=[5,4,-1],required_return=10,fcfe_terminal_value=0)
        self.assertAlmostEqual(rows[v.FCFE],5/1.1+4/1.1**2-1/1.1**3)

    def test_normalized_earnings_override_observed_earnings_for_pe(self):
        self.assertEqual(self.values(eps=10,normalized_eps=2,target_pe=12)[v.PE],24)
        self.assertIsNone(self.values(eps=10,normalized_eps=-2,target_pe=12)[v.PE])

    def test_ev_multiple_nav_sotp_and_no_negative_price(self):
        rows=self.values(ebitda_per_share=4,target_ev_ebitda=6,net_debt_per_share=8,other_claims_per_share=1,
            nav_assets_per_share=70,nav_liabilities_per_share=20,sotp_parts_per_share=100,
            sotp_adjustments_per_share=20,holding_discount=25)
        self.assertEqual(rows[v.EV],15);self.assertEqual(rows['NAV'],50);self.assertEqual(rows['Soma das partes'],60)
        self.assertIsNone(self.values(nav_assets_per_share=10,nav_liabilities_per_share=20)['NAV'])

    def test_epv_owner_and_peg_units(self):
        rows=self.values(normalized_eps=3,owner_earnings_per_share=2,required_return=10,eps=2,earnings_growth=15,target_peg=1)
        self.assertEqual(rows['EPV'],30);self.assertEqual(rows['Owner Earnings'],20);self.assertEqual(rows['PEG / Lynch'],30)

    def test_reverse_dcf_recovers_known_growth_and_rejects_missing_or_impossible(self):
        base=dict(fcfe_per_share=3,fcfe_growth=8,required_return=12,terminal_growth=3,forecast_years=5)
        price=self.values(**base)[v.FCFE]
        result=self.calculate(**base,price=price)['reverse_dcf']
        self.assertEqual(result['status'],'solved');self.assertAlmostEqual(result['growth'],8)
        self.assertEqual(self.calculate()['reverse_dcf']['status'],'missing')
        self.assertEqual(self.calculate(**base,price=1e12)['reverse_dcf']['status'],'outside_range')

    def test_numerical_guards(self):
        for kw in ({'fcff_per_share':True},{'fcfe_forecast':[True,2]},{'fcfe_forecast':[float('nan')]},
                   {'fcff_forecast':[1]*11},{'holding_discount':90},{'forecast_years':2.5}):
            with self.assertRaises(ValueError):self.calculate(**kw)

class SectorSelection(unittest.TestCase):
    def asset(self,sector,**kw):return dict(asset_type='stock',name='Empresa fictícia',ticker='EXMP3',sector=sector,sector_metrics={},**kw)
    def test_sectors_and_losses_route_to_appropriate_models(self):
        for sector,first in [('Bancos',v.RI),('Seguros',v.RI),('Holdings','Soma das partes'),('Saneamento',v.FCFF),('Tecnologia',v.FCFF)]:
            self.assertEqual(v.policy(self.asset(sector))['primary'][0],first)
        a=self.asset('Varejo');a['sector_metrics']={'eps':{'value':-2}}
        self.assertEqual(v.policy(a)['profile'],'loss')

    def test_screens_do_not_create_suggested_price(self):
        r=v.apply_policy(v.calculate(dict(eps=3,bvps=20,dividends_per_share=2,target_yield=6),app.number),v.policy(self.asset('Tecnologia')))
        self.assertIsNone(r['suggestion']['value']);self.assertEqual(r['comparison']['count'],0)

    def test_valuation_profile_override_and_broad_financial_sector(self):
        a=self.asset('Serviços financeiros e holdings')
        self.assertNotEqual(v.policy(a)['profile'],'holding')
        self.assertEqual(v.policy(a,{'valuation_profile':'holding'})['profile'],'holding')

    def test_priority_and_complementary_fallback(self):
        a=self.asset('Indústria')
        r=v.apply_policy(v.calculate(dict(eps=3,target_pe=10),app.number),v.policy(a))
        self.assertEqual(r['suggestion']['value'],30);self.assertTrue(r['suggestion']['fallback'])
        r=v.apply_policy(v.calculate(dict(eps=3,target_pe=10,fcfe_per_share=2,fcfe_growth=0,terminal_growth=0,required_return=10),app.number),v.policy(a))
        self.assertEqual(r['suggestion']['method'],v.FCFE);self.assertFalse(r['suggestion']['fallback'])

    def test_banks_exclude_ev_and_residual_models_are_one_family(self):
        inputs=dict(price=100,bvps=20,normalized_roe=15,terminal_roe=15,payout_ratio=80,required_return=12,growth=3,
            terminal_growth=3,ebitda_per_share=10,target_ev_ebitda=5,net_debt_per_share=0,other_claims_per_share=0)
        r=v.apply_policy(v.calculate(inputs,app.number),v.policy(self.asset('Bancos')))
        self.assertEqual(r['comparison']['count'],1)
        self.assertIsNone(next(m for m in r['methods'] if m['method']==v.EV)['value'])
        self.assertEqual(v.alert({'valuation':r})['status'],'above')

    def test_stale_observations_are_not_estimated(self):
        a=self.asset('Indústria');a.update(metrics={'price':30},snapshots={'quote':{'asof':'fresh'}},
            sector_metrics={'pe':{'value':10,'asof':'old'},'eps':{'value':3,'asof':'old'}})
        r=v.for_asset(a,{},app.number,lambda d:0 if d=='fresh' else 1000)
        self.assertIsNone(r['inputs']['eps']);self.assertEqual(r['estimates'],[])

class ClimateData(unittest.TestCase):
    def test_roni_season_is_dated_at_last_month_and_handles_sign_and_zero(self):
        raw='<p>RONI DJF</p><table><tr><th>2026</th><td>-0.9</td><td><span>0.0</span></td><td>0.6</td><td>NA</td><td>1.1</td></tr></table>'
        r=f.parse_enso(raw,date(2026,1,1),date(2026,6,15))
        self.assertEqual([(p['month'],p['value']) for p in r['points']],[('2026-02',-.9),('2026-03',0.),('2026-04',.6)])
        with self.assertRaises(ValueError):f.parse_enso('<p>no data</p>',date(2020,1,1),date(2026,10,19))
        snapshot=fixture();snapshot['factors']['enso']=dict(points=[dict(month='2026-09',date='2026-09-30',value=-.5)],source_url='https://example.org/climate')
        self.assertEqual(f.validate_snapshot(app,snapshot)['factors']['enso']['points'][0]['value'],-.5)
        snapshot['factors']['enso']['points'][0]['value']=20
        with self.assertRaises(ValueError):f.validate_snapshot(app,snapshot)

    def test_climate_scope_and_commodity_evidence(self):
        a=dict(asset_type='stock',name='Empresa fictícia',ticker='FOOD3',sector='Alimentos',snapshots={})
        s=f.scope(a);self.assertIn('enso',f.scope_keys(a));self.assertNotIn('corn',f.scope_keys(a))
        self.assertTrue({'regional_weather','crop_cycle','livestock_cycle'}<=set(r['key'] for r in s['research']))
        a['snapshots']['issuer_profile']=dict(asof='2026-10-19',data=dict(description='A empresa usa milho e trigo como insumos.',industry='',source_url='https://example.org'))
        self.assertTrue({'corn','wheat'}<=set(f.scope_keys(a)))

    def test_lagged_climate_recovers_known_coefficient(self):
        rng=random.Random(201);n=100
        x=[rng.uniform(-.2,.2) for _ in range(n)];m=[rng.uniform(-2,2) for _ in range(n)]
        climate=monthly_series(x,0,True)
        y=[(2*x[i-3] if i>=3 else 0)+.5*m[i] for i in range(n)]
        rows=f.analyze_series(f.changes(monthly_series(y)['points']),f.changes(monthly_series(m)['points']),{'enso':climate},'BR',date(2030,4,1),['enso'])
        self.assertAlmostEqual(rows[0]['effect'],2);self.assertEqual(rows[0]['lag_months'],3)
        self.assertEqual(f.recent(climate,f.FACTORS['enso'],date(2030,4,1))['difference_unit'],'°C')

if __name__=='__main__':unittest.main()
