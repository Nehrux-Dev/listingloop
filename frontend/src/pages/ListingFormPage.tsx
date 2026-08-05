import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  LISTING_STATUSES,
  PROPERTY_TYPES,
  createListing,
  deleteListing,
  deleteListingPhoto,
  emptyListingInput,
  fetchListing,
  listingToInput,
  unverifyListing,
  updateListing,
  uploadListingPhoto,
  verifyListing,
  type Listing,
  type ListingInput,
} from '../api/listings.ts'
import { AiContentPanel } from '../components/AiContentPanel.tsx'
import {
  Alert,
  Card,
  SelectField,
  SubmitButton,
  TextAreaField,
  TextField,
  fieldErrors,
} from '../components/FormControls.tsx'
import { VerificationBadge } from '../components/VerificationBadge.tsx'
import { ApiError } from '../lib/apiClient.ts'

const FIELD_LABELS: Record<string, string> = {
  address: 'street address',
  city: 'city or suburb',
  price: 'price',
  property_type: 'property type',
}

export default function ListingFormPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isNew = id === undefined
  const listingId = isNew ? null : Number(id)

  const [listing, setListing] = useState<Listing | null>(null)
  const [form, setForm] = useState<ListingInput>(emptyListingInput())
  const [featureDraft, setFeatureDraft] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (listingId === null) return
    try {
      const data = await fetchListing(listingId)
      setListing(data)
      setForm(listingToInput(data))
    } catch (error) {
      setLoadError(
        error instanceof ApiError ? error.message : 'Could not load this listing.',
      )
    }
  }, [listingId])

  useEffect(() => {
    void load()
  }, [load])

  function update<K extends keyof ListingInput>(key: K, value: ListingInput[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function addFeature() {
    const value = featureDraft.trim()
    if (!value || form.features.includes(value)) return
    update('features', [...form.features, value])
    setFeatureDraft('')
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setErrors({})
    setMessage(null)

    try {
      if (listingId === null) {
        const created = await createListing(form)
        void navigate(`/listings/${created.id}`, { replace: true })
        return
      }
      const updated = await updateListing(listingId, form)
      setListing(updated)
      setForm(listingToInput(updated))
      setMessage(
        updated.is_verified
          ? 'Listing saved.'
          : 'Listing saved. It now needs to be reviewed and verified.',
      )
    } catch (error) {
      const parsed = fieldErrors(error)
      setErrors(parsed)
      if (Object.keys(parsed).length === 0) {
        setErrors({ detail: 'Could not save this listing. Please try again.' })
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleVerify() {
    if (listingId === null) return
    setBusy(true)
    setErrors({})
    setMessage(null)
    try {
      const updated = await verifyListing(listingId)
      setListing(updated)
      setMessage('Listing verified. It can now be used to generate content.')
    } catch (error) {
      const parsed = fieldErrors(error)
      setErrors(
        Object.keys(parsed).length > 0
          ? parsed
          : { detail: 'Could not verify this listing.' },
      )
    } finally {
      setBusy(false)
    }
  }

  async function handleUnverify() {
    if (listingId === null) return
    setBusy(true)
    try {
      setListing(await unverifyListing(listingId))
      setMessage('Verification withdrawn.')
    } finally {
      setBusy(false)
    }
  }

  async function handlePhotos(files: FileList | null) {
    if (!files || listingId === null) return
    setBusy(true)
    setErrors({})
    const startOrder = listing?.photos.length ?? 0
    const failures: string[] = []

    // Uploaded one at a time so a single rejected file does not take the rest
    // of the batch with it.
    for (const [index, file] of Array.from(files).entries()) {
      try {
        await uploadListingPhoto(listingId, file, startOrder + index)
      } catch (error) {
        const detail = error instanceof ApiError ? error.message : 'upload failed'
        failures.push(`${file.name}: ${detail}`)
      }
    }

    await load()
    setBusy(false)
    if (failures.length > 0) {
      setErrors({ detail: `Some photos were not added — ${failures.join('; ')}` })
    }
  }

  async function handleDeletePhoto(photoId: number) {
    setBusy(true)
    try {
      await deleteListingPhoto(photoId)
      await load()
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteListing() {
    if (listingId === null) return
    setBusy(true)
    try {
      await deleteListing(listingId)
      void navigate('/listings', { replace: true })
    } finally {
      setBusy(false)
    }
  }

  if (loadError) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold tracking-tight">Listing</h1>
        <Alert kind="error">{loadError}</Alert>
      </div>
    )
  }

  if (!isNew && !listing) {
    return <p className="text-sm text-slate-500">Loading…</p>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3">
        <div className="mr-auto">
          <h1 className="text-xl font-semibold tracking-tight">
            {isNew ? 'New listing' : listing?.full_address || 'Listing'}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {isNew
              ? 'Enter the details, then review and verify.'
              : 'Editing any detail returns the listing to unverified.'}
          </p>
        </div>
        {listing && <VerificationBadge listing={listing} />}
      </div>

      {message && <Alert kind="success">{message}</Alert>}
      {errors.detail && <Alert kind="error">{errors.detail}</Alert>}

      {/* What an import did and did not manage to read. */}
      {listing?.source === 'import' && (
        <Card
          title="Imported from a URL"
          description="Everything below was read from the source page — check it before verifying."
        >
          <p className="break-all text-xs text-slate-500">{listing.source_url}</p>
          {listing.imported_fields.length > 0 && (
            <p className="text-sm text-slate-600">
              <span className="font-medium">Filled in from the page:</span>{' '}
              {listing.imported_fields.map((f) => f.replace(/_/g, ' ')).join(', ')}
            </p>
          )}
          {listing.import_warnings.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
              <p className="text-xs font-medium text-amber-800">
                Left blank rather than guessed:
              </p>
              <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-amber-700">
                {listing.import_warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}

      <form onSubmit={(event) => void handleSubmit(event)} className="space-y-6">
        <Card title="Address">
          <TextField
            label="Street address"
            value={form.address}
            onChange={(value) => update('address', value)}
            error={errors.address}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="City or suburb"
              value={form.city}
              onChange={(value) => update('city', value)}
              error={errors.city}
            />
            <TextField
              label="State or region"
              value={form.state}
              onChange={(value) => update('state', value)}
              error={errors.state}
            />
            <TextField
              label="Postcode"
              value={form.postcode}
              onChange={(value) => update('postcode', value)}
              error={errors.postcode}
            />
            <TextField
              label="Country"
              value={form.country}
              onChange={(value) => update('country', value)}
              error={errors.country}
            />
          </div>
        </Card>

        <Card title="Property details">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Price"
              type="number"
              value={form.price}
              onChange={(value) => update('price', value)}
              error={errors.price}
              hint="Leave blank if unknown — blank is better than a guess."
            />
            <SelectField
              label="Property type"
              value={form.property_type}
              options={[{ value: '' as const, label: 'Not set' }, ...PROPERTY_TYPES]}
              onChange={(value) => update('property_type', value)}
              error={errors.property_type}
            />
            <TextField
              label="Bedrooms"
              type="number"
              value={form.bedrooms}
              onChange={(value) => update('bedrooms', value)}
              error={errors.bedrooms}
            />
            <TextField
              label="Bathrooms"
              type="number"
              value={form.bathrooms}
              onChange={(value) => update('bathrooms', value)}
              error={errors.bathrooms}
              hint="Halves allowed, e.g. 2.5"
            />
            <TextField
              label="Square footage"
              type="number"
              value={form.square_footage}
              onChange={(value) => update('square_footage', value)}
              error={errors.square_footage}
            />
            <SelectField
              label="Listing status"
              value={form.status}
              options={LISTING_STATUSES}
              onChange={(value) => update('status', value)}
              error={errors.status}
            />
          </div>

          <TextAreaField
            label="Description"
            value={form.description}
            onChange={(value) => update('description', value)}
            error={errors.description}
            rows={5}
          />
        </Card>

        <Card title="Features">
          <div className="flex gap-2">
            <input
              type="text"
              value={featureDraft}
              placeholder="e.g. Ocean views"
              onChange={(event) => setFeatureDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  // Otherwise Enter would submit the whole form.
                  event.preventDefault()
                  addFeature()
                }
              }}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
            />
            <button
              type="button"
              onClick={addFeature}
              className="shrink-0 rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Add
            </button>
          </div>

          {errors.features && <p className="text-xs text-rose-600">{errors.features}</p>}

          {form.features.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {form.features.map((feature) => (
                <li
                  key={feature}
                  className="flex items-center gap-1.5 rounded-full bg-slate-100 py-1 pl-3 pr-1.5 text-sm text-slate-700"
                >
                  {feature}
                  <button
                    type="button"
                    aria-label={`Remove ${feature}`}
                    onClick={() =>
                      update(
                        'features',
                        form.features.filter((item) => item !== feature),
                      )
                    }
                    className="rounded-full px-1.5 text-slate-400 transition hover:bg-slate-200 hover:text-slate-700"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <SubmitButton saving={saving}>
          {isNew ? 'Create listing' : 'Save changes'}
        </SubmitButton>
      </form>

      {/* Photos need a listing id, so they appear once the record exists. */}
      {listing && (
        <Card
          title={`Photos (${listing.photos.length})`}
          description="PNG, JPEG or WebP, up to 5 MB each. Select several at once."
        >
          <input
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp"
            disabled={busy}
            onChange={(event) => {
              void handlePhotos(event.target.files)
              event.target.value = ''
            }}
            className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
          />

          {listing.photos.length > 0 && (
            <ul className="grid grid-cols-3 gap-3 sm:grid-cols-4">
              {listing.photos.map((photo) => (
                <li key={photo.id} className="group relative">
                  <div className="aspect-square overflow-hidden rounded-md border border-slate-200 bg-slate-100">
                    {photo.image_url && (
                      <img
                        src={photo.image_url}
                        alt={photo.caption}
                        className="size-full object-cover"
                      />
                    )}
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void handleDeletePhoto(photo.id)}
                    className="absolute right-1 top-1 rounded-md bg-white/90 px-1.5 py-0.5 text-xs font-medium text-rose-600 opacity-0 shadow transition group-hover:opacity-100 focus:opacity-100"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {/* Mounting this panel loads any existing captions. It does NOT
          generate — that only happens when the button inside is clicked. */}
      {listing && (
        <AiContentPanel listingId={listing.id} isVerified={listing.is_verified} />
      )}

      {/* The review step. */}
      {listing && (
        <Card
          title="Verification"
          description="A listing can only be used for templates and AI content once you have confirmed its details."
        >
          {listing.is_verified ? (
            <>
              <p className="text-sm text-emerald-700">
                Verified{listing.verified_at && ` on ${new Date(listing.verified_at).toLocaleDateString()}`}.
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleUnverify()}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
              >
                Withdraw verification
              </button>
            </>
          ) : (
            <>
              {listing.missing_required_fields.length > 0 ? (
                <Alert kind="error">
                  Fill in{' '}
                  {listing.missing_required_fields
                    .map((field) => FIELD_LABELS[field] ?? field.replace(/_/g, ' '))
                    .join(', ')}{' '}
                  and save before verifying.
                </Alert>
              ) : (
                <p className="text-sm text-slate-600">
                  Check every field above is correct. Confirming records that you
                  reviewed this data.
                </p>
              )}
              <button
                type="button"
                disabled={busy || listing.missing_required_fields.length > 0}
                onClick={() => void handleVerify()}
                className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                I have reviewed this — mark as verified
              </button>
            </>
          )}
        </Card>
      )}

      {listing && (
        <button
          type="button"
          disabled={busy}
          onClick={() => void handleDeleteListing()}
          className="text-sm font-medium text-rose-600 transition hover:text-rose-700 disabled:opacity-60"
        >
          Delete this listing
        </button>
      )}
    </div>
  )
}
