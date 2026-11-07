export function explosionOffset(assembly,fraction,paths,upright=false){
  const path=paths.assemblies[assembly];
  if(!path)return [0,0,0];
  const t=Math.max(0,Math.min(1,fraction));
  const p=(upright?(path.mountedExtract??path.extract):path.extract).map(v=>v*t/1000);
  // Keep compact Blender separation in device space. The parent rotates BOTH
  // geometry and offsets for band/stake views, so parts exit the lid opening.
  return [p[0],p[2],-p[1]];
}
