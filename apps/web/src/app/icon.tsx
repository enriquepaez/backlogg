import { ImageResponse } from "next/og";

/**
 * Browser tab favicon (FE-6), generated at build time — no brand assets
 * exist in the repo yet, so this uses `ImageResponse` instead of a
 * hand-crafted binary (per
 * `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/01-metadata/app-icons.md`,
 * "Generate icons using code"). Adds an extra `<link rel="icon"
 * sizes="32x32" type="image/png">` alongside the existing `favicon.ico`
 * placeholder; browsers prefer the more specific PNG.
 */
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
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
          fontSize: 22,
          fontWeight: 700,
          fontFamily: "sans-serif",
        }}
      >
        B
      </div>
    ),
    { ...size },
  );
}
