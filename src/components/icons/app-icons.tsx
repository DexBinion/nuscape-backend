import {
  siYoutube,
  siGooglechrome,
  siInstagram,
  siSteam,
  siTiktok,
  siFacebook,
  siTwitch,
  siNetflix,
  siDiscord,
  siReddit,
  siSpotify,
  siWhatsapp,
} from 'simple-icons/icons'

type SI = { path: string; hex: string }
const SI_MAP: Record<string, SI> = {
  youtube: siYoutube,
  googlechrome: siGooglechrome,
  chrome: siGooglechrome,
  instagram: siInstagram,
  steam: siSteam,
  tiktok: siTiktok,
  facebook: siFacebook,
  twitch: siTwitch,
  netflix: siNetflix,
  discord: siDiscord,
  reddit: siReddit,
  spotify: siSpotify,
  whatsapp: siWhatsapp,
}

function norm(s: string) {
  return s.toLowerCase().replace(/[.\s_-]+/g, '')
}

const SIMPLEICON_HOST = 'simpleicons.org';

function isSimpleIconSource(url?: string) {
  return !!url && url.includes(SIMPLEICON_HOST)
}

function pickSI(name?: string, slug?: string, appId?: string): SI | null {
  const candidates = [slug, appId, name, name ? norm(name) : undefined].filter(Boolean) as string[]
  for (const c of candidates) {
    const k = norm(c)
    if (SI_MAP[k]) return SI_MAP[k]
  }
  return null
}

export function AppIcon({
  name,
  kind,
  domain,
  iconUrl,
  iconB64,
  brandSlug,
  appId,
  size = 24,
}: {
  name: string
  kind?: 'app' | 'site'
  domain?: string
  iconUrl?: string
  iconB64?: string
  brandSlug?: string // simple-icons slug if you have it
  appId?: string
  size?: number
}) {
  const title = name

  // utility: compute luminance from hex to ensure visibility on dark bg
  const hexToRgb = (h: string) => {
    const m = h.match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i)
    if (!m) return { r: 0, g: 0, b: 0 }
    return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) }
  }
  const luminance = (h: string) => {
    const { r, g, b } = hexToRgb(`#${h}`)
    const a = [r, g, b].map(v => {
      const c = v / 255
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
    })
    return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]
  }

  // 1) explicit URL from backend (best) - skip simpleicons so we can recolor locally
  if (iconUrl && !isSimpleIconSource(iconUrl)) {
    return (
      <img
        src={iconUrl}
        alt=""
        title={title}
        className="h-6 w-6 rounded-md object-cover"
        loading="lazy"
        referrerPolicy="no-referrer"
      />
    )
  }

  // 2) base64 icon from backend (small inline)
  if (iconB64) {
    return (
      <img
        src={`data:image/png;base64,${iconB64}`}
        alt=""
        title={title}
        className="h-6 w-6 rounded-md object-cover"
        loading="lazy"
      />
    )
  }

  // 3) simple-icons brand (authentic vector)
  const si = pickSI(name, brandSlug, appId)
  if (si) {
    const isDark = luminance(si.hex) < 0.15
    const fill = isDark ? '#FFFFFF' : `#${si.hex}`
    const bg = isDark ? '#FFFFFF22' : `#${si.hex}22`
    return (
      <span
        className="inline-flex h-6 w-6 items-center justify-center rounded-md"
        title={title}
        aria-label={title}
        style={{ backgroundColor: bg }}
      >
        <svg viewBox="0 0 24 24" width={size - 8} height={size - 8} aria-hidden>
          <path d={si.path} fill={fill} />
        </svg>
      </span>
    )
  }

  // 4) website favicon (legit look for sites not in SI)
  if (kind === 'site' && domain) {
    const url = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`
    return (
      <img
        src={url}
        alt=""
        title={title}
        className="h-6 w-6 rounded-md"
        loading="lazy"
        referrerPolicy="no-referrer"
      />
    )
  }

  // 5) fallback: initials block (never broken)
  const initials = name
    .split(/[\s_.-]+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
  return (
    <span
      className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-base-stroke text-[10px] font-semibold"
      title={title}
    >
      {initials}
    </span>
  )
}





