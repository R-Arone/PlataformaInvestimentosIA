'use strict';
// One entry per task. Existing tools keep their routes and saved data.
const simpleBaseRender=render,simpleBaseBind=bindForms,simpleNews=newsView,simpleResult=longTermResult;
const simpleSections=[
 {id:'overview',icon:'◫',label:'Início',routes:['overview']},
 {id:'portfolio',icon:'▤',label:'Carteira',routes:['portfolio','income'],tabs:[['portfolio','Posições'],['income','Proventos']]},
 {id:'watchlist',icon:'◎',label:'Analisar ativos',routes:['watchlist','compare','sectors','prices','us','global'],tabs:[['watchlist','Minha lista'],['us','Stocks e BDRs'],['compare','Comparar']],tools:[['sectors','Setores e critérios'],['prices','Cenários de preço']]},
 {id:'long-term',icon:'◇',label:'Aportar',routes:['long-term','goals','rates','tesouro','fx','taxes'],tabs:[['long-term','Sugerir aporte'],['goals','Metas e limites']],tools:[['rates','Renda fixa'],['tesouro','Meus Tesouros'],['fx','Custo do dólar'],['taxes','Impostos por produto']]},
 {id:'news',icon:'◈',label:'Mercado',routes:['news','signals','crypto'],tools:[['signals','Modelos de IA'],['crypto','Bitcoin']]},
 {id:'settings',icon:'⚙',label:'Configurações',routes:['settings','imports','sources'],tabs:[['settings','Preferências e backup'],['imports','Importar dados'],['sources','Fontes e atualização']]}
];
let simpleFilters={query:'',type:'',market:'',ownership:'all',sector:''},simpleCompareIds=null;
const simpleMarket=a=>a.asset_type==='foreign'?'US':['global_stock','global_etf'].includes(a.asset_type)?(a.international?.listing.market==='US'?'US':'GLOBAL'):'BR';
const simpleMarketLabel=a=>({BR:'Brasil · B3 / Bitcoin',US:'Estados Unidos',GLOBAL:'Outras bolsas'}[simpleMarket(a)]);
const simpleFold=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR');
const simpleViewLink=(id,label,cls='secondary')=>`<button type="button" class="button ${cls}" data-view="${id}">${esc(label)}</button>`;

function simpleNavigation(){
 const section=simpleSections.find(s=>s.routes.includes(view))||simpleSections[0],nav=$('#sidebar nav');
 nav.innerHTML=simpleSections.map(s=>`<button type="button" data-view="${s.id}" class="${s===section?'active':''}" ${s===section?'aria-current="page"':''}><span aria-hidden="true">${s.icon}</span>${s.label}</button>`).join('');
 navItems.splice(0,navItems.length,...simpleSections.map(s=>[s.id,s.icon,s.label]));
 $('#task-navigation')?.remove();
 if(!section.tabs&&!section.tools)return;
 const links=items=>items.map(([id,label])=>`<button type="button" data-view="${id}" class="${id===view?'selected':''}" ${id===view?'aria-current="page"':''}>${esc(label)}</button>`).join('');
 const html=`<div id="task-navigation" class="task-navigation" role="navigation" aria-label="Opções de ${esc(section.label)}">${section.tabs?`<div class="task-tabs">${links(section.tabs)}</div>`:''}${section.tools?`<details class="task-tools" ${section.tools.some(([id])=>id===view)?'open':''}><summary>${section.id==='long-term'?'Simuladores':section.id==='news'?'Ferramentas avançadas':'Ferramentas de análise'}</summary><div>${links(section.tools)}</div></details>`:''}</div>`;
 const heading=$('#main > .page-heading');if(heading)heading.insertAdjacentHTML('afterend',html);else $('#main').insertAdjacentHTML('afterbegin',html);
}

