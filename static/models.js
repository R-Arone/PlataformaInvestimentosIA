'use strict';
const comparisonOriginalSignalsView=signalsView,comparisonOriginalBind=bindForms;
let comparisonSelection={market:'US',horizon:'126',ticker:'',origin:''};
let comparisonData=null,comparisonResultKey='',comparisonLoadingKey='',comparisonEpoch=0;
const comparisonClasses=['Ficar atrás da cesta','Acompanhar a cesta','Superar a cesta'];
const comparisonName=id=>({frequency:'Referência',lgb_company:'LightGBM',tabpfn:'TabPFN',bayes_company:'Bayes',average_two:'Média 50/50'}[id]||id);
const comparisonPct=value=>pct(value==null?null:value*100);
const comparisonKey=()=>JSON.stringify({...comparisonSelection,average:S?.settings?.model_average_enabled===true});
function comparisonField(name,label,options,value,disabled=false){
 return `<div class="field"><label for="comparison-${name}">${esc(label)}</label><select id="comparison-${name}" name="${name}" ${disabled?'disabled':''}>${options.map(([v,t])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(t)}</option>`).join('')}</select></div>`;
}
function comparisonControls(data){
 const options=data?.status==='ready'?data.options:null;
 return `<form id="model-comparison-filters"><div class="form-grid">${comparisonField('market','Mercado',[['US','Estados Unidos'],['BR','Brasil']],comparisonSelection.market)}${comparisonField('horizon','Prazo do teste',[['126','6 meses · 126 pregões'],['252','12 meses · 252 pregões']],comparisonSelection.horizon)}${comparisonField('ticker','Empresa da amostra',(options?.tickers||[]).map(t=>[t,t+(S.assets.some(a=>a.ticker===t)?' · na sua lista':'')]),comparisonSelection.ticker,!options)}${comparisonField('origin','Data da previsão histórica',(options?.origins||[]).map(d=>[d,dt(d)]),comparisonSelection.origin,!options)}</div><label class="check-line"><input id="comparison-average" type="checkbox" name="average" ${S.settings.model_average_enabled===true?'checked':''}> Exibir combinação experimental · média 50/50 de LightGBM e TabPFN</label><p class="form-hint">Esta preferência fica salva. A combinação usa o mesmo teste histórico e não dispara alertas.</p></form>`;
}
function comparisonBars(p){
 let x=0;return `<svg class="comparison-stack" viewBox="0 0 180 7" aria-hidden="true">${p.map((v,i)=>{const left=x;x+=v*180;return `<rect class="comparison-class-${i}" x="${left}" y="0" width="${v*180}" height="7"></rect>`;}).join('')}</svg>`;
}
function comparisonEfficacy(history){
 const rows=history.models.filter(r=>r.model!=='frequency');
 const max=Math.max(1,...rows.map(r=>Math.abs(r.brier_skill*100)));
 const accessible='Redução de erro frente à referência. '+rows.map(r=>comparisonName(r.model)+': '+pct(r.brier_skill*100)).join('; ');
 return `<div class="comparison-efficacy" role="img" aria-label="${esc(accessible)}">${rows.map(r=>{const v=r.brier_skill*100,w=Math.abs(v)/max*90;return `<div class="comparison-error-row"><span>${esc(comparisonName(r.model))}</span><svg class="comparison-error-track" viewBox="0 0 200 18" preserveAspectRatio="none" aria-hidden="true"><rect class="comparison-track-background" x="0" y="0" width="200" height="18"></rect><line class="comparison-zero" x1="100" x2="100" y1="0" y2="18"></line><rect class="comparison-error-bar ${v<0?'loss':'gain'}" x="${v<0?100-w:100}" y="0" width="${w}" height="18"></rect></svg><b>${v>0?'+':''}${pct(v)}</b></div>`;}).join('')}<div class="comparison-error-axis"><span>Mais erro</span><span>0 · referência</span><span>Menos erro</span></div></div>`;
}
function comparisonBody(data){
 if(data.status!=='ready')return `<div class="notice" role="status">${esc(data.reason||'Comparativo indisponível.')}</div>`;
 const f=data.forecast,c=data.company,h=data.history,a=h.agreement,g=data.current_agreement;
 const status=g.status==='agree'?`Concordam em ${comparisonClasses[g.class].toLowerCase()}`:g.status==='disagree'?'As classes indicadas divergem':'Sem classe única nos dois modelos';
 const sector={banks:'Bancos',steel:'Siderurgia',mining:'Mineração',technology:'Tecnologia'}[c.sector]||c.sector;
 const group=g.status==='agree'?a.agree_by_predicted_class.find(r=>r.class===g.class):null;
 const matched=group?.count?`${group.correct}/${group.count} acertos em ${group.dates} datas quando ambos indicaram essa classe.`:'Sem classe em comum nesta previsão.';
 const intervals=h.paired_differences.map(r=>`<tr><td>${esc(comparisonName(r.model))}</td><td>${esc(comparisonName(r.reference))}</td><td>${fmt(r.mean_difference,4)}</td><td>${r.ci95?`${fmt(r.ci95[0],4)} a ${fmt(r.ci95[1],4)}`:'Poucas datas'}</td></tr>`).join('');
 return `<div class="comparison-case"><div><h3>${esc(c.ticker)} · ${esc(sector)}</h3><p class="form-hint">Previsão de ${dt(f.origin)} · entrada do teste ${dt(f.entry_date)} · resultado em ${dt(f.target_date)}</p></div>${tag('Histórico · resultado já conhecido')}</div><div class="table-wrap"><table class="comparison-probabilities"><caption class="sr-only">Previsões históricas para ${esc(c.ticker)}, em ${dt(f.origin)}. Probabilidades por classe.</caption><thead><tr><th>Modelo</th><th>Ficar atrás</th><th>Acompanhar</th><th>Superar</th><th>Classe indicada</th></tr></thead><tbody>${f.models.map(r=>`<tr><td><b>${esc(r.label)}</b>${comparisonBars(r.probabilities)}</td>${r.probabilities.map(p=>`<td>${comparisonPct(p)}</td>`).join('')}<td>${r.class===null?'Sem classe única':esc(comparisonClasses[r.class])}</td></tr>`).join('')}</tbody></table></div><p class="comparison-note"><b>Resultado observado:</b> ${esc(f.observed_label)}.</p><div class="notice comparison-agreement"><b>LightGBM ↔ TabPFN: ${esc(status)}</b><p>${esc(matched)}</p><small>Distância entre as probabilidades: ${comparisonPct(g.probability_distance)}. Vai de 0% (iguais) a 100% (sem sobreposição); não representa chance de acerto.</small></div><p class="form-hint">Classes relativas à cesta de seis ações do país. “Acompanhar” usa retorno relativo entre −5% e +5%; a cotação pode oscilar. As probabilidades são experimentais.</p><div class="comparison-history"><h3>Como se saíram neste mercado e prazo?</h3><p class="form-hint">${h.count} observações · ${h.dates} datas de decisão · ${esc(h.tickers.join(', '))}. O histórico abaixo reúne todas essas empresas, independentemente da empresa selecionada acima.</p>${comparisonEfficacy(h)}<p class="form-hint">Redução do erro de probabilidades; valores positivos são melhores. Estes percentuais não medem rentabilidade.</p><div class="table-wrap"><table><thead><tr><th>Modelo</th><th>Erro de probabilidades (Brier)</th><th>Resultados</th><th>Diferença de calibração*</th></tr></thead><tbody>${h.models.map(r=>`<tr><td>${esc(comparisonName(r.model))}</td><td>${fmt(r.brier,4)}</td><td>${r.count}</td><td>${comparisonPct(r.class_calibration_error)}</td></tr>`).join('')}</tbody></table></div><p class="form-hint">*Distância média entre probabilidades previstas e frequências observadas, em grupos de 20 pontos percentuais. Menor é melhor; poucos resultados não demonstram calibração.</p><div class="comparison-agreement-totals"><div><span>Concordaram</span><b>${a.agree_count}/${a.eligible_unique_predictions} · ${comparisonPct(a.agree_rate)}</b></div><div><span>Acertaram quando concordaram</span><b>${a.agree_correct_count}/${a.agree_count} · ${comparisonPct(a.accuracy_when_agree)}</b></div><div><span>Erraram juntos na mesma classe</span><b>${a.same_class_both_wrong_count} casos</b></div></div><div class="table-wrap"><table><thead><tr><th>Classe em que concordaram</th><th>Casos</th><th>Datas</th><th>Acertos observados</th></tr></thead><tbody>${a.agree_by_predicted_class.map(r=>`<tr><td>${esc(comparisonClasses[r.class])}</td><td>${r.count}</td><td>${r.dates}</td><td>${r.count?`${r.correct}/${r.count} · ${comparisonPct(r.correct/r.count)}`:'Sem casos'}</td></tr>`).join('')}</tbody></table></div><p class="form-hint">Concordância e acerto usam denominadores diferentes. Empates são excluídos da concordância (${a.ambiguous_count} neste cenário). Uma taxa geral não é a chance de acerto de uma indicação de “superar”.</p><details><summary>Erros compartilhados e faixas de incerteza</summary><p>Correlação dos erros de Brier: ${fmt(a.brier_error_correlation,2)}. Valores positivos indicam erros que variam juntos. Concordância ajustada pelo acaso (kappa): ${fmt(a.cohen_kappa,2)}. Estes diagnósticos não medem independência das empresas.</p><div class="table-wrap"><table><thead><tr><th>Modelo</th><th>Comparador</th><th>Diferença de Brier</th><th>Faixa exploratória de 95%</th></tr></thead><tbody>${intervals}</tbody></table></div><p class="form-hint">Diferença negativa significa menos erro. Faixas que cruzam zero são inconclusivas. Bootstrap por blocos de duas datas, mantendo empresas da mesma data juntas; sem ajuste para múltiplas comparações.</p></details></div><details class="comparison-company"><summary>Dados da empresa conhecidos na origem</summary><p><b>${esc(c.ticker)} · ${esc(sector)}</b><br>Balanço de ${dt(c.period)} · disponível para este teste em ${dt(c.available)}.</p><div class="table-wrap"><table><thead><tr><th>Indicador usado</th><th>Valor histórico</th></tr></thead><tbody>${c.metrics.map(r=>`<tr><td>${esc(r.label)}</td><td>${r.value==null?'Não disponível / não aplicado ao setor':comparisonPct(r.value)}</td></tr>`).join('')}</tbody></table></div><p class="form-hint">Lucro e caixa operacional usam os últimos 12 meses; ativos e patrimônio usam o fim do período. Os indicadores não são uma nota automática de saúde financeira. Capital regulatório, inadimplência e provisões não entraram neste teste de bancos.</p></details><details><summary>O que usar em cada caso e limites do teste</summary><p>LightGBM com empresa é o primeiro candidato de pesquisa para stocks americanos em seis meses. TabPFN permite comparar tabelas com pesos prontos. No Brasil e em doze meses, a vantagem dos candidatos ainda não é consistente. A média 50/50 não superou o melhor modelo isolado nos quatro cenários observados.</p><p>Para valor justo no longo prazo: fluxo de caixa por cenários em empresas operacionais, lucro residual em bancos e resultados normalizados pelo ciclo em mineradoras e siderúrgicas. Essa avaliação responde a uma pergunta diferente das classes de desempenho relativo.</p>${data.limitations.map(t=>`<p class="form-hint">${esc(t)}</p>`).join('')}<p class="form-hint">Dados do teste até ${dt(data.asof)}. A lista da amostra não é a sua carteira. Abrir este painel não baixa dados nem treina modelos.</p></details>`;
}
function modelComparisonPanel(){
 const data=comparisonResultKey===comparisonKey()?comparisonData:null;
 return `<section class="panel model-comparison-panel" id="long-model-comparison"><div class="panel-head"><div><span class="eyebrow">EFICÁCIA E CONCORDÂNCIA EM 6 E 12 MESES</span><h2>Modelos com dados da empresa</h2></div>${tag('Teste histórico')}</div><p>Compare LightGBM, TabPFN e Bayes nas previsões históricas que testamos. As datas abaixo pertencem ao experimento; esta seção não apresenta sinais atuais de compra ou venda.</p><div id="model-comparison-controls">${comparisonControls(data)}</div><div id="model-comparison-status" role="status" aria-live="polite"></div><div id="model-comparison-content">${data?comparisonBody(data):'<p class="muted">Carregando o comparativo histórico…</p>'}</div></section>`;
}
function comparisonPaint(data){
 const content=$('#model-comparison-content'),controls=$('#model-comparison-controls');if(!content||!controls)return;
 const active=document.activeElement?.id;
 controls.innerHTML=comparisonControls(data);content.innerHTML=comparisonBody(data);
 if(active?.startsWith('comparison-'))document.getElementById(active)?.focus();
}
async function comparisonLoad(force=false){
 if(view!=='signals'||!$('#long-model-comparison'))return;
 const key=comparisonKey();if(!force&&(key===comparisonResultKey||key===comparisonLoadingKey))return;
 const epoch=++comparisonEpoch;comparisonLoadingKey=key;
 $('#model-comparison-status').textContent='Carregando a seleção do teste…';
 $('#model-comparison-content').setAttribute('aria-busy','true');
 try{
  const query=new URLSearchParams(comparisonSelection);const data=await api('/api/models/comparison?'+query.toString());
  if(epoch!==comparisonEpoch)return;
  if(data.status==='ready'){comparisonSelection={...data.selection};S.settings.model_average_enabled=data.average_enabled;}
  comparisonData=data;comparisonResultKey=comparisonKey();
  if(view==='signals')comparisonPaint(data);
  const status=$('#model-comparison-status');if(status)status.textContent='';
 }catch(ex){
  if(epoch!==comparisonEpoch)return;const status=$('#model-comparison-status');
  if(status){status.textContent=ex.message;status.append(document.createElement('br'));const retry=document.createElement('button');retry.type='button';retry.className='button secondary';retry.dataset.action='model-comparison-retry';retry.textContent='Tentar novamente';status.append(retry);}
  const content=$('#model-comparison-content');if(content)content.innerHTML='<p class="muted">A seleção não foi carregada. Tente novamente para conferir as previsões.</p>';
 }finally{if(epoch===comparisonEpoch){comparisonLoadingKey='';$('#model-comparison-content')?.removeAttribute('aria-busy');}}
}
signalsView=function(){return comparisonOriginalSignalsView()+modelComparisonPanel();};
bindForms=function(){comparisonOriginalBind();if(view==='signals'){
 const actions=$('.page-heading .actions');if(actions&&!actions.querySelector('[data-action="model-comparison-jump"]'))actions.insertAdjacentHTML('beforeend',button('model-comparison-jump','Modelos de longo prazo','secondary'));
 comparisonLoad();
}};
document.addEventListener('submit',e=>{if(e.target.id==='model-comparison-filters')e.preventDefault();});
document.addEventListener('change',async e=>{
 if(e.target.form?.id!=='model-comparison-filters')return;
 const name=e.target.name;
 if(name==='average'){
  const old=S.settings.model_average_enabled===true,value=e.target.checked;e.target.disabled=true;++comparisonEpoch;comparisonLoadingKey='';
  try{await api('/api/settings',{model_average_enabled:value});S.settings.model_average_enabled=value;comparisonData=null;comparisonResultKey='';const content=$('#model-comparison-content');if(content)content.innerHTML='<p class="muted">Atualizando a preferência da combinação…</p>';await comparisonLoad(true);toast(value?'Média experimental habilitada.':'Média experimental desabilitada.');}
  catch(ex){e.target.checked=old;toast(ex.message);}finally{e.target.disabled=false;}
  return;
 }
 if(!['market','horizon','ticker','origin'].includes(name))return;
 comparisonSelection[name]=e.target.value;
 if(['market','horizon'].includes(name)){comparisonSelection.ticker='';comparisonSelection.origin='';}
 if(name==='ticker')comparisonSelection.origin='';
 await comparisonLoad(true);
});
document.addEventListener('click',e=>{if(e.target.closest('[data-action="model-comparison-retry"]'))comparisonLoad(true);if(e.target.closest('[data-action="model-comparison-jump"]'))$('#long-model-comparison')?.scrollIntoView({block:'start'});});
