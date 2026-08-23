/**
 * The product's icon set, as inline SVG.
 *
 * Hand-written rather than pulled from an icon package on purpose: the app
 * has three runtime dependencies (react, react-dom, react-router-dom) and a
 * dozen glyphs is not a reason to make it four. Every icon here is a 24x24
 * stroked path on `currentColor`, so colour and size come from the caller's
 * text styles and nothing needs a per-icon theme.
 */

type IconProps = {
  className?: string
  strokeWidth?: number
}

function Svg({
  className = 'size-[18px]',
  strokeWidth = 1.6,
  children,
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {children}
    </svg>
  )
}

// -- navigation --------------------------------------------------------------

export const IconDashboard = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V20h14V9.5" />
    <path d="M9.5 20v-5.5h5V20" />
  </Svg>
)

export const IconMenu = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 6.5h16M4 12h16M4 17.5h16" />
  </Svg>
)

export const IconClose = (p: IconProps) => (
  <Svg {...p}>
    <path d="m6 6 12 12M18 6 6 18" />
  </Svg>
)

export const IconListings = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 21h18" />
    <path d="M5 21V6l7-3 7 3v15" />
    <path d="M9 10h2M13 10h2M9 14h2M13 14h2" />
  </Svg>
)

export const IconCalendar = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="5" width="18" height="16" rx="2.5" />
    <path d="M3 10h18M8 3v4M16 3v4" />
  </Svg>
)

export const IconTemplates = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="3" width="7.5" height="7.5" rx="1.8" />
    <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.8" />
    <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.8" />
    <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.8" />
  </Svg>
)

export const IconDesigns = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20h16" />
    <path d="M14.5 4.5a2.1 2.1 0 0 1 3 3L9 16l-4 1 1-4Z" />
  </Svg>
)

export const IconEnquiries = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="5" width="18" height="14" rx="2.5" />
    <path d="m3.5 7 8.5 6 8.5-6" />
  </Svg>
)

export const IconBrandKit = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.9 1.8-1.9 0-1.4-1-1.9-1-2.9 0-.8.7-1.5 1.6-1.5H16a5 5 0 0 0 5-5c0-3.9-4-6.7-9-6.7Z" />
    <circle cx="7.8" cy="12" r="1.1" />
    <circle cx="10.2" cy="7.9" r="1.1" />
    <circle cx="15" cy="8.4" r="1.1" />
  </Svg>
)

export const IconBrokerage = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 21h18" />
    <path d="M4 21V4.5h9V21" />
    <path d="M13 21V10h7v11" />
    <path d="M7 8h3M7 12h3M7 16h3M16 14h1M16 17.5h1" />
  </Svg>
)

export const IconReports = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20h16" />
    <rect x="5.5" y="11" width="3.4" height="6" rx="1" />
    <rect x="10.8" y="7" width="3.4" height="10" rx="1" />
    <rect x="16.1" y="13.5" width="3.4" height="3.5" rx="1" />
  </Svg>
)

export const IconSettings = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 14.5a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9h.2a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
  </Svg>
)

export const IconPlatform = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3 5 6v5.5c0 4.3 3 8.3 7 9.5 4-1.2 7-5.2 7-9.5V6Z" />
    <path d="m9.2 12 2 2 3.6-3.8" />
  </Svg>
)

// -- editor header -----------------------------------------------------------

export const IconPanel = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <path d="M9.5 4v16" />
  </Svg>
)

export const IconChevronRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="m9 5 7 7-7 7" />
  </Svg>
)

export const IconChevronLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="m15 5-7 7 7 7" />
  </Svg>
)

export const IconChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="m5 9 7 7 7-7" />
  </Svg>
)

export const IconPencil = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14.5 4.5a2.1 2.1 0 0 1 3 3L9 16l-4 1 1-4Z" />
  </Svg>
)

export const IconUndo = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 9h11a5 5 0 0 1 0 10h-6" />
    <path d="m8 5-4 4 4 4" />
  </Svg>
)

export const IconRedo = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 9H9a5 5 0 0 0 0 10h6" />
    <path d="m16 5 4 4-4 4" />
  </Svg>
)

export const IconMinus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h14" />
  </Svg>
)

export const IconPlus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
)

export const IconEye = (p: IconProps) => (
  <Svg {...p}>
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
    <circle cx="12" cy="12" r="3" />
  </Svg>
)