overview=function(){
 const t=totals(),stale=S.assets.filter(a=>!a.snapshots.quote||age(a.snapshots.quote.asof)>7).length;
 return page('Início','Seu patrimônio e os próximos passos, em um só lugar.')+refreshNotice()+
 `<div class="cards">${card('Patrimônio acompanhado',money(t.total),'Cotações disponíveis e saldos informados','feature')}${card('Posições na carteira',t.held.length+S.fixed.length,'Ativos negociados, fundos e títulos')}${card('Ativos para acompanhar',S.assets.length,stale?stale+' cotação(ões) a atualizar':'Cotações com referência recente')}</div>
 <section class="panel"><h2>O que você quer fazer agora?</h2><div class="task-cards"><article><h3>Decidir o próximo aporte</h3><p>Informe o dinheiro novo e compare qualidade, preço e contrafluxo.</p>${simpleViewLink('long-term','Sugerir meu aporte','')}</article><article><h3>Analisar um investimento</h3><p>Encontre ações, FIIs e ETFs na mesma lista e abra a análise do ativo.</p>${simpleViewLink('watchlist','Analisar minha lista')}</article><article><h3>Conferir minhas posições</h3><p>Veja saldos, operações e proventos já registrados.</p>${simpleViewLink('portfolio','Abrir carteira')}</article></div></section>
 ${t.unknown||t.stale?`<section class="notice warn">Há posições sem cotação recente ou avaliadas pelo custo. Confira as referências antes de decidir um aporte. ${simpleViewLink('sources','Conferir atualização')}</section>`:''}`;
};

function simpleAssetStatus(a){
 const study=a.fii_research?.study||a.company_research?.study,quality=study||a.company_research;
 if(quality)return tag(quality.label||'Conferir análise',quality.status==='within'?'good':quality.status==='review'?'warn':'');
 return tag(['etf','global_etf'].includes(a.asset_type)?'Índice e composição':a.asset_type==='crypto'?'Preço e exposição':'Dados a completar');
}

function simpleAssets(){
 return S.assets.filter(a=>(!simpleFilters.query||simpleFold(a.ticker+' '+a.name+' '+a.sector).includes(simpleFold(simpleFilters.query)))&&
  (!simpleFilters.type||a.asset_type===simpleFilters.type)&&(!simpleFilters.market||simpleMarket(a)===simpleFilters.market)&&
  (!simpleFilters.sector||a.sector===simpleFilters.sector)&&(simpleFilters.ownership==='all'||(simpleFilters.ownership==='held')===(a.position.quantity>0)));
}

