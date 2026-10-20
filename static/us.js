'use strict';
const usRender=render,usBind=bindForms,usInternational=internationalForm;
let usHorizon='5',usTicker='',usTimer;
const usdMoney=v=>v==null?'—':new Intl.NumberFormat('pt-BR',{style:'currency',currency:'USD'}).format(v);
const usStatus={candidate:'Priorizar análise de compra',contrary:'Sinais contrários',mixed:'Revisar divergências',unknown:'Completar dados'};

function usView(){
 const assets=S.assets.filter(a=>a.asset_type==='foreign');
 const candidates=S.us_market.candidates[usHorizon];
 const running=S.ai.job.running||S.signals.job.running;
 const rows=candidates.filter(r=>!usTicker||r.ticker===usTicker);
 return page('Stocks dos EUA','Acompanhe empresas americanas e compare candidatos para pesquisar uma compra.',button('us-add','Adicionar stock'))+`
 <section class="panel">
  <h2>Modelos preparados para o mercado americano</h2>
  <div class="grid-two signal-models">
   <article><h3>FinBERT-Tone · textos financeiros em inglês</h3><p>Já treinado com relatórios 10-K/10-Q, transcrições de resultados e relatórios de analistas. Lê o tom das notícias da empresa; não prevê o preço.</p><small>${S.us_market.prepared?'Pesos salvos nesta máquina.':'Primeiro uso baixa cerca de 440 MB.'} <a href="https://huggingface.co/yiyanghkust/finbert-tone" target="_blank" rel="noreferrer">Modelo e pesquisa ↗</a></small></article>
   <article><h3>Chronos-2, incremental e bayesiano · USD</h3><p>Chronos-2 usa pesos prontos de um modelo geral de séries temporais. O incremental aprende separadamente com cada stock e seus pares americanos, conforme os resultados se realizam. O teste bayesiano abaixo estima probabilidades com histórico e setores.</p><small>O desempenho na bolsa americana ainda precisa de avaliação. Selic e notícias brasileiras não são tratados como contexto dos EUA.</small></article>
  </div>
  <form id="us-analysis-form">
   <div class="form-grid">${select('ticker','Stock a analisar',[['','Todos os stocks · até 40'],...assets.map(a=>[a.ticker,a.ticker+' · '+a.name])],usTicker)}${select('horizon','Horizonte exibido',[['1','1 pregão após a referência'],['5','5 pregões após a referência'],['20','20 pregões após a referência']],usHorizon)}</div>
   <div class="form-error" role="alert"></div>
   <div class="actions"><button type="submit" class="button" ${running?'disabled':''}>Comparar modelos de preço</button>${button('us-news','Analisar notícias em inglês','secondary',running?'disabled':'')}${button('us-refresh','Atualizar mercado','secondary',S.job.running?'disabled':'')}</div>
  </form>
  <p class="form-hint">Dados diários em USD. Fechamento de hoje entra após 16h30 de Nova York, respeitando o horário de verão. Atualize os dados, consulte as notícias e depois compare os modelos. O contexto textual começa nas observações futuras, sem reconstruir notícias antigas.</p>
  <div class="notice" role="status">${esc(S.signals.job.running?S.signals.job.progress:S.ai.job.running?S.ai.job.progress:S.signals.job.error||S.ai.job.error||'Escolha as empresas que deseja acompanhar.')}</div>
 </section>
 <section class="panel"><div class="panel-head"><h2>Candidatos para análise de compra · ${usHorizon} pregão(ões)</h2>${tag('Experimental')}</div>
  <p>A prioridade organiza sua pesquisa. Confira resultados, caixa, dívida, preço do negócio e tamanho da posição antes de escolher uma compra.</p>
  <div class="table-wrap"><table><thead><tr><th>Stock / preços</th><th>Prioridade de pesquisa</th><th>Chronos-2 · USD</th><th>Incremental</th><th>Notícias em inglês</th><th>Motivos e pendências</th></tr></thead><tbody>
  ${rows.map(r=>{
   const a=assets.find(a=>a.ticker===r.ticker),q=a.us.quote,s=a.us.sentiment,brl=a.snapshots.quote;
   const signal=S.signals.rows.find(x=>x.ticker===r.ticker),h=signal?.horizons?.[usHorizon];
   return `<tr><td><button class="ticker-btn" data-action="detail" data-id="${a.id}">${esc(a.ticker)}</button><small>${esc(a.name)}<br>${usdMoney(q?.data?.price)} · ${dt(q?.asof)}${a.us.quote_stale?' · revisar':''}<br>Referência da carteira: ${money(a.metrics.price)}${brl?'<br>Referência BRL: '+dt(brl.asof):''}${brl?.data?.fx_rate?'<br>Câmbio usado: '+fmt(brl.data.fx_rate,4)+' R$/US$ · '+dt(brl.data.fx_asof):''}</small><button class="button secondary" data-action="us-history" data-id="${a.id}">Histórico de 5 anos</button></td>
    <td>${tag(usStatus[r.status],r.status==='candidate'?'good':r.status==='contrary'?'warn':'')}<small>Índice ${r.priority}/100 · não é chance de alta</small></td>
    <td>${signalCell(h?.pretrained,'pretrained',signal?.stale)}<small>Referência ${dt(r.asof)}</small></td><td>${signalCell(h?.incremental,'incremental',signal?.stale)}</td>
    <td>${s?.count?`${tag({positive:'Tom positivo',negative:'Tom negativo',neutral:'Sem tom dominante',unknown:'Amostra insuficiente'}[s.tone]||'Sem base')}<small>${s.count} títulos · ${s.publishers} veículos<br>${dt(s.analyzed_at)}${s.stale?' · atualizar':''}</small>`:'<small>Ainda não analisadas</small>'}</td>
    <td>${r.reasons.map(t=>`<p>${esc(t)}</p>`).join('')}<details><summary>Conferir antes de comprar</summary>${r.pending.map(t=>`<p>${esc(t)}</p>`).join('')}</details>${s?.items?.length?`<details><summary>Notícias e fontes</summary>${s.items.map(n=>`<p><a href="${esc(n.url)}" target="_blank" rel="noreferrer">${esc(n.title)}</a><small>${esc(n.publisher)} · ${dt(n.published_at)}</small></p>`).join('')}</details>`:''}</td></tr>`;
  }).join('')||'<tr><td colspan="6">Adicione os tickers que deseja comparar, como AAPL, MSFT ou AMZN. Nenhuma posição de exemplo é criada.</td></tr>'}
  </tbody></table></div>
  <details><summary>Como a prioridade é calculada</summary><p>${esc(S.us_market.method)}</p><p>Esta tabela compara somente sua lista. Não varre todas as bolsas, não determina valor justo e não executa ordens.</p></details>
 </section>
 ${bayesianPanel('US',usTicker,usHorizon)}<section class="panel"><h2>USD na análise, reais na sua carteira</h2><p>Cotações e históricos americanos são separados dos dados brasileiros. Uma cotação USD pode ser convertida com o câmbio BCB disponível, mostrando as duas referências. Custos, compras e vendas do registro atual continuam em BRL: use os valores convertidos do extrato.</p><p>O acoplamento da carteira continua mostrando cobertura parcial. Stocks em USD exigem câmbio histórico antes de serem comparados em reais; o câmbio de hoje não é aplicado aos retornos antigos. Balanços americanos e valuation não são importados automaticamente nesta etapa.</p></section>`;
}