export const IconEyeOff = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9.9 5.7A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 0 1-3 3.8" />
    <path d="M6.5 7.7A16 16 0 0 0 2.5 12S6 18.5 12 18.5c1.2 0 2.3-.2 3.3-.6" />
    <path d="M3 3l18 18" />
  </Svg>
)

export const IconCopy = (p: IconProps) => (
  <Svg {...p}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M15 5.5A1.5 1.5 0 0 0 13.5 4H5.5A1.5 1.5 0 0 0 4 5.5v8A1.5 1.5 0 0 0 5.5 15" />
  </Svg>
)

export const IconClipboard = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5.5" y="4.5" width="13" height="17" rx="2" />
    <rect x="9" y="2.5" width="6" height="4" rx="1" />
    <path d="M9 12h6M9 15.5h4" />
  </Svg>
)

export const IconPaintRoller = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.5" y="4" width="13" height="5" rx="1.5" />
    <path d="M16.5 6.5h2.5A1.5 1.5 0 0 1 20.5 8v2.5a1.5 1.5 0 0 1-1.5 1.5h-6a1 1 0 0 0-1 1v1.5" />
    <rect x="10.5" y="14.5" width="3" height="6.5" rx="1" />
  </Svg>
)

export const IconMore = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="5" r="1.4" />
    <circle cx="12" cy="12" r="1.4" />
    <circle cx="12" cy="19" r="1.4" />
  </Svg>
)

export const IconCheckCircle = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="m8.5 12 2.4 2.4 4.6-4.9" />
  </Svg>
)

export const IconBell = (p: IconProps) => (
  <Svg {...p}>
    <path d="M18 8.5a6 6 0 0 0-12 0c0 6-2 7.5-2 7.5h16s-2-1.5-2-7.5Z" />
    <path d="M13.7 19.5a2 2 0 0 1-3.4 0" />
  </Svg>
)

export const IconMoon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 13.5A8 8 0 1 1 10.5 4a6.5 6.5 0 0 0 9.5 9.5Z" />
  </Svg>
)

export const IconLogout = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9.5 4.5H6A2 2 0 0 0 4 6.5v11a2 2 0 0 0 2 2h3.5" />
    <path d="M15 8.5 19 12l-4 3.5" />
    <path d="M19 12H9.5" />
  </Svg>
)

// -- left creative panel -----------------------------------------------------

export const IconElements = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="4.2" />
    <rect x="13" y="3.8" width="8.2" height="8.2" rx="1.8" />
    <path d="M7.6 14.2 3.5 21h8.2Z" />
    <rect x="14" y="15" width="7" height="6" rx="1.8" />
  </Svg>
)

export const IconUpload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 16V4" />
    <path d="m7.5 8.5 4.5-4.5 4.5 4.5" />
    <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
  </Svg>
)

export const IconText = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 6.5V4.5h14v2" />
    <path d="M12 4.5V20" />
    <path d="M9 20h6" />
  </Svg>
)

export const IconImage = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4.5" width="18" height="15" rx="2.5" />
    <circle cx="8.7" cy="10" r="1.6" />
    <path d="m4 17 4.8-4.3a1.6 1.6 0 0 1 2.2 0L16 17" />
    <path d="m14 14.5 1.6-1.4a1.6 1.6 0 0 1 2.2 0L20.5 15" />
  </Svg>
)

export const IconLayers = (p: IconProps) => (
  <Svg {...p}>
    <path d="m12 3 9 5-9 5-9-5Z" />
    <path d="m3.5 12.5 8.5 4.7 8.5-4.7" />
    <path d="m3.5 16.8 8.5 4.7 8.5-4.7" />
  </Svg>
)

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 4.5 4.5" />
  </Svg>
)

export const IconFilter = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 6h17" />
    <path d="M6.5 12h11" />
    <path d="M10 18h4" />
  </Svg>
)

export const IconSparkle = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.5 13.7 9l5.5 1.7-5.5 1.7L12 18l-1.7-5.6L4.8 10.7 10.3 9Z" />
    <path d="M18.5 4v3M20 5.5h-3" />
  </Svg>
)

export const IconArrowRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 12h14" />
    <path d="m13 6.5 5.5 5.5-5.5 5.5" />
  </Svg>
)

/** Leaves this tab — used only where the click really does open a new one. */
export const IconExternal = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13.5 4.5H19.5V10.5" />
    <path d="M19.5 4.5 11 13" />
    <path d="M18 14.5v4a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6h4" />
  </Svg>
)

