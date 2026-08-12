/**
 * Locale-aware date formatter for review timestamps (`RatingOut.created_at`/
 * `updated_at`, FE-18's "Your rating" summary) — the first date-formatting
 * helper in the frontend. Other catalog dates (`release_date`, etc.) are
 * rendered as raw ISO strings elsewhere in the app and are out of scope
 * here (see `progress/current.md`'s refinement plan for the review dates
 * feedback).
 *
 * `iso` is an ISO 8601 date-time string (`RatingOut.created_at`/
 * `updated_at` — `docs/api.md` types both as `format: date-time`). `locale`
 * is the app's active `next-intl` locale (`useLocale()`), so the formatted
 * date matches whatever locale the rest of the page renders in.
 *
 * Pinned to `timeZone: "UTC"` rather than the runtime's local timezone: the
 * backend timestamps are UTC (`docs/schema.md`), and formatting in whatever
 * timezone the server/browser happens to run in would make the exact date
 * shown (and therefore this helper's tests) depend on where the code runs.
 */
export function formatDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "long", timeZone: "UTC" }).format(new Date(iso));
}
