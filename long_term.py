"""Local contribution planning with explicit quality/value and market/model choices."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, ROUND_CEILING
from datetime import date
import math
import fii_quality
import portfolio_strategy
import investment_exposure
import recommendation_signals
import contrarian
import market_research
import investment_value
import investment_risk
import investment_decision
import contribution_context
import quality_evidence


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
    return recommendation_signals.fresh(app,value,days)


def money_cents(value, rounding=ROUND_HALF_UP):
    return int((Decimal(str(value))*100).to_integral_value(rounding=rounding))


def options(app, data):
    allowed = {'amount', 'mode', 'universe', 'max_assets', 'min_coverage', 'accept_estimates', 'allocation_style', 'min_ticket', 'signal_horizon','scenario_id','scenario_weight'}
    if not isinstance(data, dict) or set(data)-allowed:
        raise ValueError('Opções do aporte de longo prazo inválidas.')
    if isinstance(data.get('amount'), bool): raise ValueError('Informe o valor do aporte.')
    amount = app.number(data.get('amount'), True, .01, 1e12)
    mode, universe = data.get('mode', 'base'), data.get('universe', 'all')
    if mode not in ('base', 'context','economic','scenario') or universe not in ('all', 'held'):
        raise ValueError('Escolha a versão e a lista de ativos.')
    style=data.get('allocation_style','gradual')
    if style not in ('gradual','balanced','opportunities','contrarian'):raise ValueError('Escolha contrafluxo, poucos destinos, proporcional ou oportunidades de alta.')
    horizon=data.get('signal_horizon',20)
    if isinstance(horizon,bool) or str(horizon) not in ('1','5','20'):raise ValueError('Escolha um horizonte de 1, 5 ou 20 pregões para os modelos.')
    limit = data.get('max_assets', 2)
    if isinstance(data.get('min_ticket',500),bool):raise ValueError('Informe um valor mínimo por destino.')
    ticket=app.number(data.get('min_ticket',500),True,0,1e12)
    coverage = data.get('min_coverage', 70)
    if isinstance(limit, bool) or str(limit) not in tuple(str(n) for n in range(1, 21)):
        raise ValueError('Escolha entre 1 e 20 destinos.')
    if isinstance(coverage, bool): raise ValueError('Informe a cobertura mínima dos critérios.')
    coverage = app.number(coverage, True, 50, 100)
    if 'accept_estimates' in data and type(data['accept_estimates']) is not bool:
        raise ValueError('Confirme explicitamente o uso de saldos estimados.')
    scenario_id=data.get('scenario_id','')
    if not isinstance(scenario_id,str) or len(scenario_id)>64:raise ValueError('Escolha um cenário salvo.')
    if mode=='scenario' and (len(scenario_id)!=64 or any(c not in '0123456789abcdef' for c in scenario_id)):raise ValueError('Escolha o cenário de IA para ponderar o aporte.')
    if isinstance(data.get('scenario_weight',10),bool):raise ValueError('Peso do cenário inválido.')
    scenario_weight=app.number(data.get('scenario_weight',10),True,0,20)
    return dict(amount=money_cents(amount)/100, mode=mode, universe=universe,
                max_assets=int(limit), min_coverage=coverage,
                allocation_style=style,min_ticket=money_cents(ticket)/100,signal_horizon=int(horizon),
                accept_estimates=data.get('accept_estimates', False),scenario_id=scenario_id,scenario_weight=scenario_weight)


def issuer(asset):
    # B3 share classes/units of the same ticker root share one concentration cap.
    return 'stock:'+asset['ticker'][:4] if asset.get('asset_type') == 'stock' else 'asset:'+str(asset['id'])


def sector(asset):
    return investment_risk.group(asset)['key']


def price_reference(app, asset, state):
    return investment_value.reference(app,asset,state.get('valuation_cases',{}))


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
    hypothesis = ('Candidato a estudo de contrafluxo: os filtros deste cenário passaram; há queda de pelo menos 15% '
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
                     'Sentimento das manchetes é de mercado/setor, não da empresa, e não entra na nota. '
                     'A influência dos modelos de preços aparece separadamente no painel de IA; seus escores não são chances de lucro.')


def candidate(app, asset, state, opts, budgets, risk=None):
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
    opportunity=opts['allocation_style']=='opportunities'
    contra=opts['allocation_style']=='contrarian'
    fundamental=asset.get('asset_type') in ('stock','fii')
    broad_etf=contra and asset.get('asset_type')=='etf' and contrarian.exposure(asset,app) is not None
    # In momentum mode valuation is information, not an entry ceiling. Quotes
    # and the user's mandatory FII discard remain hard gates.
    reasons = ([x for x in price['issues'] if x.startswith(('Cotação ausente','Descarte obrigatório'))]
               if opportunity else list(price['issues']))
    price_warnings=[x for x in price['issues'] if x not in reasons] if opportunity else []
    if broad_etf:
        reasons=[x for x in price['issues'] if x.startswith('Cotação ausente')]
        price_warnings=['ETF amplo: sem valor justo de empresa. Confira índice, custos, liquidez e composição antes de executar.']
    if opportunity and not fundamental or broad_etf:
        if opportunity:price_warnings=[]
        quality=None;coverage=0;counts={s:0 for s in counts};total=0;checks=[]
    if not fundamental and not opportunity and not broad_etf:
        reasons.append('Produto a escolher na análise própria da classe.')
    if not broad_etf and (fundamental or not opportunity) and (not total or coverage+1e-8 < opts['min_coverage']):
        reasons.append('Cobertura dos critérios abaixo do mínimo de '+format(opts['min_coverage'], 'g')+'%.')
    fails = [c['label'] for c in checks if c['status'] == 'fail']
    if fails: reasons.append('Critérios de qualidade a revisar: '+ '; '.join(fails))
    price_checks = [c for g in study.get('groups', []) for c in g.get('checks', [])
                    if c.get('key') == 'fii_quality_yield']
    if not opportunity and any(c['status'] == 'fail' for c in price_checks):
        reasons.append('Yield abaixo da média documentada dos FIIs comparáveis.')
    if not opportunity and not contra and not budgets.get(cls): reasons.append('Classe adiada neste cenário de poucos destinos; confira a próxima prioridade.' if opts.get('allocation_style')=='gradual' and class_row['target']>class_row['weight'] else 'Classe sem orçamento neste cenário segundo suas metas.')
    if opts['universe'] == 'held' and not item['held']: reasons.append('Ativo fora da carteira; filtro selecionado: somente posições atuais.')
    if sector(asset) == 'não classificado': reasons.append('Classifique o setor antes de aplicar limites de concentração.')
    target = (class_row['target'] or 0)/100*(allocation['total']+opts['amount'])
    deficit = max(0, target-class_row['value'])
    need = min(100, deficit/target*100) if target and not opportunity else 0
    discount = price['reading']['score'] if price['reading']['score'] is not None else 0
    sector_rating=investment_risk.rating(asset)
    diversification=risk.assess(asset['id']) if risk else None
    priority = round(.5*quality+.35*discount+.15*need, 2) if quality is not None else None
    observed=recommendation_signals.market(app,asset) if opportunity or contra or opts['mode']=='context' else None
    contraflow=contrarian.candidate(app,asset,state,observed) if contra else None
    if contra:
        if not contraflow['active']:reasons.append('Contrafluxo sem queda relevante confirmada; acompanhar em vez de forçar compra.')
        if broad_etf:
            quality=None;coverage=0;counts={s:0 for s in counts};fails=[];checks=[];price_checks=[]
            priority=round(.7*contraflow['score']+.3*need,4)
            if not observed['available']:reasons.append(observed['reason'])
        elif fundamental and quality is not None:
            priority=round(.35*quality+.25*discount+.15*contraflow['score']+.05*need+
                .1*(sector_rating['score'] if sector_rating['score'] is not None else 50)+.1*(diversification['score'] if diversification else 50),4)
    if opportunity:
        priority=observed['score']
        if not observed['available']:reasons.append(observed['reason'])
        if asset.get('asset_type')=='etf':
            meta=asset.get('exposure') or investment_exposure.metadata(asset,{})
            if not meta.get('source_url') or not meta.get('asof') or meta.get('focus')=='unknown':
                reasons.append('Confira a composição e a fonte do ETF antes de comparar oportunidades.')
    model=recommendation_signals.adjust(app,asset,state,opts,priority,observed)
    if opportunity and observed['available']:
        if model['applied'] and model['score']<40:
            reasons.append('Modelos locais desfavoráveis (escore abaixo de 40); aguardar nova leitura.')
        elif not observed['positive'] and not (model['applied'] and model['score']>=60):
            reasons.append('Mercado sem alta consistente e sem sinal favorável de virada pelos modelos.')
    priority=model['final']
    economic=contribution_context.evaluate(app,state,asset,opts,priority)
    priority=economic['priority_after']
    return dict(id=asset['id'], ticker=asset['ticker'], name=asset['name'], asset_type=asset.get('asset_type'),
                sector=asset.get('sector'), issuer=issuer(asset), sector_key=sector(asset),
                class_key=cls, class_label=class_row['label'], held=item['held'], value=item['value'],
                quality=round(quality, 2) if quality is not None else None, quality_known=round(counts['pass']/measured*100,2) if measured and quality is not None else None, coverage=round(coverage, 2),
                counts=counts,quality_evidence=quality_evidence.summarize(study),economic_context=economic, failures=fails, pending=[c['label'] for c in checks+price_checks if c['status']=='unknown'],
                previous_score=asset.get('analysis', {}).get('score'), priority=priority,
                components=dict(quality=quality, discount=discount, rebalance=need,contraflow=contraflow['score'] if contra else None,
                    sector=sector_rating['score'],diversification=diversification['score'] if diversification else None), price=price,
                sector_rating=sector_rating,diversification=diversification,
                market_signal=observed,ai=model,price_warnings=price_warnings,
                contraflow=contraflow,
                strategy='contrarian' if contra else 'opportunities' if opportunity else 'quality_value',
                eligible=not reasons, reasons=list(dict.fromkeys(reasons)), amount=0, quantity=0)


def allocate(state, rows, budgets, max_assets, min_ticket=0, available=None, risk=None):
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
    available=sum(budgets.get(r, 0) for r in {c['class_key'] for c in choices}) if available is None else available
    denominator = before+Decimal(available)/100
    stable = False
    for _ in range(300):
        remaining = dict(budgets); used_assets = dict(asset_values); used_sectors = dict(sector_values)
        total_room = money_cents(denominator-before, ROUND_FLOOR)
        purchases = {}; seen = set();pending=list(choices)
        while pending:
            def selection_score(row):
                if not risk or row['strategy']!='contrarian' or row['asset_type']=='etf':return row['priority'] or 0
                values={i:float(v) for i,v in risk.values.items()}
                for aid,(cents,_) in purchases.items():values[aid]+=cents/100
                delta=risk.assess(row['id'],values)['score']-row['diversification']['score']
                return row['priority']+.1*delta*(.7 if row['ai']['applied'] else 1)
            row=max(pending,key=selection_score);pending.remove(row)
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
            if cents<money_cents(min_ticket):
                purchases.pop(row['id']);continue
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
            final_sector=sector_values.get(row['sector_key'],Decimal('0'))+sum(Decimal(c)/100 for aid,(c,_) in purchases.items() if sector(next(a for a in state['assets'] if a['id']==aid))==row['sector_key'])
            row['after_sector_weight']=float(final_sector/denominator*100)
    return stable


def suggestion(app, state, opts, risk=None):
    risk=risk or investment_risk.Plan(app,state)
    allocation=state['allocation']
    cents = money_cents(opts['amount'])
    opportunity=opts['allocation_style']=='opportunities'
    flexible=opts['allocation_style'] in ('opportunities','contrarian')
    ideal={key:0 for key in portfolio_strategy.CLASSES}
    if allocation['has_targets']:
        _, ideal, _ = portfolio_strategy.distribution(allocation, {}, cents, app.number)
    order=lambda r:(not r['eligible'], -(r['priority'] if r['priority'] is not None else -1), r['ticker'])
    seed=sorted((candidate(app,a,state,{**opts,'allocation_style':opts['allocation_style'] if flexible else 'balanced'},ideal,risk) for a in state['assets']),key=order)
    selected=[];issuers=set()
    for row in seed:
        if not row['eligible'] or row['issuer'] in issuers:continue
        issuers.add(row['issuer']);selected.append(row['class_key'])
        if len(selected)>=opts['max_assets']:break
    selected=list(dict.fromkeys(selected))
    gradual=opts['allocation_style']=='gradual' and bool(selected)
    budgets=({key:cents for key in ideal} if flexible else
             {key:cents if key in selected else 0 for key in ideal} if gradual else dict(ideal))
    rows=sorted((candidate(app,a,state,opts,budgets,risk) for a in state['assets']),key=order)
    stable = allocate(state, rows, budgets, opts['max_assets'],opts['min_ticket'],cents,risk)
    if opts['mode'] == 'context':
        lookup = {a['id']:a for a in state['assets']}
        for row in rows: row['context'] = context(app, lookup[row['id']], row['eligible'])
    spent = sum(money_cents(r['amount']) for r in rows)
    if gradual or flexible:
        budgets={key:sum(money_cents(r['amount']) for r in rows if r['class_key']==key) for key in ideal}
        budgets[selected[0] if selected else 'other']+=cents-spent
    final_total = allocation['total']+opts['amount']
    classes = []
    for cls in allocation['classes']:
        used = sum(money_cents(r['amount']) for r in rows if r['class_key'] == cls['key'])
        classes.append({**cls, 'budget':budgets[cls['key']]/100, 'ideal_budget':ideal[cls['key']]/100,'suggested':used/100,
                        'pending':(budgets[cls['key']]-used)/100,
                        'after_weight':(cls['value']+used/100)/final_total*100 if final_total else 0})
    warnings = list(allocation['issues'])
    if any(r['eligible'] for r in rows) and not spent:
        warnings.append('Os limites por emissor/setor, os preços unitários e o número de destinos impediram uma distribuição válida. '
                        'Em uma carteira nova, pode ser necessário ampliar os destinos para diversificar; o saldo sem investir não reduz a concentração.')
    if not stable: warnings.append('Não foi possível estabilizar os limites de concentração; nenhum valor foi destinado.')
    if opts['allocation_style']=='gradual':warnings.append('Poucos destinos: as metas por classe orientam a prioridade, mas podem ficar temporariamente desequilibradas. Os limites por emissor e setor continuam obrigatórios.')
    if opportunity:warnings.append('Oportunidades de alta: metas por classe e desconto não determinam a ordem nem o orçamento. Pode aumentar o desequilíbrio. Qualidade de ações/FIIs, descarte obrigatório de FII e limites de concentração continuam sendo verificados.')
    if opts['allocation_style']=='contrarian':warnings.append('Contrafluxo: quedas só orientam estudo de aporte quando os filtros do produto passam. Metas são referência na nota, sem orçamento obrigatório por classe. O sinal não prevê o fundo nem garante recuperação; limites de concentração continuam obrigatórios.')
    if opts['mode']=='context':
        applied=sum(r['ai']['applied'] for r in rows)
        warnings.append(f'IA aplicada à nota de {applied} de {len(rows)} ativos avaliados. Nos demais, a nota usa apenas as regras sem IA; confira os motivos individuais.')
    for row in rows:
        row['allocation_note'] = ('Sugestão de aporte, sujeita a custos e preço de execução.' if row['amount'] else
            'Sem valor destinado: limite de concentração, prioridade, quantidade de destinos, aporte mínimo ou orçamento insuficiente para uma unidade.'
            if row['eligible'] else 'Aguardar e resolver as pendências antes de aportar.')
    return dict(options=opts, amount=opts['amount'], invested=spent/100, unassigned=(cents-spent)/100,
                has_targets=allocation['has_targets'],
                distance_before=sum(abs(r['weight']-r['target']) for r in classes)/2 if allocation['has_targets'] else None,
                distance_after=(sum(abs(r['after_weight']-r['target']) for r in classes)+(cents-spent)/100/final_total*100)/2 if allocation['has_targets'] else None,
                next_classes=[dict(key=r['key'],label=r['label'],gap=max(0,r['target']/100*final_total-r['value']-r['suggested'])) for r in classes if r['target'] is not None and r['after_weight']<r['target']-.01],
                unassigned_weight=(cents-spent)/100/final_total*100, candidates=rows, classes=classes,
                sector_allocation=risk.summary(rows),
                warnings=warnings, references=REFERENCES,
                method=(contrarian.METHOD if opts['allocation_style']=='contrarian' else recommendation_signals.METHOD if opportunity else METHOD+(' Com IA válida: 70% desta nota + 30% da média dos escores dos modelos locais no horizonte escolhido. Pesos experimentais.' if opts['mode']=='context' else '')),
                generated_at=app.now(),
                limits=dict(asset=state['settings']['asset_limit'], sector=state['settings']['sector_limit'],
                            scope='Emissores e setores dentro da carteira negociada efetivamente investida; ON/PN/units compartilham o limite.'),
                note='Simulação local de dinheiro novo, sem compras, vendas ou envio da carteira a serviços externos. '
                     'Quantidades inteiras estimadas ao último preço disponível; corretagem, emolumentos, spread e variação da execução não estão incluídos. '
                     'Valores sem oportunidade ou de classes sem seleção de produto ficam a decidir. O VPA de FII é contábil; preços das ações são condicionais às premissas salvas. '
                     'As pesquisas citadas não validam estes pesos, cortes, checklist ou aplicação em FIIs. Não há backtest desta estratégia; '
                     'previsões de curto prazo dos modelos são experimentais e não estimam retorno para vários anos.')


def ai_comparison(result, baseline):
    """Show the counterfactual on the same portfolio, quotes, rules and budget."""
    lookup={r['id']:(i+1,r) for i,r in enumerate(baseline['candidates'])}
    rows=[]
    for i,row in enumerate(result['candidates']):
        rank,other=lookup[row['id']]
        rows.append(dict(id=row['id'],ticker=row['ticker'],applied=row['ai']['applied'],reason=row['ai']['reason'],
                         rank_without=rank,rank_with=i+1,score_without=other['priority'],score_with=row['priority'],
                         amount_without=other['amount'],amount_with=row['amount'],
                         eligibility_changed=other['eligible']!=row['eligible']))
    requested=result['options']['mode']=='context'
    return dict(requested=requested,applied_count=sum(r['applied'] for r in rows),total=len(rows),
                ranking_changed=any(r['rank_with']!=r['rank_without'] for r in rows),
                allocation_changed=any(r['amount_with']!=r['amount_without'] for r in rows),
                invested_without=baseline['invested'],invested_with=result['invested'],rows=rows,
                rule='Com modelo válido: 70% da nota sem IA + 30% do escore dos modelos. A comparação mantém a mesma carteira, preços, metas e limites. Mudanças de nota podem não mudar compras por causa dos limites ou do número de destinos.')


def recommend(app, data):
    opts=options(app,data);state=app.state();allocation=state['allocation']
    contribution_context.selected_scenario(app,state,opts)
    if not allocation['has_targets'] and opts['allocation_style'] not in ('opportunities','contrarian'):raise ValueError('Salve suas metas ou selecione Contrafluxo ou Oportunidades de alta para usar metas apenas como referência.')
    if allocation['issues'] and not opts['accept_estimates']:
        raise ValueError('Atualize os saldos e classificações ou confirme o uso das estimativas da carteira.')
    risk=investment_risk.Plan(app,state)
    result=suggestion(app,state,opts,risk)
    result['exposure_areas']=state.get('exposure_areas',[])
    result['market_context']=state.get('contribution_context',contrarian.public_state(app,{}))
    result['market_ideas']=contrarian.ideas(app,state,result['candidates'],opts['universe'])
    result['sector_context']=market_research.for_plan(app,state,result['candidates'],opts['universe'])
    result['comparisons']=[]
    style=opts['allocation_style'] if opts['allocation_style'] in ('opportunities','contrarian') else 'gradual'
    scenarios=[(style,1,'Um destino agora'),(style,2,'Até dois destinos'),(style,3,'Até três destinos')]
    if allocation['has_targets']:scenarios.append(('balanced',20,'Distribuição proporcional'))
    for style,limit,label in scenarios:
        scenario_opts={**opts,'allocation_style':style,'max_assets':limit}
        scenario=result if style==opts['allocation_style'] and limit==opts['max_assets'] else suggestion(app,state,scenario_opts,risk)
        result['comparisons'].append(dict(label=label,allocation_style=style,max_assets=limit,invested=scenario['invested'],
            unassigned=scenario['unassigned'],distance_after=scenario['distance_after'],
            destinations=[dict(id=r['id'],ticker=r['ticker'],amount=r['amount'],quantity=r['quantity']) for r in scenario['candidates'] if r['amount']]))
    baseline=suggestion(app,state,{**opts,'mode':'base'},risk) if opts['mode']=='context' else result
    result['ai_effect']=ai_comparison(result,baseline)
    assets={a['id']:a for a in state['assets']}
    for row in result['candidates']:row['decision_evidence']=investment_decision.explain(app,assets[row['id']],row,state)
    return result