// -- canvas dock -------------------------------------------------------------

export const IconCursor = (p: IconProps) => (
  <Svg {...p}>
    <path d="m5.5 3.5 5 16 2.6-6.4 6.4-2.6Z" />
  </Svg>
)

export const IconHand = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 11V5.2a1.6 1.6 0 0 1 3.2 0V11" />
    <path d="M12.2 10.6V4.4a1.6 1.6 0 0 1 3.2 0v6.2" />
    <path d="M15.4 11.2V6.8a1.6 1.6 0 0 1 3.2 0V14a6.4 6.4 0 0 1-6.4 6.4h-.8A6 6 0 0 1 5.8 15L4.4 12.4a1.5 1.5 0 0 1 2.5-1.6L9 13.4" />
  </Svg>
)

export const IconGrid = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
  </Svg>
)

export const IconComment = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20.5 11.5a7.5 7.5 0 0 1-10.9 6.7L4.5 19.5l1.3-4.6A7.5 7.5 0 1 1 20.5 11.5Z" />
  </Svg>
)

export const IconTrash = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 6.5h16" />
    <path d="M9.5 6.5V4.8A1.3 1.3 0 0 1 10.8 3.5h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
    <path d="M6.5 6.5 7.3 19a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4l.8-12.5" />
    <path d="M10.5 10.5v6M13.5 10.5v6" />
  </Svg>
)

// -- properties panel --------------------------------------------------------

export const IconCrop = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6.5 2.5v15h15" />
    <path d="M2.5 6.5h15v15" />
  </Svg>
)

export const IconWand = (p: IconProps) => (
  <Svg {...p}>
    <path d="m4 20 10-10" />
    <path d="M14.5 3.5 16 6.5l3 1.5-3 1.5-1.5 3-1.5-3L10 8l3-1.5Z" />
    <path d="M19.5 14.5 20 16l1.5.5-1.5.5-.5 1.5-.5-1.5L17 16.5l1.5-.5Z" />
  </Svg>
)

export const IconSliders = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 20V14M5 10V4M12 20v-8M12 8V4M19 20v-4M19 12V4" />
    <path d="M2.5 14h5M9.5 8h5M16.5 16h5" />
  </Svg>
)

export const IconFilters = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="9" cy="9.5" r="5.5" />
    <circle cx="15" cy="14.5" r="5.5" />
  </Svg>
)

export const IconLock = (p: IconProps) => (
  <Svg {...p}>
    <rect x="4.5" y="10.5" width="15" height="10" rx="2.2" />
    <path d="M8 10.5V7.2a4 4 0 0 1 8 0v3.3" />
  </Svg>
)

export const IconUnlock = (p: IconProps) => (
  <Svg {...p}>
    <rect x="4.5" y="10.5" width="15" height="10" rx="2.2" />
    <path d="M8 10.5V7.2a4 4 0 0 1 7.5-2" />
  </Svg>
)

export const IconAlignLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 3.5v17" />
    <rect x="7" y="6" width="12" height="4.5" rx="1" />
    <rect x="7" y="13.5" width="8" height="4.5" rx="1" />
  </Svg>
)

export const IconAlignCenterH = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.5v17" />
    <rect x="5" y="6" width="14" height="4.5" rx="1" />
    <rect x="8" y="13.5" width="8" height="4.5" rx="1" />
  </Svg>
)

export const IconAlignRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20.5 3.5v17" />
    <rect x="5" y="6" width="12" height="4.5" rx="1" />
    <rect x="9" y="13.5" width="8" height="4.5" rx="1" />
  </Svg>
)

export const IconAlignTop = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 3.5h17" />
    <rect x="6" y="7" width="4.5" height="12" rx="1" />
    <rect x="13.5" y="7" width="4.5" height="8" rx="1" />
  </Svg>
)

export const IconAlignMiddleV = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 12h17" />
    <rect x="6" y="5" width="4.5" height="14" rx="1" />
    <rect x="13.5" y="8" width="4.5" height="8" rx="1" />
  </Svg>
)

export const IconAlignBottom = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 20.5h17" />
    <rect x="6" y="5" width="4.5" height="12" rx="1" />
    <rect x="13.5" y="9" width="4.5" height="8" rx="1" />
  </Svg>
)
