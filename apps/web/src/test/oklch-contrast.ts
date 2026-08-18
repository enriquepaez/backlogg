/**
 * Minimal OKLCH -> sRGB -> WCAG contrast-ratio helpers, used only by tests
 * that verify the design tokens in `globals.css` meet WCAG AA (FE-40, and
 * the library-status-color tokens from FE-37 before it). Not imported by
 * any production code path.
 *
 * Conversion matrices are Björn Ottosson's OKLab <-> linear sRGB ones (the
 * same ones documented, by hand, in the `globals.css` comments this test
 * file backs up with an executable check).
 */

export type Oklch = { l: number; c: number; h: number };

function oklchToLinearSrgb({ l, c, h }: Oklch): [number, number, number] {
  const hRad = (h * Math.PI) / 180;
  const a = c * Math.cos(hRad);
  const b = c * Math.sin(hRad);

  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.2914855480 * b;

  const lCubed = l_ ** 3;
  const mCubed = m_ ** 3;
  const sCubed = s_ ** 3;

  const r = 4.0767416621 * lCubed - 3.3077115913 * mCubed + 0.2309699292 * sCubed;
  const g = -1.2684380046 * lCubed + 2.6097574011 * mCubed - 0.3413193965 * sCubed;
  const bl = -0.0041960863 * lCubed - 0.7034186147 * mCubed + 1.7076147010 * sCubed;

  return [r, g, bl];
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  const clamp = (x: number) => Math.min(1, Math.max(0, x));
  return 0.2126 * clamp(r) + 0.7152 * clamp(g) + 0.0722 * clamp(b);
}

/** WCAG 2.x contrast ratio (1:1 to 21:1) between two OKLCH colors. */
export function contrastRatio(a: Oklch, b: Oklch): number {
  const lumA = relativeLuminance(oklchToLinearSrgb(a));
  const lumB = relativeLuminance(oklchToLinearSrgb(b));
  const lighter = Math.max(lumA, lumB);
  const darker = Math.min(lumA, lumB);
  return (lighter + 0.05) / (darker + 0.05);
}

/** Parses a CSS `oklch(L C H)` function body (no `/` alpha support needed here). */
export function parseOklch(value: string): Oklch {
  const match = value.trim().match(/^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)$/);
  if (!match) {
    throw new Error(`Not a plain oklch(L C H) value: ${value}`);
  }
  const [, l, c, h] = match;
  return { l: Number(l), c: Number(c), h: Number(h) };
}
