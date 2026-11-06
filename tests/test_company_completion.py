"""Missing evidence stays distinct from failures and unreviewed AI never sets a fact."""
import copy
from datetime import date
import io
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import company_completion as completion
import company_quality as quality
import company_history
import company_research
import public_reports
import market_ai
import long_term
import test_app as baseline
import test_contrarian as contra

app=baseline.app


class CompletionTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def report(self,aid,key='founded_year',value=1900):
        a=company_research.asset(app,aid);text='A companhia foi fundada em 1900. Documento público sintético para teste.'
        source=dict(id=1,title='Fonte sintética',url='https://example.org/company',content=text,kind='page_read',retrieved_at=app.now())
        candidate=dict(id='synthetic-proposal',kind='fact',key=key,value=value,asof=app.today().isoformat(),note='Trecho da história institucional, ainda exige revisão.',source_id=1,quote=text,status='pending',origin='ai_search',baseline=completion.digest(completion.current(app,a,'fact',key)),applied_hash='')
        return dict(symbol=completion.symbol(a),asof=app.today().isoformat(),model='Modelo sintético',candidates=[candidate],sources=[source],warnings=[])

    def save(self,aid,report):company_history.save(app,company_research.asset(app,aid),completion.KIND,report,'Pesquisa sintética')

    def test_pending_has_no_score_effect_and_review_retains_editable_origin(self):
        aid=self.asset();before=company_research.asset(app,aid);self.save(aid,self.report(aid))
        a=company_research.asset(app,aid);age=lambda a:next(c for c in a['company_research']['requested_quality']['checks'] if c['key']=='quality_age30')
        self.assertEqual(age(a)['status'],age(before)['status']);self.assertEqual(age(a)['status'],'unknown')
        completion.review(app,dict(asset_id=aid,items=[dict(id='synthetic-proposal',value=1900,note='História institucional conferida por mim.')]))
        a=company_research.asset(app,aid);self.assertEqual(age(a)['status'],'pass')
        c=next(c for g in a['company_research']['study']['groups'] for c in g['checks'] if c['key']=='quality_age30')
        self.assertIn('editado',c['provenance'][0]['label'])
        with app.connect() as conn:backup=app.export_data(conn);app.restore(conn,backup)
        a=company_research.asset(app,aid);self.assertEqual(age(a)['status'],'pass');self.assertTrue(a['company_research']['completion'])

    def test_concurrent_manual_change_is_not_overwritten_and_review_is_atomic(self):
        aid=self.asset();self.save(aid,self.report(aid));a=company_research.asset(app,aid)
        payload=dict(symbol=completion.symbol(a),facts={'founded_year':dict(value=1920,asof=app.today().isoformat(),note='Conferido manualmente.',source_url='https://example.org/manual')},annual_metrics=[])
        company_history.save(app,a,quality.KIND,payload,'Manual · fonte conferida')
        with self.assertRaisesRegex(ValueError,'mudou'):completion.review(app,dict(asset_id=aid,items=[dict(id='synthetic-proposal',value=1900,note='Tentar salvar pesquisa antiga.')]))
        self.assertEqual(completion.current(app,company_research.asset(app,aid),'fact','founded_year')['value'],1920)

    def test_bad_source_quote_false_corruption_and_future_date_are_rejected(self):
        aid=self.asset();valid=self.report(aid);self.assertEqual(completion.validate_snapshot(app,valid),valid)
        cases=[]
        for key,value in [('quote','Texto inventado que não está na página.'),('asof','2099-01-01'),('source_id',99),('kind',[]),('id',[])]:
            bad=copy.deepcopy(valid);bad['candidates'][0][key]=value;cases.append(bad)
        bad=copy.deepcopy(valid);bad['sources'][0]['kind']='search_excerpt';cases.append(bad)
        bad=self.report(aid,'corruption_history',False);cases.append(bad)
        for bad in cases:
            with self.assertRaises(ValueError):completion.validate_snapshot(app,bad)

    def test_ai_only_uses_received_pages_and_public_identity(self):
        aid=self.asset();a=company_research.asset(app,aid);a['name']='PRIVATE PERSONAL LABEL';report=self.report(aid)
        raw=dict(kind='fact',key='founded_year',value_json='1900',asof=app.today().isoformat(),source_id=1,quote=report['sources'][0]['content'],note='História institucional explicitamente documentada.')
        field=dict(kind='fact',key='founded_year',label='Fundação',baseline=completion.digest(None))
        with patch.object(market_ai,'research',return_value=(report['sources'],[])) as search,patch.object(market_ai,'generate',return_value=({'items':[raw]},'Sintético')) as model:
            items,_,_,_=completion.propose(app,a,[field])
        self.assertEqual(len(items),1);self.assertEqual(items[0]['status'],'pending')
        self.assertNotIn('PRIVATE PERSONAL LABEL',str(search.call_args));self.assertNotIn('PRIVATE PERSONAL LABEL',str(model.call_args))
        self.assertNotIn('quantity',str(model.call_args));self.assertNotIn('position',str(model.call_args))

    def test_financial_indicator_needs_an_explicit_period(self):
        aid=self.asset();a=company_research.asset(app,aid);report=self.report(aid)
        raw=dict(kind='metric',key='basel',value_json='17',asof=(app.today().replace(month=1,day=1)).isoformat(),source_id=1,quote=report['sources'][0]['content'],note='Indicador prudencial do conglomerado, em %.')
        field=dict(kind='metric',key='basel',label='Basileia',baseline=completion.digest(None))
        with patch.object(market_ai,'research',return_value=(report['sources'],[])),patch.object(market_ai,'generate',return_value=({'items':[raw]},'Sintético')):
            items,_,errors,_=completion.propose(app,a,[field])
        self.assertFalse(items);self.assertTrue(errors)

    def test_no_ai_preserves_manual_records_and_exposes_pending_fields(self):
        aid=self.asset();a=company_research.asset(app,aid);checks,fields=completion.missing(app,a)
        self.assertTrue(checks);self.assertTrue(any(f['key']=='founded_year' for f in fields))
        with patch.object(completion,'refresh_public',return_value={'received':['issuer_statements'],'warnings':['Fonte parcial']}),patch.object(completion,'propose') as infer:
            completion.run(app,dict(asset_ids=[aid],refresh_public=True,use_ai=False))
        infer.assert_not_called();a=company_research.asset(app,aid);self.assertFalse(a['company_research']['completion']['candidates'])
        with app.connect() as c:batch=app.read_cache(c,'issuer_completion_batch',{})
        self.assertFalse(batch['running']);self.assertEqual(batch['rows'][0]['before'],batch['rows'][0]['after'])

    def test_strict_request_and_year_only_foundation(self):
        aid=self.asset();d=dict(asset_ids=[aid],refresh_public=True,use_ai=False)
        self.assertEqual(completion.validate_request(app,d),d)
        for update in (dict(asset_ids=[aid,aid]),dict(asset_ids=[True]),dict(use_ai='yes'),dict(extra=1),dict(refresh_public=False)):
            with self.assertRaises(ValueError):completion.validate_request(app,{**d,**update})
        a=company_research.asset(app,aid)
        for year,status in ((app.today().year-31,'pass'),(app.today().year-30,'unknown'),(app.today().year-29,'fail')):
            a['snapshots'][quality.KIND]=dict(data=dict(facts={'founded_year':dict(value=year,asof=app.today().isoformat(),note='Ano documentado.',source_url='https://example.org/foundation')},annual_metrics=[]))
            c=next(c for c in quality.assess(app,a)['checks'] if c['key']=='quality_age30');self.assertEqual(c['status'],status)

    def test_public_financial_history_completes_checks_without_ai(self):
        from test_company_insights import CompanyInsightsTests
        aid=self.asset();a=company_research.asset(app,aid);payload=CompanyInsightsTests().statements()
        with patch.object(public_reports,'fetch_company',return_value=(payload,[])),patch.object(company_history,'fetch_profile',side_effect=ValueError('Sem perfil')),patch.object(company_history,'fetch_market',side_effect=ValueError('Sem mercado')),patch.object(public_reports,'company_dividends',side_effect=ValueError('Sem proventos')):
            result=completion.refresh_public(app,a)
        self.assertIn('issuer_statements',result['received']);a=company_research.asset(app,aid)
        checks={c['key']:c for c in a['company_research']['requested_quality']['checks']}
        self.assertEqual(checks['quality_roe5']['status'],'pass');self.assertEqual(checks['quality_growth5']['status'],'fail')
        before=copy.deepcopy(a['snapshots']['issuer_statements']['data'])
        company_history.save(app,a,'issuer_statements',before,'Manual · fonte conferida')
        with patch.object(public_reports,'fetch_company') as automatic,patch.object(company_history,'fetch_profile',side_effect=ValueError('Sem perfil')),patch.object(company_history,'fetch_market',side_effect=ValueError('Sem mercado')),patch.object(public_reports,'company_dividends',side_effect=ValueError('Sem proventos')):
            result=completion.refresh_public(app,company_research.asset(app,aid))
        automatic.assert_not_called();self.assertEqual(company_research.asset(app,aid)['snapshots']['issuer_statements']['data'],before)

    def test_one_company_failure_does_not_stop_the_selection(self):
        first=self.asset();second=self.asset('EFGH3');row=dict(asset_id=second,ticker='EFGH3',before=5,after=4,proposals=0,received=[],warnings=[])
        with patch.object(completion,'run_company',side_effect=[ValueError('Fonte indisponível'),row]):completion.run(app,dict(asset_ids=[first,second],refresh_public=True,use_ai=False))
        with app.connect() as c:batch=app.read_cache(c,'issuer_completion_batch',{})
        self.assertEqual(len(batch['rows']),2);self.assertEqual(batch['rows'][1]['ticker'],'EFGH3');self.assertFalse(batch['running'])

    def test_public_archive_is_reused_after_memory_cache_eviction(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:z.writestr('public.csv','Synthetic public content')
        raw=buffer.getvalue();public_reports.archive.cache_clear()
        with public_reports.shared_archives(self.tmp.name),patch.object(public_reports.urllib.request,'urlopen',return_value=io.BytesIO(raw)) as download:
            one=public_reports.archive('https://dados.cvm.gov.br/dados/synthetic.zip',100);public_reports.archive.cache_clear()
            two=public_reports.archive('https://dados.cvm.gov.br/dados/synthetic.zip',100)
        self.assertEqual(one,two);self.assertEqual(download.call_count,1);public_reports.archive.cache_clear()

    def test_search_budget_covers_each_topic_even_when_page_reads_fail(self):
        with app.connect() as c:app.write_cache(c,'ai_search_key','synthetic-key-not-valid')
        calls=[]
        def request(url,payload,token):
            calls.append((url,payload))
            if url.endswith('/web_fetch'):raise ValueError('Página indisponível')
            return {'results':[dict(title='Página sintética',url='https://example.org/'+payload['query']+'/'+str(i),content='Trecho sintético do resultado de busca.') for i in range(4)]}
        with patch.object(market_ai,'request',side_effect=request):sources,errors=market_ai.research(app,'Empresa pública',queries=['topic-'+str(i) for i in range(4)])
        reads=[p['url'] for url,p in calls if url.endswith('/web_fetch')]
        self.assertEqual(len(reads),6);self.assertTrue(any('topic-3' in url for url in reads));self.assertEqual(len(errors),6)
        self.assertTrue(all(s['kind']=='search_excerpt' for s in sources))


class ScoreTests(unittest.TestCase):
    def test_missing_and_negative_have_different_known_scores_and_coverage(self):
        local=contra.portfolio();a=local.data['assets'][0];checks=a['company_research']['study']['groups'][0]['checks']
        for c in checks[:3]:c['status']='unknown'
        unknown=next(r for r in contra.recommend(local)['candidates'] if r['id']==a['id'])
        for c in checks[:3]:c['status']='fail'
        failed=next(r for r in contra.recommend(local)['candidates'] if r['id']==a['id'])
        self.assertEqual(unknown['quality_known'],100);self.assertEqual(unknown['coverage'],70)
        self.assertEqual(failed['quality_known'],70);self.assertEqual(failed['coverage'],100);self.assertFalse(failed['eligible'])


if __name__=='__main__':unittest.main()
