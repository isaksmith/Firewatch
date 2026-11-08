"""Rebuild the first-pass FireWatch inspection model with Blender --background --python.

Geometry is a proposed mechanical layout, not routed electronic design.
All distances below are millimetres. No third-party geometry is embedded.
"""
import bpy
import math
import os
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'firewatch_first_pass.blend')
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for coll in list(bpy.data.collections):
    if coll.name != 'Collection':
        bpy.data.collections.remove(coll)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 0.001
scene.unit_settings.length_unit = 'MILLIMETERS'
scene.render.engine = 'CYCLES'
scene.cycles.samples = 32
scene.cycles.use_denoising = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 1800
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.world.color = (0.65, 0.65, 0.65)
scene.view_settings.view_transform = 'AgX'
scene.frame_end = 160
scene.render.fps = 30

def material(name, color, metal=0.0, rough=.45):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Metallic'].default_value = metal
    bsdf.inputs['Roughness'].default_value = rough
    return m

shell = material('Warm ceramic | proposed polymer', (.72,.76,.74), .05)
dark = material('Graphite | seals and connectors', (.025,.038,.045))
pcb = material('Deep teal solder mask', (.012,.16,.145), .15)
gold = material('Gold | pads and plated contacts', (.76,.49,.13), .75, .27)
silver = material('Brushed aluminium | RF shield', (.52,.60,.64), .75, .3)
ink = material('Silkscreen ivory', (.83,.92,.87))
orange = material('FireWatch amber', (.95,.28,.055), .2)
cell = material('Battery wrap', (.07,.11,.15), .15)
blue = material('I2C harness', (.06,.35,.62))
red = material('Power harness', (.65,.08,.045))
ground = material('Studio porcelain', (.82,.85,.85))
guide_mat = material('Air path blue', (.07,.50,.65), .1)
LABELS = None

def collection(name):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    return c

COL = {key: collection(name) for key,name in [
    ('shell','01 | ENCLOSURE — body / lid / shield'),
    ('plate','02 | SERVICE BACKPLATE'),
    ('power','03 | POWER — common envelope, sizing TBD'),
    ('board','04 | CUSTOM CARRIER — proposed 88 × 72 mm'),
    ('gas','05 | GAS HEAD — BME688, both tiers'),
    ('pm','06 | RICH ONLY — adapter / PMSA003I / chamber'),
    ('harness','07 | HARNESS — assembled reference'),
    ('guides','08 | OPTIONAL CLEARANCE GUIDES'),
    ('labels','09 | PRESENTATION LABELS'),
    ('studio','10 | STUDIO — camera / lighting')]}

def move_to(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)

def describe(obj, role, confidence='Proposed geometry; verify before manufacture'):
    obj['Role'] = role
    obj['Dimensional status'] = confidence
    return obj

def empty(name, coll, explosion=(0,0,0)):
    o = bpy.data.objects.new(name, None)
    coll.objects.link(o)
    o.empty_display_size = 5
    for frame, loc in [(1,(0,0,0)),(35,(0,0,0)),(100,explosion),(160,explosion)]:
        o.location = loc
        o.keyframe_insert(data_path='location', frame=frame)
    return o

def cube(name, loc, size, mat, coll, parent=None, bevel=.6):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        mod = o.modifiers.new('Machined edge softness','BEVEL')
        mod.width = bevel
        mod.segments = 3
        o.modifiers.new('Weighted corner normals','WEIGHTED_NORMAL')
    o.data.materials.append(mat)
    move_to(o,coll)
    o.parent=parent
    return o

def cylinder(name, loc, radius, depth, mat, coll, parent=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=depth, location=loc)
    o=bpy.context.object
    o.name=name
    o.data.materials.append(mat)
    mod=o.modifiers.new('Edge radius','BEVEL'); mod.width=.25; mod.segments=2
    o.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
    move_to(o,coll); o.parent=parent
    return o

