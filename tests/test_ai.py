"""Isolated AI integration tests: no real portfolio, models or network required."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from aporte_brasil.ai import market_ai as ai
import test_app as baseline
app = baseline.app


class AITests(unittest.TestCase):
    setUp = baseline.AppTests.setUp
    tearDown = baseline.AppTests.tearDown
    asset = baseline.AppTests.asset
    complete = baseline.AppTests.complete

    def report(self, profile='retail'):
        return {'profile': profile, 'retrieved_at': app.now(), 'headlines': [
            {'title': 'Manchete de teste ' + str(i), 'url': 'https://example.org/' + str(i),
             'publisher': 'Veículo ' + str(i % 2), 'published_at': app.now(), 'feed': 'RSS sintético'} for i in range(5)],
            'sources': [], 'errors': [], 'method': 'Teste'}

    def inputs(self, **changes):
        return ai.validate_scenario(app, {'question': 'Como juros menores afetam o consumo?', 'rates_delta': -2, **changes})

    def analysis(self):
        return {'summary': 'Juros menores podem favorecer consumo, conforme o crédito.', 'assumptions': ['Hipótese de juros menores.'],
                'branches': [{'name': 'Base', 'condition': 'Crédito melhora', 'consequence': 'Demanda cresce'},
                             {'name': 'Estresse', 'condition': 'Recessão', 'consequence': 'Consumo pode cair'}],
                'sectors': [{'profile': 'retail', 'direction': 'favorable', 'mechanisms': [{'factor': 'Juros', 'mechanism': 'Juros menores podem tornar o crédito mais acessível e apoiar o consumo.', 'source_ids': []}], 'watch': ['Inadimplência']}],
                'historical': [], 'invalidation': ['Recessão'], 'limitations': ['Não estima retorno.']}

    def test_local_settings_reject_remote_urls_and_keep_secret_out_of_state(self):
        for url in ('https://127.0.0.1:11434', 'http://example.org:11434', 'http://localhost:11434/api', 'http://x:y@localhost:11434', 'http://localhost:11434?x=1'):
            with self.assertRaises(ValueError):
                ai.action(app, '/api/ai/settings', {'base_url': url})
        ai.action(app, '/api/ai/settings', {'model': 'qwen2.5:3b', 'search_key': 'synthetic-test-secret'})
        ai.action(app, '/api/ai/settings', {'search_key': ''})
        state = app.state()
        self.assertTrue(state['ai']['settings']['has_search_key'])
        self.assertNotIn('synthetic-test-secret', json.dumps(state))
        with app.connect() as c:
            self.assertNotIn('synthetic-test-secret', json.dumps(app.export_data(c)))
        ai.action(app, '/api/ai/settings', {'clear_search_key': True})
        self.assertFalse(app.state()['ai']['settings']['has_search_key'])

    def test_recent_titles_remove_duplicates_old_and_future(self):
        clock = datetime.now(timezone.utc)
        r = self.report()
        r['headlines'] += [copy.deepcopy(r['headlines'][0])]
        r['headlines'][1]['published_at'] = (clock - timedelta(days=8)).isoformat()
        r['headlines'][2]['published_at'] = (clock + timedelta(days=1)).isoformat()
        self.assertEqual(len(ai.recent_headlines(r, clock + timedelta(seconds=2))), 3)

    def test_score_sample_limits_and_stale_feed_detection(self):
        r = self.report()
        scores = [{'positive': .8, 'neutral': .1, 'negative': .1}] * 5
        result = ai.summarize_sentiment(r, r['headlines'], scores, app.now(), ai.HF_MODEL, 'huggingface')
        self.assertEqual(result['tone'], 'positive')
        self.assertAlmostEqual(result['score'], .7)
        small = ai.summarize_sentiment(r, r['headlines'][:3], scores[:3], app.now(), 'test', 'huggingface')
        self.assertEqual(small['tone'], 'unknown')
        with app.connect() as c:
            app.write_cache(c, 'news_reports', {'retail': r})
            app.write_cache(c, 'ai_sentiment', {'retail': result})
        self.assertFalse(app.state()['ai']['sentiment']['retail']['stale'])
        r['headlines'][0]['title'] = 'Mudou'
        with app.connect() as c:
            app.write_cache(c, 'news_reports', {'retail': r})
        self.assertTrue(app.state()['ai']['sentiment']['retail']['stale'])

    def test_invalid_classifier_scores_and_missing_llm_ids_rejected(self):
        for scores in ([{'positive': True, 'negative': 0, 'neutral': 0}], [{'positive': 2, 'negative': -1, 'neutral': 0}], [{'positive': .2, 'negative': .2, 'neutral': .2}], []):
            with self.assertRaises(ValueError):
                ai.validate_probabilities(scores, 1)
        r = self.report()
        with patch.object(ai, 'generate', return_value=({'items': [{'id': 0, 'label': 'positive'}] * 5}, 'fake')):
            with self.assertRaises(ValueError):
                ai.llm_classify(r['headlines'], ai.DEFAULTS, 'retail')

    def test_hf_batch_inference_dedupes_and_failure_preserves_previous(self):
        def report(profile, now):
            return self.report(profile)
        with patch.object(ai.market_brief, 'fetch', side_effect=report), patch.object(ai, 'hf_classify', return_value=[{'positive': .8, 'neutral': .1, 'negative': .1}] * 5) as classify:
            ai.analyze_sentiment(app, {'profile': 'retail'})
            self.assertEqual(len(classify.call_args.args[0]), 5)
        saved = app.state()['ai']['sentiment']
        self.assertEqual(set(saved), set(ai.CORE_PROFILES))
        self.assertIn('metals', saved)
        with patch.object(ai.market_brief, 'fetch', side_effect=report), patch.object(ai, 'hf_classify', side_effect=ValueError('Falha sintética')):
            with self.assertRaises(ValueError):
                ai.analyze_sentiment(app, {'profile': 'retail'})
        self.assertEqual(app.state()['ai']['sentiment'], saved)

    def test_inputs_optional_not_zero_and_reject_orders_bad_numbers(self):
        d = self.inputs(usd_delta='', growth_delta=0)
        self.assertIsNone(d['usd_delta'])
        self.assertEqual(d['growth_delta'], 0)
        for changes in ({'rates_delta': True}, {'rates_delta': float('nan')}, {'equity_delta': -101}, {'question': ''}, {'quantity': 10}, {'research': 'yes'}, {'engine': 'channels', 'research': True}):
            with self.assertRaises(ValueError):
                self.inputs(**changes)

    def test_channels_distinguish_sector_exposure_and_unknowns(self):
        sectors = ai.mechanical_scenario(self.inputs(), [])
        self.assertEqual(next(s for s in sectors if s['profile'] == 'retail')['direction'], 'favorable')
        self.assertEqual(next(s for s in sectors if s['profile'] == 'bank')['direction'], 'mixed')
        none = ai.mechanical_scenario(self.inputs(rates_delta=''), [])
        self.assertTrue(all(s['direction'] == 'unknown' for s in none))
        flat = ai.mechanical_scenario(self.inputs(rates_delta='', growth_delta=0), [])
        self.assertTrue(all(s['direction'] == 'neutral' for s in flat))

    def test_simulation_only_uses_manual_price_delta_and_never_changes_portfolio(self):
        aid = self.asset(sector='Varejo')
        self.complete(aid)
        app.mutate('/api/trades', {'asset_id': aid, 'side': 'buy', 'quantity': 123, 'price': 987, 'date': self.day, 'institution': 'Banco confidencial de teste'})
        before = app.state()['assets']
        with patch.object(ai, 'generate', return_value=(self.analysis(), 'mock-local')) as generate:
            ai.simulate(app, self.inputs())
            sent = json.dumps(generate.call_args.args[2], ensure_ascii=False)
            self.assertNotIn('Banco confidencial', sent)
            def fields(value):
                if isinstance(value, dict):
                    return set(value) | set().union(*(fields(v) for v in value.values()))
                if isinstance(value, list):
                    return set().union(*(fields(v) for v in value))
                return set()
            self.assertFalse(fields(generate.call_args.args[2]) & {'quantity', 'position', 'average', 'trades'})
        record = app.state()['ai']['scenarios'][0]
        self.assertIsNone(record['assets'][0]['illustrative_price'])
        self.assertEqual(app.state()['assets'], before)
        ai.simulate(app, self.inputs(engine='channels', equity_delta=10))
        self.assertEqual(app.state()['ai']['scenarios'][0]['assets'][0]['illustrative_price'], 22)
        self.assertEqual(app.state()['assets'], before)

    def test_scenario_rejects_fabricated_sources_historical_claims_and_profiles(self):
        for edit in (lambda r: r['sectors'][0]['mechanisms'][0].update(source_ids=[999]),
                     lambda r: r['sectors'][0].update(profile='invalid'),
                     lambda r: r.update(probability=80),
                     lambda r: r.update(historical=[{'episode': 'Crise inventada', 'similarity': 'Teste', 'difference': 'Teste', 'source_ids': []}])):
            r = self.analysis()
            edit(r)
            with self.assertRaises(ValueError):
                ai.validate_analysis(app, r, [])
        self.assertEqual(ai.validate_analysis(app, self.analysis(), [])['historical'], [])
        repeated = self.analysis()
        repeated['sectors'].append({**copy.deepcopy(repeated['sectors'][0]), 'direction': 'unfavorable'})
        consolidated = ai.validate_analysis(app, repeated, [])
        self.assertEqual(len(consolidated['sectors']), 1)
        self.assertEqual(consolidated['sectors'][0]['direction'], 'mixed')

    def test_web_search_bounded_fetch_sources_and_no_model_generated_urls(self):
        ai.action(app, '/api/ai/settings', {'search_key': 'synthetic-key'})
        calls = []
        def fake(url, payload=None, token='', timeout=20):
            calls.append((url, payload, token))
            if url.endswith('web_search'):
                return {'results': [{'url': 'https://example.org/history', 'title': 'Teste histórico', 'content': 'Trecho'}]}
            return {'content': 'Página completa de teste'}
        with patch.object(ai, 'request', side_effect=fake):
            sources, errors = ai.research(app, 'Hipótese pública de crise')
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['kind'], 'page_read')
        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(url.startswith('https://ollama.com/api/web_') for url, _, _ in calls))

    def test_web_connection_checks_search_and_fetch_independently_of_local_model(self):
        ai.action(app, '/api/ai/settings', {'search_key': 'synthetic-key'})
        found = {'results': [{'url': 'https://example.org/policy', 'title': 'Banco Central'}]}
        with patch.object(ai, 'request', side_effect=[found, {'content': ''}]) as request:
            result = ai.action(app, '/api/ai/web-connection', {})
        self.assertEqual((result['sources'], result['pages_read']), (1, 0))
        self.assertIn('sem texto', result['warnings'][0])
        self.assertEqual([call.args[0] for call in request.call_args_list], [ai.WEB_API+'web_search', ai.WEB_API+'web_fetch'])
        self.assertIn('Banco Central', request.call_args_list[0].args[1]['query'])

    def test_web_http_errors_report_status_without_exposing_credentials(self):
        url = ai.WEB_API + 'web_search'
        key = 'synthetic-key'
        for code, message in ((401, 'autenticou'), (402, 'pagamento'), (429, 'limite'), (502, 'recusou')):
            with self.subTest(code=code), patch.object(ai.urllib.request, 'build_opener') as opener:
                opener.return_value.open.side_effect = HTTPError(url, code, key, None, None)
                with self.assertRaisesRegex(ValueError, rf'{message}.*HTTP {code}') as error:
                    ai.request(url, {'query': 'consulta pública'}, key)
                self.assertNotIn(key, str(error.exception))

    def test_later_query_error_keeps_web_evidence_from_first_query(self):
        ai.action(app, '/api/ai/settings', {'search_key': 'synthetic-key'})
        found = {'results': [{'url': 'https://example.org/company', 'title': 'Evidência pública'}]}
        responses = [found, {'content': 'Texto da página consultada.'}, ValueError('Limite de consultas atingido.')]
        with patch.object(ai, 'request', side_effect=responses):
            sources, warnings = ai.research(app, 'Empresa pública', queries=['Primeira consulta', 'Segunda consulta'])
        self.assertEqual([source['kind'] for source in sources], ['page_read'])
        self.assertIn('Limite de consultas', warnings[0])

    def test_provider_structured_outputs_and_local_api(self):
        response = {'message': {'content': json.dumps(self.analysis())}, 'done': True}
        with patch.object(ai, 'request', return_value=response) as req:
            parsed, name = ai.generate({**ai.DEFAULTS, 'model': 'qwen2.5:3b'}, 'System', {'public': True}, ai.SCENARIO_SCHEMA)
            self.assertEqual(parsed, self.analysis())
            self.assertEqual(req.call_args.args[0], 'http://127.0.0.1:11434/api/chat')
            self.assertFalse(req.call_args.args[1]['stream'])
            self.assertEqual(req.call_args.args[1]['format'], ai.SCENARIO_SCHEMA)
        response = {'choices': [{'message': {'content': json.dumps(self.analysis())}, 'finish_reason': 'stop'}]}
        with patch.object(ai, 'request', return_value=response) as req:
            ai.generate({**ai.DEFAULTS, 'provider': 'llamacpp', 'base_url': 'http://127.0.0.1:8080', 'model': 'local'}, 'System', {}, ai.SCENARIO_SCHEMA)
            self.assertTrue(req.call_args.args[0].endswith('/v1/chat/completions'))

    def test_integration_check_runs_in_background_and_verifies_local_extraction(self):
        before = ai.config(app)
        old_job = ai.job_state()
        d = {'mode': 'model', 'model': 'qwen2.5:7b'}
        try:
            for outcome, succeeds in (({'founded_year': 1984, 'source_id': 1}, True),
                                      ({'founded_year': 1984, 'source_id': True}, False),
                                      ({'founded_year': 1985, 'source_id': 1}, False)):
                with self.subTest(outcome=outcome):
                    response = {'message': {'content': json.dumps(outcome)}}
                    with patch.object(ai, 'request', return_value=response) as request:
                        job = ai.action(app, '/api/ai/integration-check', d)
                        deadline = time.monotonic() + 3
                        while ai.job_state()['running'] and time.monotonic() < deadline:
                            time.sleep(.01)
                    end = ai.job_state()
                    self.assertEqual(end['id'], job['id'])
                    self.assertFalse(end['running'])
                    self.assertEqual(not end['error'], succeeds)
                    self.assertEqual(request.call_args.args[0], ai.DEFAULTS['base_url'] + '/api/chat')
                    self.assertEqual(request.call_args.args[1]['model'], 'qwen2.5:7b')
                    self.assertIn('Empresa Exemplo', request.call_args.args[1]['messages'][1]['content'])
            self.assertEqual(ai.config(app), before)
            with self.assertRaises(ValueError):
                ai.action(app, '/api/ai/integration-check', {**d, 'base_url': 'https://example.org'})
        finally:
            with ai.LOCK:
                ai.JOB.update(old_job)

    def test_backup_restores_scenarios_rejects_tampering_and_preserves_no_key(self):
        aid = self.asset(sector='Varejo')
        self.complete(aid)
        ai.simulate(app, self.inputs(engine='channels', equity_delta=10))
        before = app.state()['ai']['scenarios']
        with app.connect() as c:
            data = app.export_data(c)
            app.write_cache(c, 'ai_scenarios', [])
        app.mutate('/api/import', copy.deepcopy(data))
        self.assertEqual(app.state()['ai']['scenarios'], before)
        bad = copy.deepcopy(data)
        bad['ai_scenarios'][0]['assets'][0]['metrics']['quantity'] = 10
        with self.assertRaises(ValueError):
            app.mutate('/api/import', bad)
        self.assertEqual(app.state()['ai']['scenarios'], before)
        legacy = copy.deepcopy(data)
        legacy.pop('ai_scenarios')
        app.mutate('/api/import', legacy)
        self.assertEqual(app.state()['ai']['scenarios'], [])

    def test_background_job_failure_and_exclusion(self):
        old = ai.job_state()
        try:
            with patch.dict(ai.JOB, running=True):
                with self.assertRaises(ValueError):
                    ai.start(app, 'scenario', self.inputs())
            done = threading.Event()
            def fail(*args):
                done.set()
                raise ValueError('Falha sintética da IA')
            with patch.object(ai, 'simulate', side_effect=fail):
                ai.start(app, 'scenario', self.inputs())
                self.assertTrue(done.wait(2))
            # Acquire the lock after the worker's final block.
            for thread in threading.enumerate():
                if thread is not threading.current_thread() and thread.name.startswith('Thread-') and 'run' in thread.name:
                    thread.join(2)
            self.assertFalse(ai.job_state()['running'])
            self.assertEqual(ai.job_state()['error'], 'Falha sintética da IA')
            self.assertEqual(app.state()['ai']['scenarios'], [])
        finally:
            ai.JOB.update(old)

    def paste(self, **changes):
        return ai.validate_paste(app, {'text': 'Hipótese: queda dos juros pode melhorar o crédito e o consumo. Varejo pode se beneficiar, mas recessão e inadimplência podem inverter o efeito. Fonte: https://www.bcb.gov.br/controleinflacao/taxaselic', **changes})

    def test_paste_preview_is_local_and_only_commit_saves_after_review(self):
        aid = self.asset(sector='Varejo')
        self.complete(aid)
        before = app.state()['assets']
        result = self.analysis()
        result['sectors'][0]['mechanisms'][0]['source_ids'] = [1]
        with patch.object(ai, 'generate', return_value=(result, 'mock-local')) as generate, patch.object(ai, 'request') as network:
            ai.translate_paste(app, self.paste())
            network.assert_not_called()
            data = generate.call_args.args[2]
            self.assertIn('queda dos juros', data['original_text'])
            self.assertNotIn('position', json.dumps(data))
        preview = app.state()['ai']['import_preview']
        self.assertEqual(app.state()['ai']['scenarios'], [])
        self.assertEqual(preview['record']['sources'][0]['kind'], 'pasted_reference')
        self.assertEqual(preview['record']['inputs']['rates_delta'], None)
        self.assertEqual(preview['record']['assets'][0]['price'], 20)
        self.assertIsNone(preview['record']['assets'][0]['illustrative_price'])
        with self.assertRaises(ValueError):
            ai.action(app, '/api/ai/import/commit', {'token': preview['token']})
        ai.action(app, '/api/ai/import/commit', {'token': preview['token'], 'reviewed': True})
        self.assertIsNone(app.state()['ai']['import_preview'])
        self.assertEqual(len(app.state()['ai']['scenarios']), 1)
        self.assertEqual(app.state()['assets'], before)
        with self.assertRaises(ValueError):
            ai.commit_paste(app, {'token': preview['token'], 'reviewed': True})

    def test_paste_limits_dates_links_and_invalid_llm_preserve_previous_preview(self):
        for changes in ({'text': 'Muito curto'}, {'text': 'x' * 12001}, {'asof': '2099-01-01'}, {'asof': None}, {'buy': True}):
            with self.assertRaises(ValueError):
                self.paste(**changes)
        text = 'Fonte [BCB](https://www.bcb.gov.br/). https://www.bcb.gov.br/. https://user:pass@example.org/ javascript:alert(1)'
        self.assertEqual([s['url'] for s in ai.pasted_sources(text, app.now())], ['https://www.bcb.gov.br/'])
        with patch.object(ai, 'generate', return_value=(self.analysis(), 'mock-local')):
            ai.translate_paste(app, self.paste())
        old = app.state()['ai']['import_preview']
        bad = self.analysis()
        bad['sectors'][0]['mechanisms'][0]['source_ids'] = [99]
        with patch.object(ai, 'generate', return_value=(bad, 'mock-local')), self.assertRaises(ValueError):
            ai.translate_paste(app, self.paste())
        self.assertEqual(app.state()['ai']['import_preview'], old)
        too_many = self.paste(text='Pesquisa com fontes para o cenário. ' + ' '.join('https://example.org/' + str(i) for i in range(9)))
        with patch.object(ai, 'generate') as generate, self.assertRaises(ValueError):
            ai.translate_paste(app, too_many)
        generate.assert_not_called()
        ai.commit_paste(app, {'token': old['token']}, discard=True)

    def test_paste_preview_expiry_scope_discard_and_backup_provenance(self):
        with patch.object(ai, 'generate', return_value=(self.analysis(), 'mock-local')):
            ai.translate_paste(app, self.paste(asof=app.today().isoformat()))
        preview = app.state()['ai']['import_preview']
        plan = app.CSV_PREVIEWS[preview['token']]
        plan['expires'] = time.time() - 1
        self.assertIsNone(app.state()['ai']['import_preview'])
        with self.assertRaises(ValueError):
            ai.commit_paste(app, {'token': preview['token'], 'reviewed': True})
        plan['expires'] = time.time() + 900
        plan['scope'] = 'different-wallet'
        with self.assertRaises(ValueError):
            ai.commit_paste(app, {'token': preview['token'], 'reviewed': True})
        plan['scope'] = str(app.DB_PATH)
        ai.commit_paste(app, {'token': preview['token'], 'reviewed': True})
        with app.connect() as c:
            exported = app.export_data(c)
        app.mutate('/api/import', copy.deepcopy(exported))
        saved = app.state()['ai']['scenarios'][0]
        self.assertEqual(saved['import_context']['text'], self.paste()['text'])
        for edit in (lambda r: r['import_context'].update(text='Adulterado'),
                     lambda r: r['sources'][0].update(url='https://invented.example.org'),
                     lambda r: r['sources'][0].update(kind='page_read')):
            bad = copy.deepcopy(exported)
            edit(bad['ai_scenarios'][0])
            with self.assertRaises(ValueError):
                app.mutate('/api/import', bad)
        self.assertEqual(app.state()['ai']['scenarios'][0], saved)

    def test_paste_retries_weak_translation_once_and_rejects_duplicate_paths(self):
        bad = self.analysis()
        bad['branches'][1]['condition'] = bad['branches'][0]['condition']
        bad['sectors'][0]['mechanisms'][0]['mechanism'] = 'mais acessível'
        with patch.object(ai, 'generate', side_effect=[(bad, 'mock-local'), (self.analysis(), 'mock-local')]) as generate:
            ai.translate_paste(app, self.paste())
            self.assertEqual(generate.call_count, 2)
        before = app.state()['ai']['import_preview']
        with patch.object(ai, 'generate', return_value=(bad, 'mock-local')) as generate, self.assertRaises(ValueError):
            ai.translate_paste(app, self.paste())
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(app.state()['ai']['import_preview'], before)
        ai.commit_paste(app, {'token': before['token']}, discard=True)


if __name__ == '__main__':
    unittest.main()
