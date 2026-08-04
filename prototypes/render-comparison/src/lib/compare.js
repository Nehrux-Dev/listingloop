/**
 * Pixel comparison between the two outputs.
 *
 * A percentage is a blunt instrument — antialiasing differences alone will
 * produce a non-zero number, and two images can differ by 3% while looking
 * identical, or by 3% because a whole text block vanished. The diff PNG is the
 * artefact that actually answers "how close is it", so it is always written.
 */

import pixelmatch from 'pixelmatch'
import { PNG } from 'pngjs'

export function comparePngs(bufferA, bufferB) {
  const imageA = PNG.sync.read(bufferA)
  const imageB = PNG.sync.read(bufferB)

  if (imageA.width !== imageB.width || imageA.height !== imageB.height) {
    return {
      comparable: false,
      reason: `Different dimensions: ${imageA.width}x${imageA.height} vs ${imageB.width}x${imageB.height}`,
      dimensions: {
        a: [imageA.width, imageA.height],
        b: [imageB.width, imageB.height],
      },
    }
  }

  const diff = new PNG({ width: imageA.width, height: imageA.height })
  const differingPixels = pixelmatch(
    imageA.data,
    imageB.data,
    diff.data,
    imageA.width,
    imageA.height,
    // 0.1 is pixelmatch's default: strict enough to catch real layout shifts,
    // tolerant enough to ignore subpixel antialiasing noise.
    { threshold: 0.1, includeAA: false },
  )

  const totalPixels = imageA.width * imageA.height
  return {
    comparable: true,
    width: imageA.width,
    height: imageA.height,
    differing_pixels: differingPixels,
    total_pixels: totalPixels,
    differing_percent: Math.round((differingPixels / totalPixels) * 10000) / 100,
    diff_png: PNG.sync.write(diff),
  }
}
