"""Extend the retained first pass with component detail, solar and two mount options.

Uses Blender's Python API, millimetre modeling coordinates, and the prior .blend
as a reproducible input. Does not overwrite the first-pass model.
"""
import bpy
import os
import math
import json
from mathutils import Vector, Matrix

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bpy.ops.wm.open_mainfile(filepath=os.path.join(ROOT,'firewatch_first_pass.blend'))
inspection=bpy.context.scene
inspection.name='01 | LAYER INSPECTION — Rich / Bare'
inspection.frame_set(1)
bpy.context.view_layer.update()
COL={k: next(c for c in inspection.collection.children if c.name.startswith(prefix))
     for k,prefix in [('shell','01 |'),('plate','02 |'),('power','03 |'),('board','04 |'),
                      ('gas','05 |'),('pm','06 |'),('harness','07 |'),('labels','09 |'),('studio','10 |')]}
MAT={k:bpy.data.materials[name] for k,name in [
    ('shell','Warm ceramic | proposed polymer'),('dark','Graphite | seals and connectors'),
    ('pcb','Deep teal solder mask'),('gold','Gold | pads and plated contacts'),
    ('silver','Brushed aluminium | RF shield'),('ink','Silkscreen ivory'),
    ('orange','FireWatch amber'),('blue','I2C harness'),('ground','Studio porcelain')]}

def material(name,color,metal=0,rough=.45):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.use_nodes=True
    p=m.node_tree.nodes.get('Principled BSDF'); p.inputs['Base Color'].default_value=(*color,1)
    p.inputs['Metallic'].default_value=metal; p.inputs['Roughness'].default_value=rough
    return m
MAT['solar']=material('Solar cells | navy monocrystalline',(.012,.035,.080),.35,.24)
MAT['band']=material('Adjustable woven band | charcoal',(.045,.055,.048),0,.8)
MAT['rubber']=material('Saddle contact pad',(.045,.052,.049),0,.9)
MAT['pole']=material('Reference pole | muted grey',(.27,.32,.30),.15,.7)
MAT['soil']=material('Ground reference',(.32,.35,.30),0,1)

def coll(name,scene=inspection):
    c=bpy.data.collections.new(name); scene.collection.children.link(c); return c
for k,n in [('solar','11 | SOLAR — shared bracket / cable'),('sr','12 | SOLAR — Rich P105 5 W'),
            ('sb','13 | SOLAR — Bare P126 2 W'),('mount','14 | SHARED REAR MOUNT INTERFACE'),
            ('band','15 | OPTION A — adjustable tree / pole bands'),
            ('stake','16 | OPTION B — ground stake'),('context','17 | POLE REFERENCE — not hardware')]:
    COL[k]=coll(n)

def link(o,c):
    for cc in list(o.users_collection): cc.objects.unlink(o)
    c.objects.link(o)

def cube(name,loc,size,mat,c,parent=None,bevel=.3):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc)
    o=bpy.context.object; o.name='SM_V2 | '+name; o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    if bevel:
        m=o.modifiers.new('Edge finish','BEVEL'); m.width=bevel; m.segments=2
        o.modifiers.new('Corner normals','WEIGHTED_NORMAL')
    o.data.materials.append(MAT[mat]); link(o,c); o.parent=parent
    return o

def cyl(name,loc,radius,depth,mat,c,parent=None,axis='Z'):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=radius,depth=depth,location=loc)
    o=bpy.context.object; o.name='SM_V2 | '+name
    if axis=='Y': o.rotation_euler.x=math.pi/2
    if axis=='X': o.rotation_euler.y=math.pi/2
    o.data.materials.append(MAT[mat]); link(o,c); o.parent=parent
    return o

def beam(name,a,b,width,depth,mat,c,parent=None):
    a,b=Vector(a),Vector(b)
    o=cube(name,(a+b)/2,(width,depth,(b-a).length),mat,c,parent)
    o.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler(); return o

