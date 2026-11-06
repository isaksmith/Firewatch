import type { StyleSpecification } from 'maplibre-gl'

export const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/dark'

export const KANSAS_VIEW = { longitude: -98.3, latitude: 38.5, zoom: 6.2 }

export const TERRAIN_SOURCE = {
  type: 'raster-dem' as const,
  tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
  encoding: 'terrarium' as const,
  tileSize: 256,
  maxzoom: 15,
  attribution: 'Terrain: AWS Terrain Tiles (Mapzen)',
}

export const IMAGERY_TERRAIN_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    imagery: {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 18,
      attribution: 'Imagery: Esri, Maxar, Earthstar Geographics',
    },
    dem: TERRAIN_SOURCE,
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#0b0f14' } },
    { id: 'imagery', type: 'raster', source: 'imagery', paint: { 'raster-saturation': -0.25, 'raster-brightness-max': 0.85 } },
  ],
  terrain: { source: 'dem', exaggeration: 1.5 },
  sky: {},
}
