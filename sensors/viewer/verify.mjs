// Non-visual checks against the actual exported model, not a mocked part list.
// Run with Node.js: node sensors/viewer/verify.mjs
import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const root=new URL('.',import.meta.url);
const [visibility,specs,model]=await Promise.all([
  fs.readFile(new URL('visibility.js',root),'utf8'),
  fs.readFile(new URL('specs.js',root),'utf8'),
  fs.readFile(new URL('assets/firewatch.glb',root))
]);
const context=vm.createContext({});
vm.runInContext(visibility.replace(/export /g,'')+'\n'+specs.replace(/export /g,''),context);
const json=JSON.parse(model.subarray(20,20+model.readUInt32LE(12)).toString());
const parts=json.nodes.map(n=>n.extras).filter(n=>n?.component);
assert.equal(parts.length,477);
const components=[...new Set(parts.map(p=>p.component))];
let combinations=0;
for(const tier of ['rich','bare'])for(const mount of ['band','stake','none']){
  const layers=Object.fromEntries([...new Set(parts.map(p=>p.layer))].map(k=>[k,true]));
  const state={tier,mount,layers,explode:.65,isolated:null,beforeIsolation:null};
  for(const id of components){
    const matching=parts.filter(p=>p.component===id&&context.partVisible(p,{...state,explode:0}));
    if(!matching.length)continue;
    const detail=context.getSpecs(id,tier);
    assert.ok(detail.sections.length>=2);
    assert.ok(detail.sections.some(s=>/limit/i.test(s.heading)));
    detail.sources.forEach(([,url])=>assert.ok(url.startsWith('https://')));
    combinations++;
  }
  const visible=parts.filter(p=>context.partVisible(p,state));
  if(tier==='bare')assert.ok(visible.every(p=>p.tier!=='rich'));
  if(mount==='none')assert.ok(visible.every(p=>p.layer!=='mount'));
}
const radio=context.getSpecs('radio','rich');
const detailText=JSON.stringify(radio);
for(const value of ['nRF52840','SX1262','64 MHz','1 MB','256 KB','902–928 MHz'])assert.ok(detailText.includes(value),value);
const paths=JSON.parse(await fs.readFile(new URL('explosion-paths.json',root),'utf8'));
vm.runInContext((await fs.readFile(new URL('explosion.js',root),'utf8')).replace(/export /g,''),context);
for(const part of parts){
  assert.ok(paths.assemblies[part.assembly],part.originalName);
  const zero=context.explosionOffset(part.assembly,0,paths);
  assert.ok(zero.every(v=>v===0));
  for(let step=1;step<=100;step++)assert.ok(context.explosionOffset(part.assembly,step/100,paths).every(Number.isFinite));
  const restored=paths.assemblies[part.assembly].extract.map(v=>v/1000);
  assert.ok(restored.every((v,i)=>Math.abs(v-part.explode[i])<.000001),`Blender offset mismatch: ${part.originalName}`);
}
assert.ok(Math.abs(context.explosionOffset('carrier',1,paths)[1]-.17)<.000001);
assert.equal(context.explosionOffset('carrier',.25,paths)[0],0);
assert.equal(context.explosionOffset('carrier',1,paths)[0],0);
assert.equal(context.explosionOffset('battery',1,paths)[0],0);
// Mounted root Rx(90°) maps device-normal +Y to outward +Z, not world up.
const mounted=context.explosionOffset('carrier',1,paths);
assert.ok(Math.abs(mounted[1]-.17)<.000001);
assert.ok(context.explosionOffset('carrier',1,paths,true).every((v,i)=>v===mounted[i]));
assert.ok(context.explosionOffset('solar',1,paths,true).every(v=>v===0));
for(const name of ['app.js','specs.js','visibility.js','panel-resize.js','explosion.js']){
  const code=await fs.readFile(new URL(name,root),'utf8');
  new vm.Script(code.replace(/^import .*;\r?\n/gm,'').replace(/export /g,''),{filename:name});
}
// Exercise the actual UI handlers with a minimal DOM, leaving WebGL to browser QA.
class Element{
  constructor(){this.children=[];this.events={};this.attributes={};this.dataset={};this.value='';this.selectedOptions=[{textContent:'Tree / pole band'}];}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this.attributes[k]=v;}
  addEventListener(k,fn){this.events[k]=fn;}
  focus(){}
  set id(value){this._id=value;elements.set(value,this);}
  get id(){return this._id;}
  get firstChild(){return this.children[0];}
}
const elements=new Map();
const document={getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement(){return new Element();},createTextNode(text){const e=new Element();e.textContent=text;return e;},querySelectorAll(){return [];}};
document.getElementById('focus-part').append(document.createTextNode('Focus on this component '));
const mockThree={Vector2:class{},Vector3:class{},Raycaster:class{},Quaternion:class{setFromAxisAngle(){return this;}}};
const ui=vm.createContext({document,window:{addEventListener(){}},THREE:mockThree,console,setupPanelResize(){}});
const app=(await fs.readFile(new URL('app.js',root),'utf8')).replace(/^import .*;\r?\n/gm,'').replace('renderControls();renderDetails();initialize();','renderControls();renderDetails();');
vm.runInContext(visibility.replace(/export /g,'')+'\n'+specs.replace(/export /g,'')+'\n'+app,ui);
vm.runInContext("select('radio',true);",ui);
const beforeFocus=vm.runInContext('JSON.stringify({layers:state.layers,explode:state.explode})',ui);
elements.get('focus-part').events.click();
assert.equal(vm.runInContext('JSON.stringify({layers:state.layers,explode:state.explode})',ui),beforeFocus);
elements.get('detail-tab-specs').events.click();
assert.equal(vm.runInContext('state.detailsView',ui),'specs');
assert.equal(elements.get('detail-tab-specs').attributes['aria-selected'],'true');
assert.equal(elements.get('detail-tab-specs').textContent,'Specs & Limits');
vm.runInContext("select('environmental',true);",ui);
vm.runInContext("select('particulate',true);",ui);elements.get('focus-part').events.click();
vm.runInContext("state.tier='bare';configure();",ui);
assert.equal(vm.runInContext('state.selected',ui),null);
const html=await fs.readFile(new URL('index.html',root),'utf8');
for(const id of ['details-resizer','expand-details','component-details'])assert.ok(html.includes(`id="${id}"`));
for(const id of ['restore-assembly','isolation-notice'])assert.ok(!html.includes(`id="${id}"`));
// Test drag direction, clamping, keyboard resizing and expand/collapse handlers.
const resizeElements=new Map();
function resizeElement(){const e=new Element();e.clientWidth=1400;e.style={setProperty(k,v){this[k]=v;}};e.classList={add(){},remove(){}};e.getBoundingClientRect=()=>({right:1400,width:272});e.setPointerCapture=()=>{};e.hasPointerCapture=()=>false;return e;}
for(const id of ['app','controls','details-resizer','expand-details'])resizeElements.set(id,resizeElement());
const resizeDocument={querySelector(selector){return resizeElements.get(selector.slice(1));},getElementById(id){return resizeElements.get(id);}};
const resizeContext=vm.createContext({document:resizeDocument,window:{innerWidth:1400,addEventListener(){}},getComputedStyle(){return {getPropertyValue(){return '290';}};}});
vm.runInContext((await fs.readFile(new URL('panel-resize.js',root),'utf8')).replace(/export /g,''),resizeContext);
vm.runInContext('setupPanelResize()',resizeContext);
const separator=resizeElements.get('details-resizer'),expand=resizeElements.get('expand-details');
assert.equal(separator.attributes['aria-valuenow'],'290');
expand.events.click();assert.equal(separator.attributes['aria-valuenow'],'700');
expand.events.click();assert.equal(separator.attributes['aria-valuenow'],'290');
separator.events.pointerdown({button:0,pointerId:1,preventDefault(){}});
separator.events.pointermove({clientX:900});assert.equal(separator.attributes['aria-valuenow'],'496');
separator.events.pointermove({clientX:2000});assert.equal(separator.attributes['aria-valuenow'],'240');
separator.events.pointerup();
separator.events.keydown({key:'ArrowLeft',preventDefault(){}});assert.equal(separator.attributes['aria-valuenow'],'256');
separator.events.dblclick();assert.equal(separator.attributes['aria-valuenow'],'290');
console.log(`PASS: ${parts.length} exported parts; ${combinations} component/tier/mount Specs combinations; camera-only focus preserves visibility; Specs tabs; panel drag/clamping/expand/collapse/keyboard; JavaScript syntax.`);