def empty(name,c,loc=(0,0,0)):
    o=bpy.data.objects.new(name,None); c.objects.link(o); o.location=loc; o.empty_display_size=5
    return o

def label(name,body,loc,size,c,parent=None,mat='ink'):
    data=bpy.data.curves.new(name,'FONT'); data.body=body; data.size=size; data.extrude=.003
    o=bpy.data.objects.new('TXT_V2 | '+name,data); c.objects.link(o)
    o.location=loc; o.parent=parent; data.materials.append(MAT[mat]); return o

def path(name,points,radius,mat,c,parent=None):
    data=bpy.data.curves.new(name,'CURVE'); data.dimensions='3D'; data.bevel_depth=radius; data.bevel_resolution=2
    spl=data.splines.new('POLY'); spl.points.add(len(points)-1)
    for p,xyz in zip(spl.points,points): p.co=(*xyz,1)
    o=bpy.data.objects.new('CURVE_V2 | '+name,data); c.objects.link(o)
    o.data.materials.append(MAT[mat]); o.parent=parent; return o

def screw(name,loc,c,parent=None,r=1.2,axis='Z'):
    o=cyl(name,loc,r,.65,'silver',c,parent,axis)
    slot=cube(name+' drive slot',loc,(r*1.4,.25,.10),'dark',c,parent,0)
    if axis=='Z': slot.location.z+=.35
    if axis=='Y': slot.rotation_euler.x=math.pi/2; slot.location.y-=.35
    return o

# Refine existing component envelopes without changing the declared sensor sizes.
bpy.data.objects['Battery marking'].data.body='BATTERY PACK'
COL['power'].name='03 | POWER — battery pack / retention'
battery=bpy.data.objects['SM_Protected 1S battery | ENVELOPE ONLY']
battery['Display label']='BATTERY PACK'
battery['Dimensional status']='Common visual envelope; actual 4400/6600 mAh pack dimensions still require validation'
gas_parent=bpy.data.objects['LAYER 05b | BME688 daughterboard']
board_parent=bpy.data.objects['LAYER 04 | custom PCB']
adapter_parent=bpy.data.objects['LAYER 06d | rich RAK12039 adapter']
pm_parent=bpy.data.objects['LAYER 06b | rich particulate sensor']

# BME688: package lip, pin-one mark, surrounding decoupling and keyed cable socket.
cube('BME688 package base',(-91,25,27.72),(3.1,3.1,.15),'dark',COL['gas'],gas_parent,.05)
for x in [-92.65,-89.35]:
    for y in [24.1,24.7,25.3,25.9]:
        cube('BME688 exposed pad indication',(x,y,27.74),(.35,.32,.16),'gold',COL['gas'],gas_parent,.02)
cyl('BME688 pin-one marking',(-92,24,28.64),.15,.02,'dark',COL['gas'],gas_parent)
for x,y in [(-97,23),(-97,26),(-86,23),(-86,27)]:
    cube('Gas head passive body',(x,y,28.02),(1.5,.8,.65),'dark',COL['gas'],gas_parent,.08)
    for dx in [-.65,.65]: cube('Passive solder termination',(x+dx,y,27.95),(.35,.9,.5),'silver',COL['gas'],gas_parent,.04)
for x in [-98,-84]:
    for y in [17,33]:
        cyl('Gas board mounting annulus',(x,y,27.65),.85,.1,'gold',COL['gas'],gas_parent)
        cyl('Gas board mounting hole indication',(x,y,27.72),.45,.1,'dark',COL['gas'],gas_parent)
cube('Gas head keyed cable socket',(-91,17.7,28.8),(6,3.5,2.4),'shell',COL['gas'],gas_parent,.2)
cube('Gas head socket opening',(-91,16,28.85),(4.7,.12,1.4),'dark',COL['gas'],gas_parent,.05)
for x in [-92.5,-91.5,-90.5,-89.5]: cube('Gas socket contact',(x,15.9,28.8),(.25,.2,.7),'gold',COL['gas'],gas_parent,.02)
label('Gas electrical legend','3V3 GND SDA SCL',(-98,20,27.69),.8,COL['gas'],gas_parent)
label('Gas sensor role','ENVIRONMENT',(-98,28.5,27.69),.9,COL['gas'],gas_parent)