function usForm(){
 modal('Adicionar stock dos EUA',`<form id="us-stock-form"><p>Informe o ticker negociado nos EUA. O cadastro entra na lista de acompanhamento; compras e quantidades são registradas separadamente.</p><div class="form-grid">${field('ticker','Ticker americano','','text','required maxlength="9" placeholder="AAPL, MSFT, AMZN ou BRK-B"').replaceAll('f-ticker','us-stock-ticker')}${field('name','Nome da empresa (opcional)','','text','maxlength="150"')}${select('sector','Setor / tema',S.sectors,'Tecnologia')}${textarea('notes','Tese e pontos para conferir','','maxlength="5000"')}</div>${footer('Adicionar à lista')}</form>`);
 wireForm('#us-stock-form',async d=>{
  d.ticker=d.ticker.trim().toUpperCase();
  if(!/^[A-Z]{1,6}(?:[.-][A-Z]{1,2})?$/.test(d.ticker))throw Error('Informe um ticker dos EUA, como AAPL ou BRK-B.');
  const r=await api('/api/assets',{...d,name:d.name.trim()||d.ticker,asset_type:'foreign',financial:false});
  $('#modal').close();await load();await refresh(r.id);toast('Stock adicionado à lista; consultando dados públicos dos EUA.');
 });
}

navItems.splice(navItems.findIndex(x=>x[0]==='signals'),0,['us','US','Stocks dos EUA']);
$('nav').innerHTML=navItems.map(([id,icon,label])=>`<button data-view="${id}"><span>${icon}</span>${id==='news'?'Notícias, IA e cenários':label}</button>`).join('');
render=function(){
 if(view!=='us')return usRender();if(!S)return;
 $$('nav button').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);b.setAttribute('aria-current',b.dataset.view===view?'page':'false');});
 $('#main').innerHTML=usView();bindForms();
};
async function usPoll(){
 clearTimeout(usTimer);
 try{await load(false);if(view==='us')render();clearTimeout(usTimer);if(S.ai.job.running||S.signals.job.running)usTimer=setTimeout(usPoll,2000);else toast(S.ai.job.error||S.signals.job.error||'Análise concluída; confira os resultados.');}
 catch(e){toast(e.message);}
}
bindForms=function(){
 usBind();if(view!=='us')return;
 wireForm('#us-analysis-form',async d=>{usTicker=d.ticker;await api('/api/signals/analyze',{ticker:d.ticker,market:'US',pretrained:true});await usPoll();});
 clearTimeout(usTimer);if(S.ai.job.running||S.signals.job.running)usTimer=setTimeout(usPoll,2000);
};
document.addEventListener('change',e=>{if(e.target.form?.id!=='us-analysis-form')return;if(e.target.name==='horizon')usHorizon=e.target.value;if(e.target.name==='ticker')usTicker=e.target.value;render();});
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action]');if(!b)return;
 try{switch(b.dataset.action){
  case 'us-add':usForm();break;
  case 'us-news':await api('/api/ai/us-sentiment',{ticker:usTicker});await usPoll();break;
  case 'us-refresh':await refresh();break;
  case 'us-history':b.disabled=true;await api('/api/history/fetch',{asset_id:Number(b.dataset.id),years:5});await load();toast('Histórico americano salvo; compare os modelos novamente.');break;
 }}catch(e){b.disabled=false;toast(e.message);}
});
internationalForm=function(id){usInternational(id);const intro=$('.section-intro',$('#modal-body'));if(intro)intro.textContent='Stocks dos EUA podem usar cotações e históricos automáticos em USD na página própria. Operações, custos e cotações manuais desta carteira continuam em reais.';const hint=$('.form-hint',$('#modal-body'));if(hint)hint.textContent='BDRs puxam a cotação em reais da B3 ao salvar e pelo botão Atualizar mercado. Stocks confirmados nos EUA têm comparação própria em dólares. Custos e operações seguem em reais, separados do ranking brasileiro.';};
