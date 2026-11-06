'use strict';
const accessibilityRenderBefore=render;
let accessibilityFrame;
const accessibilityOriginals=new WeakMap();
function accessibleColor(hex){
 let s=hex.slice(1);if(s.length===3)s=[...s].map(x=>x+x).join('');
 const r=parseInt(s.slice(0,2),16)/255,g=parseInt(s.slice(2,4),16)/255,b=parseInt(s.slice(4,6),16)/255,max=Math.max(r,g,b),min=Math.min(r,g,b),delta=max-min;
 if(!delta)return hex;let hue=(max===r?(g-b)/delta+(g<b?6:0):max===g?(b-r)/delta+2:(r-g)/delta+4)*60;
 const positive=hue>=75&&hue<=175,negative=hue<=25||hue>=345;if(!positive&&!negative)return hex;
 const light=(max+min)/2,sat=delta/(1-Math.abs(2*light-1)),h=(positive?212:278)/60,c=(1-Math.abs(2*light-1))*sat,x=c*(1-Math.abs(h%2-1)),m=light-c/2;
 const rgb=h<4?[0,x,c]:[x,0,c];return '#'+rgb.map(v=>Math.round(255*(v+m)).toString(16).padStart(2,'0')).join('');
}
function accessibilityPaint(){
 const active=document.documentElement.dataset.colorMode==='accessible';
 for(const e of document.querySelectorAll('svg [fill],svg [stroke],[style*="#"]')){
  let fields=accessibilityOriginals.get(e);if(!fields){fields={};accessibilityOriginals.set(e,fields);}
  for(const attr of ['fill','stroke','style']){const current=e.getAttribute(attr);if(current==null)continue;let row=fields[attr];if(!row||current!==row.last)row=fields[attr]={original:current,last:current};
   const next=active?row.original.replace(/#[0-9a-f]{6}\b|#[0-9a-f]{3}\b/gi,accessibleColor):row.original;
   if(next!==current){row.last=next;e.setAttribute(attr,next);}
  }
 }
}
function accessibilityTheme(mode){document.documentElement.dataset.colorMode=mode;try{localStorage.setItem('aporte-color-mode',mode);}catch(_){}accessibilityPaint();}
try{accessibilityTheme(localStorage.getItem('aporte-color-mode')==='accessible'?'accessible':'standard');}catch(_){accessibilityTheme('standard');}
new MutationObserver(()=>{cancelAnimationFrame(accessibilityFrame);accessibilityFrame=requestAnimationFrame(accessibilityPaint);}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['fill','stroke','style']});
render=function(){accessibilityRenderBefore();if(!S?.settings)return;accessibilityTheme(S.settings.color_mode||'standard');if(document.body.classList.contains('vault-locked'))return;
 if(view==='settings')$('.page-heading')?.insertAdjacentHTML('afterend',`<section class="panel accessibility-panel"><h2>Cores e acessibilidade</h2><label class="check"><input id="accessible-mode" type="checkbox" ${S.settings.color_mode==='accessible'?'checked':''}>Modo daltônico · azul para positivo e roxo para negativo</label><p><span class="tag good">+ Positivo</span> <span class="tag bad">− Negativo</span> Sinais, textos e números acompanham as cores. Correlação positiva significa movimentos na mesma direção, não investimento melhor.</p><p id="accessibility-status" class="form-hint" role="status"></p></section>`);
};
document.addEventListener('change',async e=>{if(e.target.id!=='accessible-mode')return;
 const old=S.settings.color_mode||'standard',mode=e.target.checked?'accessible':'standard';S.settings.color_mode=mode;accessibilityTheme(mode);e.target.disabled=true;
 try{await api('/api/settings',{color_mode:mode});$('#accessibility-status').textContent='Preferência salva neste banco local.';}
 catch(ex){S.settings.color_mode=old;accessibilityTheme(old);e.target.checked=old==='accessible';toast(ex.message);}
 finally{e.target.disabled=false;}
});
