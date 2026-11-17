'use strict';
// Fixed-income calculator: value at maturity, tax, real return and comparison with inflation, Selic and CDI.
const fixedIncomeRatesBefore=rates,fixedIncomeBindBefore=bindForms;
let fixedIncomeResult=null;
const fiPct=v=>v==null?'—':fmt(v)+'% a.a.';
const fiYear=v=>v==null?'—':fmt(v)+'% ao ano';
const fiSign=v=>v==null?'—':(v>0?'+':'')+money(v);
const fiMacro=k=>S.macro?.[k]?.value??'';

function fixedIncomeForm(){
 const products=(S.tax_references||[]).filter(r=>r.automatic).map(r=>r.product);
 const savedConditions=(S.fixed||[]).filter(f=>f.indexer!=='Manual'&&f.rate_known&&f.conditions_known).map(f=>[String(f.id),f.name]);
 const asof=['cdi','selic','ipca'].map(k=>S.macro?.[k]?.asof).filter(Boolean).sort().pop();
 return `<section class="panel" id="fixed-income-panel"><h2>Calculadora: valor no vencimento, inflação e juros</h2>
  <p class="section-intro">Informe o investimento e as premissas de juros e inflação. A calculadora mostra o saldo líquido no vencimento, o poder de compra, a comparação com CDI, Selic, poupança e inflação, e cenários com juros mais baixos e mais altos.</p>
  <form id="fixed-income-form"><div class="form-grid">
   ${select('saved_fixed','Usar condição de um investimento registrado',[['','Condição personalizada'],...savedConditions])}
   ${numField('principal','Valor investido (R$)',10000,'min="0.01" required')}
   ${numField('months','Prazo (meses)',24,'min="1" max="600" step="1"')}
   ${field('maturity','Ou data de vencimento','','date')}
   ${select('product','Produto / regime fiscal',[...products,['','Outro · informar o IR']],'CDB')}
   ${numField('tax','IR personalizado sobre o ganho (%)',15,'min="0" max="100" disabled')}
   ${select('indexer','Indexador',['CDI','Selic','IPCA+','Prefixado'],'CDI')}
   ${numField('rate','Taxa: % do CDI, ou adicional / prefixado a.a.',100,'min="-50" max="1000" required')}
   ${numField('fee','Custo anual (%)',0,'min="0" max="100"')}
  </div>
  <h3>Premissas de juros e inflação</h3>
  <p class="form-hint">Os valores de hoje vêm do Banco Central${asof?` (até ${dt(asof)})`:''}. Informe também o valor ao final do prazo para testar queda ou alta dos juros: a taxa varia em linha reta, mês a mês, do valor de hoje até o final. Sem valor final, a taxa fica constante. São premissas suas, não previsões.</p>
  <div class="form-grid">
   ${numField('cdi','CDI hoje (% a.a.)',fiMacro('cdi'),'min="-99"')}${numField('cdi_end','CDI ao final do prazo (% a.a.)','','min="-99"')}
   ${numField('selic','Selic hoje (% a.a.)',fiMacro('selic'),'min="-99"')}${numField('selic_end','Selic ao final do prazo (% a.a.)','','min="-99"')}
   ${numField('ipca','Inflação hoje (IPCA 12 meses, % a.a.)',fiMacro('ipca'),'min="-99"')}${numField('ipca_end','Inflação ao final do prazo (% a.a.)','','min="-99"')}
  </div>
  <div class="form-error" role="alert"></div><button class="button" type="submit">Calcular</button></form>
  <div id="fixed-income-result" aria-live="polite">${fixedIncomeResult?fixedIncomeOutput(fixedIncomeResult):'<div class="chart-empty">Informe as condições e calcule.</div>'}</div></section>`;
}

