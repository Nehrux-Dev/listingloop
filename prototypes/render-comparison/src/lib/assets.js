/**
 * Sample imagery, generated procedurally as PNG data URIs.
 *
 * Drawn in code rather than shipped as binaries so the prototype stays
 * self-contained, deterministic and free of committed blobs. These are stand-in
 * shapes, not photographs — what matters for the comparison is that both
 * engines receive byte-identical image input.
 *
 * Data URIs also keep the render offline: no network fetch, so neither engine
 * is measured waiting on one.
 */

import { PNG } from 'pngjs'

function createCanvas(width, height) {
  const png = new PNG({ width, height })
  const set = (x, y, [r, g, b, a = 255]) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return
    const index = (width * (y | 0) + (x | 0)) << 2
    // Simple source-over blend so overlapping shapes look intentional.
    const alpha = a / 255
    png.data[index] = png.data[index] * (1 - alpha) + r * alpha
    png.data[index + 1] = png.data[index + 1] * (1 - alpha) + g * alpha
    png.data[index + 2] = png.data[index + 2] * (1 - alpha) + b * alpha
    png.data[index + 3] = 255
  }

  return {
    png,
    set,
    fill(color) {
      for (let y = 0; y < height; y += 1) for (let x = 0; x < width; x += 1) set(x, y, color)
    },
    verticalGradient(y0, y1, top, bottom) {
      for (let y = y0; y < y1; y += 1) {
        const t = (y - y0) / Math.max(1, y1 - y0 - 1)
        const color = top.map((value, index) => value + (bottom[index] - value) * t)
        for (let x = 0; x < width; x += 1) set(x, y, color)
      }
    },
    rect(x0, y0, w, h, color) {
      for (let y = y0; y < y0 + h; y += 1) for (let x = x0; x < x0 + w; x += 1) set(x, y, color)
    },
    circle(cx, cy, radius, color) {
      for (let y = cy - radius; y <= cy + radius; y += 1) {
        for (let x = cx - radius; x <= cx + radius; x += 1) {
          if ((x - cx) ** 2 + (y - cy) ** 2 <= radius * radius) set(x, y, color)
        }
      }
    },
    /** Filled triangle, for roof lines. */
    triangle(ax, ay, bx, by, cx, cy, color) {
      const minX = Math.min(ax, bx, cx)
      const maxX = Math.max(ax, bx, cx)
      const minY = Math.min(ay, by, cy)
      const maxY = Math.max(ay, by, cy)
      const sign = (px, py, qx, qy, rx, ry) => (px - rx) * (qy - ry) - (qx - rx) * (py - ry)
      for (let y = minY; y <= maxY; y += 1) {
        for (let x = minX; x <= maxX; x += 1) {
          const d1 = sign(x, y, ax, ay, bx, by)
          const d2 = sign(x, y, bx, by, cx, cy)
          const d3 = sign(x, y, cx, cy, ax, ay)
          const hasNeg = d1 < 0 || d2 < 0 || d3 < 0
          const hasPos = d1 > 0 || d2 > 0 || d3 > 0
          if (!(hasNeg && hasPos)) set(x, y, color)
        }
      }
    },
    toDataUri() {
      return `data:image/png;base64,${PNG.sync.write(png).toString('base64')}`
    },
  }
}

/** A stylised property shot: sky, sun, water, headland, house. */
function heroPhoto(width = 1080, height = 720) {
  const canvas = createCanvas(width, height)

  canvas.verticalGradient(0, height * 0.62, [56, 105, 168], [173, 199, 224])
  canvas.circle(width * 0.78, height * 0.2, 58, [255, 241, 214])
  canvas.verticalGradient(height * 0.62, height, [37, 84, 122], [22, 54, 82])

  // Headland
  canvas.triangle(0, height * 0.62, width * 0.34, height * 0.34, width * 0.62, height * 0.62, [
    46, 74, 62,
  ])
  canvas.triangle(width * 0.5, height * 0.62, width * 0.78, height * 0.42, width, height * 0.62, [
    38, 63, 53,
  ])

  // Foreshore and house
  canvas.rect(0, height * 0.78, width, height * 0.22, [214, 199, 172])
  canvas.rect(width * 0.16, height * 0.5, 300, 200, [240, 238, 232])
  canvas.triangle(
    width * 0.16 - 26,
    height * 0.5,
    width * 0.16 + 150,
    height * 0.5 - 92,
    width * 0.16 + 326,
    height * 0.5,
    [122, 74, 58],
  )
  for (let i = 0; i < 3; i += 1) {
    canvas.rect(width * 0.16 + 34 + i * 92, height * 0.5 + 46, 54, 66, [96, 132, 158])
  }

  return canvas.toDataUri()
}

/** A neutral avatar placeholder. */
function agentPhoto(size = 208) {
  const canvas = createCanvas(size, size)
  canvas.fill([203, 213, 225])
  canvas.circle(size / 2, size * 0.38, size * 0.19, [100, 116, 139])
  canvas.circle(size / 2, size * 1.05, size * 0.45, [100, 116, 139])
  return canvas.toDataUri()
}

/** An abstract brokerage mark — content is irrelevant to the comparison. */
function brokerageLogo(width = 440, height = 112) {
  const canvas = createCanvas(width, height)
  canvas.fill([15, 23, 42, 0])
  canvas.triangle(24, 84, 68, 26, 112, 84, [194, 135, 74])
  canvas.rect(24, 88, 88, 8, [194, 135, 74])
  canvas.rect(140, 34, 210, 14, [255, 255, 255])
  canvas.rect(140, 60, 150, 10, [203, 213, 225])
  return canvas.toDataUri()
}

/** Built once and reused, so image generation is never inside a timed render. */
export function buildAssets() {
  return {
    heroPhoto: heroPhoto(),
    agentPhoto: agentPhoto(),
    brokerageLogo: brokerageLogo(),
  }
}
