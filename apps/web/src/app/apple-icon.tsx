import { ImageResponse } from "next/og";

/**
 * Apple touch icon (FE-6) for "Add to Home Screen" on iOS/iPadOS — Safari
 * reads this dedicated icon rather than the web manifest's `icons` array.
 * 180x180 is Apple's recommended size. See `icon.tsx` for why this is
 * generated rather than a static file.
 */
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
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
          fontSize: 108,
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
