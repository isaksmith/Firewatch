"""Inspect the actual saved Blender scene, including both animation poses."""
import bpy
import os
import json
from collections import Counter

root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bpy.ops.wm.open_mainfile(filepath=os.path.join(root,'firewatch_first_pass.blend'))
s=bpy.context.scene
carrier=bpy.data.objects['SM_FireWatch custom carrier | proposed 88 × 72 × 1.6']
assert all(abs(a-b)<.01 for a,b in zip(carrier.dimensions,(88,72,1.6)))
poses={}
for f in [1,100]:
    s.frame_set(f)
    bpy.context.view_layer.update()
    poses[str(f)]={name:round(bpy.data.objects[name].matrix_world.translation.z,2)
        for name in ['SM_FireWatch custom carrier | proposed 88 × 72 × 1.6',
                     'SM_Removable insulating backplate',
                     'SM_Protected 1S battery | ENVELOPE ONLY',
                     'SM_Lid | service cover']}
assert abs(poses['100'][carrier.name]-poses['1'][carrier.name]-170)<.01
assert s.view_layers['BARE | no particulate assembly'].layer_collection.children['06 | RICH ONLY — adapter / PMSA003I / chamber'].exclude
nonmanifold=[]
for o in s.objects:
    if o.type!='MESH': continue
    assert o.name.startswith('SM_')
    assert min(o.scale)>0
    edge_count=Counter()
    for p in o.data.polygons:
        ids=list(p.vertices)
        for a,b in zip(ids,ids[1:]+ids[:1]): edge_count[tuple(sorted((a,b)))]+=1
    if any(n!=2 for n in edge_count.values()): nonmanifold.append(o.name)
assert not nonmanifold,nonmanifold
s.frame_set(1)
bpy.context.view_layer.update()
def planes(name):
    o=bpy.data.objects[name]
    z=[(o.matrix_world @ __import__('mathutils').Vector(v)).z for v in o.bound_box]
    return min(z),max(z)
board_bottom,board_top=planes(carrier.name)
contacts={
    'radio_to_carrier_gap_mm':round(planes('SM_U1 | RAK4630 — LoRa + BLE + MCU')[0]-board_top,3),
    'battery_to_backplate_gap_mm':round(planes('SM_Protected 1S battery | ENVELOPE ONLY')[0]-planes('SM_Removable insulating backplate')[1],3),
    'carrier_to_standoff_gap_mm':round(board_bottom-planes('SM_Carrier standoff')[1],3),
}
report={'blender':bpy.app.version_string,'objects':len(s.objects),
        'mesh_objects':sum(o.type=='MESH' for o in s.objects),
        'unique_meshes':len({o.data.name for o in s.objects if o.type=='MESH'}),
        'triangles_before_modifiers':sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in s.objects if o.type=='MESH'),
        'unit_scale':s.unit_settings.scale_length,'carrier_mm':list(carrier.dimensions),
        'poses_mm':poses,'contact_review_mm':contacts,'bare_excludes_pm':True,'base_mesh_nonmanifold':nonmanifold,
        'result':'PASS for concept scene structure; not an electrical or manufacturing validation'}
with open(os.path.join(root,'scene_audit.json'),'w') as f: json.dump(report,f,indent=2)
print(json.dumps(report,indent=2))