function fiChart(points){
 const series=[['net','Saldo líquido','#008965',''],['real','Poder de compra','#0c2135','6 4'],['cdi_net','100% do CDI líquido','#8a9aab','2 3']].filter(([k])=>points.some(p=>p[k]!=null));
 if(points.length<2||!series.length)return '';
 const W=640,H=240,padL=62,padR=14,padT=26,padB=34,values=points.flatMap(p=>series.map(([k])=>p[k]).filter(v=>v!=null)),lo=Math.min(...values),hi=Math.max(...values),spread=hi-lo||Math.abs(hi)*.01||1,last=points[points.length-1].month||1;
 const x=m=>padL+m/last*(W-padL-padR),y=v=>H-padB-(v-lo)/spread*(H-padT-padB);
 const lines=series.map(([k,,color,dash])=>`<polyline fill="none" stroke="${color}" stroke-width="2.4" ${dash?`stroke-dasharray="${dash}"`:''} points="${points.filter(p=>p[k]!=null).map(p=>x(p.month).toFixed(1)+','+y(p[k]).toFixed(1)).join(' ')}"/>`).join('');
 const summary=series.map(([k,name])=>`${name}: ${money(points[points.length-1][k])}`).join('; ');
 return `<figure class="fi-chart"><svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Saldos ao longo de ${fmt(last,0)} meses. Ao final, ${esc(summary)}"><line x1="${padL}" y1="${H-padB}" x2="${W-padR}" y2="${H-padB}" stroke="#dce5ed"/><line x1="${padL}" y1="${padT}" x2="${padL}" y2="${H-padB}" stroke="#dce5ed"/>${lines}
  <text x="${padL-6}" y="${padT+4}" text-anchor="end">${esc(money(hi))}</text><text x="${padL-6}" y="${H-padB}" text-anchor="end">${esc(money(lo))}</text><text x="${padL}" y="${H-10}">hoje</text><text x="${W-padR}" y="${H-10}" text-anchor="end">${fmt(last,0)} meses</text></svg>
  <figcaption class="fi-legend">${series.map(([,name,color,dash])=>`<span><i style="background:${color}"></i>${esc(name)}</span>`).join('')}</figcaption></figure>`;
}

