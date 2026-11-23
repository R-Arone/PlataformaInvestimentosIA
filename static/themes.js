'use strict';
(function(){
const KEY='aporte-theme';
const THEMES=[
 {id:'auto',name:'Automático',icon:'🖥️',group:'Sistema'},
 {id:'claro',name:'Claro',icon:'☀️',group:'Claros'},
 {id:'jade',name:'Jade',icon:'🌿',group:'Essenciais'},
 {id:'areia',name:'Areia',icon:'☀️',group:'Essenciais'},
 {id:'meia-noite',name:'Meia-noite',icon:'🌙',group:'Essenciais'},
 {id:'solarized-claro',name:'Solarized Claro',icon:'🌅',group:'Claros'},
 {id:'sepia',name:'Papel (sépia)',icon:'📜',group:'Claros'},
 {id:'noturno',name:'Noturno',icon:'🌙',group:'Escuros'},
 {id:'github-escuro',name:'GitHub Escuro',icon:'🐙',group:'Escuros'},
 {id:'dracula',name:'Dracula',icon:'🧛',group:'Escuros'},
 {id:'nord',name:'Nord',icon:'❄️',group:'Escuros'},
 {id:'tokyo-night',name:'Tokyo Night',icon:'🌃',group:'Escuros'},
 {id:'catppuccin',name:'Catppuccin',icon:'🐱',group:'Escuros'},
 {id:'gruvbox',name:'Gruvbox',icon:'🍂',group:'Escuros'},
 {id:'monokai',name:'Monokai',icon:'🎨',group:'Escuros'},
 {id:'solarized-escuro',name:'Solarized Escuro',icon:'🌊',group:'Escuros'},
 {id:'bloomberg',name:'Terminal Bloomberg',icon:'📈',group:'Profissionais'},
 {id:'wallstreet',name:'Wall Street',icon:'🏦',group:'Profissionais'},
 {id:'planilha',name:'Planilha verde',icon:'📊',group:'Profissionais'},
 {id:'maca',name:'Mac claro',icon:'🍎',group:'Profissionais'},
 {id:'retrowave',name:'Retrowave',icon:'🌆',group:'Divertidos'},
 {id:'fofo',name:'Fofo',icon:'🌸',group:'Divertidos'},
 {id:'matrix',name:'Matrix',icon:'🟩',group:'Divertidos'},
 {id:'ambar',name:'Terminal âmbar',icon:'📟',group:'Divertidos'},
 {id:'retro95',name:'Retrô 95',icon:'💾',group:'Divertidos'},
 {id:'cyberpunk',name:'Cyberpunk',icon:'🤖',group:'Bem diferentes'},
 {id:'neobrutalista',name:'Neobrutalista',icon:'🟨',group:'Bem diferentes'},
 {id:'vidro',name:'Vidro aurora',icon:'🔮',group:'Bem diferentes'},
 {id:'blueprint',name:'Blueprint',icon:'📐',group:'Bem diferentes'},
 {id:'gameboy',name:'Game Boy',icon:'🎮',group:'Bem diferentes'},
 {id:'jornal',name:'Jornal rosado',icon:'📰',group:'Bem diferentes'},
 {id:'halloween',name:'Halloween',icon:'🎃',group:'Bem diferentes'},
 {id:'floresta',name:'Floresta',icon:'🌲',group:'Bem diferentes'},
 {id:'windows-xp',name:'Windows XP',icon:'🪟',group:'Temáticos'},
 {id:'vaporwave',name:'Vaporwave',icon:'🌴',group:'Temáticos'},
 {id:'tron',name:'Tron',icon:'💠',group:'Temáticos'},
 {id:'lousa',name:'Lousa de giz',icon:'🧑‍🏫',group:'Temáticos'},
 {id:'hq-pop',name:'HQ pop art',icon:'💥',group:'Temáticos'},
 {id:'pergaminho',name:'Pergaminho medieval',icon:'🏰',group:'Temáticos'},
 {id:'espaco',name:'Espaço sideral',icon:'🚀',group:'Temáticos'},
 {id:'por-do-sol',name:'Pôr do sol',icon:'🌇',group:'Temáticos'},
 {id:'japao',name:'Japão zen',icon:'⛩️',group:'Temáticos'},
 {id:'steampunk',name:'Steampunk',icon:'⚙️',group:'Temáticos'},
 {id:'natalino',name:'Natalino',icon:'🎄',group:'Nostalgia e festas'},
 {id:'dos',name:'MS-DOS',icon:'💾',group:'Nostalgia e festas'},
 {id:'windows-7',name:'Windows 7 Aero',icon:'🪟',group:'Nostalgia e festas'},
 {id:'windows-8',name:'Windows 8 Metro',icon:'🟦',group:'Nostalgia e festas'},
 {id:'wii',name:'Nintendo Wii',icon:'🎮',group:'Nostalgia e festas'},
 {id:'c64',name:'Commodore 64',icon:'🕹️',group:'Nostalgia e festas'},
 {id:'orkut',name:'Orkut',icon:'💗',group:'Nostalgia e festas'},
 {id:'ubuntu',name:'Ubuntu',icon:'🟠',group:'Nostalgia e festas'},
 {id:'brasil',name:'Brasil',icon:'🇧🇷',group:'Nostalgia e festas'},
 {id:'verao',name:'Verão',icon:'🏖️',group:'Nostalgia e festas'},
 {id:'outlook',name:'Outlook',icon:'📧',group:'Apps famosos'},
 {id:'fintech',name:'Fintech roxo',icon:'💜',group:'Apps famosos'},
 {id:'musica',name:'Música verde',icon:'🎧',group:'Apps famosos'},
 {id:'mensageiro',name:'Mensageiro',icon:'💬',group:'Apps famosos'},
 {id:'ludico',name:'Lúdico 3D',icon:'🦉',group:'Apps famosos'},
 {id:'plataforma',name:'Plataforma 8-bit',icon:'🧱',group:'Mundos'},
 {id:'blocos',name:'Blocos',icon:'⛏️',group:'Mundos'},
 {id:'arcade',name:'Arcade CRT',icon:'👾',group:'Mundos'},
 {id:'postit',name:'Mural de post-its',icon:'📌',group:'Mundos'},
 {id:'caderno',name:'Caderno',icon:'📓',group:'Mundos'},
 {id:'carnaval',name:'Carnaval',icon:'🎭',group:'Mundos'},
 {id:'festa-junina',name:'Festa junina',icon:'🌽',group:'Mundos'},
 {id:'vscode',name:'Editor de código',icon:'🧑‍💻',group:'Softwares'},
 {id:'notion',name:'Notas minimalistas',icon:'📝',group:'Softwares'},
 {id:'winamp',name:'Player metálico',icon:'🎵',group:'Softwares'},
 {id:'cassino',name:'Cassino',icon:'🎰',group:'Fora da casinha'},
 {id:'faroeste',name:'Faroeste',icon:'🤠',group:'Fora da casinha'},
 {id:'painel-nave',name:'Painel de nave',icon:'🖖',group:'Fora da casinha'},
 {id:'art-deco',name:'Art déco dourado',icon:'🏛️',group:'Fora da casinha'},
 {id:'memphis',name:'Memphis anos 80',icon:'🔺',group:'Fora da casinha'},
 {id:'lofi',name:'Lo-fi noite de chuva',icon:'🌧️',group:'Fora da casinha'},
 {id:'rose-gold',name:'Rosé gold',icon:'💎',group:'Delicados'},
 {id:'wmp-xp',name:'Media player XP',icon:'📀',group:'Mídia e web antiga'},
 {id:'msn',name:'Messenger 2005',icon:'🧑‍🤝‍🧑',group:'Mídia e web antiga'},
 {id:'geocities',name:'Web anos 90',icon:'🌐',group:'Mídia e web antiga'},
 {id:'vhs',name:'Fita VHS',icon:'📼',group:'Mídia e web antiga'},
 {id:'jukebox',name:'Jukebox diner',icon:'🎶',group:'Mídia e web antiga'},
 {id:'runas',name:'Runas nórdicas',icon:'ᚱ',group:'Antigo e místico'},
 {id:'egito',name:'Egito antigo',icon:'𓂀',group:'Antigo e místico'},
 {id:'alquimia',name:'Alquimia',icon:'⚗️',group:'Antigo e místico'},
 {id:'rpg-menu',name:'Menu de RPG',icon:'⚔️',group:'Antigo e místico'},
 {id:'radar',name:'Radar sonar',icon:'📡',group:'Curiosos'},
 {id:'maquina-escrever',name:'Máquina de escrever',icon:'⌨️',group:'Curiosos'},
 {id:'azulejo',name:'Azulejo português',icon:'🔷',group:'Curiosos'},
 {id:'terminal',name:'Terminal fósforo verde',icon:'🖥️',group:'Texto e papel'},
 {id:'jornal-antigo',name:'Jornal antigo',icon:'🗞️',group:'Texto e papel'},
 {id:'formulario',name:'Formulário contínuo',icon:'🧾',group:'Texto e papel'},
 {id:'tela-azul',name:'Tela azul',icon:'😵',group:'Texto e papel'},
 {id:'preto-branco',name:'Preto e branco',icon:'◼️',group:'Preto e branco'},
 {id:'noir',name:'Film noir',icon:'🕵️',group:'Preto e branco'},
 {id:'alto-contraste',name:'Alto contraste',icon:'👁️',group:'Acessibilidade'}
];
const LIGHT=new Set(['claro','solarized-claro','sepia','fofo','retro95','neobrutalista','gameboy','jornal','planilha','maca','windows-xp','vaporwave','hq-pop','pergaminho','por-do-sol','japao','wii','windows-7','orkut','brasil','verao','outlook','fintech','mensageiro','ludico','plataforma','blocos','postit','caderno','festa-junina','notion','faroeste','memphis','egito','geocities','msn','jukebox','maquina-escrever','azulejo','jornal-antigo','preto-branco','formulario','rose-gold']);
LIGHT.add('jade').add('areia');
const known=id=>THEMES.some(t=>t.id===id);
const root=document.documentElement;
const dark=window.matchMedia?matchMedia('(prefers-color-scheme: dark)'):null;
const phone=matchMedia('(max-width: 760px), (max-width: 1000px) and (max-height: 520px) and (pointer: coarse)');
const essentials=['auto','jade','meia-noite','areia','alto-contraste'];
const defaultChoice=()=>phone.matches?'auto':'claro';
let savedChoice=null,choice=defaultChoice();
try{const saved=localStorage.getItem(KEY);if(saved&&known(saved))savedChoice=choice=saved;}catch(_){}
const resolve=id=>id==='auto'?(dark?.matches?(phone.matches?'meia-noite':'noturno'):(phone.matches?'jade':'claro')):id;
const info=id=>THEMES.find(t=>t.id===id)||THEMES[1];
function cssVar(name,fallback){const v=getComputedStyle(root).getPropertyValue(name).trim();return v||fallback;}
function iconSvg(){
 const bg=cssVar('--side-bg','#0c2135'),fg=cssVar('--mint','#56e6ad');
 return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="${bg}"/><path d="M8 24V17h4v7m3 0V12h4v12m3 0V7h4v17" stroke="${fg}" stroke-width="3" fill="none"/></svg>`;
}
function paintIcons(){
 const href='data:image/svg+xml,'+encodeURIComponent(iconSvg());
 let link=document.querySelector('link[rel~="icon"]');
 if(!link){link=document.createElement('link');link.rel='icon';document.head.appendChild(link);}
 if(link.getAttribute('href')!==href)link.setAttribute('href',href);
 for(const img of document.querySelectorAll('img[src$="favicon.svg"],img[data-themed-icon]')){img.dataset.themedIcon='1';if(img.getAttribute('src')!==href)img.setAttribute('src',href);}
 let meta=document.querySelector('meta[name="theme-color"]');
 if(!meta){meta=document.createElement('meta');meta.name='theme-color';document.head.appendChild(meta);}
 meta.content=cssVar('--bg','#f1f5f9');
}
function apply(id,{save=true,announce=false,animate=false}={}){
 if(!known(id))id='claro';
 choice=id;
 const real=resolve(id);
 if(animate&&!phone.matches){root.classList.add('theme-fade');setTimeout(()=>root.classList.remove('theme-fade'),400);}
 root.dataset.theme=real;
 root.dataset.tone=LIGHT.has(real)?'light':'dark';
 if(save){savedChoice=id;try{localStorage.setItem(KEY,id);}catch(_){}}
 paintIcons();
 refreshUi(announce);
}
/* ---------- interface ---------- */
let wrap,btn,menu,live,catalog;
const paletteSvg='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.8 1.8-1.7 0-.5-.2-.9-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1 .8-1.7 1.8-1.7H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10.5" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/></svg>';
function preview(id){return id==='auto'?'<span class="theme-pv theme-pv-auto" aria-hidden="true"><i></i><b><u></u><s></s></b></span>':`<span class="theme-pv" data-pv="${id}" aria-hidden="true"><i></i><b><u></u><s></s></b></span>`;}
function options(group,themes){
 const buttons=themes.map(t=>`<button type="button" class="theme-opt" role="radio" aria-checked="false" data-theme-id="${t.id}">${preview(t.id)}<span class="nm"><span class="ic" aria-hidden="true">${t.icon}</span>${t.name}<span class="ck" aria-hidden="true">✓</span></span></button>`).join('');
 return `<div class="theme-grid" role="radiogroup" aria-label="${group}">${buttons}</div>`;
}
function build(){
 wrap=document.createElement('div');wrap.className='theme-switch';wrap.id='theme-switch';
 btn=document.createElement('button');btn.type='button';btn.id='theme-btn';btn.className='button secondary theme-btn';
 btn.setAttribute('aria-haspopup','dialog');btn.setAttribute('aria-expanded','false');btn.setAttribute('aria-controls','theme-menu');
 btn.innerHTML=paletteSvg+'<span class="theme-label">Tema</span><span class="theme-current" aria-hidden="true"></span>';
 menu=document.createElement('div');menu.id='theme-menu';menu.className='theme-menu';menu.hidden=true;menu.setAttribute('role','dialog');menu.setAttribute('aria-label','Escolher aparência');
 const remaining=THEMES.filter(t=>!essentials.includes(t.id));
 const groups=[...new Set(remaining.map(t=>t.group))];
 menu.innerHTML=`<header class="theme-menu-heading"><h2>Aparência</h2><span class="theme-choice-name"></span></header>${options('Temas essenciais',essentials.map(info))}<details class="theme-catalog" ${phone.matches?'':'open'}><summary>Todos os temas</summary>${groups.map(group=>`<h2>${group}</h2>${options(group,remaining.filter(t=>t.group===group))}`).join('')}</details>`;
 catalog=menu.querySelector('.theme-catalog');
 live=document.createElement('div');live.className='sr-only';live.setAttribute('role','status');live.setAttribute('aria-live','polite');
 wrap.append(btn,menu,live);
 btn.addEventListener('click',()=>menu.hidden?open():close(true));
 menu.addEventListener('click',e=>{const o=e.target.closest('.theme-opt');if(o)apply(o.dataset.themeId,{announce:true,animate:true});});
 menu.addEventListener('keydown',e=>{
  if(!['ArrowRight','ArrowLeft','ArrowDown','ArrowUp'].includes(e.key))return;
  const opts=[...menu.querySelectorAll('.theme-opt')].filter(o=>o.getClientRects().length),i=opts.indexOf(document.activeElement);if(i<0)return;
  e.preventDefault();const step=e.key==='ArrowRight'||e.key==='ArrowDown'?1:-1;opts[(i+step+opts.length)%opts.length].focus();
 });
}
function mount(){
 const bar=document.querySelector('.header-actions');if(!bar||document.getElementById('theme-switch'))return;
 if(!wrap)build();
 const refresh=bar.querySelector('#refresh');
 refresh?bar.insertBefore(wrap,refresh):bar.appendChild(wrap);
 refreshUi(false);
 new MutationObserver(()=>{if(!document.getElementById('theme-switch'))bar.appendChild(wrap);}).observe(bar,{childList:true});
}
function open(){
 menu.hidden=false;btn.setAttribute('aria-expanded','true');
 const current=menu.querySelector('.theme-opt[aria-checked="true"]');
 (current?.getClientRects().length?current:menu.querySelector('.theme-opt')).focus({preventScroll:phone.matches});
 if(phone.matches)menu.scrollTop=0;
}
function close(focusBtn){if(!menu||menu.hidden)return false;menu.hidden=true;btn.setAttribute('aria-expanded','false');if(focusBtn)btn.focus();return true;}
function refreshUi(announce){
 if(!menu)return;
 for(const o of menu.querySelectorAll('.theme-opt'))o.setAttribute('aria-checked',String(o.dataset.themeId===choice));
 const t=info(choice);
 menu.querySelector('.theme-choice-name').textContent=t.name;
 btn.querySelector('.theme-current').textContent=t.icon;
 btn.title='Aparência: '+t.name;
 btn.setAttribute('aria-label','Aparência: '+t.name+'. Alterar tema');
 if(announce)live.textContent='Tema '+t.name+' aplicado.';
}
document.addEventListener('click',e=>{if(menu&&!menu.hidden&&!e.target.closest('#theme-switch'))close(false);});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&menu&&!menu.hidden){e.stopPropagation();close(true);}},true);
if(dark)(dark.addEventListener?dark.addEventListener.bind(dark,'change'):dark.addListener.bind(dark))(()=>{if(choice==='auto')apply('auto',{save:false});});
phone.addEventListener('change',()=>{if(catalog)catalog.open=!phone.matches;apply(savedChoice||defaultChoice(),{save:false});});
window.addEventListener('storage',e=>{if(e.key===KEY){savedChoice=known(e.newValue)?e.newValue:null;apply(savedChoice||defaultChoice(),{save:false});}});
apply(choice,{save:false});
const ready=()=>{mount();paintIcons();let q;new MutationObserver(()=>{cancelAnimationFrame(q);q=requestAnimationFrame(paintIcons);}).observe(document.body,{childList:true,subtree:true});};
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',ready):ready();
window.AporteTheme={apply:id=>apply(id,{animate:true}),current:()=>choice,list:()=>THEMES.map(t=>t.id),close:()=>close(true)};
})();
