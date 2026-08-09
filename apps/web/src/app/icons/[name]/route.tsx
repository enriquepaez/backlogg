import { ImageResponse } from "next/og";

/**
 * PNG icons referenced by `src/app/manifest.ts`'s `icons` array — Lighthouse's
 * installability audit requires at least one icon >= 192x192 and one >=
 * 512x512. Generated with `ImageResponse` (see `icon.tsx`) rather than
 * static files, since no brand assets exist in the repo yet.
 *
 * A single parametrized route (instead of three near-identical files) keeps
 * the "B" mark definition in one place. `force-static` + `generateStaticParams`
 * prerender all three at build time — the response doesn't depend on the
 * request.
 */
const ICON_SPECS = {
  "icon-192": { size: 192, maskable: false },
  "icon-512": { size: 512, maskable: false },
  "icon-512-maskable": { size: 512, maskable: true },
} as const;

type IconName = keyof typeof ICON_SPECS;

function isIconName(value: string): value is IconName {
  return Object.hasOwn(ICON_SPECS, value);
}

export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  return Object.keys(ICON_SPECS).map((name) => ({ name }));
}

export async function GET(_request: Request, { params }: RouteContext<"/icons/[name]">) {
  const { name } = await params;
  if (!isIconName(name)) {
    return new Response("Not found", { status: 404 });
  }

  const { size, maskable } = ICON_SPECS[name];
  // Maskable icons are cropped into arbitrary shapes by the OS, so the
  // background must fill the entire canvas edge-to-edge and the mark must
  // stay within the ~80% "safe zone" (a smaller scale here than the regular,
  // non-maskable icons).
  const markFontSize = Math.round(size * (maskable ? 0.42 : 0.56));

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#18181b",
          color: "#fafafa",
          fontSize: markFontSize,
          fontWeight: 700,
          fontFamily: "sans-serif",
        }}
      >
        B
      </div>
    ),
    { width: size, height: size },
  );
}
