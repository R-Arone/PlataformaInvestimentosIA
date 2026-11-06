"""Dated, product-specific value labels shared by the list and contribution plan."""
import math
import fii_quality
import recommendation_signals


def numeric(v):return type(v) in (int,float) and math.isfinite(v)
def recent(app,value,days):return recommendation_signals.fresh(app,value,days)


def reading(asset,p):
    result=dict(status='unknown',label='Valor inconclusivo',score=None,basis=p['method'],
        explanation='Confira os dados e as premissas antes de chamar o ativo de barato ou caro.',
        issues=list(p['issues']),disagreement=False)
    # A price veto is a conclusion, not missing valuation evidence.
    veto=('Cotação acima do teto','O FII não atende','Descarte obrigatório')
    invalid=[s for s in p['issues'] if not s.startswith(veto)]
    if invalid:return result
    if not numeric(p['reference']) or p['reference']<=0 or not numeric(p['price']):return result
    if asset['asset_type']=='fii':
        ratio=p.get('pvp')
        status='cheap' if ratio<1 else 'expensive' if ratio>1 else 'fair'
        result.update(status=status,label='Desconto patrimonial' if ratio<1 else 'Prêmio patrimonial' if ratio>1 else 'No valor patrimonial',
            explanation='P/VP compara a cota ao patrimônio informado. Avaliação patrimonial, crédito, contratos e renda precisam ser conferidos; desconto patrimonial não comprova valor justo.')
    else:
        price,ref,ceiling=p['price'],p['reference'],p['ceiling']
        status='expensive' if price>ref*1.05 else 'cheap' if price<=ref*.95 and price<=ceiling else 'fair' if price>=ref*.95 else 'no_margin'
        result.update(status=status,label=dict(expensive='Caro pelas premissas',cheap='Barato com margem',fair='Perto do valor estimado',no_margin='Desconto sem margem suficiente')[status],
            explanation=asset.get('valuation',{}).get('selection',{}).get('reason') or 'Referência do método prioritário aplicável ao negócio, com premissas revisadas. Não faz média entre fórmulas.')
        result['disagreement']=asset.get('valuation',{}).get('comparison',{}).get('classification')=='mixed'
        if result['disagreement']:result['issues'].append('Outros métodos aplicáveis divergem; confira as premissas no dossiê.')
    result['score']=round(min(100,max(0,p['discount'])/30*100),2)
    result['rule']='Barato: pelo menos 5% abaixo da referência e dentro do teto. Perto do valor: faixa de ±5%. Desconto sem margem: abaixo da referência, acima do teto. Cortes de estudo, sem calibração. Em FIIs, usa somente a posição em relação ao VPA.'
    return result


def reference(app, asset, cases):
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
        saved = cases.get(asset['ticker'], {})
        base.update(reference=suggestion.get('value'), ceiling=suggestion.get('ceiling'),
                    method=suggestion.get('method'), asof=saved.get('saved_at'),
                    safety_margin=valuation.get('inputs', {}).get('safety_margin'))
        if not recent(app, saved.get('saved_at'), 180):
            base['issues'].append('Salve ou revise as premissas de avaliação; validade de 180 dias.')
        chosen = next((r for r in valuation.get('methods', []) if r.get('method') == suggestion.get('method')), {})
        manual=suggestion.get('mode')=='manual' and valuation.get('inputs',{}).get('reference_method')==chosen.get('method') and chosen.get('role') not in (None,'not_applicable')
        if chosen.get('role') not in ('primary', 'complementary') and not manual:
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
    base['reading']=reading(asset,base)
    return base