# PM body: seam, fasteners, real-depth port grilles and connector detail.
for x in [81,117]: cube('PMSA003I folded case seam',(x,23,31.8),(.45,33,.45),'dark',COL['pm'],pm_parent,.08)
for x in [83,115]:
    for y in [9,37]: screw('PMSA003I case screw',(x,y,32.3),COL['pm'],pm_parent,.8)
for center in [89,109]:
    # The dark port already present is the recess back; narrow ribs sit in front.
    for x in [center-3,center-1.5,center,center+1.5,center+3]:
        cube('PM intake/exhaust grille rib',(x,4.35,25),(.4,.4,5.5),'silver',COL['pm'],pm_parent,.08)
cube('PM chamber upper rain cap',(99,48,28),(49,3,20),'shell',COL['pm'],bpy.data.objects['LAYER 06a | rich PM chamber base'],.7)
cube('Gas pod upper rain cap',(-91,45,30),(34,3,16),'shell',COL['gas'],bpy.data.objects['LAYER 05c | ventilated hood'],.7)
cube('PMSA003I flex socket',(118.3,28,25.5),(1.8,12,4),'dark',COL['pm'],pm_parent,.2)
for y in range(24,33): cube('PM flex contact',(119.3,y,25.7),(.3,.45,2),'gold',COL['pm'],pm_parent,.03)
label('PM serial label','FW / PM / 001',(87,12,32.32),1.15,COL['pm'],pm_parent)
for i,height in enumerate([3,4,3,4,4,3,4,3,4,4,3,4]):
    cube('PM ID barcode',(86+i*.65,29,32.32),(.3,height,.03),'ink',COL['pm'],pm_parent,0)

# More legible adapter and carrier detail; pin patterns are illustrative, not footprints.
for x in [11,14,17,24,27]:
    cube('PM adapter capacitor',(x,34,42.3),(1.8,.9,.7),'silver',COL['pm'],adapter_parent,.1)
cube('PM boost inductor',(25,38,43.5),(3.5,3.5,2.5),'dark',COL['pm'],adapter_parent,.25)
label('PM inductor marking','4R7',(23.7,37.6,44.78),.9,COL['pm'],adapter_parent)
for y in [32,44]: screw('PM adapter fixing',(11,y,42.4),COL['pm'],adapter_parent,.9)
for x in range(14,29,2): cube('PM connector solder pad',(x,31,41.9),(1,.7,.2),'gold',COL['pm'],adapter_parent,.05)
for cx,cy,sz in [(-25,3,3),(-13,3,4),(20,8,2.5)]:
    for side in [-1,1]:
        for dy in [-.9,0,.9]:
            cube('Power IC solder lead',(cx+side*(sz/2+.35),cy+dy,37.2),(.6,.35,.25),'silver',COL['board'],board_parent,.04)
for x in [-30,-15,0,31]:
    cube('Keyed connector recessed mouth',(x,-10.05,40),(6.8,.18,3.6),'dark',COL['board'],board_parent,.1)
    for dx in [-2,0,2]: cube('Keyed connector contact',(x+dx,-10.2,39.6),(.45,.3,1.6),'gold',COL['board'],board_parent,.04)
for x in [-26,-14]:
    for y in [29,47]: screw('RF shield weld indication',(x,y,40.65),COL['board'],board_parent,.3)
for x in range(0,34,4):
    cyl('Carrier plated test via',(x,47,36.92),.42,.12,'gold',COL['board'],board_parent)
    cyl('Carrier via drill indication',(x,47,37),.2,.05,'dark',COL['board'],board_parent)

