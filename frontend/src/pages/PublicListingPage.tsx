import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'

import {
  PublicApiError,
  fetchPublicListing,
  submitEnquiry,
  type PublicListing,
} from '../api/public.ts'
import { ListingMap } from '../components/ListingMap.tsx'

/**
 * The public property page. No authentication, no app chrome.
 *
 * Rendered outside the router's protected tree, and it deliberately does not
 * use the authenticated api client — that would attach a bearer token and try
 * to refresh on 401, which is meaningless for an anonymous visitor.
 */
export default function PublicListingPage() {
  const { slug } = useParams<{ slug: string }>()
  const [listing, setListing] = useState<PublicListing | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activePhoto, setActivePhoto] = useState(0)

  useEffect(() => {
    if (!slug) return
    fetchPublicListing(slug)
      .then(setListing)
      .catch((err: unknown) => {
        if (err instanceof PublicApiError && err.status === 404) setNotFound(true)
        else setError('This page could not be loaded. Please try again shortly.')
      })
  }, [slug])

  if (notFound) {
    return (
      <Shell>
        <div className="py-24 text-center">
          <p className="text-sm font-medium text-slate-400">404</p>
          <h1 className="mt-1 text-xl font-semibold text-slate-900">
            This listing is not available
          </h1>
          <p className="mt-2 text-sm text-slate-500">
            It may have been withdrawn, or the link may be out of date.
          </p>
        </div>
      </Shell>
    )
  }

  if (error) {
    return (
      <Shell>
        <p className="py-24 text-center text-sm text-rose-600">{error}</p>
      </Shell>
    )
  }

  if (!listing) {
    return (
      <Shell>
        <p className="py-24 text-center text-sm text-slate-500">Loading…</p>
      </Shell>
    )
  }

  const photo = listing.photos[activePhoto] ?? listing.photos[0]

  return (
    <Shell brokerage={listing.brokerage}>
      <article className="space-y-10">
        {/* Gallery */}
        <section>
          <div className="aspect-[16/10] w-full overflow-hidden rounded-xl bg-slate-100">
            {photo?.image_url ? (
              <img
                src={photo.image_url}
                alt={photo.caption || listing.full_address}
                className="size-full object-cover"
              />
            ) : (
              <div className="flex size-full items-center justify-center text-sm text-slate-400">
                No photos yet
              </div>
            )}
          </div>

          {listing.photos.length > 1 && (
            <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
              {listing.photos.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActivePhoto(index)}
                  className={`size-16 shrink-0 overflow-hidden rounded-md border-2 transition ${
                    index === activePhoto ? 'border-slate-900' : 'border-transparent'
                  }`}
                >
                  {item.image_url && (
                    <img src={item.image_url} alt="" className="size-full object-cover" />
                  )}
                </button>
              ))}
            </div>
          )}
        </section>

        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="space-y-8">
            {/* Headline */}
            <section>
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-slate-900 px-2.5 py-0.5 text-xs font-medium text-white">
                  {listing.status_display}
                </span>
                {listing.property_type_display && (
                  <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600">
                    {listing.property_type_display}
                  </span>
                )}
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
                {listing.address || listing.full_address}
              </h1>
              <p className="mt-1 text-slate-500">
                {[listing.city, listing.state, listing.postcode].filter(Boolean).join(' ')}
              </p>
              {listing.price && (
                <p className="mt-4 text-2xl font-semibold text-slate-900">
                  {formatPrice(listing.price)}
                </p>
              )}
            </section>

            <Stats listing={listing} />

            {listing.description && (
              <section>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                  About this property
                </h2>
                <p className="mt-3 whitespace-pre-wrap leading-relaxed text-slate-700">
                  {listing.description}
                </p>
              </section>
            )}

            {listing.features.length > 0 && (
              <section>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                  Features
                </h2>
                <ul className="mt-3 flex flex-wrap gap-2">
                  {listing.features.map((feature) => (
                    <li
                      key={feature}
                      className="rounded-full border border-slate-200 px-3 py-1 text-sm text-slate-700"
                    >
                      {feature}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                Location
              </h2>
              <div className="mt-3">
                <ListingMap location={listing.location} />
              </div>
            </section>
          </div>

          {/* Agent and enquiry */}
          <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
            <AgentCard listing={listing} />
            <EnquiryForm listing={listing} />
          </aside>
        </div>

        {listing.brokerage?.required_disclaimer && (
          <footer className="border-t border-slate-200 pt-6">
            <p className="text-xs leading-relaxed text-slate-500">
              {listing.brokerage.required_disclaimer}
            </p>
          </footer>
        )}
      </article>
    </Shell>
  )
}

function Shell({
  children,
  brokerage,
}: {
  children: React.ReactNode
  brokerage?: PublicListing['brokerage']
}) {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="border-b border-slate-200">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-4 sm:px-6">
          {brokerage?.logo_url ? (
            <img src={brokerage.logo_url} alt={brokerage.name} className="h-8 object-contain" />
          ) : (
            <span className="text-sm font-semibold tracking-tight">
              {brokerage?.name ?? 'Property'}
            </span>
          )}
          {brokerage?.phone && (
            <span className="ml-auto text-sm text-slate-500">{brokerage.phone}</span>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">{children}</main>
    </div>
  )
}

function Stats({ listing }: { listing: PublicListing }) {
  const stats = [
    listing.bedrooms !== null ? [String(listing.bedrooms), 'Beds'] : null,
    listing.bathrooms !== null ? [String(Number(listing.bathrooms)), 'Baths'] : null,
    listing.square_footage !== null
      ? [listing.square_footage.toLocaleString(), 'Sq ft']
      : null,
  ].filter(Boolean) as [string, string][]

  if (stats.length === 0) return null

  return (
    <section className="flex gap-10 border-y border-slate-200 py-5">
      {stats.map(([value, label]) => (
        <div key={label}>
          <p className="text-2xl font-semibold text-slate-900">{value}</p>
          <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
        </div>
      ))}
    </section>
  )
}

function AgentCard({ listing }: { listing: PublicListing }) {
  const { agent, brokerage } = listing
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="flex items-center gap-3">
        {agent.photo_url ? (
          <img
            src={agent.photo_url}
            alt=""
            className="size-14 rounded-full object-cover"
          />
        ) : (
          <div className="size-14 rounded-full bg-slate-100" />
        )}
        <div className="min-w-0">
          <p className="truncate font-medium text-slate-900">{agent.name}</p>
          <p className="truncate text-sm text-slate-500">{agent.job_title}</p>
        </div>
      </div>

      {agent.tagline && <p className="mt-3 text-sm text-slate-600">{agent.tagline}</p>}

      <dl className="mt-3 space-y-1 text-sm">
        {agent.phone && (
          <div className="flex justify-between gap-3">
            <dt className="text-slate-500">Phone</dt>
            <dd>
              <a href={`tel:${agent.phone}`} className="text-slate-800 hover:underline">
                {agent.phone}
              </a>
            </dd>
          </div>
        )}
        {agent.email && (
          <div className="flex justify-between gap-3">
            <dt className="text-slate-500">Email</dt>
            <dd className="min-w-0">
              <a
                href={`mailto:${agent.email}`}
                className="block truncate text-slate-800 hover:underline"
              >
                {agent.email}
              </a>
            </dd>
          </div>
        )}
        {brokerage && (
          <div className="flex justify-between gap-3">
            <dt className="text-slate-500">Brokerage</dt>
            <dd className="min-w-0 truncate text-slate-800">{brokerage.name}</dd>
          </div>
        )}
      </dl>
    </div>
  )
}

function EnquiryForm({ listing }: { listing: PublicListing }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [message, setMessage] = useState(
    `I'd like to know more about ${listing.address || 'this property'}.`,
  )
  // The honeypot. Bots fill every field they find; a person never sees it.
  const [website, setWebsite] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSending(true)
    setErrors({})

    try {
      await submitEnquiry(listing.public_slug, {
        name,
        email,
        phone,
        message,
        website,
        form_token: listing.enquiry_form_token,
      })
      setSent(true)
    } catch (err) {
      if (err instanceof PublicApiError && err.status === 429) {
        setErrors({ detail: 'Too many enquiries from this connection. Please try later.' })
      } else if (err instanceof PublicApiError && err.data && typeof err.data === 'object') {
        const parsed: Record<string, string> = {}
        for (const [key, value] of Object.entries(err.data as Record<string, unknown>)) {
          parsed[key] = Array.isArray(value) ? String(value[0]) : String(value)
        }
        setErrors(parsed)
      } else {
        setErrors({ detail: 'Your enquiry could not be sent. Please try again.' })
      }
    } finally {
      setSending(false)
    }
  }

  if (sent) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
        <p className="text-sm font-medium text-emerald-800">Thank you — enquiry sent.</p>
        <p className="mt-1 text-sm text-emerald-700">
          {listing.agent.name} will be in touch.
        </p>
      </div>
    )
  }

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="space-y-3 rounded-lg border border-slate-200 p-4"
      noValidate
    >
      <h2 className="text-sm font-semibold text-slate-800">Enquire about this property</h2>

      {errors.detail && (
        <p role="alert" className="rounded-md bg-rose-50 px-2 py-1 text-sm text-rose-700">
          {errors.detail}
        </p>
      )}

      <Field label="Your name" error={errors.name}>
        <input
          type="text"
          value={name}
          required
          autoComplete="name"
          onChange={(event) => setName(event.target.value)}
          className={inputClass}
        />
      </Field>

      <Field label="Email" error={errors.email}>
        <input
          type="email"
          value={email}
          autoComplete="email"
          onChange={(event) => setEmail(event.target.value)}
          className={inputClass}
        />
      </Field>

      <Field label="Phone" error={errors.phone}>
        <input
          type="tel"
          value={phone}
          autoComplete="tel"
          onChange={(event) => setPhone(event.target.value)}
          className={inputClass}
        />
      </Field>

      <Field label="Message" error={errors.message}>
        <textarea
          rows={4}
          value={message}
          required
          onChange={(event) => setMessage(event.target.value)}
          className={inputClass}
        />
      </Field>

      {/* Honeypot: hidden from people and from screen readers, visible to bots.
          `display:none` via a class is skipped by some crawlers, so it is also
          taken out of the tab order and marked aria-hidden. */}
      <div aria-hidden="true" className="hidden">
        <label>
          Website
          <input
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(event) => setWebsite(event.target.value)}
          />
        </label>
      </div>

      <button
        type="submit"
        disabled={sending}
        className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
      >
        {sending ? 'Sending…' : 'Send enquiry'}
      </button>

      <p className="text-[11px] text-slate-400">
        Your details are sent to {listing.agent.name} only.
      </p>
    </form>
  )
}

const inputClass =
  'mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900'

function Field({
  label,
  error,
  children,
}: {
  label: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-600">{label}</span>
      {children}
      {error && <span className="mt-0.5 block text-xs text-rose-600">{error}</span>}
    </label>
  )
}

function formatPrice(price: string): string {
  const value = Number(price)
  return Number.isFinite(value)
    ? value.toLocaleString(undefined, {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 0,
      })
    : price
}