def text(name, body, loc, size, mat, coll, parent=None):
    data=bpy.data.curves.new(name,'FONT'); data.body=body; data.size=size
    data.extrude=.005
    o=bpy.data.objects.new(name,data); coll.objects.link(o)
    o.location=loc; o.data.materials.append(mat); o.parent=parent
    return o

def line(name, points, radius, mat, coll, parent=None):
    data=bpy.data.curves.new(name,'CURVE'); data.dimensions='3D'
    s=data.splines.new('POLY'); s.points.add(len(points)-1)
    for p,co in zip(s.points,points): p.co=(*co,1)
    data.bevel_depth=radius; data.bevel_resolution=3
    o=bpy.data.objects.new(name,data); coll.objects.link(o)
    o.data.materials.append(mat); o.parent=parent
    return o

body=empty('LAYER 01a | dry enclosure fixed',COL['shell'])
plate=empty('LAYER 02 | backplate',COL['plate'],(0,0,85))
power=empty('LAYER 03 | battery and retention',COL['power'],(0,-12,120))
board=empty('LAYER 04 | custom PCB',COL['board'],(0,0,170))
lid=empty('LAYER 01b | removable lid',COL['shell'],(0,0,230))
shield=empty('LAYER 01c | sun shield',COL['shell'],(0,0,256))
gas=empty('LAYER 05a | gas pod base',COL['gas'],(-18,0,15))
gas_sensor=empty('LAYER 05b | BME688 daughterboard',COL['gas'],(-18,0,130))
gas_hood=empty('LAYER 05c | ventilated hood',COL['gas'],(-18,0,165))
pm_base=empty('LAYER 06a | rich PM chamber base',COL['pm'],(24,0,15))
pm_sensor=empty('LAYER 06b | rich particulate sensor',COL['pm'],(24,0,130))
pm_hood=empty('LAYER 06c | rich PM hood',COL['pm'],(24,0,165))
pm_adapter=empty('LAYER 06d | rich RAK12039 adapter',COL['pm'],(0,0,187))

# Dry box: 125 X × 175 Y × 75 Z. Open shell pieces keep the interior inspectable.
describe(cube('Dry box | 125 × 175 × 75 nominal', (0,0,1.5),(125,175,3),shell,COL['shell'],body,2),
         'Common dry electronics housing','Nominal outer envelope from sensors/README; wall geometry proposed')
for name,loc,size in [
    ('Left wall',(-61,0,36),(3,175,69)),('Right wall',(61,0,36),(3,175,69)),
    ('Front wall',(0,-86,36),(119,3,69)),('Rear wall',(0,86,36),(119,3,69))]:
    cube(name,loc,size,shell,COL['shell'],body,1)
for x in [-53,53]:
    for y in [-78,78]:
        cylinder('Lid screw tower',(x,y,36),4,66,shell,COL['shell'],body)
        cylinder('Tower insert',(x,y,69.3),1.5,1,gold,COL['shell'],body)
cube('Lid | service cover',(0,0,73),(125,175,4),shell,COL['shell'],lid,2)
# Gasket represented as a closed rounded rectangular loop.
line('Perimeter gasket | conceptual seal', [(-57,-82,70.7),(57,-82,70.7),(57,82,70.7),(-57,82,70.7),(-57,-82,70.7)],1,dark,COL['shell'],lid)
for x in [-53,53]:
    for y in [-78,78]:
        cylinder('Captive lid screw',(x,y,76),2.5,2,silver,COL['shell'],lid)
cube('Opaque sun shield',(0,0,82),(131,181,2.5),shell,COL['shell'],shield,2)
text('Enclosure wordmark','FIREWATCH',(-48,-56,83.3),9,dark,COL['shell'],shield)
text('Enclosure revision','FIELD NODE  /  DESIGN 01',(-47,-66,83.3),3,dark,COL['shell'],shield)
cube('Identity accent',(-46,-36,83.4),(6,19,.5),orange,COL['shell'],shield,.2)
cube('Removable insulating backplate',(0,0,7),(108,153,2.5),dark,COL['plate'],plate,2)
for x in [-39,39]:
    for y in [-6,54]:
        cylinder('Carrier standoff',(x,y,22),2.7,27,silver,COL['plate'],plate)