# Shared rear interface: crossbars attach to enclosure rear (local Z=0).
for y in [-55,55]:
    for x in [-35,35]:
        cube('Enclosure rear spacer',(x,y,-2),(14,16,4),'rubber',COL['mount'])
    cube('Rear load spreader',(0,y,-6),(90,20,5),'silver',COL['mount'])
    for x in [-35,35]: screw('Rear interface fastener',(x,y,-8.8),COL['mount'],r=2)
rail=cube('Shared mounting spine',(0,0,-12),(32,190,8),'dark',COL['mount'])
rail['Interface']='Common to both tiers; choose band saddle OR stake adapter'
rail['Status']='Concept mount; load and fastener selection not validated'

# Solar bracket connects to the mounting spine, not the hot electronics lid.
solar_root=empty('SOLAR | common inspection movement',COL['solar'])
for f,xyz in [(1,(0,0,0)),(35,(0,0,0)),(100,(-160,0,80)),(160,(-160,0,80))]:
    solar_root.location=xyz; solar_root.keyframe_insert(data_path='location',frame=f)
for x in [-45,45]:
    beam('Solar bracket support',(x,55,-6),(x,185,32),8,5,'silver',COL['solar'],solar_root)
    beam('Solar rail crossbar',(x,55,-6),(0,55,-12),6,5,'silver',COL['solar'],solar_root)
cyl('Solar tilt axle',(0,185,32),4,105,'silver',COL['solar'],solar_root,'X')
for x in [-53,53]: cyl('Solar tilt lock',(x,185,32),7,5,'dark',COL['solar'],solar_root,'X')
for key,width,length,thickness,power_name in [('sr',137,222,4,'P105 / 5 W'),('sb',112,136,2.7,'P126 / 2 W')]:
    p=empty('PANEL | '+power_name,COL[key],(0,185,40))
    p.rotation_euler.x=math.radians(-35); p.parent=solar_root
    panel=cube('Solar panel substrate | '+power_name,(0,0,0),(width,length,thickness),'dark',COL[key],p,.7)
    panel['Vendor envelope mm']=[width,length,thickness]
    panel['Source']='https://www.adafruit.com/product/'+('5367' if key=='sr' else '5366')
    panel['Detail status']='Envelope from vendor; cell pattern, mounting and hinge geometry illustrative'
    cube('Solar rear pivot brace',(0,0,-thickness/2-3),(103,16,6),'silver',COL[key],p,.5)
    rows=6 if key=='sr' else 4
    for row in range(rows):
        for col in range(3):
            cw=(width-18)/3; ch=(length-23)/rows
            x=(col-1)*cw; y=(row-(rows-1)/2)*ch
            cube('Solar cell',(x,y,thickness/2+.1),(cw-1.2,ch-1.2,.2),'solar',COL[key],p,.5)
            for dx in [-cw/4,cw/4]:
                cube('Cell collector ribbon',(x+dx,y,thickness/2+.24),(.25,ch-2,.07),'silver',COL[key],p,0)
    for x in [-(width/2-6),width/2-6]:
        for y in [-(length/2-6),length/2-6]: screw('Solar mounting eyelet',(x,y,thickness/2+.2),COL[key],p,1.5)
    label('Panel rating '+power_name,power_name,(-width/2+12,-length/2+3,thickness/2+.3),3,COL[key],p)
    cube('Solar rear junction box',(0,-30,-thickness/2-4),(25,18,8),'dark',COL[key],p,1)
path('Solar lead / drip loop',[(0,157,52.3),(40,145,10),(65,10,-15),(58,-102,5),(36,-106,8),(30,-86,12)],1.1,'dark',COL['solar'],solar_root)

