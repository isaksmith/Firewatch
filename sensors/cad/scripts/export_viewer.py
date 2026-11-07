"""Export revision 2 to a flattened, annotated, browser-sized GLB."""
import bpy
import os
import json
from mathutils import Matrix
CAD=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT=os.path.join(os.path.dirname(CAD),'viewer','assets')
bpy.ops.wm.open_mainfile(filepath=os.path.join(CAD,'firewatch_revision2.blend'))
src=bpy.data.scenes['01 | LAYER INSPECTION — Rich / Bare']
bpy.context.window.scene=src
for c in bpy.context.view_layer.layer_collection.children: c.exclude=False
for c in src.collection.children: c.hide_viewport=False
src.frame_set(1); bpy.context.view_layer.update()
keys={'01':'enclosure','02':'backplate','03':'power','04':'pcb','05':'gas','06':'particulate',
      '07':'wiring','11':'solar','12':'solar','13':'solar','14':'mount','15':'mount','16':'mount'}
items=[]
for col in src.collection.children:
    prefix=col.name[:2]
    if prefix not in keys: continue
    for o in col.objects:
        if o.type not in {'MESH','CURVE','FONT'} or o.name.startswith('Inspection label'): continue
        if o.type=='EMPTY': continue
        items.append((o,prefix,keys[prefix]))
assembled={o.name:o.matrix_world.copy() for o,_,_ in items}
src.frame_set(100); bpy.context.view_layer.update()
exploded={o.name:o.matrix_world.translation-assembled[o.name].translation for o,_,_ in items}
src.frame_set(1); bpy.context.view_layer.update()
deps=bpy.context.evaluated_depsgraph_get()
dest=bpy.data.scenes.new('WEB EXPORT')
dest.unit_settings.system='METRIC'; dest.unit_settings.scale_length=1
def component(o,prefix):
    n=o.name.lower()
    if prefix=='01':
        if any(t in n for t in ['sun shield','wordmark','revision','identity accent']): return 'sunshield'
        if any(t in n for t in ['lid |','gasket','captive lid']): return 'lid'
        return 'enclosure'
    if prefix=='02': return 'backplate'
    if prefix=='03': return 'battery'
    if prefix=='04':
        if any(t in n for t in ['rak4630','rak castellated','radio section','antenna','coax','rf shield']): return 'radio'
        if 'bq24074' in n: return 'charger'
        if any(t in n for t in ['buck-boost','inductor','power ic','decoupling','power section','power path']): return 'regulator'
        if 'connector' in n or 'j |' in n: return 'interfaces'
        return 'carrier'
    if prefix=='05': return 'environmental'
    if prefix=='06':
        if o.parent and 'adapter' in o.parent.name: return 'pm_interface'
        return 'particulate'
    if prefix=='07': return 'wiring'
    if prefix=='11': return 'solar_bracket'
    if prefix in ['12','13']: return 'solar_panel'
    if prefix=='14': return 'mount_interface'
    if prefix=='15': return 'band_mount'
    return 'stake_mount'
counts={}
def assembly(obj,prefix):
    parent=obj.parent.name if obj.parent else ''
    if prefix=='01': return 'lid' if '01b' in parent else 'shield' if '01c' in parent else 'body'
    if prefix=='02': return 'backplate'
    if prefix=='03': return 'battery'
    if prefix=='04': return 'carrier'
    if prefix=='05': return 'gas_head' if '05b' in parent else 'gas_hood' if '05c' in parent else 'gas_base'
    if prefix=='06':
        if obj.name.startswith('PM flex'): return 'wiring'
        return 'pm_sensor' if '06b' in parent else 'pm_hood' if '06c' in parent else 'pm_adapter' if '06d' in parent else 'pm_base'
    if prefix in ['11','12','13']: return 'solar'
    if prefix in ['14','15','16']: return 'mount'
    return 'wiring'
for obj,prefix,layer in items:
    evaluated=obj.evaluated_get(deps)
    mesh=bpy.data.meshes.new_from_object(evaluated,depsgraph=deps)
    if not mesh or not mesh.vertices: continue
    o=bpy.data.objects.new(obj.name,mesh); dest.collection.objects.link(o)
    o.matrix_world=Matrix.Scale(.001,4)@assembled[obj.name]
    o['layer']=layer; o['component']=component(obj,prefix)
    o['originalName']=obj.name
    o['assembly']=assembly(obj,prefix)
    o['explode']=[round(v*.001,6) for v in exploded[obj.name]]
    o['tier']='rich' if prefix in ['06','12'] else 'bare' if prefix=='13' else 'both'
    o['mount']='band' if prefix=='15' else 'stake' if prefix=='16' else 'both'
    o['hideWhenExploded']=prefix=='07' or obj.name.startswith('PM flex')
    counts[layer]=counts.get(layer,0)+1
bpy.context.window.scene=dest
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT,'firewatch.glb'),export_format='GLB',
    use_active_scene=True,export_extras=True,export_animations=False,export_yup=True,
    export_cameras=False,export_lights=False,export_apply=False)
report={'source':'sensors/cad/firewatch_revision2.blend','units':'meters','blenderToGltf':'x,z,-y',
    'meshCounts':counts,'totalMeshes':sum(counts.values()),'bytes':os.path.getsize(os.path.join(OUT,'firewatch.glb')),
    'notes':'Evaluated geometry including labels; studio, pole, ground and clearance guides excluded. Explode vectors are Blender-space meters.'}
with open(os.path.join(OUT,'model-manifest.json'),'w') as f: json.dump(report,f,indent=2)
print('EXPORT_COMPLETE',json.dumps(report))
