import { useState } from 'react'

// Always-visible "Sources" button that lives in a bar (dashboard footer, 3D header),
// so the legal text never overlaps map controls or the timeline. The popover is fixed
// so it escapes overflow-hidden parents.
export function Attribution({ placement = 'footer' }: { placement?: 'footer' | 'header' }) {
  const [open, setOpen] = useState(false)
  const pos = placement === 'footer' ? 'bottom-9 right-3' : 'top-12 right-3'
  return (
    <span className="ml-2 inline-flex">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="num cursor-pointer border border-line-2 px-2 py-[1px] text-[11px] tracking-[0.08em] text-text hover:border-text"
      >
        SOURCES<span className="hidden sm:inline"> &amp; ATTRIBUTION</span>
      </button>
      {open && (
        <p
          role="dialog"
          aria-label="Data sources and attribution"
          className={`fixed ${pos} z-50 max-w-[min(94vw,460px)] border border-line-2 bg-void p-3 text-[12px] leading-relaxed whitespace-normal text-text normal-case`}
        >
          Weather: Open-Meteo.com (CC BY 4.0). Fire detections: NASA FIRMS (LANCE/EOSDIS). Forecasts, alerts and models: NOAA/NWS/NCEP/SPC. NOAA does
          not endorse this app. Surface obs: Iowa Environmental Mesonet. Terrain: Terrain Tiles (USGS and other sources). Imagery: USDA, USGS The
          National Map. Map data © OpenStreetMap contributors, available under the Open Database License (ODbL). Data accuracy is not guaranteed.
          <button type="button" onClick={() => setOpen(false)} className="mt-2 block cursor-pointer text-[11px] text-muted underline">
            Close
          </button>
        </p>
      )}
    </span>
  )
}
