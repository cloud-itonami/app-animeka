/**
 * Procedural SVG art generator. Produces deterministic-from-seed SVG strings
 * suitable for inline rendering as work covers (3:4 aspect) and cut thumbs
 * (16:9 aspect).
 *
 * The pipeline-side image gen (ComfyUI animagine-xl-4) currently returns
 * blobCid:null in 119ms; until that's fixed every work + cut would render as
 * a flat gradient block. These procedural placeholders deliver visible
 * anime-flavored art with zero backend dependency, deterministic per seed,
 * and match the look-and-feel users expect from a storyboard/anime app.
 */

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

function rng(seed: number): () => number {
  let s = seed || 1;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

const SCENES = [
  // Each scene returns the layered shapes for a 16:9 or 3:4 frame.
  // 0..1 normalized coordinates; the caller scales.
  'rooftop', 'classroom', 'station', 'forest', 'ocean', 'mountain', 'shrine', 'street', 'bedroom', 'bridge',
] as const;
type Scene = (typeof SCENES)[number];

const PALETTES: Record<string, string[]> = {
  // [sky_top, sky_bottom, mid, accent, char_silhouette]
  sunset: ['#ffb088', '#ff6b6b', '#5d4d6f', '#ffe5b4', '#1a1a2e'],
  morning: ['#a8d8ea', '#fffbe7', '#9ec5d8', '#ffd166', '#2d3047'],
  night: ['#1a1a2e', '#16213e', '#0f3460', '#e94560', '#0a0a0a'],
  cherry: ['#ffd1dc', '#ffb6c1', '#ff8fab', '#ffffff', '#3a1c2e'],
  twilight: ['#5d4e8c', '#a16ae8', '#3a2c5c', '#fbc9d9', '#1a0f24'],
  rain: ['#5b6e8c', '#7d8ca6', '#3a4a63', '#aac8e8', '#1a2030'],
  cyber: ['#0f0524', '#3d1654', '#ff00aa', '#00ffe0', '#0a0014'],
  forest: ['#2d5016', '#4a7c2a', '#6b8e3d', '#fff7c4', '#1a2410'],
};
const PALETTE_NAMES = Object.keys(PALETTES);

function pickPalette(rand: () => number): { name: string; colors: string[] } {
  const name = PALETTE_NAMES[Math.floor(rand() * PALETTE_NAMES.length)];
  return { name, colors: PALETTES[name] };
}

function pickScene(rand: () => number): Scene {
  return SCENES[Math.floor(rand() * SCENES.length)];
}

/**
 * Generate cover art (3:4 vertical, e.g. 300×400). Returns a self-contained
 * SVG string suitable for use as `data:image/svg+xml;base64,…` in a CSS url().
 */
export function coverSVG(seedKey: string, title: string): string {
  const r = rng(hash(seedKey));
  const pal = pickPalette(r);
  const [c0, c1, c2, c3, cs] = pal.colors;
  const scene = pickScene(r);
  const initials = title.replace(/\s+/g, '').slice(0, 2).toUpperCase() || 'A';

  const stars = Array.from({ length: pal.name === 'night' || pal.name === 'twilight' ? 28 : 0 }, () => ({
    x: r() * 100,
    y: r() * 50,
    s: 0.8 + r() * 1.2,
  }));
  const sunY = 30 + r() * 25;
  const sunX = 20 + r() * 60;
  const horizonY = 55 + r() * 15;

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 133" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${c0}"/>
      <stop offset="100%" stop-color="${c1}"/>
    </linearGradient>
    <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${c2}"/>
      <stop offset="100%" stop-color="${cs}"/>
    </linearGradient>
  </defs>
  <rect width="100" height="133" fill="url(#sky)"/>
  ${stars.map((s) => `<circle cx="${s.x.toFixed(1)}" cy="${s.y.toFixed(1)}" r="${(s.s * 0.3).toFixed(2)}" fill="#fff" opacity="${(0.5 + r() * 0.5).toFixed(2)}"/>`).join('')}
  <circle cx="${sunX.toFixed(0)}" cy="${sunY.toFixed(0)}" r="${(8 + r() * 6).toFixed(1)}" fill="${c3}" opacity="0.85"/>
  <path d="M0,${horizonY.toFixed(1)} Q25,${(horizonY - 4).toFixed(1)} 50,${horizonY.toFixed(1)} T100,${horizonY.toFixed(1)} L100,133 L0,133 Z" fill="url(#ground)"/>
  ${scene === 'mountain' ? `<polygon points="10,${horizonY},25,${(horizonY - 18).toFixed(1)},40,${horizonY}" fill="${c2}" opacity="0.85"/><polygon points="55,${horizonY},75,${(horizonY - 22).toFixed(1)},95,${horizonY}" fill="${c2}" opacity="0.7"/>` : ''}
  ${scene === 'shrine' ? `<rect x="38" y="${(horizonY - 10).toFixed(1)}" width="3" height="10" fill="${cs}"/><rect x="59" y="${(horizonY - 10).toFixed(1)}" width="3" height="10" fill="${cs}"/><rect x="35" y="${(horizonY - 10).toFixed(1)}" width="30" height="2" fill="${cs}"/>` : ''}
  ${scene === 'forest' ? Array.from({ length: 7 }, (_, i) => `<polygon points="${(i * 15 + 5).toFixed(0)},${horizonY},${(i * 15 + 9).toFixed(0)},${(horizonY - 10 - r() * 5).toFixed(1)},${(i * 15 + 13).toFixed(0)},${horizonY}" fill="${cs}" opacity="0.7"/>`).join('') : ''}
  ${scene === 'rooftop' ? `<rect x="0" y="${(horizonY - 2).toFixed(1)}" width="100" height="3" fill="${cs}"/><rect x="40" y="${(horizonY - 12).toFixed(1)}" width="2" height="12" fill="${cs}"/>` : ''}
  ${scene === 'ocean' ? Array.from({ length: 4 }, (_, i) => `<path d="M0,${(horizonY + 5 + i * 6).toFixed(1)} Q25,${(horizonY + 4 + i * 6).toFixed(1)} 50,${(horizonY + 5 + i * 6).toFixed(1)} T100,${(horizonY + 5 + i * 6).toFixed(1)}" stroke="${c3}" stroke-width="0.5" fill="none" opacity="0.4"/>`).join('') : ''}
  <ellipse cx="50" cy="${(horizonY + 8).toFixed(1)}" rx="6" ry="14" fill="${cs}"/>
  <circle cx="50" cy="${(horizonY - 1).toFixed(1)}" r="3.5" fill="${cs}"/>
  <text x="50" y="120" font-family="serif" font-size="13" font-weight="700" fill="${c3}" text-anchor="middle" opacity="0.95" stroke="${cs}" stroke-width="0.4">${escapeXml(initials)}</text>
</svg>`;
}

/**
 * Generate cut thumb art (16:9, e.g. 320×180). A storyboard-style
 * monochrome-ish frame with simple shapes hinting at the scene.
 */
export function thumbSVG(seedKey: string): string {
  const r = rng(hash(seedKey || 'cut'));
  const pal = pickPalette(r);
  const [c0, c1, c2, c3, cs] = pal.colors;
  const scene = pickScene(r);
  const horizonY = 50 + r() * 25;
  const sunX = 20 + r() * 60;
  const sunY = 20 + r() * 20;
  const cloudCount = Math.floor(r() * 4);

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="sky2" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${c0}"/>
      <stop offset="100%" stop-color="${c1}"/>
    </linearGradient>
  </defs>
  <rect width="160" height="90" fill="url(#sky2)"/>
  <circle cx="${sunX.toFixed(0)}" cy="${sunY.toFixed(0)}" r="${(5 + r() * 5).toFixed(1)}" fill="${c3}" opacity="0.8"/>
  ${Array.from({ length: cloudCount }, () => {
    const cx = r() * 160;
    const cy = 10 + r() * 25;
    return `<ellipse cx="${cx.toFixed(0)}" cy="${cy.toFixed(0)}" rx="${(8 + r() * 6).toFixed(0)}" ry="${(2 + r() * 2).toFixed(0)}" fill="#fff" opacity="0.45"/>`;
  }).join('')}
  <rect x="0" y="${horizonY.toFixed(0)}" width="160" height="${(90 - horizonY).toFixed(0)}" fill="${c2}"/>
  ${scene === 'mountain' ? `<polygon points="20,${horizonY},45,${(horizonY - 18).toFixed(0)},70,${horizonY}" fill="${cs}" opacity="0.7"/><polygon points="80,${horizonY},110,${(horizonY - 22).toFixed(0)},140,${horizonY}" fill="${cs}" opacity="0.85"/>` : ''}
  ${scene === 'rooftop' ? `<rect x="0" y="${(horizonY - 4).toFixed(0)}" width="160" height="6" fill="${cs}"/><rect x="60" y="${(horizonY - 12).toFixed(0)}" width="2" height="12" fill="${cs}"/>` : ''}
  ${scene === 'station' ? `<rect x="0" y="${(horizonY - 1).toFixed(0)}" width="160" height="2" fill="${cs}"/><rect x="0" y="${(horizonY + 4).toFixed(0)}" width="160" height="1" fill="${cs}" opacity="0.5"/>` : ''}
  ${scene === 'forest' ? Array.from({ length: 8 }, (_, i) => `<polygon points="${(i * 22 + 8).toFixed(0)},${horizonY},${(i * 22 + 12).toFixed(0)},${(horizonY - 10 - r() * 6).toFixed(1)},${(i * 22 + 16).toFixed(0)},${horizonY}" fill="${cs}" opacity="0.7"/>`).join('') : ''}
  ${scene === 'ocean' ? Array.from({ length: 3 }, (_, i) => `<path d="M0,${(horizonY + 6 + i * 5).toFixed(0)} Q40,${(horizonY + 4 + i * 5).toFixed(0)} 80,${(horizonY + 6 + i * 5).toFixed(0)} T160,${(horizonY + 6 + i * 5).toFixed(0)}" stroke="${c3}" stroke-width="0.5" fill="none" opacity="0.4"/>`).join('') : ''}
  <ellipse cx="80" cy="${(horizonY + 6).toFixed(0)}" rx="5" ry="9" fill="${cs}"/>
  <circle cx="80" cy="${(horizonY - 2).toFixed(0)}" r="2.5" fill="${cs}"/>
</svg>`;
}

function escapeXml(s: string): string {
  return s.replace(/[<>&'"]/g, (ch) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[ch] as string));
}

/** Convert SVG string to a data URI usable in CSS background-image. */
export function svgDataUri(svg: string): string {
  // base64 is safer than url-encoding for arbitrary characters
  const b64 = btoa(unescape(encodeURIComponent(svg)));
  return `url("data:image/svg+xml;base64,${b64}") center/cover`;
}