function simpleAssetRows(){
 const rows=simpleAssets();
 return `<p class="form-hint">${rows.length} de ${S.assets.length} ativo(s) · a análise completa fica em Ver análise. ${simpleFilters.query||simpleFilters.type||simpleFilters.market||simpleFilters.sector||simpleFilters.ownership!=='all'?button('simple-reset','Limpar filtros','text-button'):''}</p>${rows.length?`<div class="table-wrap"><table class="simple-assets-table"><thead><tr><th>Ativo</th><th>Tipo / mercado</th><th>Análise</th><th>Cotação em reais</th><th>Minha posição</th><th></th></tr></thead><tbody>${rows.map(a=>`<tr><td><b>${esc(a.ticker)}</b><small>${esc(a.name)}</small><small>${esc(a.sector)}</small></td><td data-label="Tipo / mercado">${esc(typeLabel(a))}<small>${esc(simpleMarketLabel(a))}</small></td><td data-label="Análise">${simpleAssetStatus(a)}</td><td data-label="Cotação em reais">${money(a.metrics.price)}<small>${dt(a.snapshots.quote?.asof)}${a.snapshots.quote&&age(a.snapshots.quote.asof)>7?' · atualizar':''}</small></td><td data-label="Minha posição">${a.position.quantity>0?`${money(a.value)}<small>${fmt(a.position.quantity,8)} unidade(s)${a.value_at_cost?' · pelo custo':''}</small>`:tag('Acompanhando')}</td><td>${button('detail','Ver análise','secondary',`data-id="${a.id}"`)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="notice">Nenhum ativo neste filtro. Ajuste os filtros ou adicione um investimento à sua lista.</p>'}`;
}

watchlist=function(){
 return page('Analisar ativos','Uma lista para ações, FIIs, ETFs, Bitcoin e investimentos no exterior.',button('simple-add','Adicionar ativo',''))+refreshNotice()+
 `<section class="panel"><form id="simple-filter-form" class="simple-filter-form"><div class="form-grid">${field('query','Buscar ativo',simpleFilters.query,'search','placeholder="Ticker, nome ou setor"')}${select('type','Tipo de investimento',[['','Todos os tipos'],...Object.entries(S.asset_types)],simpleFilters.type)}${select('market','Mercado da negociação',[['','Todos os mercados'],['BR','Brasil / Bitcoin'],['US','Estados Unidos'],['GLOBAL','Outras bolsas']],simpleFilters.market)}${select('ownership','Minha posição',[['all','Carteira + acompanhamento'],['held','Só os que tenho'],['watch','Só acompanhamento']],simpleFilters.ownership)}${select('sector','Setor / tema',[['','Todos os setores'],...[...new Set(S.assets.map(a=>a.sector))].sort().map(s=>[s,s])],simpleFilters.sector)}</div></form><div id="simple-assets-result">${simpleAssetRows()}</div></section><details class="panel simple-fold"><summary>Organizar setores e critérios</summary><p>Os critérios e a análise são os mesmos em qualquer caminho de acesso ao ativo.</p><div class="actions">${button('choose-sectors','Setores de interesse','secondary')}${button('sector-rules','Ajustar critérios por setor','secondary')}${simpleViewLink('sectors','Exposição e pares por setor')}</div></details>`;
};

function simpleComparisonAssets(){
 if(simpleCompareIds===null)simpleCompareIds=S.assets.slice(0,2).map(a=>a.id);
 return simpleCompareIds.map(id=>assetById(id)).filter(Boolean);
}

compare=function(){
 const assets=simpleComparisonAssets();
 const cell=(a,key)=>key==='price'?money(a.metrics.price):key==='reference'?money(a.valuation?.suggestion?.value):
  key==='ceiling'?money(a.valuation?.suggestion?.ceiling):key==='pe'?multiple(a.metrics.pe):key==='pvp'?multiple(a.metrics.pvp):simpleAssetStatus(a);
 return page('Comparar ativos','Veja os mesmos dados lado a lado. A prioridade de aporte fica em Aportar.',button('simple-compare','Escolher ativos',''))+
 `<section class="panel">${assets.length?`<div class="table-wrap"><table class="simple-comparison"><thead><tr><th>Informação</th>${assets.map(a=>`<th>${esc(a.ticker)}<small>${esc(typeLabel(a))}</small></th>`).join('')}</tr></thead><tbody>${[['price','Cotação em reais'],['status','Qualidade / situação'],['reference','Referência condicional de valor'],['ceiling','Teto com margem de segurança'],['pe','P/L'],['pvp','P/VP']].map(([key,label])=>`<tr><th>${label}</th>${assets.map(a=>`<td>${cell(a,key)}</td>`).join('')}</tr>`).join('')}<tr><th>Análise completa</th>${assets.map(a=>`<td>${button('detail','Ver análise','secondary',`data-id="${a.id}"`)}</td>`).join('')}</tr></tbody></table></div><p class="form-hint">${assets.length<2?'Escolha pelo menos dois ativos para comparar. ':''}Campos sem referência aplicável ficam vazios. P/L e critérios de empresas não se aplicam a todos os produtos; confira tipo, setor, fonte e data na análise.</p>`:'<p>Adicione ativos à sua lista para começar a comparar.</p>'}</section>`;
};

sectorView=function(){
 return page('Setores e critérios','Exposição da carteira, referências de mercado e comparação de pares.',button('sector-rules','Ajustar critérios',''))+
 sectorCharts()+benchmarkPanel()+peerPanel()+`<p class="notice">A análise de cada empresa ou fundo fica na lista única de ativos. ${simpleViewLink('watchlist','Voltar à minha lista')}</p>`;
};

goalsView=function(){
 const a=S.allocation;
 return page('Metas e limites','Defina as referências usadas no seu próximo aporte.')+
 `<div class="grid-two"><section class="panel"><h2>Distribuição atual</h2><div class="card-value">${money(a.total)}</div>${allocationBars()}<p class="form-hint">Barra: peso atual · traço: sua meta. ${a.issues.length?'Há saldos ou classificações a revisar.':''}</p></section><section class="panel"><h2>Minhas metas por classe</h2><form id="goals-form"><div class="form-grid">${Object.entries(S.allocation_classes).map(([key,label])=>numField('goal_'+key,label+' (%)',S.settings.allocation_targets?.[key]??'','required min="0" max="100"')).join('')}</div><p id="goals-sum" class="form-hint">${a.has_targets?'Total: 100%':'Preencha as metas; a soma precisa ser 100%.'}</p><div class="form-error" role="alert"></div><button type="submit" class="button">Salvar minhas metas</button></form></section></div>
 <section class="panel"><h2>Limites de concentração</h2><p>${pct(S.settings.asset_limit)} por emissor e ${pct(S.settings.sector_limit)} por setor da carteira negociada.</p><div class="actions">${simpleViewLink('settings','Ajustar meus limites')}${simpleViewLink('long-term','Voltar à sugestão de aporte','')}</div></section>
 <details class="panel simple-fold"><summary>Conferir a classe de cada investimento</summary><p>A classificação orienta suas metas. Para fundos e ETFs, confira a composição.</p><form id="class-form"><div class="classification-list">${a.items.map(r=>`<div><b>${esc(r.name)}</b><small>${r.held?'Na carteira':'Acompanhando'} · ${money(r.value)}</small>${select(r.key,'Classe de '+r.name,Object.entries(S.allocation_classes),r.class)}</div>`).join('')}</div><div class="form-error" role="alert"></div><button class="button" type="submit">Salvar classificação</button></form></details>`;
};

// Every checklist entry opens the same dossier, including old shortcuts.
riskDetail=function(id){const a=assetById(id);if(a?.company_research)companyTabs.set(a.id,'company');detail(id);};

function simpleWrap(node,title,{open=false,moveTo=null}={}){
 if(!node||node.closest('.simple-fold'))return null;
 const details=document.createElement('details');details.className='panel simple-fold';details.open=open;
 const summary=document.createElement('summary');summary.textContent=title;details.append(summary);
 node.before(details);details.append(node);if(moveTo)moveTo.append(details);return details;
}

function simpleNewsLayout(root){
 const heading=$('.page-heading',root);if(heading){root.prepend(heading);$('h1',heading).textContent='Mercado';$('.page-heading p',root).textContent='Notícias e contexto para acompanhar as suas decisões.';}
 for(const [selector,label] of [['.hourly-monitor','Alertas e acompanhamento'],['.ai-dashboard','Leitura das notícias com IA'],['.ai-chatgpt','Trazer uma pesquisa externa'],['.ai-lab','Simular cenários com IA'],['.scenario-panel','Premissas do cenário econômico'],['.exposure-panel','Conferir exposições dos investimentos']]){
  simpleWrap($(selector,root),label,{open:selector==='.ai-dashboard'&&!!S.ai.job.running,moveTo:root});
 }
 for(const panel of $$('.panel',root)){
  if(panel.closest('.simple-fold'))continue;
  const h=$('h2',panel)?.textContent||'';
  if(/Aprofundar no ChatGPT|Trazer a análise para o aplicativo/.test(h))simpleWrap(panel,h,{moveTo:root});
 }
 for(const grid of $$('.grid-two',root))if(grid.children.length===1)grid.classList.add('single-column');
}

newsView=function(){const template=document.createElement('template');template.innerHTML=simpleNews();simpleNewsLayout(template.content);return template.innerHTML;};

function simpleContribution(root){
 const form=$('#long-term-form',root);if(!form)return;
 const grid=$('.form-grid',form),advanced=document.createElement('details');advanced.className='simple-advanced';
 advanced.innerHTML='<summary>Ajustar destinos, mínimo por compra e critérios</summary><div class="form-grid"></div>';
 const target=$('.form-grid',advanced);
 for(const name of ['universe','max_assets','min_ticket','min_coverage','signal_horizon']){const item=form.elements[name]?.closest('.field');if(item)target.append(item);}
 const aiTools=document.createElement('div');aiTools.className='actions simple-ai-tools';
 for(const selector of ['[data-action=long-term-ai-refresh]','[data-view=signals]']){const b=$(selector,form);if(b)aiTools.append(b);}
 advanced.append(aiTools);
 for(const note of $$('.form-hint',form))if(note.textContent.startsWith('Com IA válida')||note.textContent.startsWith('Atualizar IA busca'))advanced.append(note);
 grid.after(advanced);
 simpleAIMode(form);
 const panel=form.closest('section'),heading=$('.page-heading',root);heading?.after(panel);
 const strategy=$$('h2',root).find(h=>h.textContent==='Como você quer escolher?');
 simpleWrap(strategy?.closest('section'),'Entender as estratégias de aporte',{moveTo:root});
 const areas=$('.exposure-area-map',root);if(areas){areas.open=false;root.append(areas);}
}

function simpleAIMode(form){const tools=$('.simple-ai-tools',form),advanced=$('.simple-advanced',form),actions=$('button[type=submit]',form)?.closest('.actions');if(!tools||!actions)return;(form.elements.mode.value==='context'?actions:advanced).append(tools);}

function simpleSessionControls(){
 const restart=$('#restart-vault'),exit=$('#exit-vault');if(!restart&&!exit)return;
 let menu=$('#app-session-menu');
 if(!menu){menu=document.createElement('details');menu.id='app-session-menu';menu.className='app-session-menu';menu.innerHTML='<summary>Aplicativo</summary><div class="app-session-choices"></div>';$('.header-actions').append(menu);}
 for(const b of [restart,exit])if(b)$('.app-session-choices',menu).append(b);
}

longTermResult=function(p){
 const template=document.createElement('template');template.innerHTML=simpleResult(p);const root=template.content;
 const buttons=$$('[data-action=long-term-scenario]',root),comparisons=buttons[0]?.closest('.long-term-comparisons');
 if(comparisons){const title=comparisons.previousElementSibling?.previousElementSibling,description=comparisons.previousElementSibling;
  const content=document.createElement('div');comparisons.before(content);if(title?.tagName==='H3')content.append(title);if(description?.tagName==='P')content.append(description);content.append(comparisons);simpleWrap(content,'Comparar outras divisões do aporte');}
 const classTable=$('table',root)?.closest('.table-wrap');if(classTable&&$('thead',classTable)?.textContent.includes('Classe'))simpleWrap(classTable,'Conferir distribuição por classe');
 const eligibleSection=$$('.panel',root).find(n=>$('h2',n)?.textContent==='Lista de prioridades');
 if(eligibleSection){const cards=$$('.long-term-candidate',eligibleSection),funded=new Set(p.candidates.filter(r=>r.amount>0).map(r=>String(r.id))),rest=cards.filter((c,i)=>funded.size?!funded.has(c.dataset.recommendationId):i>=3);
  if(rest.length){const group=document.createElement('div');rest[0].before(group);rest.forEach(c=>group.append(c));simpleWrap(group,'Outros ativos elegíveis ('+rest.length+')');}}
 return template.innerHTML;
};

function simpleTidy(){
 const root=$('#main');
 if(view==='watchlist'){
  const f=$('#simple-filter-form'),d=document.createElement('details');d.className='simple-advanced';
  d.innerHTML='<summary>'+simpleFilterLabel()+'</summary><div class="form-grid"></div>';
  for(const name of ['market','ownership','sector'])$('.form-grid',d).append(f.elements[name].closest('.field'));
  f.append(d);
 }
 if(view==='long-term')simpleContribution(root);
 if(view==='portfolio'){
  for(const panel of $$('.panel',root)){const title=$('h2',panel)?.textContent||'';
   if(title.startsWith('Fundos e títulos removidos')){panel.remove();continue;}
   if(panel.classList.contains('coupling-panel'))simpleWrap(panel,'Diversificação e movimentos da carteira');
   else if(['Por instituição','Por tipo'].includes(title))simpleWrap(panel,'Distribuição '+title.toLocaleLowerCase('pt-BR'));}
 }
 if(view==='signals'){$$('.coupling-panel',root).forEach(n=>n.remove());root.insertAdjacentHTML('beforeend',`<p class="notice">A diversificação e a correlação das suas posições ficam em Carteira. ${simpleViewLink('portfolio','Conferir minha carteira')}</p>`);}
 if(view==='settings'){
  const title=$('.page-heading h1',root);if(title)title.textContent='Configurações';
  if(S.archived_assets.length||S.archived_fixed.length)root.insertAdjacentHTML('beforeend',`<details class="panel simple-fold"><summary>Investimentos removidos</summary><p>Você pode restaurar os registros e seu histórico.</p>${S.archived_assets.map(a=>`<div class="mini-stat"><span>${esc(a.ticker)} · ${esc(a.name)}</span>${button('restore-asset','Restaurar','secondary',`data-id="${a.id}"`)}</div>`).join('')}${S.archived_fixed.map(f=>`<div class="mini-stat"><span>${esc(f.name)}</span>${button('restore-fixed','Restaurar','secondary',`data-id="${f.id}"`)}</div>`).join('')}</details>`);
 }
}

render=function(){
 if(!S)return simpleBaseRender();
 if(view==='global'){simpleFilters.market=view==='us'?'US':'GLOBAL';view='watchlist';history.replaceState(null,'','#watchlist');}
 simpleBaseRender();if(!S||document.body.classList.contains('vault-locked'))return;
 simpleTidy();simpleNavigation();simpleSessionControls();
};

function simpleFilterLabel(){const count=Number(!!simpleFilters.market)+Number(!!simpleFilters.sector)+Number(simpleFilters.ownership!=='all');return 'Mais filtros'+(count?' · '+count+' ativo(s)':'');}
bindForms=function(){simpleBaseBind();const mode=$('#long-term-form [name=mode]');if(mode&&!mode.dataset.simpleBound){mode.dataset.simpleBound='true';mode.addEventListener('change',()=>simpleAIMode(mode.form));}const f=$('#simple-filter-form');if(f&&!f.dataset.bound){f.dataset.bound='true';f.addEventListener('submit',e=>e.preventDefault());
 const update=()=>{const next=formData(f);if(Object.keys(next).every(k=>next[k]===simpleFilters[k]))return;simpleFilters=next;$('#simple-assets-result').innerHTML=simpleAssetRows();const summary=$('details > summary',f);if(summary)summary.textContent=simpleFilterLabel();};f.addEventListener('input',update);f.addEventListener('change',update);}};

document.addEventListener('invalid',e=>{const d=e.target.closest('details');if(d)d.open=true;},true);
document.addEventListener('click',e=>{const b=e.target.closest('[data-action]');if(!b)return;
 if(b.dataset.action==='simple-reset'){simpleFilters={query:'',type:'',market:'',ownership:'all',sector:''};render();}
 if(b.dataset.action==='simple-add')modal('Adicionar à minha lista',`<p>Escolha onde o investimento é negociado. Todos aparecem na mesma lista.</p><div class="task-cards"><article><h3>Brasil</h3><p>Ações, FIIs, ETFs, BDRs e Bitcoin.</p>${button('asset','Escolher ativo','')}</article><article><h3>Estados Unidos</h3><p>Stocks e ETFs negociados nos EUA.</p>${button('us-add','Cadastrar nos EUA','')}</article><article><h3>Outras bolsas</h3><p>Stocks internacionais e ETFs globais.</p>${button('global-add','Cadastrar no exterior','')}</article></div>`);
 if(b.dataset.action==='simple-compare'){
  const chosen=new Set(simpleComparisonAssets().map(a=>a.id));
  modal('Escolher ativos para comparar',`<form id="simple-compare-form"><p>Escolha de dois a seis ativos da sua lista.</p><div class="comparison-choices">${S.assets.map(a=>`<label class="check"><input type="checkbox" name="asset_${a.id}" value="${a.id}" ${chosen.has(a.id)?'checked':''}> ${esc(a.ticker)} · ${esc(a.name)}</label>`).join('')}</div>${footer('Comparar ativos')}</form>`);
  wireForm('#simple-compare-form',async(d,f)=>{const ids=$$('input:checked',f).map(i=>Number(i.value));if(ids.length<2||ids.length>6)throw Error('Escolha entre dois e seis ativos.');simpleCompareIds=ids;$('#modal').close();render();});
 }
});

// Replace the former full sidebar as soon as all feature modules are loaded.
simpleNavigation();
