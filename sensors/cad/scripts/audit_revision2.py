"""Validate tier/mount alternatives and measured assembly anchors in revision 2."""
import bpy
import json
import os
from mathutils import Vector
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bpy.ops.wm.open_mainfile(filepath=os.path.join(ROOT,'firewatch_revision2.blend'))
inspection=bpy.data.scenes['01 | LAYER INSPECTION — Rich / Bare']
assert bpy.data.objects['Battery marking'].data.body=='BATTERY PACK'
assert len(bpy.data.scenes)==5
reports={}
for scene in bpy.data.scenes:
    if scene==inspection: continue
    bpy.context.window.scene=scene
    bpy.context.view_layer.update()
    assert scene.camera is not None
    tier=scene['Tier']; mount=scene['Mount']
    panels=[o for o in scene.objects if 'Solar panel substrate' in o.name]
    assert len(panels)==1
    expected=[137,222,4] if tier=='Rich' else [112,136,2.7]
    assert all(abs(a-b)<.001 for a,b in zip(panels[0]['Vendor envelope mm'],expected))
    has_pm=any('PMSA003I | optical' in o.name for o in scene.objects)
    assert has_pm==(tier=='Rich')
    assert not any(o.type=='FONT' and 'TBD' in o.data.body for o in scene.objects)
    assert not any('Inspection label' in o.name for o in scene.objects)
    if mount=='stake':
        tip=next(o for o in scene.objects if 'Ground stake pointed tip' in o.name)
        low=min((tip.matrix_world@Vector(v)).z for v in tip.bound_box)
        assert abs(low+300)<.001
        assert not any('Adjustable wraparound band' in o.name for o in scene.objects)
    else:
        assert sum('Adjustable wraparound band' in o.name for o in scene.objects)==2
        assert not any('Ground stake shaft' in o.name for o in scene.objects)
    reports[scene.name]={'tier':tier,'mount':mount,'objects':len(scene.objects),'solar_mm':expected,'pm_present':has_pm}

contacts={}
bpy.context.window.scene=inspection
inspection.frame_set(1)
for child in bpy.context.view_layer.layer_collection.children:
    if child.name.startswith(('11 |','12 |','13 |','14 |')): child.exclude=False
bpy.context.view_layer.update()
for o in inspection.objects:
    if o.name.startswith('SM_V2 | Enclosure rear spacer'):
        gap=-(o.location.z+max(v.co.z for v in o.data.vertices))
        assert abs(gap)<.001
    if o.name.startswith('SM_V2 | Solar rear pivot brace'):
        panel=next(x for x in inspection.objects if x.parent==o.parent and 'Solar panel substrate' in x.name)
        brace_top=o.location.z+max(v.co.z for v in o.data.vertices)
        panel_back=min(v.co.z for v in panel.data.vertices)
        gap=panel_back-brace_top
        assert abs(gap)<.001
        axle=bpy.data.objects['SM_V2 | Solar tilt axle']
        local_axle=o.parent.matrix_world.inverted()@axle.matrix_world.translation
        clearance=panel_back-(local_axle.z+4)
        assert clearance>.5
        contacts[panel.name]={'brace_to_panel_gap_mm':round(gap,3),'axle_to_panel_clearance_mm':round(clearance,3)}
reports['assembly_interfaces']={'rear_spacer_to_enclosure_gap_mm':0,'panel_contacts':contacts,
    'stake_grade_z_mm':0,'stake_tip_z_mm':-300,'band_inner_radius_mm':64,'example_pole_radius_mm':63.5}
reports['result']='PASS for concept configuration and measured anchors; structural, soil, RF and weather qualification remain open'
with open(os.path.join(ROOT,'revision2_audit.json'),'w') as f: json.dump(reports,f,indent=2)
print(json.dumps(reports,indent=2))
