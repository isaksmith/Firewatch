// Variant and layer visibility is independent of camera focus.
export function partVisible(meta,state){
  return Boolean(state.layers[meta.layer]&&
    (meta.tier==='both'||meta.tier===state.tier)&&
    (meta.layer!=='mount'||state.mount!=='none')&&
    (meta.mount==='both'||meta.mount===state.mount)&&
    (!meta.hideWhenExploded||state.explode<.015));
}
