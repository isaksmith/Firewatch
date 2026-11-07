import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { getSpecs } from './specs.js';
import { partVisible } from './visibility.js';
import { setupPanelResize } from './panel-resize.js';
import { explosionOffset } from './explosion.js';

const $ = (id) => document.getElementById(id);
const layerNames = {enclosure:'Enclosure & covers',backplate:'Service backplate',power:'Battery & retention',pcb:'Carrier PCB & radio',gas:'Environmental head',particulate:'Particulate assembly',solar:'Solar power',mount:'Mounting hardware',wiring:'Cable harness'};
const state = {tier:'rich',mount:'band',explode:0,layers:Object.fromEntries(Object.keys(layerNames).map(k=>[k,true])),selected:null,detailsView:'overview'};
const components = {
  radio:{title:'RAK4630',subtitle:'Radio + microcontroller',icon:'⌁',layer:'pcb',body:'The shared communications core combines LoRa, Bluetooth and processing. It connects the node to the Meshtastic-powered network.',facts:[['Radio region','US915 concept'],['Module envelope','15 × 23 × 3 mm'],['Used by','Bare + Rich']]},
  environmental:{title:'BME688 sensor head',subtitle:'Environmental sensing',icon:'◉',layer:'gas',body:'One small package measures gas resistance, temperature, humidity and pressure. Its replaceable daughterboard sits in a shaded, ventilated external pod, away from electronics heat.',facts:[['Measurements','Gas · T · RH · pressure'],['Sensor package','3 × 3 × 0.93 mm'],['Used by','Bare + Rich']]},
  particulate:{title:'PMSA003I',subtitle:'Optical particulate sensing',icon:'≋',layer:'particulate',rich:true,body:'The Rich node adds optical particle measurements. A separate air chamber provides protected intake and exhaust paths for the fan-driven sensor.',facts:[['Measurements','PM1 · PM2.5 · PM10'],['Sensor envelope','38 × 35 × 12 mm'],['Used by','Rich only']]},
  pm_interface:{title:'RAK12039 adapter',subtitle:'Particulate interface',icon:'⊞',layer:'particulate',rich:true,body:'A retained plug-in adapter interfaces the particulate sensor with the proposed custom carrier. It provides the PM supply boost and I²C connection for the first custom-board concept.',facts:[['Board envelope','25 × 15 mm'],['Sensor supply','5 V'],['Used by','Rich only']]},
  battery:{title:'Battery pack',subtitle:'Stored energy',icon:'▰',layer:'power',body:'A removable, protected single-cell pack stores solar energy. Retention straps keep the pack serviceable without permanently bonding it to the enclosure.',facts:()=>[['Pack','Protected 1S'],['Design capacity',state.tier==='rich'?'6,600 mAh':'4,400 mAh'],['Envelope','Provisional fit model']]},
  carrier:{title:'Custom carrier PCB',subtitle:'A shared foundation',icon:'▦',layer:'pcb',body:'The proposed FireWatch carrier brings radio, power management, service pads and sensor connections onto one common board. The small external environmental board stays separate.',facts:[['Proposed outline','88 × 72 mm'],['Board thickness','1.6 mm'],['Design stage','Concept placement']]},
  charger:{title:'BQ24074 power path',subtitle:'Solar charging',icon:'ϟ',layer:'pcb',body:'The charging block manages the connection between solar input, battery and system load. The design calls for battery temperature sensing and charge-current configuration.',facts:[['Battery topology','Single-cell lithium'],['Inputs','Solar + thermistor'],['Design stage','Reference-circuit concept']]},
  regulator:{title:'Regulated power',subtitle:'Carrier power rail',icon:'ϟ',layer:'pcb',body:'The proposed buck-boost stage supplies a regulated carrier rail as battery voltage changes. The PM adapter retains its own sensor supply boost.',facts:[['Carrier rail','3.3 V'],['Role','Buck-boost regulation'],['Used by','Bare + Rich']]},
  interfaces:{title:'Keyed interfaces',subtitle:'Service & connection',icon:'⊞',layer:'pcb',body:'Clearly identified connectors separate solar input, battery, temperature sensing and the gas head. Connector bodies and contacts are representative in this concept.',facts:[['Connections','Solar · pack · head'],['Service','Accessible with lid off'],['Footprints','Not released']]},
  enclosure:{title:'Dry electronics enclosure',subtitle:'Protected core',icon:'▢',layer:'enclosure',body:'The common enclosure separates the carrier and battery from the external air-sampling heads. Its modified seals and feedthroughs still need physical verification.',facts:[['Height','6.89 in'],['Width × depth','4.92 × 2.95 in'],['Used by','Bare + Rich']]},
  lid:{title:'Service lid',subtitle:'Access & sealing',icon:'▱',layer:'enclosure',body:'The removable lid, gasket and captive fasteners expose the serviceable interior. Move the explode slider to separate the lid from the enclosure.',facts:[['Closure','Gasket + fasteners'],['Access','Carrier and battery'],['Design stage','Mechanical concept']]},
  sunshield:{title:'Opaque sun shield',subtitle:'Thermal protection concept',icon:'☀',layer:'enclosure',body:'A light-colored cover shades the enclosure face. It is separate from the solar panel, allowing the panel to sit on its own rear bracket.',facts:[['Placement','Above service lid'],['Role','Shade enclosure'],['Used by','Bare + Rich']]},
  backplate:{title:'Service backplate',subtitle:'Removable internal support',icon:'▤',layer:'backplate',body:'An insulating backplate supports the carrier standoffs and the removable pack. It forms a distinct layer in the exploded assembly.',facts:[['Supports','Carrier + pack'],['Construction','Insulating plate'],['Used by','Bare + Rich']]},
  solar_panel:{title:'Solar panel',subtitle:'Harvested energy',icon:'☀',layer:'solar',body:'The two tiers use different panel envelopes. The panel is mounted on a separate adjustable rear bracket, rather than fastened to the electronics lid.',facts:()=>state.tier==='rich'?[['Panel','Voltaic P105'],['Nominal tier rating','5 W'],['Envelope','8.74 × 5.39 × 0.16 in']]:[['Panel','Voltaic P126'],['Nominal tier rating','2 W'],['Envelope','5.35 × 4.41 × 0.11 in']]},
  solar_bracket:{title:'Solar bracket',subtitle:'Separate panel support',icon:'∠',layer:'solar',body:'A rear-supported frame, pivot brace and locking axle hold the panel independently of the lid. A cable lead includes a proposed drip loop.',facts:[['Mounting','Shared rear interface'],['Display inclination','55° above horizontal'],['Adjustment','Concept hinge']]},
  mount_interface:{title:'Shared rear interface',subtitle:'One node, two mounting options',icon:'⊞',layer:'mount',body:'Load spreaders and a rear spine form a common interface for either deployment mount. Both sensor tiers use the same attachment concept.',facts:[['Options','Band or stake'],['Attachment','Rear spreaders + spine'],['Design stage','Load testing pending']]},
  band_mount:{title:'Adjustable bands',subtitle:'Tree / pole mounting',icon:'◎',layer:'mount',mount:'band',body:'Two wraparound bands use simple buckle and tail details. Cushioned saddles separate the node mounting spine from the support surface.',facts:[['Bands','Two'],['Example loop ID','5.04 in'],['Adjustment','Illustrative buckle + tail']]},
  stake_mount:{title:'Ground stake',subtitle:'Freestanding deployment',icon:'↥',layer:'mount',mount:'stake',body:'A square-section stake includes retaining collars, a foot bar, depth collar, anti-rotation fin and pointed tip. The browser model shows the full tip for inspection.',facts:[['Node center above grade','27.6 in concept'],['Tip below grade','11.8 in concept'],['Validation','Soil + wind loads pending']]},
  wiring:{title:'Cable harness',subtitle:'Power & sensor connections',icon:'⌁',layer:'wiring',body:'The installed harness connects the pack and external head to the carrier. It disappears when layers separate because these paths represent installed cable lengths.',facts:[['Connections','Power + I²C'],['Exploded view','Harness hidden'],['Design stage','Routing concept']]}
};
const featured=['radio','environmental','particulate','pm_interface','battery','carrier','solar_panel','solar_bracket','mount_interface','band_mount','stake_mount'];
const internalParts = new Set(['radio','environmental','particulate','pm_interface','battery','carrier','charger','regulator','interfaces']);
const records=[]; const rayMeshes=[]; let renderer,scene,camera,controls,modelRoot;
let explosionPaths;
const raycaster=new THREE.Raycaster(); const pointer=new THREE.Vector2();
const upRotation=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),Math.PI/2);