function fixedIncomeOutput(r){
 const b=r.balances,rate=r.rates,real=r.real,inf=r.inflation,eq=r.equivalence||{},ref=r.tax_reference||{};
 const stats=[['Saldo líquido no vencimento',money(b.net),'positive'],['Ganho líquido',money(b.net_gain),b.net_gain>=0?'positive':'negative'],['Rentabilidade líquida',fiPct(rate.net_annual),''],
  [`IR (${fmt(b.tax_rate)}% sobre o ganho)`,money(b.tax),''],
  ['Poder de compra no vencimento (valores de hoje)',real?money(real.value):'—',''],['Ganho real',real?`${fiSign(real.gain)} · ${fiPct(real.annual)}`:'—',real?(real.beats?'positive':'negative'):'']];
 const bench=r.benchmarks.length?`<h3>Comparação no mesmo prazo</h3><div class="table-wrap"><table class="pc-table"><thead><tr><th>Referência</th><th>Saldo líquido</th><th>Rentabilidade líquida</th><th>Este investimento vs. referência</th><th></th></tr></thead><tbody>${r.benchmarks.map(x=>`<tr><th scope="row">${esc(x.label)}</th><td>${money(x.net)}</td><td>${fiPct(x.net_annual)}</td><td>${fiSign(x.product_minus)}</td><td>${tag(x.beats?'À frente':'Atrás',x.beats?'good':'bad')}</td></tr>`).join('')}</tbody></table></div>`:'';
 const scen=r.scenarios.length?`<h3>Cenários de juros e inflação</h3><div class="table-wrap"><table class="pc-table"><thead><tr><th>Cenário</th><th>CDI final</th><th>Selic final</th><th>Inflação final</th><th>Saldo líquido</th><th>Rent. líquida</th><th>Poder de compra</th><th>Ganho real</th></tr></thead><tbody>${r.scenarios.map(s=>`<tr><th scope="row">${esc(s.label)}</th><td>${fiPct(s.cdi_end)}</td><td>${fiPct(s.selic_end)}</td><td>${fiPct(s.ipca_end)}</td><td>${money(s.net)}</td><td>${fiPct(s.net_annual)}</td><td>${s.real==null?'—':money(s.real)}</td><td>${fiPct(s.real_annual)}</td></tr>`).join('')}${r.expected?`<tr class="fi-expected"><th scope="row">Valor esperado <small>(pesos ${Object.values(r.expected.weights).map(w=>fmt(w*100,0)+'%').join(' / ')} para juros menores, informado e maiores)</small></th><td colspan="3"></td><td>${money(r.expected.net)}</td><td>${fiPct(r.expected.net_annual)}</td><td>${r.expected.real==null?'—':money(r.expected.real)}</td><td>${fiPct(r.expected.real_annual)}</td></tr>`:''}</tbody></table></div><p class="form-hint">Os cenários mudam o valor final de CDI e Selic em 3 pontos percentuais e a inflação em 2 pontos. Os pesos do valor esperado são uma premissa de exemplo, não uma probabilidade estimada.</p>`:'';
 const equivalence=[
  eq.cdb_gross_annual!=null?`<li>Para render o mesmo saldo líquido, um CDB tributado a ${fmt(eq.cdb_rate)}% teria de pagar <b>${fiPct(eq.cdb_gross_annual)}</b>${eq.cdb_pct_cdi!=null?` (cerca de ${fmt(eq.cdb_pct_cdi,0)}% do rendimento acumulado do CDI no período)`:''}. Um CDB de 100% do CDI rende mais que este investimento se o CDI médio do período ficar acima desse valor.</li>`:'',
  eq.breakeven_inflation_annual!=null?`<li>O ganho real zera se a inflação média do período chegar a <b>${fiYear(eq.breakeven_inflation_annual)}</b>.</li>`:'',
  inf?`<li>Inflação acumulada nas premissas: <b>${fmt(inf.cumulative)}%</b> (${fiPct(inf.annual)}).</li>`:''].filter(Boolean);
 return `<h3>Resultado até ${dt(r.maturity)} · ${fmt(r.months,1)} meses (${r.days} dias)</h3>
  <p>${tag(r.inputs.product)} ${tag(r.inputs.indexer==='CDI'?fmt(r.inputs.rate,0)+'% do CDI':r.inputs.indexer==='Prefixado'?'Prefixado '+fmt(r.inputs.rate)+'% a.a.':r.inputs.indexer+' + '+fmt(r.inputs.rate)+'% a.a.')} ${real?tag(real.beats?'Supera a inflação':'Perde para a inflação',real.beats?'good':'bad'):''}</p>
  ${stats.map(([l,v,c])=>`<div class="mini-stat"><span>${esc(l)}</span><b class="${c}">${v}</b></div>`).join('')}
  ${fiChart(r.points)}${bench}${scen}
  ${equivalence.length?`<ul class="pc-readings">${equivalence.join('')}</ul>`:''}
  ${r.warnings.length?`<div class="notice warn"><ul>${r.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div>`:''}
  <p class="form-hint">${esc(ref.rule||'')} ${esc(ref.note||'')} ${ref.source?`<a href="${esc(ref.source)}" target="_blank" rel="noreferrer">Fonte oficial ↗</a>`:''}</p>
  <details><summary>Como é calculado e o que não está incluído</summary><p>${esc(r.method)}</p><p>${esc(r.not_included)}</p></details>`;
}

rates=function(){
 const html=fixedIncomeRatesBefore(),marker='<section class="panel"><div class="panel-head"><h2>Investimentos registrados',panel=fixedIncomeForm();
 return html.includes(marker)?html.replace(marker,()=>panel+marker):html+panel;
};
bindForms=function(){
 fixedIncomeBindBefore();
 wireForm('#fixed-income-form',async d=>{
  const manual=d.product==='',payload={...d,product:manual?'CDB':d.product,tax_mode:manual?'manual':'auto'};
  delete payload.saved_fixed;
  fixedIncomeResult=await api('/api/fixed/analyze',payload);
  $('#fixed-income-result').innerHTML=fixedIncomeOutput(fixedIncomeResult);
 });
};
document.addEventListener('change',e=>{
 const form=e.target.form;if(!form||form.id!=='fixed-income-form')return;
 const set=(name,value)=>{const el=$(`[name=${name}]`,form);if(el)el.value=value;};
 if(e.target.name==='product')$('[name=tax]',form).disabled=e.target.value!=='';
 if(e.target.name==='indexer')set('rate',e.target.value==='CDI'?100:e.target.value==='Prefixado'?12:e.target.value==='IPCA+'?6:0);
 if(e.target.name==='saved_fixed'){
  const f=(S.fixed||[]).find(x=>String(x.id)===e.target.value);if(!f)return;
  set('indexer',f.indexer);set('rate',f.rate);set('fee',f.fee);set('product','');set('tax',f.tax);$('[name=tax]',form).disabled=false;
 }
});
