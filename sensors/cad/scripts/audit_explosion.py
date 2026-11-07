"""Check inter-assembly mesh intersections along the browser's actual paths."""
import bpy
import os
import json
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from itertools import combinations
CAD=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWER=os.path.join(os.path.dirname(CAD),'viewer')
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.join(VIEWER,'assets','firewatch.glb'))
with open(os.path.join(VIEWER,'explosion-paths.json')) as f: paths=json.load(f)['assemblies']
bpy.context.view_layer.update()
objects=[o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('assembly')]
def offset(assembly,t):
    p=paths[assembly]
    return Vector([v*t/1000 for v in p.get('mountedExtract',p['extract'])])
def grouped(tier,mount):
    groups={}
    for o in objects:
        if o.get('tier') not in ['both',tier]: continue
        if o.get('mount') not in ['both',mount]: continue
        if o.get('assembly')=='wiring': continue
        group=groups.setdefault(o['assembly'],{'vertices':[],'polygons':[]})
        mesh=o.data; mesh.calc_loop_triangles(); base=len(group['vertices'])
        group['vertices'].extend([o.matrix_world@v.co for v in mesh.vertices])
        group['polygons'].extend([tuple(base+i for i in tri.vertices) for tri in mesh.loop_triangles])
    return groups
def trees(groups,t):
    return {name:BVHTree.FromPolygons([v+offset(name,t) for v in g['vertices']],g['polygons'],all_triangles=True,epsilon=0)
            for name,g in groups.items()}
report={}
all_issues=[]
samples=[] if os.environ.get('FIREWATCH_PREVIEW_ONLY') else [.005]+[i/100 for i in range(1,101)]
for tier,mount in [('bare','band'),('rich','band'),('bare','stake'),('rich','stake')]:
    groups=grouped(tier,mount); pairs=list(combinations(groups,2))
    baseline_trees=trees(groups,0)
    baseline={f'{a}/{b}':len(baseline_trees[a].overlap(baseline_trees[b])) for a,b in pairs}
    issues=[]
    for t in samples:
        current=trees(groups,t)
        for a,b in pairs:
            count=len(current[a].overlap(current[b])); previous=baseline[f'{a}/{b}']
            if count and (not previous or count>previous*1.2+4):
                issues.append({'slider':round(t*100,1),'pair':f'{a}/{b}','intersections':count,'assembled_intersections':previous})
    report[f'{tier}/{mount}']={'samples':len(samples),'baseline_contacts':{k:v for k,v in baseline.items() if v},'new_or_increased_intersections':issues}
    all_issues.extend(issues)
report['method']='Triangle BVH overlap between rigid assemblies, using actual exported GLB. Existing CAD contacts recorded separately. Rigid view rotations do not alter intersections.'
report['result']='PASS' if not all_issues else 'NEEDS_REPAIR'
if not os.environ.get('FIREWATCH_PREVIEW_ONLY'):
    with open(os.path.join(VIEWER,'assets','explosion-audit.json'),'w') as f:json.dump(report,f,indent=2)
    print('EXPLOSION_AUDIT',json.dumps(report))
if os.environ.get('FIREWATCH_PATH_PREVIEW'):
    from mathutils import Matrix
    for o in list(objects):
        if o.get('tier')=='bare' or o.get('mount')=='stake' or o.get('assembly')=='wiring':
            o.hide_render=True; continue
        move=offset(o['assembly'],.7)
        o.matrix_world=Matrix.Rotation(1.57079632679,4,'X')@o.matrix_world
        o.location+=Matrix.Rotation(1.57079632679,3,'X')@move
    scene=bpy.context.scene
    scene.render.engine='CYCLES';scene.cycles.samples=16;scene.cycles.use_denoising=True
    scene.render.resolution_x=1400;scene.render.resolution_y=1200;scene.render.resolution_percentage=100
    if scene.world is None: scene.world=bpy.data.worlds.new('Path preview world')
    scene.world.color=(.65,.65,.65)
    for pos,energy,size in [((1,-1.5,2),180,2),((-1,-.2,1),90,2),((0,1,2),150,2)]:
        bpy.ops.object.light_add(type='AREA',location=pos);o=bpy.context.object;o.data.energy=energy;o.data.shape='DISK';o.data.size=size
        o.rotation_euler=(Vector((0,-.15,.12))-o.location).to_track_quat('-Z','Y').to_euler()
    bpy.ops.object.camera_add(location=(1,-1.7,1))
    scene.camera=bpy.context.object;scene.camera.data.type='ORTHO';scene.camera.data.ortho_scale=.95
    scene.camera.rotation_euler=(Vector((0,-.15,.12))-scene.camera.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=os.path.join(VIEWER,'assets','explosion-path-preview.png')
    bpy.ops.render.render(write_still=True)
