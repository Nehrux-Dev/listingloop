/**
 * Curated colour palettes for the picker — static data, no runtime cost.
 *
 * Eight palettes of six, in the moods real-estate artwork actually uses
 * (the same idea as Canva's "Warm & earthy" rows, sized for a 320px
 * sidebar). Hex only: these are starting points an agent taps, not tokens —
 * brand tokens (`@primary_color`...) stay a separate row so the difference
 * between "a colour I liked" and "my brand's colour" remains visible.
 */

export type PresetPalette = { name: string; colors: string[] }

export const PRESET_PALETTES: PresetPalette[] = [
  {
    name: 'Warm earth',
    colors: ['#8B4F24', '#B87333', '#D9A066', '#EDE3D9', '#5C3A21', '#2A1A10'],
  },
  {
    name: 'Luxury neutrals',
    colors: ['#1C1C1C', '#3D3D3D', '#8A8578', '#C9C2B6', '#E8E4DC', '#B49B57'],
  },
  {
    name: 'Coastal',
    colors: ['#0F3B4C', '#2E6E8E', '#7FB4C7', '#D8E8EE', '#F2EFE9', '#E3B23C'],
  },
  {
    name: 'Forest',
    colors: ['#1E3A2A', '#3E5F45', '#7A9B76', '#C5D6BE', '#F0F2E9', '#8B4F24'],
  },
  {
    name: 'Sunset',
    colors: ['#7A1E2C', '#C0392B', '#E67E22', '#F5C16C', '#FBEEDB', '#2C2C34'],
  },
  {
    name: 'Monochrome',
    colors: ['#000000', '#333333', '#666666', '#999999', '#CCCCCC', '#FFFFFF'],
  },
  {
    name: 'Pastel',
    colors: ['#F6D6D6', '#F9E9CF', '#E8F0D8', '#D6E8E4', '#DCD6F6', '#FBF7F0'],
  },
  {
    name: 'Bold',
    colors: ['#0D1B2A', '#1B4965', '#D7263D', '#F4B400', '#3AAFA9', '#FFFFFF'],
  },
]
