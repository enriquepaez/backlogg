import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { contrastRatio, parseOklch, type Oklch } from "@/test/oklch-contrast";

// Reads the real stylesheet so this test regresses if a future edit to
// `globals.css` drops the accent token's chroma/lightness below the WCAG AA
// floor this feature (FE-40) was built to satisfy — see the token
// definitions and their rationale comments in `globals.css` itself.
const CSS_PATH = path.join(process.cwd(), "src/app/globals.css");
// Strips `/* ... */` comments before any parsing below — several of them are
// long design-rationale notes that themselves contain inline-code snippets
// like `` `--background: oklch(...)` ``, which would otherwise be
// misread as real declarations by the regex-based parsing below.
const css = readFileSync(CSS_PATH, "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Extracts the `{ ... }` body of the first `selector { ... }` block, by brace counting (handles the nested `@theme inline { ... }` block elsewhere in the file, and comments containing braces, safely since we only scan from the selector's own opening brace). */
function extractBlock(source: string, selectorPattern: RegExp): string {
  const match = selectorPattern.exec(source);
  if (!match) {
    throw new Error(`Selector not found: ${selectorPattern}`);
  }
  const start = match.index + match[0].length;
  let depth = 1;
  let i = start;
  while (depth > 0 && i < source.length) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}") depth--;
    i++;
  }
  return source.slice(start, i - 1);
}

/** Parses `--name: value;` declarations out of a block body into a name -> raw-value map. */
function parseDeclarations(block: string): Map<string, string> {
  const declarations = new Map<string, string>();
  const re = /(--[a-z0-9-]+)\s*:\s*([^;]+);/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(block)) !== null) {
    declarations.set(m[1], m[2].trim());
  }
  return declarations;
}

/** Resolves a raw value that may be a literal `oklch(...)` or a `var(--other)` reference into the other token in the same theme block. */
function resolveOklch(name: string, declarations: Map<string, string>): Oklch {
  const raw = declarations.get(name);
  if (!raw) {
    throw new Error(`Token not found: ${name}`);
  }
  const varMatch = raw.match(/^var\((--[a-z0-9-]+)\)$/);
  if (varMatch) {
    return resolveOklch(varMatch[1], declarations);
  }
  return parseOklch(raw);
}

const rootBlock = extractBlock(css, /:root\s*\{/);
const darkBlock = extractBlock(css, /\n\.dark\s*\{/);

const root = parseDeclarations(rootBlock);
const dark = parseDeclarations(darkBlock);

const AA_TEXT = 4.5;
const AA_UI = 3;

describe("globals.css brand accent tokens (FE-40)", () => {
  it("gives --accent real chroma in both themes (not the chroma-0 gray the design audit flagged)", () => {
    expect(resolveOklch("--accent", root).c).toBeGreaterThan(0);
    expect(resolveOklch("--accent", dark).c).toBeGreaterThan(0);
  });

  it.each([
    ["light", root, "--background"],
    ["dark", dark, "--background"],
  ] as const)(
    "--accent as link text on %s --background clears AA (>= 4.5:1)",
    (_theme, tokens, bgName) => {
      const ratio = contrastRatio(resolveOklch("--accent", tokens), resolveOklch(bgName, tokens));
      expect(ratio).toBeGreaterThanOrEqual(AA_TEXT);
    },
  );

  it.each([
    ["light", root],
    ["dark", dark],
  ] as const)("--accent-foreground text on --accent button background clears AA (%s theme)", (_theme, tokens) => {
    const ratio = contrastRatio(resolveOklch("--accent", tokens), resolveOklch("--accent-foreground", tokens));
    expect(ratio).toBeGreaterThanOrEqual(AA_TEXT);
  });

  it.each([
    ["light", root],
    ["dark", dark],
  ] as const)("--accent-hover keeps AA against --accent-foreground (%s theme)", (_theme, tokens) => {
    const ratio = contrastRatio(
      resolveOklch("--accent-hover", tokens),
      resolveOklch("--accent-foreground", tokens),
    );
    expect(ratio).toBeGreaterThanOrEqual(AA_TEXT);
  });

  it.each([
    ["light", root],
    ["dark", dark],
  ] as const)("--ring (focus indicator) clears the non-text AA floor (>= 3:1) against --background (%s theme)", (
    _theme,
    tokens,
  ) => {
    const ratio = contrastRatio(resolveOklch("--ring", tokens), resolveOklch("--background", tokens));
    expect(ratio).toBeGreaterThanOrEqual(AA_UI);
  });

  it.each([
    ["light", root],
    ["dark", dark],
  ] as const)("--primary/--ring alias --accent, so primary buttons/links/focus rings inherit the brand color (%s theme)", (
    _theme,
    tokens,
  ) => {
    expect(tokens.get("--primary")).toBe("var(--accent)");
    expect(tokens.get("--primary-foreground")).toBe("var(--accent-foreground)");
    expect(tokens.get("--ring")).toBe("var(--accent)");
  });
});

describe("globals.css --font-heading token (FE-40)", () => {
  it("is no longer aliased to --font-sans", () => {
    const themeInline = extractBlock(css, /@theme inline\s*\{/);
    const declarations = parseDeclarations(themeInline);
    expect(declarations.get("--font-heading")).not.toBe("var(--font-sans)");
    expect(declarations.get("--font-heading")).toBe("var(--font-heading)");
  });

  it("h1-h6 apply the font-heading utility in the base layer", () => {
    const baseLayer = extractBlock(css, /@layer base\s*\{/);
    expect(baseLayer).toMatch(/h1,\s*\n\s*h2,\s*\n\s*h3,\s*\n\s*h4,\s*\n\s*h5,\s*\n\s*h6\s*\{\s*\n\s*@apply font-heading;/);
  });
});
