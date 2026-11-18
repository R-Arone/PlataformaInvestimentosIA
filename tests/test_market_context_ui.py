"""Renders the new panels in Node with the real output of the Python modules (synthetic data only)."""
from datetime import date, timedelta
from pathlib import Path
import importlib.util
import json
import math
import random
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from aporte_brasil.portfolio import asset_correlation
from aporte_brasil.portfolio import fixed_income
from aporte_brasil.market import price_context

TODAY = date(2026, 11, 17)
STAMP = '2026-11-17T22:00:00+00:00'

HARNESS = r'''
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const appSrc=fs.readFileSync(input.root+'/static/app.js','utf8');
const wanted=['esc','fmt','money','pct','multiple','dt','tag','field','select','numField','button'];
const helpers=appSrc.split('\n').filter(l=>wanted.some(n=>l.startsWith('const '+n+' =')||l.startsWith('const '+n+'=')));
const S={assets:input.assets,macro:input.macro,fixed:[],tax_references:[{product:'CDB',automatic:true},{product:'LCI',automatic:true}],benchmark_info:input.benchmark_info};
const listeners=[];
const ctx=vm.createContext({S,console,document:{addEventListener:(t,f)=>listeners.push([t,f])},valuationTicker:input.assets[0].ticker,
  assetById:id=>S.assets.find(a=>a.id===Number(id)),$:()=>null,$$:()=>[],wireForm:()=>{},api:async()=>({}),toast:()=>{},load:async()=>{},Math,Number,String,Object,Array,JSON,Intl});
vm.runInContext(helpers.join('\n'),ctx);
vm.runInContext('var detail=function(){};var valuationView=function(){return "<p>base</p>"};var rates=function(){return "<h1>x</h1><section class=\\"panel\\"><div class=\\"panel-head\\"><h2>Investimentos registrados</h2></div></section>"};var bindForms=function(){};',ctx);
for(const f of ['price-context.js','fixed-income.js'])vm.runInContext(fs.readFileSync(input.root+'/static/'+f,'utf8'),ctx,{filename:f});
const out={};
out.price=input.assets.map(a=>vm.runInContext('priceContextPanel(assetById('+a.id+'))',ctx));
out.corr=input.assets.map(a=>vm.runInContext('correlationPanel(assetById('+a.id+'))',ctx));
out.rates=vm.runInContext('rates()',ctx);
out.valuation=vm.runInContext('valuationView()',ctx);
out.fixed=input.fixed.map(r=>vm.runInContext('fixedIncomeOutput('+JSON.stringify(r)+')',ctx));
out.listeners=listeners.map(l=>l[0]);
process.stdout.write(JSON.stringify(out));
'''


