"use client"; // Error boundaries must be Client Components.

import { useEffect } from "react";

// Last-resort boundary for errors thrown by the root layout itself
// (`[locale]/layout.tsx`) — `[locale]/error.tsx` does NOT cover those (see
// `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md`:
// "error.js ... does not wrap the layout.js ... above it in the same
// segment"). Renders its own <html>/<body> and intentionally skips the
// design system / next-intl (neither is guaranteed to be usable if the root
// layout itself failed) — plain, static, English-only markup per the Next.js
// docs' own recommendation to keep this page minimal.
export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, sans-serif",
          display: "flex",
          minHeight: "100dvh",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          padding: "1.5rem",
          textAlign: "center",
        }}
      >
        <h2 style={{ fontSize: "1.5rem", fontWeight: 600, margin: 0 }}>
          Something went wrong
        </h2>
        <p style={{ color: "#71717a", margin: 0, maxWidth: "28rem" }}>
          An unexpected error occurred. You can try again.
        </p>
        <button
          type="button"
          onClick={() => retry()}
          style={{
            marginTop: "0.5rem",
            padding: "0.5rem 1.25rem",
            borderRadius: "0.5rem",
            border: "1px solid #d4d4d8",
            background: "transparent",
            cursor: "pointer",
            fontSize: "0.875rem",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
