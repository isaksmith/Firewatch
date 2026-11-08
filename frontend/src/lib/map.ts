import type { StyleSpecification } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'

// maplibre-gl v6 looks for its worker beside its own file, which the production build doesn't copy; without
// the worker no tile ever loads. Pass this as every <Map>'s workerUrl.
export const MAPLIBRE_WORKER = workerUrl

export const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/dark'

export const KANSAS_VIEW = { longitude: -98.3, latitude: 38.5, zoom: 6.2 }

export const AOI_BBOX = [-102.05, 36.99, -94.59, 40.0] as const

export function ringPolygon(lat: number, lon: number, km: number, steps = 96): GeoJSON.Feature<GeoJSON.LineString> {
  const kx = 111.32 * Math.cos((lat * Math.PI) / 180)
  const ky = 110.57
  const coordinates = Array.from({ length: steps + 1 }, (_, i) => {
    const t = (i / steps) * 2 * Math.PI
    return [lon + (km * Math.sin(t)) / kx, lat + (km * Math.cos(t)) / ky]
  })
  return { type: 'Feature', properties: { km }, geometry: { type: 'LineString', coordinates } }
}

export const TERRAIN_SOURCE = {
  type: 'raster-dem' as const,
  tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
  encoding: 'terrarium' as const,
  tileSize: 256,
  maxzoom: 15,
  attribution: 'Terrain Tiles (USGS and other sources)',
}

export const IMAGERY_TERRAIN_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    imagery: {
      type: 'raster',
      tiles: ['https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 16, // tiles verified at z16 over Kansas, z17 returns 404
      attribution: 'USDA, USGS The National Map: Orthoimagery',
    },
    dem: TERRAIN_SOURCE,
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#050607' } },
    { id: 'imagery', type: 'raster', source: 'imagery', paint: { 'raster-saturation': -0.25, 'raster-brightness-max': 0.85 } },
  ],
  terrain: { source: 'dem', exaggeration: 1.5 },
  sky: {},
}

/** Low data mode: no tiles at all, just a dark background under the local Kansas layers. */
export const BLANK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#0a0c0f' } }],
}
