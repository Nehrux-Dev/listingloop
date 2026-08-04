/**
 * The sample template — ONE source, rendered by both approaches.
 *
 * Feeding both engines the same HTML string is what makes the comparison
 * honest. It also forces the template to obey Satori's constraints, and those
 * constraints ARE the main finding of this prototype:
 *
 *   1. INLINE STYLES ONLY. satori-html reads `style` attributes; it does not
 *      process <style> blocks, classes, or any external CSS.
 *   2. FLEXBOX ONLY, and declared explicitly. No grid, no float, no
 *      `display: block` with multiple children. Every container below says
 *      `display:flex` even where a browser would not need it.
 *   3. MARGINS, NOT `gap`. Support varies by Satori version; margins always
 *      work.
 *   4. IMAGES AS DATA URIs. Keeps the render offline and deterministic, and
 *      side-steps Satori's separate image-loading path.
 *   5. NO pseudo-elements, filters, blend modes, transforms, or web fonts
 *      loaded via @font-face. Fonts are handed to Satori as buffers.
 *
 * A browser renders this happily. The reverse is not true: an arbitrary
 * designer-authored template will NOT render in Satori without being rewritten
 * to these rules. That asymmetry is the decision this prototype exists to
 * inform.
 *
 * To try your own design, add a sibling module exporting the same interface
 * and pass `--template <name>`.
 */

export const name = 'listing-card'

// 4:5 portrait — the usual social-post shape for property marketing.
export const width = 1080
export const height = 1350

function formatPrice(price) {
  const value = Number(price)
  if (!Number.isFinite(value)) return String(price ?? '')
  return `$${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * @param {object} data    the property payload (see src/data/property.json)
 * @param {object} assets  { heroPhoto, agentPhoto, brokerageLogo } data URIs
 * @returns {string} HTML
 */
export function render(data, assets) {
  const { listing, agent, brokerage, brand_kit: brand } = data

  const heading = brand.heading_font
  const body = brand.body_font

  const stats = [
    listing.bedrooms != null ? [`${listing.bedrooms}`, 'Beds'] : null,
    listing.bathrooms != null ? [`${Number(listing.bathrooms)}`, 'Baths'] : null,
    listing.square_footage != null
      ? [listing.square_footage.toLocaleString('en-US'), 'Sq ft']
      : null,
  ].filter(Boolean)

  const statBlocks = stats
    .map(
      ([value, label], index) => `
      <div style="display:flex; flex-direction:column; align-items:flex-start; margin-right:${
        index === stats.length - 1 ? 0 : 56
      }px;">
        <div style="display:flex; font-family:'${heading}'; font-size:44px; font-weight:700; color:${
          brand.primary_color
        };">${escapeHtml(value)}</div>
        <div style="display:flex; font-family:'${body}'; font-size:20px; letter-spacing:2px; text-transform:uppercase; color:${
          brand.secondary_color
        }; margin-top:4px;">${escapeHtml(label)}</div>
      </div>`,
    )
    .join('')

  const featureChips = listing.features
    .slice(0, 4)
    .map(
      (feature) => `
      <div style="display:flex; align-items:center; border:2px solid ${brand.accent_color}; border-radius:999px; padding:10px 22px; margin-right:12px; margin-bottom:12px;">
        <div style="display:flex; font-family:'${body}'; font-size:22px; color:${brand.primary_color};">${escapeHtml(feature)}</div>
      </div>`,
    )
    .join('')

  return `
<div style="display:flex; flex-direction:column; width:${width}px; height:${height}px; background-color:#FFFFFF; font-family:'${body}';">

  <!-- Hero -->
  <div style="display:flex; position:relative; width:${width}px; height:620px;">
    <img src="${assets.heroPhoto}" width="${width}" height="620" style="width:${width}px; height:620px; object-fit:cover;" />

    <!-- Scrim so the price stays legible over any photo -->
    <div style="display:flex; position:absolute; left:0px; top:320px; width:${width}px; height:300px; background-image:linear-gradient(to bottom, rgba(15,23,42,0), rgba(15,23,42,0.82));"></div>

    <div style="display:flex; position:absolute; left:64px; top:56px; background-color:${brand.accent_color}; border-radius:6px; padding:10px 20px;">
      <div style="display:flex; font-family:'${body}'; font-size:20px; font-weight:700; letter-spacing:3px; text-transform:uppercase; color:#FFFFFF;">For sale</div>
    </div>

    <div style="display:flex; position:absolute; left:64px; top:492px; flex-direction:column;">
      <div style="display:flex; font-family:'${heading}'; font-size:76px; font-weight:700; color:#FFFFFF;">${formatPrice(listing.price)}</div>
    </div>
  </div>

  <!-- Body -->
  <div style="display:flex; flex-direction:column; padding:44px 64px 0px 64px; flex-grow:1;">

    <div style="display:flex; font-family:'${heading}'; font-size:52px; font-weight:700; color:${brand.primary_color}; line-height:1.15;">${escapeHtml(listing.address)}</div>
    <div style="display:flex; font-family:'${body}'; font-size:28px; color:${brand.secondary_color}; margin-top:10px;">${escapeHtml(
      [listing.city, listing.state, listing.postcode].filter(Boolean).join(' '),
    )}</div>

    <div style="display:flex; flex-direction:row; margin-top:34px;">${statBlocks}</div>

    <div style="display:flex; flex-wrap:wrap; margin-top:34px;">${featureChips}</div>

    <div style="display:flex; font-family:'${body}'; font-size:24px; line-height:1.5; color:${brand.secondary_color}; margin-top:26px;">${escapeHtml(
      listing.description,
    )}</div>
  </div>

  <!-- Footer -->
  <div style="display:flex; flex-direction:column;">
    <div style="display:flex; width:${width}px; height:6px; background-color:${brand.accent_color};"></div>

    <div style="display:flex; flex-direction:row; align-items:center; background-color:${brand.primary_color}; padding:28px 64px;">
      <img src="${assets.agentPhoto}" width="104" height="104" style="width:104px; height:104px; border-radius:52px; object-fit:cover;" />

      <div style="display:flex; flex-direction:column; margin-left:24px;">
        <div style="display:flex; font-family:'${heading}'; font-size:30px; font-weight:700; color:#FFFFFF;">${escapeHtml(agent.name)}</div>
        <div style="display:flex; font-family:'${body}'; font-size:22px; color:#CBD5E1; margin-top:4px;">${escapeHtml(agent.job_title)}</div>
        <div style="display:flex; font-family:'${body}'; font-size:22px; color:#CBD5E1; margin-top:2px;">${escapeHtml(agent.phone)}</div>
      </div>

      <div style="display:flex; flex-direction:column; align-items:flex-end; margin-left:auto;">
        <img src="${assets.brokerageLogo}" width="220" height="56" style="width:220px; height:56px; object-fit:contain;" />
        <div style="display:flex; font-family:'${body}'; font-size:20px; color:#CBD5E1; margin-top:8px;">${escapeHtml(brokerage.website)}</div>
      </div>
    </div>

    <!-- Compliance text travels with the image, not the caption -->
    <div style="display:flex; background-color:#0B1220; padding:18px 64px;">
      <div style="display:flex; font-family:'${body}'; font-size:16px; line-height:1.4; color:#94A3B8;">${escapeHtml(
        brokerage.required_disclaimer,
      )}</div>
    </div>
  </div>
</div>`.trim()
}
