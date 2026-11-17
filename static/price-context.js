'use strict';
// Price in its own history (previous visits to the same level) and per-asset correlations.
const priceContextDetailBefore=detail,priceContextPricesBefore=valuationView;
let priceContextSeries='';
const pcMonthly=L=>L.series==='monthly';
const pcWhen=(iso,monthly)=>!iso?'—':monthly?iso.slice(5,7)+'/'+iso.slice(0,4):dt(iso);
const pcAgo=days=>days==null?'':days>=730?`há ${fmt(days/365.25,1)} anos`:days>=60?`há ${Math.round(days/30.44)} meses`:days===0?'hoje':`há ${days} dias`;
const pcSigned=v=>v==null?'—':(v>0?'+':'')+fmt(v,1)+'%';
const pcUnit=(L,n)=>pcMonthly(L)?(n===1?'mês':'meses'):(n===1?'pregão':'pregões');
const pcPlural=(n,one,many)=>n===1?one:many;

function pcFetchButtons(a){
 return button('price-context-history','Buscar histórico diário de 5 anos','secondary',`data-id="${a.id}"`)+
  (['stock','fii'].includes(a.asset_type)?button('price-context-monthly','Buscar histórico mensal de 10 anos','secondary',`data-id="${a.id}"`):'');
}
function pcVisitCard(L){
 const v=L.visit,p=v.previous,m=pcMonthly(L);
 if(!p)return `<article class="pc-card"><b>Última visita à faixa ±${fmt(L.band,0)}%</b><div class="pc-value">Primeira vez</div><p>Neste histórico (${pcWhen(L.start,m)} a ${pcWhen(L.end,m)}), o preço ainda não tinha estado nesta faixa.</p></article>`;
 const low=p.between_low,high=p.between_high;
 return `<article class="pc-card"><b>Última visita à faixa ±${fmt(L.band,0)}%</b><div class="pc-value">${esc(pcWhen(p.end,m))}<small>${esc(pcAgo(p.days_ago))}</small></div>
  <p>A visita anterior durou ${p.observations} ${pcUnit(L,p.observations)} (${esc(pcWhen(p.start,m))} a ${esc(pcWhen(p.end,m))}).</p>
  ${low&&high?`<p>Depois dela, o fechamento chegou a <b>${pcSigned(low.change)}</b> em ${esc(pcWhen(low.date,m))} e a <b>${pcSigned(high.change)}</b> em ${esc(pcWhen(high.date,m))}, em relação ao preço de referência.</p>`:''}</article>`;
}
function pcBeyondCard(L,key){
 const x=L.beyond[key],m=pcMonthly(L),title=key==='cheaper'?`Última vez ${fmt(L.band,0)}% ou mais abaixo`:`Última vez ${fmt(L.band,0)}% ou mais acima`;
 if(!x)return `<article class="pc-card"><b>${title}</b><div class="pc-value">Não houve</div><p>Nenhum fechamento do histórico ficou ${key==='cheaper'?'tão abaixo':'tão acima'} do preço de referência.</p></article>`;
 return `<article class="pc-card"><b>${title}</b><div class="pc-value">${esc(pcWhen(x.date,m))}<small>${esc(pcAgo(x.days_ago))}</small></div><p>Fechou a ${money(x.close)}, ${pcSigned(x.change)} em relação à referência.</p></article>`;
}
function pcStayCard(L){
 const v=L.visit,m=pcMonthly(L);
 return `<article class="pc-card"><b>Permanência na faixa atual</b><div class="pc-value">${v.stay_observations?`${v.stay_observations} ${pcUnit(L,v.stay_observations)}`:'Fora da faixa'}${v.stay_start?`<small>desde ${esc(pcWhen(v.stay_start,m))}</small>`:''}</div><p>Referência de comparação: ${money(L.reference)}${m?' (cotação atual)':' (último fechamento ajustado)'}. Faixa de ${money(L.reference*(1-L.band/100))} a ${money(L.reference*(1+L.band/100))}.</p></article>`;
}
function pcWindowTable(L){
 const rows=Object.values(L.windows).filter(w=>w.available);
 if(!rows.length)return '<p class="form-hint">Janelas de 1, 3, 5 e 10 anos aparecem quando o histórico cobre o período.</p>';
 const m=pcMonthly(L);
 return `<div class="table-wrap"><table class="pc-table"><caption class="sr-only">Posição do preço atual em cada janela de histórico</caption><thead><tr><th>Janela</th><th>Percentil</th><th>Mediana</th><th>Máxima (distância)</th><th>Mínima (distância)</th><th>Maior queda</th></tr></thead><tbody>${rows.map(w=>{
  const d=w.max_drawdown;
  return `<tr><th scope="row">${w.years} ${pcPlural(w.years,'ano','anos')}</th><td>${fmt(w.percentile,0)}</td><td>${money(w.median)} <small>(${pcSigned(w.vs_median)})</small></td>
   <td>${money(w.high.close)} <small>${esc(pcWhen(w.high.date,m))} · ${pcSigned(w.high.distance)}</small></td>
   <td>${money(w.low.close)} <small>${esc(pcWhen(w.low.date,m))} · ${pcSigned(w.low.distance)}</small></td>
   <td>${pcSigned(d.value)} <small>${esc(pcWhen(d.peak,m))} → ${esc(pcWhen(d.trough,m))}${d.recovered?`; recuperou em ${fmt(d.months_to_recover,1)} meses`:'; ainda não recuperou'}</small></td></tr>`;}).join('')}</tbody></table></div>`;
}
function priceContextPanel(a){
 const p=a?.price_context;if(!p?.applicable)return '';
 const keys=Object.keys(p.levels||{}),head=(extra='')=>`<div class="panel-head"><div><h3>Preço no histórico</h3><p class="form-hint">${esc(p.caveat)}</p></div>${extra}</div>`;
 if(!keys.length)return `<section class="details-section price-context-panel" data-id="${a.id}">${head()}<div class="notice">${esc(p.message||'Sem histórico de preços.')}</div><div class="actions">${pcFetchButtons(a)}</div></section>`;
 const key=keys.includes(priceContextSeries)?priceContextSeries:p.preferred,L=p.levels[key];
 const tabs=keys.length>1?`<div class="tabs" role="group" aria-label="Série de preços">${keys.map(k=>`<button type="button" data-action="price-context-series" data-series="${k}" class="${k===key?'selected':''}" aria-pressed="${k===key}">${k==='monthly'?'Mensal · 10 anos':'Diário · 5 anos'}</button>`).join('')}</div>`:'';
 return `<section class="details-section price-context-panel" data-id="${a.id}">${head(tabs)}
  <p class="pc-reading">${esc(L.reading)}</p>
  <div class="pc-grid">${pcVisitCard(L)}${pcBeyondCard(L,'cheaper')}${pcBeyondCard(L,'dearer')}${pcStayCard(L)}</div>
  <h4>Posição do preço em cada janela</h4>${pcWindowTable(L)}
  <p class="form-hint">${esc(L.label)} · ${esc(pcWhen(L.start,pcMonthly(L)))} a ${esc(pcWhen(L.end,pcMonthly(L)))} · ${L.count} observações. ${esc(L.note)}</p>
  <details><summary>Como ler e como é calculado</summary><p>${esc(L.method)}</p><p><b>Percentil</b>: 0 significa o menor fechamento da janela e 100, o maior. <b>Mediana</b>: valor central dos fechamentos. <b>Maior queda</b>: pior distância entre um pico e o fundo seguinte na janela, e quanto tempo levou para voltar ao pico, quando voltou.</p></details>
  <div class="actions">${pcFetchButtons(a)}</div></section>`;
}