# Option A: two adjustable annular bands, an example pole and a cushioned saddle.
def band_ring(y):
    verts=[]; faces=[]; N=96; outer=66; inner=64; cz=-92; halfwidth=7
    for i in range(N):
        t=2*math.pi*i/N
        for r,dy in [(inner,-halfwidth),(outer,-halfwidth),(outer,halfwidth),(inner,halfwidth)]:
            verts.append((r*math.sin(t),y+dy,cz+r*math.cos(t)))
    for i in range(N):
        j=(i+1)%N
        for k in range(4): faces.append((4*i+k,4*j+k,4*j+(k+1)%4,4*i+(k+1)%4))
    mesh=bpy.data.meshes.new('Continuous band ribbon'); mesh.from_pydata(verts,[],faces); mesh.update()
    o=bpy.data.objects.new('SM_V2 | Adjustable wraparound band',mesh); COL['band'].objects.link(o); mesh.materials.append(MAT['band'])
    o['Adjustment']='Illustrative 128 mm ID loop; buckle and tail suggest adjustment, not a rigged diameter control'
for y in [-55,55]:
    cube('Band saddle cushion',(0,y,-22),(48,23,12),'rubber',COL['band'],bevel=2)
    band_ring(y)
    cube('Band cam buckle',(65,y,-92),(10,20,14),'silver',COL['band'],bevel=1.2)
    cube('Buckle release tab',(70,y,-92),(3,12,8),'dark',COL['band'])
    cube('Band adjustment tail',(64,y+23,-92),(2,35,14),'band',COL['band'],bevel=.4)
    for dy in range(13,39,4): cube('Band tail weave indication',(65.1,y+dy,-92),(.15,.7,10),'silver',COL['band'],bevel=0)
cyl('Example pole / tree envelope',(0,0,-92),63.5,520,'pole',COL['context'],axis='Y')

# Option B: square-section stake with depth stop, foot bar, anti-rotation fin and tip.
for y in [-55,55]:
    cube('Stake saddle bridge',(0,y,-17),(40,23,4),'silver',COL['stake'])
    cube('Stake retention collar',(0,y,-28),(30,25,27),'dark',COL['stake'],bevel=1)
    for x in [-20,20]: screw('Stake adapter fixing',(x,y,-14.7),COL['stake'],r=2)
shaft=cube('Ground stake shaft',(0,-420,-28),(20,960,20),'silver',COL['stake'],bevel=.8)
shaft['Stake concept']='Node center 700 mm above grade; 300 mm pointed embedment shown'
shaft['Status']='Concept dimensions; soil stability, wind loads and installation force untested'
cube('Ground stake foot bar',(0,-650,-28),(135,15,24),'dark',COL['stake'],bevel=1)
cube('Stake depth collar',(0,-700,-28),(34,15,34),'orange',COL['stake'],bevel=1)
cube('Anti-rotation ground fin',(0,-820,-28),(75,160,3),'silver',COL['stake'],bevel=.6)
v=[(-10,-900,-38),(10,-900,-38),(10,-900,-18),(-10,-900,-18),(0,-1000,-28)]
f=[(3,2,1,0),(0,1,4),(1,2,4),(2,3,4),(3,0,4)]
me=bpy.data.meshes.new('Stake pointed tip'); me.from_pydata(v,[],f); me.update()
o=bpy.data.objects.new('SM_V2 | Ground stake pointed tip',me); COL['stake'].objects.link(o); me.materials.append(MAT['silver'])

# Main inspection view retains animated layers; mount options are available but excluded.
for vl in inspection.view_layers:
    bpy.context.view_layer.update()
    for k in ['mount','band','stake','context']: vl.layer_collection.children[COL[k].name].exclude=True
    vl.layer_collection.children[COL['sb' if vl.name.startswith('RICH') else 'sr'].name].exclude=True
inspection['Revision']='02 — detailed components, clean battery label, tier solar panels, two external mount options'
inspection['Navigation']='Use Scene dropdown for layer inspection, Rich/Bare band mount, or Rich/Bare ground stake.'
main_cam=inspection.camera
main_cam.animation_data_clear(); main_cam.data.animation_data_clear()
for frame,target,scale in [(1,(0,0,42),320),(35,(0,0,42),320),(100,(0,0,166),490),(160,(0,0,166),490)]:
    main_cam.rotation_euler=(Vector(target)-main_cam.location).to_track_quat('-Z','Y').to_euler()
    main_cam.keyframe_insert(data_path='rotation_euler',frame=frame)
    main_cam.data.ortho_scale=scale; main_cam.data.keyframe_insert(data_path='ortho_scale',frame=frame)