function applicable(id){const c=components[id];return c&&(!c.rich||state.tier==='rich')&&(!c.mount||c.mount===state.mount)&&(!(id==='mount_interface')||state.mount!=='none');}
function announce(message){$('live-status').textContent=message;}
function renderControls(){
  $('layers').replaceChildren();
  Object.entries(layerNames).forEach(([key,name])=>{
    const label=document.createElement('label'); label.className='layer';
    const input=document.createElement('input'); input.type='checkbox'; input.checked=state.layers[key]; input.dataset.layer=key;
    input.disabled=(key==='particulate'&&state.tier==='bare')||(key==='mount'&&state.mount==='none');
    input.setAttribute('aria-label',`Show ${name}`);
    input.addEventListener('change',()=>{state.layers[key]=input.checked;if(state.selected&&components[state.selected].layer===key&&!input.checked)select(null);updateModel();refreshCount();announce(`${name} ${input.checked?'shown':'hidden'}.`);});
    label.append(input,document.createTextNode(name));
    if(key==='particulate'){const note=document.createElement('small');note.textContent='RICH';label.append(note);}
    $('layers').append(label);
  });
  $('component-list').replaceChildren();
  featured.filter(applicable).forEach((id,index)=>{
    const button=document.createElement('button');button.className='component-button'+(state.selected===id?' active':'');
    button.dataset.component=id;button.setAttribute('aria-pressed',String(state.selected===id));
    const number=document.createElement('span');number.className='part-index';number.textContent=String(index+1).padStart(2,'0');
    const name=document.createElement('span');name.textContent=components[id].title;
    const arrow=document.createElement('span');arrow.className='part-arrow';arrow.textContent='↗';
    button.append(number,name,arrow);button.addEventListener('click',()=>select(id,true));$('component-list').append(button);
  });
  $('tier-note').textContent=state.tier==='rich'?'Environmental sensing + optical particulate confirmation.':'Gas resistance, temperature, humidity and pressure.';
  const mounts={band:'Band mount',stake:'Ground stake',none:'Node only'};
  $('model-title').replaceChildren(document.createTextNode(`${state.tier==='rich'?'Rich':'Bare'} node `));
  const slash=document.createElement('span');slash.textContent='/';$('model-title').append(slash,document.createTextNode(` ${mounts[state.mount]}`));
}
function renderDetails(){
  const c=state.selected?components[state.selected]:null;
  const data=c||{title:'Two tiers.\nOne platform.',subtitle:state.tier==='rich'?'RICH NODE / PARTICULATE ENABLED':'BARE NODE / ENVIRONMENTAL',icon:'◈',body:'A solar-powered sensor node designed to bring local observations into FireWatch. Select a component or separate the layers to see how it comes together.',facts:[['Enclosure height','6.89 in'],['Width × depth','4.92 × 2.95 in'],['Power','Solar + protected pack']]};
  const host=$('detail-content');host.replaceChildren();
  const icon=document.createElement('div');icon.className='detail-icon';icon.textContent=data.icon;
  const title=document.createElement('h2');title.className='detail-title';title.textContent=data.title;
  const subtitle=document.createElement('p');subtitle.className='detail-subtitle';subtitle.textContent=data.subtitle;
  const body=document.createElement('p');body.className='detail-body';body.textContent=data.body;
  const dl=document.createElement('dl');dl.className='detail-facts';
  const facts=typeof data.facts==='function'?data.facts():data.facts;
  facts.forEach(([label,value])=>{const row=document.createElement('div');const dt=document.createElement('dt');dt.textContent=label;const dd=document.createElement('dd');dd.textContent=value;row.append(dt,dd);dl.append(row);});
  host.append(icon,title,subtitle);
  if(c){
    const tabs=document.createElement('div');tabs.className='detail-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Component information');
    ['overview','specs'].forEach(mode=>{
      const tab=document.createElement('button');tab.id=`detail-tab-${mode}`;tab.type='button';tab.setAttribute('role','tab');
      tab.textContent=mode==='overview'?'Overview':'Specs & Limits';tab.setAttribute('aria-selected',String(state.detailsView===mode));tab.setAttribute('aria-controls','detail-panel');tab.tabIndex=state.detailsView===mode?0:-1;
      const activate=()=>{state.detailsView=mode;renderDetails();$(`detail-tab-${mode}`).focus();};
      tab.addEventListener('click',activate);
      tab.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();state.detailsView=e.key==='Home'?'overview':e.key==='End'?'specs':mode==='overview'?'specs':'overview';renderDetails();$(`detail-tab-${state.detailsView}`).focus();}});
      tabs.append(tab);
    });host.append(tabs);
  }
  const panel=document.createElement('div');panel.id='detail-panel';
  if(c){panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',`detail-tab-${state.detailsView}`);panel.tabIndex=0;}
  if(c&&state.detailsView==='specs'){
    const specs=getSpecs(state.selected,state.tier);
    const basis=document.createElement('p');basis.className='spec-basis';basis.textContent=specs.basis;panel.append(basis);
    specs.sections.forEach(section=>{
      const block=document.createElement('section');block.className='spec-section';const heading=document.createElement('h3');heading.textContent=section.heading;block.append(heading);
      if(section.text){const p=document.createElement('p');p.textContent=section.text;block.append(p);}
      if(section.rows.length){const list=document.createElement('dl');list.className='spec-facts';section.rows.forEach(([key,value])=>{const row=document.createElement('div');const dt=document.createElement('dt');dt.textContent=key;const dd=document.createElement('dd');dd.textContent=value;row.append(dt,dd);list.append(row);});block.append(list);}
      panel.append(block);
    });
    if(specs.sources.length){
      const sources=document.createElement('section');sources.className='spec-sources';const heading=document.createElement('h3');heading.textContent='Sources';sources.append(heading);
      specs.sources.forEach(([name,url])=>{const a=document.createElement('a');a.href=url;a.textContent=`${name} ↗`;a.target='_blank';a.rel='noopener noreferrer';sources.append(a);});
      const checked=document.createElement('p');checked.textContent='Reviewed November 7, 2026';sources.append(checked);panel.append(sources);
    }
  }else panel.append(body,dl);
  host.append(panel);$('clear-selection').hidden=!c;$('focus-part').hidden=!c;
}
function select(id,reveal=false){
  state.selected=id&&applicable(id)?id:null;
  if(reveal&&id){
    state.layers[components[id].layer]=true;
    if(internalParts.has(id)){state.layers.enclosure=false;state.explode=Math.max(state.explode,.65);syncSlider();}
  }
  renderControls();renderDetails();
  if(modelRoot){updateModel();highlight();refreshCount();if(reveal)fitView('current',id);}
  announce(id?`Selected ${components[id].title}.`:'Selection cleared.');
}
function isVisible(o){while(o){if(!o.visible)return false;o=o.parent;}return true;}
function updateModel(){
  if(!modelRoot)return;
  const upright=state.mount!=='none';modelRoot.quaternion.copy(upright?upRotation:new THREE.Quaternion());
  records.forEach(r=>{
    const {meta,node}=r;
    node.visible=partVisible(meta,state);
    // Same compact device-local path for node-only and mounted configurations.
    const d=new THREE.Vector3(...explosionOffset(meta.assembly,state.explode,explosionPaths,upright));
    node.position.copy(r.base).add(d);
  });
  modelRoot.updateMatrixWorld(true);
}
function highlight(){
  rayMeshes.forEach(mesh=>{
    const selected=state.selected&&mesh.userData.component===state.selected;
    const mats=Array.isArray(mesh.material)?mesh.material:[mesh.material];
    mats.forEach(m=>{if(m.emissive){m.emissive.set(selected?0xc7752f:0x000000);m.emissiveIntensity=selected?.27:0;}});
  });
}
function bounds(component=null){
  const box=new THREE.Box3();
  rayMeshes.forEach(o=>{if(isVisible(o)&&(!component||o.userData.component===component))box.expandByObject(o);});
  return box;
}
function fitView(view='current',component=null){
  if(!camera||!records.length)return;
  const box=bounds(component);if(box.isEmpty()){announce('No visible parts. Use Show all to restore the model.');return;}
  const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
  let direction=camera.position.clone().sub(controls.target).normalize();
  if(view==='front')direction.set(.85,.55,1.55).normalize();
  if(view==='rear')direction.set(-1,.5,-1.5).normalize();
  if(view==='top')direction.set(.05,1,.02).normalize();
  const radius=Math.max(size.length()/2,.008);
  const vertical=THREE.MathUtils.degToRad(camera.fov/2);
  const angle=Math.min(vertical,Math.atan(Math.tan(vertical)*camera.aspect));
  const distance=radius/Math.sin(angle)*1.15;
  camera.position.copy(center).addScaledVector(direction,distance);controls.target.copy(center);
  camera.near=Math.max(.0001,distance/1000);camera.far=Math.max(20,distance*20);camera.updateProjectionMatrix();controls.update();
}
function syncSlider(){const percent=Math.round(state.explode*100);$('explode').value=percent;$('explode-output').value=`${percent}%`;$('pose-label').textContent=percent===0?'ASSEMBLED':`EXPLODED / ${percent}%`;}
function explode(value){state.explode=value/100;syncSlider();updateModel();refreshCount();fitView();}
function refreshCount(){const count=rayMeshes.filter(isVisible).length;$('part-count').textContent=`${count} visible parts`;}
function configure(){
  if(state.selected&&!applicable(state.selected))state.selected=null;
  renderControls();renderDetails();updateModel();highlight();refreshCount();fitView('front');
  announce(`${state.tier==='rich'?'Rich':'Bare'} node, ${$('mount').selectedOptions[0].textContent}.`);
}

