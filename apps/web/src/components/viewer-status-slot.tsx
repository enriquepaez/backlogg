export type ViewerStatusSlotProps = {
  /**
   * `MovieOut.viewer_status` / `SeriesOut.viewer_status` / etc — the caller's
   * library status for this item (`want`/`in_progress`/`completed`/
   * `dropped`), or `null`/`undefined` when unauthenticated or with no
   * library entry (`docs/api.md`). Currently unused: see doc comment below.
   */
  status: string | null | undefined;
};

/**
 * Extension point for the item detail page's "your status" UI (FE-10
 * acceptance: "hueco de viewer_status (auth-opcional)"). Auth-optional
 * fetching already exists end-to-end on the backend (every detail endpoint
 * accepts an optional bearer token and echoes back `viewer_status`), but the
 * frontend has no session plumbing yet on public catalog pages — FE-2/FE-4's
 * `getApiClient()` (reused by `src/lib/catalog.ts`) deliberately never sends
 * cookies or an `Authorization` header for these public, ISR-cached fetches.
 * Session UX (FE-14) and the library/backlog feature that actually reads
 * and writes this status (FE-20) are both still pending in
 * `frontend_feature_list.json`.
 *
 * Renders nothing today by design — this is purely a wiring point (imported
 * and mounted from `item-hero.tsx` with the item's `viewer_status` already
 * threaded through) so that a future feature only has to fill in this one
 * component instead of re-plumbing the item detail page. Doesn't block
 * render when there's no session, per the acceptance criteria.
 */
// `status` is unused today (see doc comment above); kept as a named, typed
// parameter so the prop stays part of this component's public contract for
// whichever future feature (FE-14/FE-20) fills in the render.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function ViewerStatusSlot({ status }: ViewerStatusSlotProps) {
  return null;
}