# Upright deployment snapshots: local +Y becomes world up, lid faces world -Y.
inspection.frame_set(1); bpy.context.view_layer.update()
deploy=Matrix.Translation((0,0,700)) @ Matrix.Rotation(math.pi/2,4,'X')
inspection.view_layers[0].layer_collection.children[COL['sb'].name].exclude=False
bpy.context.view_layer.update()
sources={k:[(o,o.matrix_world.copy()) for o in c.objects if o.type not in {'EMPTY','CAMERA','LIGHT'} and not o.name.startswith('Inspection label')]
         for k,c in COL.items() if k not in {'studio','labels'}}
inspection.view_layers[0].layer_collection.children[COL['sb'].name].exclude=True
for vl in inspection.view_layers:
    for key in ['solar','sr','sb']:
        vl.layer_collection.children[COL[key].name].exclude=True
deployment_scenes=[]
def set_scene(sc):
    bpy.context.window.scene=sc

def camera(sc,name,loc,target,scale,c):
    bpy.ops.object.camera_add(location=loc)
    cam=bpy.context.object; cam.name=name; cam.data.type='ORTHO'; cam.data.ortho_scale=scale
    cam.data.clip_end=100000; cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
    link(cam,c); sc.camera=cam; return cam

def studio(sc,is_stake):
    c=coll('STUDIO | '+sc.name,sc)
    cube('Ground plane',(0,0,-3),(20000,20000,6),'ground',c,bevel=0)
    for loc,energy,size in [((200,-500,1400),10000000,600),((-650,-100,1100),6500000,500),((50,550,1400),10000000,500)]:
        bpy.ops.object.light_add(type='AREA',location=loc); o=bpy.context.object
        o.name='Deployment softbox'; o.data.energy=energy; o.data.shape='DISK'; o.data.size=size
        o.rotation_euler=(Vector((0,0,650))-o.location).to_track_quat('-Z','Y').to_euler(); link(o,c)
    if is_stake:
        camera(sc,'Ground stake camera',(650,-1050,1100),(0,0,500),1220,c)
        # Grade line disc differentiates the 300 mm embedded portion; tip remains inspectable by hiding ground.
        cyl('Grade reference disc',(0,28,.4),180,.8,'soil',c)
    else:
        camera(sc,'Band mount camera',(520,-850,1130),(0,0,785),680,c)
        camera(sc,'Band rear inspection camera',(550,650,1050),(0,25,760),650,c)
        sc.camera=bpy.data.objects.get('Band mount camera') if sc.name.startswith('02') else next(o for o in c.objects if o.name.startswith('Band mount camera'))
    return c

for index,tier,mount in [(2,'Rich','band'),(3,'Bare','band'),(4,'Rich','stake'),(5,'Bare','stake')]:
    sc=bpy.data.scenes.new(f'{index:02} | {tier.upper()} — '+('BAND MOUNT' if mount=='band' else 'GROUND STAKE'))
    set_scene(sc); sc.unit_settings.system='METRIC'; sc.unit_settings.scale_length=.001; sc.unit_settings.length_unit='MILLIMETERS'
    sc.world=inspection.world; sc.render.engine='CYCLES'; sc.cycles.samples=24; sc.cycles.use_denoising=True
    sc.render.resolution_x=1400; sc.render.resolution_y=1600; sc.render.resolution_percentage=100
    sc.render.image_settings.file_format='PNG'; sc.view_settings.view_transform='AgX'
    keys=['shell','plate','power','board','gas','harness','mount','solar','sr' if tier=='Rich' else 'sb',mount]
    if tier=='Rich': keys.append('pm')
    if mount=='band': keys.append('context')
    for k in keys:
        c=coll(COL[k].name+' | '+tier+' '+mount,sc)
        for src,world in sources[k]:
            o=src.copy(); o.animation_data_clear(); o.parent=None
            o.name=sc.name.split(' | ')[0]+'::'+src.name
            c.objects.link(o); o.matrix_world=deploy@world
            o.hide_render=False; o.hide_viewport=False
    studio(sc,mount=='stake')
    sc['Tier']=tier; sc['Mount']=mount
    sc['Pose']='Static assembled deployment snapshot; edits to original meshes are shared, object transforms are independent'
    sc['Ground']='Grade Z=0; stake penetrates to Z=-300; hide ground plane to inspect tip'
    deployment_scenes.append(sc)

