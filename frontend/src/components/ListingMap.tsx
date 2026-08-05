/**
 * Map for the public listing page, with a swappable provider.
 *
 * Default is **OpenStreetMap**, which needs no API key, no billing account and
 * sets no third-party cookies — worth something on a page served to anonymous
 * visitors who have consented to nothing. Google and Mapbox are selectable via
 * `VITE_MAP_PROVIDER`; both need a public, referrer-restricted token in
 * `VITE_MAP_API_KEY`.
 *
 * That token is public by design — it ships to every browser. Restrict it by
 * HTTP referrer in the provider's console. Never put a secret key here.
 *
 * All three render as an <iframe> rather than a JS SDK: no third-party script
 * runs on the page, the component cannot break the rest of the render, and
 * swapping providers stays a one-line change.
 */

import type { PublicLocation } from '../api/public.ts'

type Provider = 'openstreetmap' | 'google' | 'mapbox' | 'none'

const PROVIDER = (import.meta.env.VITE_MAP_PROVIDER ?? 'openstreetmap') as Provider
const API_KEY = import.meta.env.VITE_MAP_API_KEY ?? ''

function buildSrc(latitude: number, longitude: number): string | null {
  switch (PROVIDER) {
    case 'openstreetmap': {
      // A small bounding box around the pin, plus a marker.
      const delta = 0.004
      const bbox = [
        longitude - delta,
        latitude - delta / 2,
        longitude + delta,
        latitude + delta / 2,
      ].join('%2C')
      return (
        `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}` +
        `&layer=mapnik&marker=${latitude}%2C${longitude}`
      )
    }
    case 'google':
      if (!API_KEY) return null
      return (
        `https://www.google.com/maps/embed/v1/place?key=${encodeURIComponent(API_KEY)}` +
        `&q=${latitude},${longitude}&zoom=15`
      )
    case 'mapbox':
      if (!API_KEY) return null
      return (
        `https://api.mapbox.com/styles/v1/mapbox/streets-v12.html` +
        `?title=false&access_token=${encodeURIComponent(API_KEY)}` +
        `&zoomwheel=false#15/${latitude}/${longitude}`
      )
    default:
      return null
  }
}

export function ListingMap({ location }: { location: PublicLocation }) {
  // No pin is a normal state, not an error: the agent has not placed one.
  // Showing the address in words is more use than an empty grey box.
  if (!location.has_pin || location.latitude === null || location.longitude === null) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-center">
        <p className="text-sm font-medium text-slate-700">{location.label}</p>
        <p className="mt-1 text-xs text-slate-500">
          Contact the agent for the exact location.
        </p>
      </div>
    )
  }

  const src = buildSrc(location.latitude, location.longitude)

  if (!src) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-center">
        <p className="text-sm font-medium text-slate-700">{location.label}</p>
        <p className="mt-1 text-xs text-slate-500">
          Map unavailable — no provider is configured.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <iframe
        title={`Map of ${location.label}`}
        src={src}
        className="block h-72 w-full border-0"
        loading="lazy"
        // The map is decorative context; it has no business reaching for
        // geolocation, a camera, or the page it is embedded in.
        referrerPolicy="no-referrer-when-downgrade"
        sandbox="allow-scripts allow-same-origin allow-popups"
      />
      <div className="flex items-center justify-between bg-white px-3 py-2">
        <p className="truncate text-xs text-slate-600">{location.label}</p>
        <a
          href={`https://www.openstreetmap.org/?mlat=${location.latitude}&mlon=${location.longitude}#map=16/${location.latitude}/${location.longitude}`}
          target="_blank"
          rel="noreferrer noopener"
          className="shrink-0 text-xs font-medium text-slate-600 underline underline-offset-2"
        >
          Open map
        </a>
      </div>
    </div>
  )
}