// --- correlations ---------------------------------------------------------
const corrStrength=r=>Math.abs(r)>=.7?'forte':Math.abs(r)>=.4?'moderada':'fraca';
function corrBar(r){const left=Math.max(0,Math.min(100,(r+1)/2*100));return `<span class="corr-bar" role="img" aria-label="Correlação ${fmt(r,2)} numa escala de −1 a +1"><i class="corr-zero"></i><i class="corr-dot" style="left:${left.toFixed(1)}%"></i></span>`;}
function corrBenchCard(label,s){
 if(!s)return '';
 if(s.status!=='ready')return `<article class="pc-card"><b>${esc(label)}</b><p>${esc(s.reason||'Sem dados suficientes.')}</p></article>`;
 const ci=s.interval?` <small>(95%: ${fmt(s.interval[0],2)} a ${fmt(s.interval[1],2)})</small>`:'',ro=s.rolling;
 return `<article class="pc-card"><b>${esc(label)}</b><div class="pc-value">${fmt(s.correlation,2)}<small>correlação ${corrStrength(s.correlation)}${s.correlation<0?' (oposta)':''}</small></div>${corrBar(s.correlation)}
  <dl class="pc-stats"><div><dt>Intervalo</dt><dd>${s.interval?fmt(s.interval[0],2)+' a '+fmt(s.interval[1],2):'—'}</dd></div>
  <div><dt>Beta</dt><dd>${fmt(s.beta,2)}</dd></div><div><dt>R²</dt><dd>${fmt(s.r2*100,0)}%</dd></div>
  <div><dt>Beta em dias de alta</dt><dd>${s.up_beta==null?'—':fmt(s.up_beta,2)}</dd></div><div><dt>Beta em dias de queda</dt><dd>${s.down_beta==null?'—':fmt(s.down_beta,2)}</dd></div>
  <div><dt>Volatilidade anual</dt><dd>${fmt(s.volatility,1)}% <small>(${esc(label)}: ${fmt(s.benchmark_volatility,1)}%)</small></dd></div>
  <div><dt>Estabilidade (janelas de ${ro?.window||63})</dt><dd>${ro?`${fmt(ro.min,2)} a ${fmt(ro.max,2)} <small>(última ${fmt(ro.last,2)})</small>`:'histórico curto'}</dd></div></dl>
  <p class="form-hint">${s.n} retornos diários · ${dt(s.start)} a ${dt(s.end)} · ${s.up_days} dias de alta e ${s.down_days} de queda.</p></article>`;
}
function corrHoldingsCard(h){
 if(!h)return '';
 if(h.status!=='ready')return `<article class="pc-card"><b>Com o restante da carteira</b><p>${esc(h.reason||'Sem dados suficientes.')}</p></article>`;
 const row=p=>`<li><span>${esc(p.ticker)}</span>${corrBar(p.correlation)}<b>${fmt(p.correlation,2)}</b><small>${fmt(p.weight,0)}% do peso</small></li>`;
 return `<article class="pc-card pc-wide"><b>Com o restante da carteira</b><div class="pc-value">${fmt(h.mean_correlation,2)}<small>média ponderada pelo valor · ${esc(h.reading)}</small></div>${corrBar(h.mean_correlation)}
  ${h.peers<=3?`<div><h5>Posições comparadas</h5><ul class="pc-peers">${h.highest.map(row).join('')}</ul></div>`:`<div class="pc-columns"><div><h5>Mais parecidos</h5><ul class="pc-peers">${h.highest.map(row).join('')}</ul></div><div><h5>Menos parecidos</h5><ul class="pc-peers">${h.lowest.map(row).join('')}</ul></div></div>`}
  <p class="form-hint">${h.peers} ${pcPlural(h.peers,'posição comparada','posições comparadas')}, ${h.coverage==null?'—':fmt(h.coverage,0)}% do valor das demais posições com histórico suficiente.</p></article>`;
}
function correlationPanel(a){
 const c=a?.correlation_context;if(!c?.applicable)return '';
 const info=S.benchmark_info||{},sources=Object.values(info.series||{}),when=typeof localTime==='function'?localTime:dt;
 const missing=(c.missing||[]).length?`<div class="notice">${c.missing.map(esc).join('<br>')}</div>`:'';
 const body=c.status==='missing'&&!c.ibov&&!c.usd&&!c.holdings?'':`<div class="pc-grid pc-grid-corr">${corrBenchCard('Ibovespa',c.ibov)}${corrBenchCard('Dólar (USD/BRL)',c.usd)}${corrHoldingsCard(c.holdings)}</div>`;
 const readings=(c.readings||[]).length?`<ul class="pc-readings">${c.readings.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`:'';
 const needHistory=(c.missing||[]).some(t=>t.startsWith('Falta histórico'));
 return `<section class="details-section correlation-panel" data-id="${a.id}"><div class="panel-head"><div><h3>Correlação e beta</h3><p class="form-hint">${esc(c.caveat||'')}</p></div></div>
  ${missing}${body}${readings}
  <details><summary>Como ler e como é calculado</summary><p>${esc(c.method||'')}</p><p><b>Correlação</b> vai de −1 (movimentos opostos) a +1 (mesmo movimento); perto de 0, os movimentos são independentes. <b>Beta</b> mede a amplitude: beta 1,5 significa que o preço variou, em média, 1,5% para cada 1% do índice. <b>R²</b> é a parcela da variação do ativo que o índice explica. Os betas de alta e de queda separam os dias pelo sinal do índice.</p></details>
  ${sources.length?`<p class="date-source">${sources.map(s=>`${esc(s.label)}: ${esc(s.source)} · até ${dt(s.asof)} · <a href="${esc(s.source_url)}" target="_blank" rel="noreferrer">fonte ↗</a>`).join(' · ')}${info.retrieved_at?` · consultado em ${esc(when(info.retrieved_at))}`:''}</p>`:''}
  <div class="actions">${button('benchmarks-fetch',sources.length?'Atualizar Ibovespa e dólar (5 anos)':'Buscar Ibovespa e dólar (5 anos)','secondary')}${needHistory?pcFetchButtons(a):''}</div></section>`;
}

