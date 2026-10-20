"""Batch work isolates selection, failures, optional inference and shared sources."""
import copy
import unittest
from unittest.mock import patch
import company_batch as batch
import company_research
import company_history
import factor_analysis as factors
import market_ai
import test_app as baseline
from test_factor_analysis import fixture
app=baseline.app


class BatchTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def args(self,ids,**kw):return dict(asset_ids=ids,years=10,refresh=True,use_ai=False,**kw)

    def test_strict_selection_and_options(self):
        aid=self.asset();self.assertEqual(batch.validate(app,self.args([aid]))['asset_ids'],[aid])
        for change in (dict(asset_ids=[]),dict(asset_ids=[aid,aid]),dict(asset_ids=[True]),dict(asset_ids=[99999]),dict(years=True),dict(years=15),dict(use_ai='yes'),dict(extra=1)):
            with self.assertRaises(ValueError):batch.validate(app,{**self.args([aid]),**change})

    def test_group_fetch_once_selection_preserved_and_ai_opt_in(self):
        one=self.asset();two=self.asset('EFGH3');other=self.asset('IJKL3')
        selected=[one,two]
        with patch.object(company_research,'action',return_value={'received':['Ficha'],'warnings':[]}) as history,patch.object(company_history,'fetch_opinions',return_value={'warnings':[]}),patch.object(factors,'refresh',return_value={'received':['ABCD3','EFGH3'],'warnings':[]}) as refresh,patch.object(company_research,'analyze') as analyze:
            batch.run(app,self.args(selected))
        self.assertEqual(history.call_count,2);self.assertEqual(refresh.call_count,1);analyze.assert_not_called()
        self.assertEqual(refresh.call_args.kwargs['asset_ids'],selected)
        self.assertNotIn(other,[x.args[2]['asset_id'] for x in history.call_args_list])
        with app.connect() as c:r=app.read_cache(c,'issuer_batch',{})
        self.assertFalse(r['running']);self.assertEqual([x['asset_id'] for x in r['rows']],selected)

    def test_one_source_failure_does_not_stop_others_or_erase_old_data(self):
        one=self.asset();two=self.asset('EFGH3')
        with patch.object(company_research,'action',side_effect=[ValueError('Fonte fora do ar'),{'received':['Ficha'],'warnings':[]}]),patch.object(company_history,'fetch_opinions',return_value={}),patch.object(factors,'refresh',return_value={'received':['ABCD3','EFGH3'],'warnings':[]}),patch.object(company_research,'analyze',side_effect=[ValueError('IA indisponível'),None]):
            batch.run(app,{**self.args([one,two]),'use_ai':True})
        with app.connect() as c:r=app.read_cache(c,'issuer_batch',{})
        self.assertEqual(len(r['rows']),2);self.assertEqual(r['rows'][0]['review'],'failed');self.assertEqual(r['rows'][1]['review'],'done')
        self.assertIn('Fonte fora do ar',r['rows'][0]['warnings'])

    def test_saved_only_never_queries_or_calls_model(self):
        aid=self.asset()
        with patch.object(company_history,'refresh') as history,patch.object(factors,'refresh') as refresh,patch.object(company_research,'analyze') as analyze:
            batch.run(app,{**self.args([aid]),'refresh':False})
        history.assert_not_called();refresh.assert_not_called();analyze.assert_not_called()

    def test_factor_refresh_writes_only_selected_and_reuses_market_sources(self):
        one=self.asset();other=self.asset('EFGH3');third=self.asset('IJKL3',sector='Varejo')
        a=next(a for a in app.state()['assets'] if a['id']==one);b=next(a for a in app.state()['assets'] if a['id']==third);d=fixture();shared={}
        with patch.object(factors,'fetch_factor',side_effect=lambda *args:copy.deepcopy(d['factors']['usd'])) as macro,patch.object(factors,'fetch_prices',side_effect=lambda app,symbol,mk,index=False,years=5:copy.deepcopy(d['benchmark'] if index else d['prices'])) as prices:
            factors.refresh(app,a,10,asset_ids=[one,third],shared=shared);before=macro.call_count
            factors.refresh(app,b,10,asset_ids=[one,third],shared=shared)
        # Retail adds demand proxies; common five macro factors are reused.
        self.assertLess(macro.call_count-before,5)
        self.assertEqual(sum(c.args[3] if len(c.args)>3 else False for c in prices.call_args_list),1)
        state=app.state()['assets'];self.assertNotIn(factors.KINDS[0],next(a for a in state if a['id']==other)['snapshots'])

    def test_qualitative_review_invalidates_after_factor_evidence_changes(self):
        aid=self.asset();a=app.state()['assets'][0];_,before=company_research.inputs(app,a)
        with app.connect() as c:app.add_snapshot(c,aid,factors.KINDS[0],fixture(),'Fictício',app.today().isoformat())
        _,after=company_research.inputs(app,app.state()['assets'][0]);self.assertNotEqual(before,after)


if __name__=='__main__':unittest.main()