# Battery envelope intentionally remains provisional; both variants share this placeholder.
describe(cube('Protected 1S battery | ENVELOPE ONLY',(0,-46,19),(68,45,20),cell,COL['power'],power,3),
         'Removable battery; 4400 mAh bare / 6600 mAh rich; verify actual pack envelope')
for x in [-22,22]:
    cube('Battery retention strap',(x,-46,30),(7,47,1.2),dark,COL['power'],power,.4)
text('Battery marking','1S  /  PACK SIZE TBD',(-27,-43,29.2),3,ink,COL['power'],power)

describe(cube('FireWatch custom carrier | proposed 88 × 72 × 1.6',(0,24,36),(88,72,1.6),pcb,COL['board'],board,1.6),
         'Common custom carrier with radio, power path and sensor interfaces')
for x in [-39,39]:
    for y in [-6,54]:
        cylinder('Carrier mounting washer',(x,y,37),2.8,.35,gold,COL['board'],board)
        cylinder('Carrier mounting screw',(x,y,38),1.7,1.5,silver,COL['board'],board)

radio=describe(cube('U1 | RAK4630 — LoRa + BLE + MCU',(-20,38,39.1),(15,23,3),silver,COL['board'],board,.4),
               'US915 radio and microcontroller','15 × 23 × 3 mm manufacturer envelope; suffix / footprint unresolved')
text('RAK module legend','RAK4630',(-26,35,40.7),2, dark,COL['board'],board)
for x in [-28.1,-11.9]:
    for y in range(29,48,2):
        cube('RAK castellated pad',(x,y,37.1),(1.2,1,.3),gold,COL['board'],board,.1)
cylinder('LoRa antenna connector',(-20,50,41),1.8,1.5,gold,COL['board'],board)
line('LoRa coax | indicative',[(-20,50,41),(-33,60,44),(-44,68,53),(-46,65,62)],.65,dark,COL['board'],board)
cube('LoRa adhesive antenna | envelope',(-46,64,54),(7,30,2),dark,COL['board'],board,.6)
text('Radio section','RADIO',(-30,21,37),2.4,ink,COL['board'],board)

for name,loc,size in [('U2 | BQ24074 charger',(-25,3,38.1),(3,3,1)),
                       ('U3 | 3.3 V buck-boost',(-13,3,38.1),(4,4,1.4)),
                       ('L1 | power inductor',(-7,4,39),(5,5,3)),
                       ('Q1 | PM load switch',(20,8,38),(2.5,2,1))]:
    describe(cube(name,loc,size,dark,COL['board'],board,.2),'Indicative power component placement; circuit and package not released')
