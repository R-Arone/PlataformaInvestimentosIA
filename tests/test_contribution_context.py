"""Evidence coverage, operating exposures and bounded scenario influence."""
import copy
import unittest
from datetime import timedelta
from unittest.mock import patch
from aporte_brasil.company import business_drivers as business
from aporte_brasil.portfolio import contribution_context as context
from aporte_brasil.company import quality_evidence
from aporte_brasil.company import company_evidence
from aporte_brasil.company import company_history
from aporte_brasil.company import company_research
from aporte_brasil.portfolio import long_term
from aporte_brasil.ai import market_ai
import test_app as baseline
import test_long_term as examples

app=baseline.app


def report(a):
    quote='As pessoas físicas representam 40% da carteira de crédito; juros maiores podem pressionar a inadimplência.'
    source=dict(id=1,title='Relatório sintético',url='https://example.org/report',content='Referência: '+app.today().isoformat()+'. '+quote,kind='page_read',retrieved_at=app.now())
    row=dict(id='synthetic-business',segment='pessoas físicas',basis='loan_book',share=40,factor='rates',sensitivity='hurts',mechanism='Juros maiores podem pressionar a capacidade de pagamento dos clientes; margem e garantias podem compensar.',asof=app.today().isoformat(),source_id=1,quote=quote,reviewed=False,origin='ai')
    return dict(symbol=company_history.symbol(a),asof=app.today().isoformat(),model='Modelo sintético',items=[row],sources=[source],warnings=[])


class EvidenceTests(unittest.TestCase):
    def test_three_known_passes_do_not_become_full_documented_quality(self):
        study={'groups':[{'key':'company','checks':[dict(status='pass') for _ in range(3)]+[dict(status='unknown') for _ in range(17)]}]}
        q=quality_evidence.summarize(study);self.assertEqual(q['documented_score'],15);self.assertEqual(q['coverage'],15);self.assertEqual(q['observed_score'],100);self.assertEqual(q['status'],'insufficient');self.assertEqual(q['fail'],0)
        study['groups'][0]['checks'][-1]['status']='fail';q=quality_evidence.summarize(study);self.assertEqual(q['unknown'],16);self.assertEqual(q['fail'],1);self.assertEqual(q['documented_score'],15);self.assertEqual(q['coverage'],20)

    def test_price_and_not_applicable_checks_do_not_dilute_company_evidence(self):
        q=quality_evidence.summarize({'groups':[dict(key='price',checks=[dict(status='fail')]),dict(key='company',checks=[dict(status='pass'),dict(status='na')])]})
        self.assertEqual(q['total'],1);self.assertEqual(q['documented_score'],100)
        self.assertIsNone(quality_evidence.summarize({})['documented_score'])


