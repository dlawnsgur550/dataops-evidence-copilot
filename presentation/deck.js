'use strict';
(() => {
  const data=window.DECK, $=id=>document.getElementById(id);
  const slides=[...document.querySelectorAll('.slide')];
  const presenter=new URLSearchParams(location.search).get('presenter')==='1';
  const stamp=n=>String(Math.floor(n/60)).padStart(2,'0')+':'+String(Math.floor(n%60)).padStart(2,'0');
  let index=Math.max(0,Math.min(slides.length-1,(Number(location.hash.replace('#slide-',''))||1)-1));
  let guard='fake_evidence',recovery='new_run',clock={elapsed:0,startedAt:null},channel=null;
  let down=null;
  try { if(location.protocol!=='file:' && 'BroadcastChannel' in window) channel=new BroadcastChannel('dataops-presentation-v1'); } catch (_) {}
  const elapsed=()=>clock.elapsed+(clock.startedAt===null?0:Math.max(0,(Date.now()-clock.startedAt)/1000));
  const state=()=>({index,guard,recovery,clock});
  const publish=()=>channel?.postMessage({type:'state',value:state()});
  const announce=text=>{$('announcement').textContent=text;};
  function showGuard() {
    const g=data.guards[guard];
    $('guard-input').textContent=g.input; $('guard-code').textContent=g.code;
    $('guard-verdict').textContent=g.verdict; $('guard-verdict').className='verdict '+g.tone;
    $('guard-detail').textContent=g.detail;
    document.querySelectorAll('[data-guard]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.guard===guard)));
  }
  function showRecovery() {
    const r=data.recovery[recovery];
    $('recovery-verdict').textContent=r.verdict; $('recovery-verdict').className='verdict '+r.tone;
    $('recovery-detail').textContent=r.detail;
    document.querySelectorAll('[data-recovery]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.recovery===recovery)));
    document.querySelector('.aggregate').hidden=recovery==='same_run';
  }
  function tick(){
    const n=elapsed(); $('timer').textContent=stamp(n)+' / 05:00';
    $('timer').classList.toggle('over',n>data.total);
    $('start-timer').textContent=clock.startedAt===null?(clock.elapsed?'타이머 계속':'타이머 시작'):'일시정지';
  }
  function show(next,send=true) {
    index=Math.max(0,Math.min(slides.length-1,next));
    const s=data.slides[index];
    slides.forEach((el,i)=>{el.hidden=i!==index;});
    $('prev').disabled=index===0; $('next').disabled=index===slides.length-1;
    $('jump').value=String(index);
    const viewURL=new URL(location.href);
    if(presenter)viewURL.searchParams.delete('presenter');else viewURL.searchParams.set('presenter','1');
    viewURL.hash='#slide-'+(index+1);$('presenter').href=viewURL.href;
    $('source').href=s.source;
    $('time-range').textContent=stamp(s.start)+'–'+stamp(s.end)+' · '+s.duration+'초';
    $('planned-time').textContent='권장 '+stamp(s.start)+'–'+stamp(s.end);
    $('cue').textContent='화면 동작: '+s.cue;
    $('script').replaceChildren(...s.notes.split('\n\n').map(t=>{const p=document.createElement('p');p.textContent=t;return p;}));
    $('next-slide').textContent=index+1<slides.length?'다음: '+data.slides[index+1].title:'마지막 장표 · 질의응답';
    document.title=(index+1)+' / '+slides.length+' · '+s.title+' · DataOps';
    const hash='#slide-'+(index+1);
    if(location.hash!==hash) {
      try{history.replaceState(null,'',hash);}catch(_){location.hash=hash;}
    }
    announce((index+1)+' / '+slides.length+' · '+s.title);
    showGuard();showRecovery();tick();
    if(send) publish();
  }
  data.slides.forEach((s,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=(i+1)+' / '+slides.length+' · '+s.title;$('jump').append(o);});
  document.body.classList.toggle('presenter-mode',presenter);
  $('speaker-notes').hidden=!presenter;
  $('presenter').textContent=presenter?'청중 창 열기':'발표자 보기';
  $('prev').addEventListener('click',()=>show(index-1));
  $('next').addEventListener('click',()=>show(index+1));
  $('jump').addEventListener('change',e=>show(Number(e.target.value)));
  $('fullscreen').addEventListener('click',async()=>{
    try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}
    catch(_){announce('전체 화면 전환이 지원되지 않습니다. 브라우저 창을 확대하세요.');}
  });
  $('print').addEventListener('click',()=>window.print());
  $('start-timer').addEventListener('click',()=>{
    if(clock.startedAt===null)clock.startedAt=Date.now();
    else clock={elapsed:elapsed(),startedAt:null};
    tick();publish();
  });
  $('reset-timer').addEventListener('click',()=>{clock={elapsed:0,startedAt:null};tick();publish();});
  document.querySelectorAll('[data-guard]').forEach(b=>b.addEventListener('click',()=>{guard=b.dataset.guard;showGuard();publish();}));
  document.querySelectorAll('[data-recovery]').forEach(b=>b.addEventListener('click',()=>{recovery=b.dataset.recovery;showRecovery();publish();}));
  window.addEventListener('hashchange',()=>show((Number(location.hash.replace('#slide-',''))||1)-1));
  window.addEventListener('keydown',e=>{
    if(e.altKey||e.ctrlKey||e.metaKey||e.target.closest('input,textarea,select,[contenteditable=true]'))return;
    if((e.key===' '||e.key==='Enter')&&e.target.closest('button,a'))return;
    if(e.key==='ArrowRight'||e.key==='PageDown'||e.key===' '){e.preventDefault();show(index+1);}
    if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();show(index-1);}
    if(e.key==='Home'){e.preventDefault();show(0);}
    if(e.key==='End'){e.preventDefault();show(slides.length-1);}
  });
  $('slides').addEventListener('pointerdown',e=>{if(e.pointerType==='touch'&&!e.target.closest('button,a,select,table'))down={x:e.clientX,y:e.clientY};});
  $('slides').addEventListener('pointerup',e=>{
    if(down){const dx=e.clientX-down.x,dy=e.clientY-down.y;if(Math.abs(dx)>65&&Math.abs(dy)<35)show(index+(dx<0?1:-1));}
    down=null;
  });
  $('slides').addEventListener('pointercancel',()=>{down=null;});
  if(channel) {
    channel.onmessage=({data:m})=>{
      if(m?.type==='hello'){publish();return;}
      const s=m?.value;
      if(m?.type!=='state'||!s||!Number.isInteger(s.index)||s.index<0||s.index>=slides.length)return;
      if(!Object.hasOwn(data.guards,s.guard)||!Object.hasOwn(data.recovery,s.recovery))return;
      if(!s.clock||!Number.isFinite(s.clock.elapsed)||s.clock.elapsed<0||
        !(s.clock.startedAt===null||Number.isFinite(s.clock.startedAt)))return;
      guard=s.guard;recovery=s.recovery;clock=s.clock;show(s.index,false);
    };
  }
  document.querySelectorAll('.web-demo').forEach(a=>{
    if(location.protocol==='http:'||location.protocol==='https:')a.href=location.origin+'/?page=diagnosis&case=connection#main';
  });
  show(index,false);
  channel?.postMessage({type:'hello'});
  setInterval(tick,200);
})();