function priceContextRefresh(){
 $$('.price-context-panel').forEach(p=>{const html=priceContextPanel(assetById(p.dataset.id));if(html)p.outerHTML=html;});
 $$('.correlation-panel').forEach(p=>{const html=correlationPanel(assetById(p.dataset.id));if(html)p.outerHTML=html;});
}
detail=function(id){
 priceContextDetailBefore(id);
 const a=assetById(id),body=$('#modal-body');
 if(!a||!body||!['stock','fii','etf'].includes(a.asset_type))return;
 if(!$('.price-context-panel',body))body.insertAdjacentHTML('beforeend',priceContextPanel(a));
 if(!$('.correlation-panel',body))body.insertAdjacentHTML('beforeend',correlationPanel(a));
};
valuationView=function(){
 const html=priceContextPricesBefore(),a=S.assets.find(x=>x.ticker===valuationTicker),panel=priceContextPanel(a);
 return panel?html+`<section class="panel">${panel}</section>`:html;
};
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action]');if(!b)return;
 const action=b.dataset.action;
 if(action==='price-context-series'){priceContextSeries=b.dataset.series;priceContextRefresh();return;}
 if(!['price-context-history','price-context-monthly','benchmarks-fetch'].includes(action))return;
 const label=b.textContent;b.disabled=true;b.textContent='Buscando…';
 try{
  if(action==='price-context-history')await api('/api/history/fetch',{asset_id:Number(b.dataset.id),years:5});
  else if(action==='price-context-monthly')await api('/api/multiples/history',{asset_id:Number(b.dataset.id),force:true});
  else{const r=await api('/api/prices/benchmarks',{force:true});if(r.errors?.length)toast(r.errors.join(' · '));}
  await load(false);priceContextRefresh();toast('Histórico atualizado; indicadores recalculados.');
 }catch(ex){toast(ex.message);if(b.isConnected){b.disabled=false;b.textContent=label;}}
});