for i in range(8):
    cube('Decoupling / charge setting passive',(-30+(i%4)*5,-3+(i//4)*11,37.4),(2,1,.7),silver,COL['board'],board,.1)
for x,label in [(-30,'SOLAR'),(-15,'BATT'),(0,'THERM'),(31,'GAS')]:
    describe(cube('J | '+label+' keyed connector',(x,-7,40),(9,6,6),shell,COL['board'],board,.5),label+' interface; pinout and part selection pending')
    text(label+' silkscreen',label,(x-4,-.5,36.9),1.7,ink,COL['board'],board)
text('Carrier identity','FIREWATCH / C01',(-35,57,37),3,ink,COL['board'],board)
text('Carrier subtitle','CONCEPT PLACEMENT  -  NOT ROUTED',(-34,52,37),1.45,ink,COL['board'],board)
text('Power section','POWER PATH',(-32,14,37),2.2,ink,COL['board'],board)
for i in range(6):
    cylinder('SWD / rail test pad',(4+i*4,18,37),1,.2,gold,COL['board'],board)
text('Debug legend','SWD / TEST',(2,13,37),1.8,ink,COL['board'],board)
# Illustrative bus traces only; deliberately sparse, no suggestion of routed design.
for i in range(3):
    line('Illustrative bus | not routed',[(-10+i*2,29,36.88),(-4+i*2,24,36.88),(22+i*2,24,36.88),(31+i*2,17,36.88)],.18,gold,COL['board'],board)

# Rich-only adapter remains an add-on, not a second custom sensor on the carrier.
describe(cube('RAK12039 | optional PM interface',(21,38,41),(25,15,1.6),pcb,COL['pm'],pm_adapter),
         'Rich-only PM adapter with 5 V boost; retained for first custom spin','25 × 15 mm adapter envelope; mounting and IO connector indicative')
cube('RAK12039 boost package',(20,37,43),(5,4,2),dark,COL['pm'],pm_adapter,.2)
cube('RAK12039 flex connector',(31,38,43),(4,11,3),shell,COL['pm'],pm_adapter,.3)
text('Adapter text','PM / RAK12039',(10,41,42),1.65,ink,COL['pm'],pm_adapter)

# External gas head; board and lid separate in inspection mode.
cube('Gas pod mounting arm',(-73,25,20),(25,8,5),shell,COL['gas'],gas)
cube('Gas pod base',(-91,25,21),(30,39,3),shell,COL['gas'],gas,2)
describe(cube('BME688 daughterboard | proposed 18 × 20',(-91,25,27),(18,20,1.2),pcb,COL['gas'],gas_sensor),
         'Replaceable external gas / temperature / humidity / pressure head')
describe(cube('U4 | BME688 — environmental sensor',(-91,25,28.15),(3,3,.93),silver,COL['gas'],gas_sensor,.1),
         'Gas resistance + temperature + RH + pressure; shaded outside air','3 × 3 × 0.93 mm Bosch package; daughterboard proposed')
cylinder('BME688 gas opening',(-91,25,28.7),.45,.05,dark,COL['gas'],gas_sensor)
text('Gas PCB legend','BME688',(-98,31,27.7),1.8,ink,COL['gas'],gas_sensor)
for y in [10,17,24,31,38]:
    cube('Gas hood louver',(-91,y,36),(34,4,2),shell,COL['gas'],gas_hood,.6)
for x in [-106,-76]:
    cube('Gas hood support',(x,25,30),(2,38,13),shell,COL['gas'],gas_hood,.5)
text('Gas hood marking','GAS / T / RH / P',(-104,38,37.1),2,dark,COL['gas'],gas_hood)

# Separate particle chamber: open in first pass to expose intake/exhaust topology.
cube('PM chamber mounting arm',(74,23,17),(26,8,5),shell,COL['pm'],pm_base)
cube('PM chamber base',(99,23,18),(49,48,3),shell,COL['pm'],pm_base,2)
for x in [77,121]:
    cube('PM chamber sidewall',(x,23,26),(3,48,16),shell,COL['pm'],pm_base)
describe(cube('PMSA003I | optical particulate sensor',(99,23,26),(38,35,12),silver,COL['pm'],pm_sensor,1),
         'Rich-only optical particulate sensor: PM1 / PM2.5 / PM10','38 × 35 × 12 mm envelope; ports shown schematically')
cube('PM sensor top label',(99,23,32.1),(28,24,.2),dark,COL['pm'],pm_sensor,.4)
text('PM sensor legend','PMSA003I',(86,23,32.3),3,ink,COL['pm'],pm_sensor)
text('PM sensor function','PARTICULATE',(86,17,32.3),2,ink,COL['pm'],pm_sensor)
for x,name in [(89,'INTAKE'),(109,'EXHAUST')]:
    cube('PM '+name+' port | schematic',(x,5,25),(9,1,7),dark,COL['pm'],pm_sensor,.8)
    cube('PM downward '+name+' hood',(x,-3,27),(13,13,3),shell,COL['pm'],pm_hood,1)
    text('Port label '+name,name,(x-5,-5,28.7),1.5,dark,COL['pm'],pm_hood)
cube('PM chamber removable roof',(99,23,37),(49,48,3),shell,COL['pm'],pm_hood,2)
text('PM hood title','RICH / PM',(81,32,38.7),3,dark,COL['pm'],pm_hood)

# Harness only depicts installed pose; animate its disappearance before explosion.
for name,points,mat in [
    ('Battery lead',[(0,-26,23),(-15,-21,27),(-15,-7,39)],red),
    ('Gas I2C',[(31,-7,40),(46,-15,28),(-66,-15,18),(-91,16,28)],blue),
    ('PM flex | simplified',[(33,38,43),(57,38,32),(70,38,24),(81,30,26)],gold)]:
    o=line(name,points,.65,mat,COL['pm'] if name.startswith('PM flex') else COL['harness'])
    for frame,hidden in [(1,False),(35,False),(36,True),(160,True)]:
        o.hide_render=hidden; o.hide_viewport=hidden
        o.keyframe_insert(data_path='hide_render',frame=frame)
        o.keyframe_insert(data_path='hide_viewport',frame=frame)

# Optional symbolic keepouts. Hidden by default and excluded from rendering.
for name,loc,size in [('Radio clearance | indicative',(-25,52,45),(42,40,20)),
                      ('Battery service access',(0,-46,35),(75,53,40))]:
    o=cube(name,loc,size,guide_mat,COL['guides'],bevel=0)
    o.display_type='WIRE'; o.hide_render=True
COL['guides'].hide_viewport=True
COL['guides'].hide_render=True

# Labels are separate from physical geometry and can be toggled as a group.
for label,loc,parent in [
    ('01  DRY ENCLOSURE',(-51,-70,4),body),
    ('02  SERVICE BACKPLATE',(-46,-70,8.5),plate),
    ('03  REMOVABLE POWER',(-32,-74,32),power),
    ('04  CUSTOM CARRIER',(-36,-21,38),board),
    ('05  EXTERNAL GAS HEAD',(-112,-1,30),gas_sensor),
    ('06  RICH-ONLY PM',(77,49,33),pm_sensor)]:
    text('Inspection label | '+label,label,loc,3,dark,COL['pm'] if label.startswith('06') else COL['labels'],parent)

# Studio camera, background and lighting.
cube('Studio floor',(0,0,-5),(20000,20000,4),ground,COL['studio'],bevel=0)
def aim(o, target):
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(420,-540,490))
camera=bpy.context.object; camera.name='Inspection camera | orthographic'
move_to(camera,COL['studio']); camera.data.type='ORTHO'; camera.data.ortho_scale=490
aim(camera,(0,0,166)); scene.camera=camera
camera.data.clip_end=100000
for frame,target,scale in [(1,(0,0,42),320),(35,(0,0,42),320),(100,(0,0,166),490),(160,(0,0,166),490)]:
    aim(camera,target)
    camera.keyframe_insert(data_path='rotation_euler',frame=frame)
    camera.data.ortho_scale=scale
    camera.data.keyframe_insert(data_path='ortho_scale',frame=frame)
bpy.ops.object.camera_add(location=(125,-135,170))
pcb_camera=bpy.context.object; pcb_camera.name='PCB inspection camera | select then Ctrl Numpad 0'
move_to(pcb_camera,COL['studio']); pcb_camera.data.type='ORTHO'; pcb_camera.data.ortho_scale=130
pcb_camera.data.clip_end=100000
aim(pcb_camera,(0,25,38))
for name,loc,power,size in [('Key softbox',(120,-190,440),2300000,280),
                            ('Fill softbox',(-280,-30,230),1600000,230),
                            ('Rim softbox',(70,260,360),2600000,200)]:
    bpy.ops.object.light_add(type='AREA',location=loc)
    o=bpy.context.object; o.name=name; o.data.energy=power; o.data.shape='DISK'; o.data.size=size
    move_to(o,COL['studio']); aim(o,(0,0,80))
for frame,label in [(1,'ASSEMBLED — both tiers share carrier'),(35,'START EXPLOSION'),(100,'EXPLODED — inspect layers'),(160,'EXPLODED HOLD')]:
    scene.timeline_markers.new(label,frame=frame)
scene['README']='Frame 1 = assembled; Frame 100 = exploded. Space plays transition. Hide collection 06 for bare tier; battery/solar sizing remains provisional. See cad/README.md.'
scene['PCB status']='Concept component placement only. No schematic, routing, footprint or RF sign-off.'
scene['Tier']='Rich default; hide 06 | RICH ONLY for bare inspection. See Bare view layer.'

# Share identical primitive meshes for repeated fasteners/passives and use explicit names.
mesh_library={}
for o in list(scene.objects):
    if o.type=='MESH':
        o.name='SM_'+o.name
        signature=(tuple(tuple(round(v,5) for v in vert.co) for vert in o.data.vertices),
                   tuple(tuple(p.vertices) for p in o.data.polygons),
                   tuple(m.name for m in o.data.materials))
        if signature in mesh_library: o.data=mesh_library[signature]
        else: mesh_library[signature]=o.data

# Two view layers: same shared geometry, rich-only components excluded in Bare.
rich=scene.view_layers[0]; rich.name='RICH | complete assembly'
bare=scene.view_layers.new('BARE | no particulate assembly')
bare.layer_collection.children[COL['pm'].name].exclude=True
bare.use=False
# Save an approachable workspace with material colors and collection visibility controls.
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            space=area.spaces.active
            space.shading.type='MATERIAL'
            space.overlay.show_floor=False
            space.overlay.show_axis_x=False; space.overlay.show_axis_y=False
            space.clip_end=5000
            space.region_3d.view_perspective='CAMERA'
        elif area.type=='OUTLINER':
            area.spaces.active.show_restrict_column_hide=True
            area.spaces.active.show_restrict_column_render=True
        elif area.type=='PROPERTIES':
            area.spaces.active.context='OBJECT'

scene.frame_set(100)
bpy.ops.object.select_all(action='DESELECT')
radio.select_set(True); bpy.context.view_layer.objects.active=radio
bpy.ops.wm.save_as_mainfile(filepath=OUT)

def render(name,frame,rich_visible=True):
    scene.frame_set(frame)
    COL['pm'].hide_render=not rich_visible
    # Hide the particulate inspection label in bare previews as well.
    for o in COL['labels'].objects:
        if '06  RICH-ONLY' in o.name: o.hide_render=not rich_visible
    scene.render.filepath=os.path.join(ROOT,'renders',name+'.png')
    bpy.ops.render.render(write_still=True)

if not os.environ.get('FIREWATCH_DETAIL_ONLY'):
    render('rich_exploded',100)
    render('rich_assembled',1)
    render('bare_exploded',100,False)
COL['pm'].hide_render=False
for o in COL['labels'].objects: o.hide_render=False
scene.frame_set(1)
scene.camera=pcb_camera
for key in ['shell','plate','power','gas','harness','labels']:
    COL[key].hide_render=True
pm_visibility={o:o.hide_render for o in COL['pm'].objects}
for o in COL['pm'].objects:
    if o.parent != pm_adapter and o != pm_adapter: o.hide_render=True
pm_flex=bpy.data.objects['PM flex | simplified']
pm_flex.data.bevel_depth=0  # Animation keys otherwise re-enable this installed harness.
scene.render.filepath=os.path.join(ROOT,'renders','custom_pcb_detail.png')
bpy.ops.render.render(write_still=True)
pm_flex.data.bevel_depth=.65
for key in ['shell','plate','power','gas','harness','labels']:
    COL[key].hide_render=False
for o,hidden in pm_visibility.items(): o.hide_render=hidden
scene.camera=camera
scene.frame_set(100)
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print('FIREWATCH_BUILD_COMPLETE',OUT)
