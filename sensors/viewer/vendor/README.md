# Vendored browser dependency

Three.js **0.181.1**, MIT licensed, from the published `three` npm package.
Files were downloaded without modification from:

`https://cdn.jsdelivr.net/npm/three@0.181.1/`

Included modules are `build/three.module.js`, `build/three.core.js`, and the
`examples/jsm` modules for GLTFLoader, OrbitControls, BufferGeometryUtils and
RoomEnvironment. The two build files are stored directly under `three/`; example
modules are under `three/addons/`. The original license is `three/LICENSE`.

These files are served locally so the viewer needs no CDN connection at runtime.

`fonts/` holds IBM Plex Sans and IBM Plex Mono (Latin, weights 400–600) as woff2, copied from the
`@fontsource/ibm-plex-sans` and `@fontsource/ibm-plex-mono` npm packages so the viewer matches the
FireWatchOS console. SIL Open Font License 1.1; see `fonts/LICENSE-IBM-Plex.txt`.