async function initialize(){
  const host=$('canvas-host');
  try{
    renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'high-performance'});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.75));renderer.setClearColor(0x000000,0);
    renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.15;
    host.append(renderer.domElement);renderer.domElement.setAttribute('aria-label','FireWatch 3D node. Drag to orbit, scroll to zoom, or use the component list to inspect parts.');renderer.domElement.setAttribute('role','img');
    scene=new THREE.Scene();camera=new THREE.PerspectiveCamera(36,1,.001,20);camera.position.set(.8,.5,1.5);
    controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.08;controls.minDistance=.015;controls.maxDistance=8;
    const pmrem=new THREE.PMREMGenerator(renderer);const room=new RoomEnvironment();
    scene.environment=pmrem.fromScene(room,.04).texture;room.dispose();pmrem.dispose();scene.environmentIntensity=.8;
    scene.add(new THREE.HemisphereLight(0xffffff,0xa3af93,2));
    const key=new THREE.DirectionalLight(0xfff8eb,3);key.position.set(2,4,3);scene.add(key);
    const fill=new THREE.DirectionalLight(0xdce8ff,1.5);fill.position.set(-3,1,-2);scene.add(fill);
    const [gltf,pathResponse]=await Promise.all([new GLTFLoader().loadAsync('./assets/firewatch.glb'),fetch('./explosion-paths.json')]);
    if(!pathResponse.ok)throw new Error('Explosion path configuration could not be loaded.');
    explosionPaths=await pathResponse.json();
    modelRoot=gltf.scene;scene.add(modelRoot);
    modelRoot.traverse(node=>{
      if(node.userData.layer){if(!explosionPaths.assemblies[node.userData.assembly])throw new Error('Assembly path metadata missing. Re-export the model.');records.push({node,meta:node.userData,base:node.position.clone()});}
      if(node.isMesh){
        let owner=node;while(owner&&!owner.userData.component)owner=owner.parent;
        if(owner)node.userData.component=owner.userData.component;
        node.material=Array.isArray(node.material)?node.material.map(m=>m.clone()):node.material.clone();
        if(node.geometry&&!node.geometry.boundingBox)node.geometry.computeBoundingBox();
        rayMeshes.push(node);
      }
    });
    if(!records.length)throw new Error('The model has no component metadata. Re-export the annotated model.');
    const resize=()=>{const w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();fitView();};
    new ResizeObserver(resize).observe(host);resize();configure();$('loading').hidden=true;
    let down=null;
    renderer.domElement.addEventListener('pointerdown',e=>{down={x:e.clientX,y:e.clientY};});
    renderer.domElement.addEventListener('pointerup',e=>{
      if(!down||Math.hypot(e.clientX-down.x,e.clientY-down.y)>5)return;down=null;
      const rect=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);
      raycaster.setFromCamera(pointer,camera);const hits=raycaster.intersectObjects(rayMeshes,false).filter(h=>isVisible(h.object));
      if(hits[0])select(hits[0].object.userData.component);else select(null);
    });
    renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();showError('The 3D graphics context was interrupted. Reload to restore the viewer.');});
    renderer.setAnimationLoop(()=>{if(document.hidden)return;controls.update();renderer.render(scene,camera);});
    announce('Model ready. Choose a tier, mount, or component to explore.');
  }catch(error){console.error(error);showError(error.message.includes('WebGL')?'This browser could not start 3D graphics. Try a browser with WebGL enabled.':'The model could not be loaded. Check that the local server is running, then retry.');}
}
function showError(message){const loading=$('loading');loading.hidden=false;loading.replaceChildren();const title=document.createElement('strong');title.textContent='Unable to open the 3D view';const p=document.createElement('span');p.textContent=message;const retry=document.createElement('button');retry.className='focus-button';retry.textContent='Reload viewer';retry.onclick=()=>location.reload();loading.append(title,p,retry);}

document.querySelectorAll('input[name=tier]').forEach(input=>input.addEventListener('change',()=>{state.tier=input.value;configure();}));
$('mount').addEventListener('change',e=>{state.mount=e.target.value;configure();});
$('explode').addEventListener('input',e=>explode(Number(e.target.value)));
$('assemble').addEventListener('click',()=>explode(0));$('explode-all').addEventListener('click',()=>explode(100));
$('show-all').addEventListener('click',()=>{Object.keys(state.layers).forEach(k=>state.layers[k]=true);renderControls();updateModel();refreshCount();fitView();announce('All applicable layers shown.');});
$('reset-view').addEventListener('click',()=>fitView('front'));
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>fitView(button.dataset.view)));
$('clear-selection').addEventListener('click',()=>select(null));
$('focus-part').addEventListener('click',()=>fitView('current',state.selected));
window.addEventListener('keydown',e=>{if(e.key==='Escape')select(null);});
setupPanelResize();
renderControls();renderDetails();initialize();
