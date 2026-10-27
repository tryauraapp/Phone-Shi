const token=location.pathname.split('/').filter(Boolean)[1];
const screen=document.querySelector('#screen'),status=document.querySelector('#status'),stage=document.querySelector('#stage');
let objectUrl='',refreshing=false,pointer=null;
async function refresh(){if(refreshing)return;refreshing=true;try{const response=await fetch(`/phone/${encodeURIComponent(token)}/screen.png?t=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw new Error(response.status===403?'Link expired':'Phone unavailable');const blob=await response.blob(),next=URL.createObjectURL(blob);screen.src=next;if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=next;status.textContent='Live · tap or swipe to control'}catch(error){status.textContent=error.message}finally{refreshing=false}}
async function input(body){try{const response=await fetch(`/phone/${encodeURIComponent(token)}/input`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||'Input failed')}setTimeout(refresh,120)}catch(error){status.textContent=error.message}}
function point(event){const rect=screen.getBoundingClientRect();return{x:Math.round((event.clientX-rect.left)*screen.naturalWidth/rect.width),y:Math.round((event.clientY-rect.top)*screen.naturalHeight/rect.height)}}
screen.addEventListener('pointerdown',event=>{event.preventDefault();screen.setPointerCapture(event.pointerId);pointer={...point(event),time:Date.now()}});
screen.addEventListener('pointerup',event=>{if(!pointer)return;const end=point(event),start=pointer;pointer=null;const distance=Math.hypot(end.x-start.x,end.y-start.y);if(distance<24)input({action:'tap',x:end.x,y:end.y});else input({action:'swipe',x1:start.x,y1:start.y,x2:end.x,y2:end.y,duration:Math.max(100,Math.min(1200,Date.now()-start.time))})});
screen.addEventListener('pointercancel',()=>{pointer=null});
document.querySelectorAll('[data-key]').forEach(button=>button.onclick=()=>input({action:button.dataset.key}));
document.querySelector('#fullscreen').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else stage.requestFullscreen?.()};
setInterval(refresh,900);refresh();