set_scene(inspection)
inspection.frame_set(100)
# Keep all workspaces in the active scene camera; scene switching remains in the top dropdown.
for screen in bpy.data.screens:
    for a in screen.areas:
        if a.type=='VIEW_3D':
            a.spaces.active.region_3d.view_perspective='CAMERA'
            a.spaces.active.clip_end=100000
            a.spaces.active.shading.type='MATERIAL'
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ROOT,'firewatch_revision2.blend'))

def render(sc,name,cam=None):
    set_scene(sc)
    if cam: sc.camera=cam
    sc.render.filepath=os.path.join(ROOT,'renders',name+'.png')
    bpy.ops.render.render(write_still=True)

render(inspection,'v2_rich_exploded')
rich_band=deployment_scenes[0]
render(rich_band,'v2_rich_band')
rear=next(o for o in rich_band.objects if o.name.startswith('Band rear inspection camera'))
render(rich_band,'v2_band_rear',rear)
rich_band.camera=next(o for o in rich_band.objects if o.name.startswith('Band mount camera'))
render(deployment_scenes[2],'v2_rich_stake')
render(deployment_scenes[3],'v2_bare_stake')

# Sensor close-up uses the original carrier camera with shells hidden temporarily.
set_scene(inspection); inspection.frame_set(1)
saved_cam=inspection.camera
inspection.camera=bpy.data.objects['PCB inspection camera | select then Ctrl Numpad 0']
for key in ['shell','plate','power','gas','harness','labels','solar','sr','sb']: COL[key].hide_render=True
pm_flex=bpy.data.objects['PM flex | simplified']; old_depth=pm_flex.data.bevel_depth; pm_flex.data.bevel_depth=0
pm_hidden={o:o.hide_render for o in COL['pm'].objects}
for o in COL['pm'].objects:
    if o.parent!=adapter_parent: o.hide_render=True
render(inspection,'v2_carrier_detail')
pm_flex.data.bevel_depth=old_depth
for o,v in pm_hidden.items(): o.hide_render=v
for key in ['shell','plate','power','gas','harness','labels','solar','sr','sb']: COL[key].hide_render=False

# Gas head close-up: show the actual tiny sensor package and daughterboard detail.
inspection.camera=bpy.data.objects['PCB inspection camera | select then Ctrl Numpad 0']
cam=inspection.camera; cam_matrix=cam.matrix_world.copy(); old_scale=cam.data.ortho_scale
cam.location=(-55,-17,76); cam.rotation_euler=(Vector((-91,25,28))-cam.location).to_track_quat('-Z','Y').to_euler(); cam.data.ortho_scale=38
for key in ['shell','plate','power','board','pm','harness','labels','solar','sr','sb']: COL[key].hide_render=True
gas_hidden={o:o.hide_render for o in COL['gas'].objects}
for o in COL['gas'].objects:
    if o.parent!=gas_parent: o.hide_render=True
render(inspection,'v2_gas_head_detail')
for o,v in gas_hidden.items(): o.hide_render=v
for key in ['shell','plate','power','board','pm','harness','labels','solar','sr','sb']: COL[key].hide_render=False
cam.matrix_world=cam_matrix; cam.data.ortho_scale=old_scale
inspection.camera=saved_cam; inspection.frame_set(100)
set_scene(inspection)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ROOT,'firewatch_revision2.blend'))
print('FIREWATCH_REVISION_2_COMPLETE')