def weekdays(n, end=TODAY - timedelta(days=1)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def prices(returns, days, start=20.0):
    level, out = start, [{'date': days[0].isoformat(), 'close': start}]
    for d, r in zip(days[1:], returns):
        level *= math.exp(r)
        out.append({'date': d.isoformat(), 'close': level})
    return out


def month_ends(n):
    out, y, m = [], 2026, 10
    for _ in range(n):
        nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        out.append((nxt - timedelta(days=1)).isoformat())
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


@unittest.skipUnless(shutil.which('node'), 'Node.js não está instalado')
class MarketContextUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        days = weekdays(400)
        rng = random.Random(4)
        mkt = [rng.gauss(0, .012) for _ in range(len(days) - 1)]
        bench = {'ibov': {'prices': prices(mkt, days, 120000.)}, 'usd': {'prices': prices([-.3 * m + rng.gauss(0, .005) for m in mkt], days, 5.)}}

        def stock(i, ticker, beta, history=True, monthly=True):
            r = random.Random(i)
            closes = prices([beta * m + r.gauss(0, .006) for m in mkt], days)
            snaps = {'quote': {'data': {'price': closes[-1]['close']}, 'asof': TODAY.isoformat()}}
            if history:
                snaps['history'] = {'retrieved_at': STAMP, 'data': {'prices': closes, 'years': 5}}
            if monthly:
                mr = random.Random(i + 9)
                level, months = 12., []
                for d in month_ends(120):
                    level *= math.exp(mr.gauss(.004, .06))
                    months.append({'date': d, 'close': level})
                snaps['issuer_price_history'] = {'data': {'months': months}}
            return {'id': i, 'ticker': ticker, 'asset_type': 'stock', 'value': 1000 + i, 'position': {'quantity': 10}, 'metrics': {'price': closes[-1]['close']}, 'snapshots': snaps}
        assets = [stock(1, 'AAAA3', 1.1), stock(2, 'BBBB3', .4), stock(3, 'CCCC3', .8, history=False, monthly=False)]
        for a in assets:
            a['price_context'] = price_context.analyze(a, TODAY)
        asset_correlation.enrich(assets, bench, TODAY, STAMP)
        base = dict(principal=10000, months=24, product='CDB', tax_mode='auto', indexer='CDI', rate=105, cdi=14.65, selic=14.75, ipca=4.5, selic_end=11, cdi_end=10.9)
        fixed = [fixed_income.analyze(base, TODAY),
                 fixed_income.analyze({**base, 'indexer': 'Prefixado', 'rate': 13, 'ipca': None, 'product': 'LCI'}, TODAY),
                 fixed_income.analyze({**base, 'indexer': 'IPCA+', 'rate': 6.5, 'months': None, 'maturity': '2031-05-15'}, TODAY)]
        payload = {'root': str(ROOT), 'assets': assets, 'fixed': fixed, 'benchmark_info': {'retrieved_at': '2026-11-17T12:00:00+00:00', 'series': {
                       'ibov': {'label': 'Ibovespa', 'asof': TODAY.isoformat(), 'count': 399, 'source': 'Yahoo Finance · chart/^BVSP', 'source_url': 'https://finance.yahoo.com/quote/%5EBVSP/'}}},
                   'macro': {'cdi': {'value': 14.65, 'asof': '2026-11-14'}, 'selic': {'value': 14.75, 'asof': '2026-11-14'}, 'ipca': {'value': 4.5, 'asof': '2026-10-31'}}}
        done = subprocess.run(['node', '-e', HARNESS], input=json.dumps(payload), capture_output=True, text=True, timeout=60)
        if done.returncode:
            raise RuntimeError(done.stderr)
        cls.out = json.loads(done.stdout)

    def assertClean(self, html):
        for bad in ('undefined', 'NaN', '[object', 'null'):
            self.assertNotIn(bad, html)

    def test_price_panel_with_both_series(self):
        html = self.out['price'][0]
        self.assertIn('Preço no histórico', html)
        self.assertIn('Última visita à faixa', html)
        self.assertIn('Posição do preço em cada janela', html)
        self.assertIn('Mensal · 10 anos', html)
        self.assertIn('Diário · 5 anos', html)
        self.assertIn('Percentil', html)
        self.assertIn('Não indica valor justo', html)
        self.assertClean(html)

    def test_price_panel_without_history_offers_the_fetch_buttons(self):
        html = self.out['price'][2]
        self.assertIn('Falta histórico de preços', html)
        self.assertIn('data-action="price-context-history"', html)
        self.assertIn('data-action="price-context-monthly"', html)
        self.assertClean(html)

    def test_correlation_panel_shows_benchmarks_holdings_and_sources(self):
        html = self.out['corr'][0]
        self.assertIn('Correlação e beta', html)
        self.assertIn('Ibovespa', html)
        self.assertIn('Dólar (USD/BRL)', html)
        self.assertIn('Com o restante da carteira', html)
        self.assertIn('Posições comparadas', html)
        self.assertIn('Beta em dias de queda', html)
        self.assertIn('Atualizar Ibovespa e dólar', html)
        self.assertIn('Yahoo Finance', html)
        self.assertClean(html)

    def test_correlation_panel_without_history_explains_what_is_missing(self):
        html = self.out['corr'][2]
        self.assertIn('Falta histórico', html)
        self.assertIn('data-action="price-context-history"', html)
        self.assertClean(html)

    def test_calculator_is_inserted_before_the_registered_investments(self):
        html = self.out['rates']
        self.assertLess(html.index('id="fixed-income-form"'), html.index('Investimentos registrados'))
        for text in ('Valor investido (R$)', 'Premissas de juros e inflação', 'CDI ao final do prazo', 'value="14.65"', 'Outro · informar o IR'):
            self.assertIn(text, html)
        self.assertClean(html)

    def test_valuation_view_gets_the_price_panel(self):
        self.assertIn('<p>base</p>', self.out['valuation'])
        self.assertIn('Preço no histórico', self.out['valuation'])

    def test_calculator_output_for_each_kind_of_product(self):
        cdi, lci, ipca = self.out['fixed']
        for html in (cdi, lci, ipca):
            self.assertIn('Saldo líquido no vencimento', html)
            self.assertIn('Comparação no mesmo prazo', html)
            self.assertIn('<svg', html)
            self.assertIn('Como é calculado', html)
            self.assertClean(html)
        self.assertIn('Cenários de juros e inflação', cdi)
        self.assertIn('Valor esperado', cdi)
        self.assertIn('Supera a inflação', ipca)
        # without inflation there is no real-return claim, and the page says so instead of inventing one
        self.assertNotIn('Supera a inflação', lci)
        self.assertNotIn('Perde para a inflação', lci)
        self.assertIn('Sem inflação informada', lci)

    def test_handlers_are_registered(self):
        self.assertEqual(self.out['listeners'].count('click'), 1)
        self.assertEqual(self.out['listeners'].count('change'), 1)


if __name__ == '__main__':
    unittest.main()