class ContextTests(unittest.TestCase):
    def fixture(self):
        local=examples.fixture();a=local.data['assets'][0];a['company_research']['factor_analysis']={'company':[dict(key='rates',label='Selic',status='positive',recent_status='positive',n=60,start='2020-01',end=(local.today().replace(day=1)-timedelta(days=1)).isoformat()[:7])]}
        local.data['contribution_context']={'indicators':[dict(key='rates',label='Selic',frequency='daily',source_url='https://example.org/rates',observation=dict(fresh=True,date=local.today().isoformat(),value=15,direction='up'))]}
        local.age=lambda ref:(local.today()-__import__('datetime').date.fromisoformat(str(ref)[:10])).days if ref else 99999
        return local,a

    def scenario(self,local,a,**kw):
        row=dict(id='a'*64,created_at=local.now(),model='Modelo sintético',inputs={'engine':'llm','question':'Hipótese sintética de investimento'},assets=[dict(ticker=a['ticker'],direction='favorable')],analysis={'assumptions':['Atividade mantém estabilidade'],'invalidation':['Inflação acelera e restringe o crédito']},sources=[])
        row.update(kw);local.data['ai']={'scenarios':[row]};return row

    def test_optional_economic_adjustment_and_stale_or_unstable_data(self):
        local,a=self.fixture();before=copy.deepcopy(local.data)
        base=context.evaluate(local,local.data,a,{'mode':'base'},70);self.assertEqual(base['priority_after'],70);self.assertEqual(base['adjustment'],0)
        r=context.evaluate(local,local.data,a,{'mode':'economic'},70);self.assertEqual(r['adjustment'],2.5);self.assertEqual(local.data,before)
        a['company_research']['factor_analysis']['company'][0]['recent_status']='negative'
        self.assertEqual(context.evaluate(local,local.data,a,{'mode':'economic'},70)['adjustment'],0)
        a['company_research']['factor_analysis']['company'][0]['recent_status']='positive';local.data['contribution_context']['indicators'][0]['observation']['date']='2000-01-01'
        self.assertEqual(context.evaluate(local,local.data,a,{'mode':'economic'},70)['adjustment'],0)

    def test_reviewed_business_can_matter_without_price_correlation(self):
        local,a=self.fixture();a['company_research']['factor_analysis']={};r=report(a);r['items'][0]['asof']=local.today().isoformat();a['snapshots'][business.KIND]={'data':r}
        self.assertEqual(context.evaluate(local,local.data,a,{'mode':'economic'},70)['adjustment'],0)
        r['items'][0]['reviewed']=True;self.assertEqual(context.evaluate(local,local.data,a,{'mode':'economic'},70)['adjustment'],-2.5)
        r['items'][0]['share']=0;self.assertEqual(context.evaluate(local,local.data,a,{'mode':'economic'},70)['adjustment'],0);r['items'][0]['share']=40
        # Overlapping shares are not summed into a fabricated 80% exposure.
        second=copy.deepcopy(r['items'][0]);second.update(id='second',sensitivity='benefits');r['items'].append(second)
        self.assertEqual(context.evaluate(local,local.data,a,{'mode':'economic'},70)['adjustment'],0)

    def test_selected_scenario_requires_recent_llm_and_explicit_ticker_coverage(self):
        local,a=self.fixture();s=self.scenario(local,a);opts=dict(mode='scenario',scenario_id=s['id'],scenario_weight=10)
        r=context.evaluate(local,local.data,a,opts,70);self.assertEqual(r['scenario_points'],5);self.assertEqual(r['adjustment'],7.5)
        s['assets']=[];self.assertEqual(context.evaluate(local,local.data,a,opts,70)['scenario_points'],0)
        s['created_at']='2000-01-01'
        with self.assertRaises(ValueError):context.evaluate(local,local.data,a,opts,70)
        s['created_at']=local.now();s['inputs']['engine']='channels'
        with self.assertRaises(ValueError):context.evaluate(local,local.data,a,opts,70)

    def test_scenario_cannot_release_an_asset_that_failed_quality_and_price_filters(self):
        local,a=self.fixture();s=self.scenario(local,a)
        check=a['company_research']['study']['groups'][0]['checks'][0];check['status']='fail'
        p=long_term.recommend(local,dict(amount=1000,mode='scenario',scenario_id=s['id'],scenario_weight=20,allocation_style='gradual',min_ticket=0))
        row=next(r for r in p['candidates'] if r['id']==a['id']);self.assertFalse(row['eligible']);self.assertEqual(row['amount'],0);self.assertLessEqual(row['economic_context']['adjustment'],10)
        for update in ({'scenario_weight':True},{'scenario_weight':21},{'scenario_id':'invalid'}):
            with self.assertRaises(ValueError):long_term.options(local,dict(amount=1000,mode='scenario',scenario_id=s['id'],**update)) if 'scenario_id' not in update else long_term.options(local,dict(amount=1000,mode='scenario',**update))


class BusinessTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def test_source_validation_review_and_backup_preserve_distinct_exposure(self):
        aid=self.asset();a=company_research.asset(app,aid);r=report(a);company_history.save(app,a,business.KIND,r,'Pesquisa sintética')
        self.assertFalse(business.active(company_research.asset(app,aid),app.age))
        business.review(app,dict(asset_id=aid,items=[dict(id=r['items'][0]['id'],share=35,sensitivity='mixed',mechanism='Fonte conferida: margem e risco de crédito têm efeitos opostos.')]));a=company_research.asset(app,aid)
        active=business.active(a,app.age);self.assertEqual(active[0]['share'],35);self.assertEqual(active[0]['origin'],'edited')
        with app.connect() as c:backup=app.export_data(c);app.restore(c,backup)
        self.assertEqual(business.active(company_research.asset(app,aid),app.age)[0]['share'],35)
        for key,value in [('quote','Trecho inventado sem sustentação na página'),('share',True),('share',101),('asof','2099-01-01')]:
            bad=copy.deepcopy(r);bad['items'][0][key]=value
            with self.assertRaises(ValueError):business.validate_snapshot(app,bad)
        bad=copy.deepcopy(r);bad['sources'][0]['kind']='search_excerpt'
        with self.assertRaises(ValueError):business.validate_snapshot(app,bad)

    def test_research_sends_only_public_identity_and_requires_real_quoted_percent(self):
        aid=self.asset();a=company_research.asset(app,aid);r=report(a);raw={k:v for k,v in r['items'][0].items() if k in ('segment','basis','share','factor','sensitivity','mechanism','asof','source_id','quote')}
        with app.connect() as c:c.execute('UPDATE assets SET name=? WHERE id=?',('PRIVATE PERSONAL LABEL',aid))
        with patch.object(market_ai,'research',return_value=(r['sources'],[])) as search,patch.object(market_ai,'generate',return_value=({'items':[raw]},'Synthetic model')) as generate:
            business.generate(app,{'asset_id':aid})
        self.assertNotIn('PRIVATE PERSONAL LABEL',str(search.call_args));self.assertNotIn('quantity',str(generate.call_args));self.assertFalse(business.active(company_research.asset(app,aid),app.age))
        saved=company_research.asset(app,aid)['snapshots'][business.KIND]['data'];self.assertEqual(saved['items'][0]['share'],40)
        original_segment=raw['segment'];raw['segment']='Segmento ausente do documento'
        with patch.object(market_ai,'research',return_value=(r['sources'],[])),patch.object(market_ai,'generate',return_value=({'items':[raw]},'Synthetic model')):business.generate(app,{'asset_id':aid})
        self.assertFalse(company_research.asset(app,aid)['snapshots'][business.KIND]['data']['items']);raw['segment']=original_segment
        raw['share']=90
        with patch.object(market_ai,'research',return_value=(r['sources'],[])),patch.object(market_ai,'generate',return_value=({'items':[raw]},'Synthetic model')):business.generate(app,{'asset_id':aid})
        self.assertFalse(company_research.asset(app,aid)['snapshots'][business.KIND]['data']['items'])
        raw['share']=40;r['sources'][0]['content']=r['items'][0]['quote']
        with patch.object(market_ai,'research',return_value=(r['sources'],[])),patch.object(market_ai,'generate',return_value=({'items':[raw]},'Synthetic model')):business.generate(app,{'asset_id':aid})
        self.assertFalse(company_research.asset(app,aid)['snapshots'][business.KIND]['data']['items'])

    def test_scenario_company_reference_uses_whole_checklist_not_tiny_positive_subset(self):
        a=company_research.asset(app,self.asset());a['company_research']['study']={'groups':[dict(key='company',checks=[dict(label='Known',status='pass')]*3+[dict(label='Missing',status='unknown')]*17)]}
        c=company_evidence.context(a,app.today());self.assertEqual(c['quality'],'incomplete');self.assertEqual(c['quality_counts']['unknown'],17)


if __name__=='__main__':unittest.main()
