export function panelLimits(total,controls){
  return {min:240,max:Math.max(240,Math.min(700,total-controls-308))};
}
export function setupPanelResize(){
  const app=document.querySelector('.app'),left=document.querySelector('.controls');
  const handle=document.getElementById('details-resizer'),button=document.getElementById('expand-details');
  let width=null,dragging=false,pointerId=null;
  const limits=()=>panelLimits(app.clientWidth,left.getBoundingClientRect().width);
  const defaultWidth=()=>parseFloat(getComputedStyle(app).getPropertyValue('--details-default'))||290;
  const setWidth=(value)=>{
    const {min,max}=limits();width=Math.round(Math.max(min,Math.min(max,value)));
    app.style.setProperty('--details-width',`${width}px`);
    handle.setAttribute('aria-valuemin',String(min));handle.setAttribute('aria-valuemax',String(max));handle.setAttribute('aria-valuenow',String(width));handle.setAttribute('aria-valuetext',`${width} pixels wide`);
    const expanded=width>=max-1;button.textContent=expanded?'Collapse ↔':'Expand ↔';button.setAttribute('aria-expanded',String(expanded));
  };
  const finish=()=>{dragging=false;app.classList.remove('resizing-panel');if(pointerId!==null&&handle.hasPointerCapture(pointerId))handle.releasePointerCapture(pointerId);pointerId=null;};
  handle.addEventListener('pointerdown',e=>{
    if(e.button!==0||window.innerWidth<=860)return;e.preventDefault();dragging=true;pointerId=e.pointerId;handle.setPointerCapture(pointerId);app.classList.add('resizing-panel');
  });
  handle.addEventListener('pointermove',e=>{if(dragging)setWidth(app.getBoundingClientRect().right-e.clientX-4);});
  handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);handle.addEventListener('lostpointercapture',finish);
  handle.addEventListener('dblclick',()=>setWidth(defaultWidth()));
  handle.addEventListener('keydown',e=>{
    const step=e.shiftKey?40:16;
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();
    setWidth(e.key==='Home'?limits().min:e.key==='End'?limits().max:(width??defaultWidth())+(e.key==='ArrowLeft'?step:-step));
  });
  button.addEventListener('click',()=>setWidth(width>=limits().max-1?defaultWidth():limits().max));
  window.addEventListener('resize',()=>{if(window.innerWidth<=860)finish();else setWidth(width??defaultWidth());});
  if(window.innerWidth>860)setWidth(defaultWidth());
}
