"""Local, explainable quality/value contribution planning. No orders or forecasts."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, ROUND_CEILING
from datetime import date
import math
import fii_quality
import portfolio_strategy


REFERENCES = [
    {'title': 'Templeton · qualidade, valor e fundamentos de longo prazo', 'url': 'https://www.franklintempleton.com/corporate/articles/2024/equity/quality-account-an-introduction-to-the-quality-value-proposition'},
    {'title': 'Templeton · oportunidades em bolsões de pessimismo', 'url': 'https://www.franklintempleton.com/corporate/articles/2024/equity/hunting-for-pockets-of-pessimism'},
    {'title': 'AQR · Quality Minus Junk (pesquisa)', 'url': 'https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk'},
    {'title': 'MSCI · rentabilidade, estabilidade de lucros e alavancagem', 'url': 'https://www.msci.com/indexes/group/quality-indexes'},
    {'title': 'Damodaran · contrarian investing e armadilhas de valor', 'url': 'https://pages.stern.nyu.edu/~adamodar/pdfiles/blog/Contrarian.pdf'},
    {'title': 'AQR · Value and Momentum Everywhere', 'url': 'https://www.aqr.com/insights/research/journal-article/value-and-momentum-everywhere'},
    {'title': 'Investor.gov · alocação, diversificação e rebalanceamento', 'url': 'https://www.investor.gov/introduction-investing/getting-started/asset-allocation'},
]
METHOD = ('Prioridade = 50% nota de qualidade + 35% desconto + 15% necessidade da classe. '
          'Qualidade = critérios atendidos / critérios aplicáveis, incluindo pendências no denominador. '
          'Desconto = distância abaixo do valor de referência, limitada a 30% para compor a nota. '
          'Necessidade = déficit da classe após o aporte / meta em reais da classe, limitada a 100%. '
          'Pesos e cortes são regras iniciais do aplicativo, sem calibração ou validação como estratégia. '
          'A nota anterior do comparador é exibida separadamente porque inclui 20% de tendência. '
          'Uma queda isolada, sentimento negativo ou P/VP baixo não comprova subavaliação.')


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def recent(app, value, days):
    try: return 0 <= (app.today()-date.fromisoformat(value[:10])).days <= days
    except (ValueError, TypeError): return False


def money_cents(value, rounding=ROUND_HALF_UP):
    return int((Decimal(str(value))*100).to_integral_value(rounding=rounding))


def options(app, data):
    allowed = {'amount', 'mode', 'universe', 'max_assets', 'min_coverage', 'accept_estimates'}
    if not isinstance(data, dict) or set(data)-allowed:
        raise ValueError('Opções do aporte de longo prazo inválidas.')
    if isinstance(data.get('amount'), bool): raise ValueError('Informe o valor do aporte.')
    amount = app.number(data.get('amount'), True, .01, 1e12)
    mode, universe = data.get('mode', 'base'), data.get('universe', 'all')
    if mode not in ('base', 'context') or universe not in ('all', 'held'):
        raise ValueError('Escolha a versão e a lista de ativos.')
    limit = data.get('max_assets', 10)
    coverage = data.get('min_coverage', 70)
    if isinstance(limit, bool) or str(limit) not in tuple(str(n) for n in range(1, 21)):
        raise ValueError('Escolha entre 1 e 20 destinos.')
    if isinstance(coverage, bool): raise ValueError('Informe a cobertura mínima dos critérios.')
    coverage = app.number(coverage, True, 50, 100)
    if 'accept_estimates' in data and type(data['accept_estimates']) is not bool:
        raise ValueError('Confirme explicitamente o uso de saldos estimados.')
    return dict(amount=money_cents(amount)/100, mode=mode, universe=universe,
                max_assets=int(limit), min_coverage=coverage,
                accept_estimates=data.get('accept_estimates', False))


def issuer(asset):
    # B3 share classes/units of the same ticker root share one concentration cap.
    return 'stock:'+asset['ticker'][:4] if asset.get('asset_type') == 'stock' else 'asset:'+str(asset['id'])


def sector(asset):
    return str(asset.get('sector') or 'Não classificado').strip().casefold()


def price_reference(app, asset, state):
    quote = asset.get('snapshots', {}).get('quote', {})
    price = quote.get('data', {}).get('price')
    base = dict(price=price if numeric(price) and price > 0 else None,
                quote_asof=quote.get('asof'), quote_source=quote.get('source', ''),
                reference=None, ceiling=None, method=None, asof=None, discount=None, issues=[])
    if base['price'] is None or not recent(app, quote.get('asof'), 7):
        base['issues'].append('Cotação ausente, futura ou com mais de 7 dias.')
    if asset.get('asset_type') == 'fii':
        pvp, evidence, note = fii_quality.market_pvp(app, asset)
        base.update(method='VPA de referência (P/VP 1; não é valor justo)', asof=evidence.get('asof'),
                    evidence=note, pvp=pvp)
        if pvp is None or base['price'] is None:
            base['issues'].append('P/VP recente e positivo indisponível para comparar com o VPA.')
        else:
            base.update(reference=base['price']/pvp, ceiling=base['price']/pvp)
            if not recent(app, evidence.get('asof'), 7) or evidence.get('asof', '')[:10] != str(quote.get('asof', ''))[:10]:
                base['issues'].append('Confira P/VP e cotação na mesma data antes de derivar o VPA de referência.')
            if pvp > 1.5: base['issues'].append('Descarte obrigatório: P/VP acima de 1,5.')
            elif pvp >= 1: base['issues'].append('O FII não atende ao seu critério de P/VP abaixo de 1.')
    elif asset.get('asset_type') == 'stock':
        valuation = asset.get('valuation', {})
        suggestion = valuation.get('suggestion', {})
        saved = state.get('valuation_cases', {}).get(asset['ticker'], {})
        base.update(reference=suggestion.get('value'), ceiling=suggestion.get('ceiling'),
                    method=suggestion.get('method'), asof=saved.get('saved_at'),
                    safety_margin=valuation.get('inputs', {}).get('safety_margin'))
        if not recent(app, saved.get('saved_at'), 180):
            base['issues'].append('Salve ou revise as premissas de avaliação; validade de 180 dias.')
        chosen = next((r for r in valuation.get('methods', []) if r.get('method') == suggestion.get('method')), {})
        if chosen.get('role') not in ('primary', 'complementary'):
            base['issues'].append('Falta um método de avaliação aplicável ao negócio.')
        if set(chosen.get('requirements', [])) & set(valuation.get('estimates', [])):
            base['issues'].append('Confira as entradas estimadas por múltiplos antes de usar o preço de referência.')
        if not all(numeric(base[k]) and base[k] > 0 for k in ('reference', 'ceiling')):
            base['issues'].append('Falta valor de referência e teto positivos nas fórmulas do setor.')
        elif base['price'] is not None and base['price'] > base['ceiling']:
            base['issues'].append('Cotação acima do teto com a margem de segurança escolhida.')
    else:
        base['issues'].append('Esta versão compara qualidade e preço apenas de ações brasileiras e FIIs.')
    if base['price'] is not None and numeric(base['reference']) and base['reference'] > 0:
        base['discount'] = (1-base['price']/base['reference'])*100
    return base


def context(app, asset, eligible):
    research = asset.get('fii_research' if asset.get('asset_type') == 'fii' else 'company_research', {})
    news = research.get('news_context') or {}
    sections = [s for s in news.get('sections', []) if not s.get('stale', True)
                and recent(app, s.get('retrieved_at'), 1) and s.get('items')]
    items = list({r['url']: r for s in sections for r in s.get('items', [])}.values())[:6]
    sentiments = []
    for s in sections:
        tone = s.get('sentiment') or {}
        if not tone.get('stale', True) and recent(app, tone.get('analyzed_at'), 1):
            sentiments.append(dict(label=s['label'], tone=tone.get('tone', 'unknown'),
                asof=tone.get('analyzed_at'), model=tone.get('model'), engine=tone.get('engine'),
                count=tone.get('count'), publishers=tone.get('publishers')))
    points = asset.get('snapshots', {}).get('history', {}).get('data', {}).get('prices', [])
    points = sorted((p for p in points if recent(app, p.get('date'), 370)
                     and numeric(p.get('close')) and p['close'] > 0), key=lambda p:p['date'])
    drawdown = None
    if len(points) >= 120 and recent(app, points[-1]['date'], 7):
        drawdown = dict(value=(points[-1]['close']/max(p['close'] for p in points)-1)*100,
                        start=points[0]['date'], asof=points[-1]['date'], count=len(points))
    drivers = [r for r in research.get('drivers', {}).get('rows', []) if r.get('fresh')
               and r.get('observation') and recent(app, r['observation'].get('asof'), 45)]
    pessimism = any(s['tone'] == 'negative' for s in sentiments)
    fallen = drawdown is not None and drawdown['value'] <= -15
    hypothesis = ('Candidato a estudo de contrafluxo: qualidade e desconto passaram; há queda de pelo menos 15% '
                  'na série ajustada disponível ou cobertura negativa de mercado/setor. Investigue se o problema é temporário.'
                  if eligible and (fallen or pessimism) else
                  'Preço ou cobertura desfavorável não compensa as pendências da tese. Resolva os bloqueios primeiro.'
                  if not eligible and (fallen or pessimism) else
                  'Sem evidência recente de pessimismo pelo recorte usado. Qualidade e desconto podem existir sem queda recente.')
    return dict(headlines=items, sentiments=sentiments, drivers=drivers, drawdown=drawdown,
                hypothesis=hypothesis, available=bool(items or drivers or drawdown),
                invalidation='Revisar a tese se lucro/caixa recorrente, solvência, governança ou renda do FII se deteriorarem; recalcular o valor de referência após fatos relevantes.',
                note='Contexto salvo neste computador. Queda de 15% é um marcador editorial, não um ponto de compra. '
                     'Séries ajustadas são comparadas entre si; a cotação nominal não é comparada com o máximo ajustado. '
                     'Sentimento é de mercado/setor, não da empresa; IA e manchetes não alteram os valores do aporte nem estimam probabilidade de alta.')


def candidate(app, asset, state, opts, budgets):
    allocation = state['allocation']
    item = next(r for r in allocation['items'] if r['key'] == 'asset:'+str(asset['id']))
    cls = item['class']; class_row = next(r for r in allocation['classes'] if r['key'] == cls)
    research = asset.get('fii_research' if asset.get('asset_type') == 'fii' else 'company_research', {})
    study = research.get('study', {})
    checks = [c for g in study.get('groups', []) if g['key'] != 'price'
              for c in g.get('checks', []) if c.get('scope') != 'price' and c['status'] != 'na']
    counts = {s:sum(c['status'] == s for c in checks) for s in ('pass', 'fail', 'unknown')}
    total = sum(counts.values()); measured = counts['pass']+counts['fail']
    coverage = measured/total*100 if total else 0
    quality = counts['pass']/total*100 if total else None
    price = price_reference(app, asset, state)
    reasons = list(price['issues'])
    if asset.get('asset_type') not in ('stock', 'fii'):
        reasons.append('Produto a escolher na análise própria da classe.')
    if not total or coverage+1e-8 < opts['min_coverage']:
        reasons.append('Cobertura dos critérios abaixo do mínimo de '+format(opts['min_coverage'], 'g')+'%.')
    fails = [c['label'] for c in checks if c['status'] == 'fail']
    if fails: reasons.append('Critérios de qualidade a revisar: '+ '; '.join(fails))
    price_checks = [c for g in study.get('groups', []) for c in g.get('checks', [])
                    if c.get('key') == 'fii_quality_yield']
    if any(c['status'] == 'fail' for c in price_checks):
        reasons.append('Yield abaixo da média documentada dos FIIs comparáveis.')
    if not budgets.get(cls): reasons.append('Classe sem déficit para este aporte segundo suas metas.')
    if opts['universe'] == 'held' and not item['held']: reasons.append('Ativo fora da carteira; filtro selecionado: somente posições atuais.')
    if sector(asset) == 'não classificado': reasons.append('Classifique o setor antes de aplicar limites de concentração.')
    target = class_row['target']/100*(allocation['total']+opts['amount'])
    deficit = max(0, target-class_row['value'])
    need = min(100, deficit/target*100) if target else 0
    discount = min(100, max(0, price.get('discount') or 0)/30*100)
    priority = round(.5*quality+.35*discount+.15*need, 2) if quality is not None else None
    return dict(id=asset['id'], ticker=asset['ticker'], name=asset['name'], asset_type=asset.get('asset_type'),
                sector=asset.get('sector'), issuer=issuer(asset), sector_key=sector(asset),
                class_key=cls, class_label=class_row['label'], held=item['held'], value=item['value'],
                quality=round(quality, 2) if quality is not None else None, coverage=round(coverage, 2),
                counts=counts, failures=fails, pending=[c['label'] for c in checks+price_checks if c['status']=='unknown'],
                previous_score=asset.get('analysis', {}).get('score'), priority=priority,
                components=dict(quality=quality, discount=discount, rebalance=need), price=price,
                eligible=not reasons, reasons=list(dict.fromkeys(reasons)), amount=0, quantity=0)


def allocate(state, rows, budgets, max_assets):
    """Whole units, cents, and caps recomputed on the actually invested portfolio.

    Start with the maximum possible invested denominator, then monotonically reduce
    it until purchases and denominator agree. Unassigned cash never dilutes risk.
    """
    asset_values = {}; sector_values = {}; before = Decimal('0')
    for asset in state['assets']:
        value = Decimal(str(asset['value']))
        before += value
        key = issuer(asset); group = sector(asset)
        asset_values[key] = asset_values.get(key, Decimal('0'))+value
        sector_values[group] = sector_values.get(group, Decimal('0'))+value
    cfg = state['settings']
    asset_limit = Decimal(str(cfg['asset_limit']))/100
    sector_limit = Decimal(str(cfg['sector_limit']))/100
    choices = [r for r in rows if r['eligible']]
    denominator = before+Decimal(sum(budgets.get(r, 0) for r in {c['class_key'] for c in choices}))/100
    stable = False
    for _ in range(300):
        remaining = dict(budgets); used_assets = dict(asset_values); used_sectors = dict(sector_values)
        total_room = money_cents(denominator-before, ROUND_FLOOR)
        purchases = {}; seen = set()
        for row in choices:
            key, group = row['issuer'], row['sector_key']
            if key in seen: continue
            unit = money_cents(row['price']['price'], ROUND_CEILING)
            room = min(Decimal(total_room)/100, Decimal(remaining.get(row['class_key'], 0))/100,
                       max(Decimal('0'), asset_limit*denominator-used_assets.get(key, Decimal('0'))),
                       max(Decimal('0'), sector_limit*denominator-used_sectors.get(group, Decimal('0'))))
            quantity = int((room*100/unit).to_integral_value(rounding=ROUND_FLOOR))
            if quantity <= 0: continue
            if len(purchases) >= max_assets: break
            cents = quantity*unit; purchases[row['id']] = (cents, quantity)
            remaining[row['class_key']] -= cents; seen.add(key)
            total_room -= cents
            used_assets[key] = used_assets.get(key, Decimal('0'))+Decimal(cents)/100
            used_sectors[group] = used_sectors.get(group, Decimal('0'))+Decimal(cents)/100
        actual = before+Decimal(sum(c for c, q in purchases.values()))/100
        if actual == denominator:
            stable = True; break
        denominator = actual
    if not stable:
        purchases = {}; denominator = before
    final_assets = dict(asset_values)
    for row in rows:
        cents, _ = purchases.get(row['id'], (0, 0))
        final_assets[row['issuer']] = final_assets.get(row['issuer'], Decimal('0'))+Decimal(cents)/100
    for row in rows:
        cents, quantity = purchases.get(row['id'], (0, 0))
        row.update(amount=cents/100, quantity=quantity)
        if denominator > 0:
            row['after_issuer_weight'] = float(final_assets.get(row['issuer'], Decimal('0'))/denominator*100)
    return stable


def recommend(app, data):
    opts = options(app, data)
    state = app.state(); allocation = state['allocation']
    if not allocation['has_targets']: raise ValueError('Salve suas metas em Metas e aportes antes de gerar sugestões.')
    if allocation['issues'] and not opts['accept_estimates']:
        raise ValueError('Atualize os saldos e classificações ou confirme o uso das estimativas da carteira.')
    cents = money_cents(opts['amount'])
    _, budgets, _ = portfolio_strategy.distribution(allocation, {}, cents, app.number)
    rows = [candidate(app, asset, state, opts, budgets) for asset in state['assets']]
    rows.sort(key=lambda r:(not r['eligible'], -(r['priority'] if r['priority'] is not None else -1), r['ticker']))
    stable = allocate(state, rows, budgets, opts['max_assets'])
    if opts['mode'] == 'context':
        lookup = {a['id']:a for a in state['assets']}
        for row in rows: row['context'] = context(app, lookup[row['id']], row['eligible'])
    spent = sum(money_cents(r['amount']) for r in rows)
    final_total = allocation['total']+opts['amount']
    classes = []
    for cls in allocation['classes']:
        used = sum(money_cents(r['amount']) for r in rows if r['class_key'] == cls['key'])
        classes.append({**cls, 'budget':budgets[cls['key']]/100, 'suggested':used/100,
                        'pending':(budgets[cls['key']]-used)/100,
                        'after_weight':(cls['value']+used/100)/final_total*100 if final_total else 0})
    warnings = list(allocation['issues'])
    if any(r['eligible'] for r in rows) and not spent:
        warnings.append('Os limites por emissor/setor, os preços unitários e o número de destinos impediram uma distribuição válida. '
                        'Em uma carteira nova, pode ser necessário ampliar os destinos para diversificar; o saldo sem investir não reduz a concentração.')
    if not stable: warnings.append('Não foi possível estabilizar os limites de concentração; nenhum valor foi destinado.')
    for row in rows:
        row['allocation_note'] = ('Sugestão de aporte, sujeita a custos e preço de execução.' if row['amount'] else
            'Sem valor destinado: limite de concentração, prioridade, quantidade de destinos ou orçamento insuficiente para uma unidade.'
            if row['eligible'] else 'Aguardar e resolver as pendências antes de aportar.')
    return dict(options=opts, amount=opts['amount'], invested=spent/100, unassigned=(cents-spent)/100,
                unassigned_weight=(cents-spent)/100/final_total*100, candidates=rows, classes=classes,
                warnings=warnings, references=REFERENCES, method=METHOD, generated_at=app.now(),
                limits=dict(asset=state['settings']['asset_limit'], sector=state['settings']['sector_limit'],
                            scope='Emissores e setores dentro da carteira negociada efetivamente investida; ON/PN/units compartilham o limite.'),
                note='Simulação local de dinheiro novo, sem compras, vendas ou envio da carteira a serviços externos. '
                     'Quantidades inteiras estimadas ao último preço disponível; corretagem, emolumentos, spread e variação da execução não estão incluídos. '
                     'Valores sem oportunidade ou de classes sem seleção de produto ficam a decidir. O VPA de FII é contábil; preços das ações são condicionais às premissas salvas. '
                     'As pesquisas citadas não validam estes pesos, cortes, checklist ou aplicação em FIIs; não há previsão de retorno ou backtest desta estratégia.')
