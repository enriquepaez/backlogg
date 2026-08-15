import { z } from "zod";

/**
 * Client-side mirror of the backend's `ListCreate`/`ListUpdate`
 * (`docs/api.md`: `POST /v1/lists`, `PATCH /v1/lists/{slug}`) — kept free of
 * `server-only` imports so `create-list-dialog.tsx`/`edit-list-dialog.tsx`
 * ("use client") can import it directly, same split as
 * `../settings/schemas.ts` vs `../library.ts`.
 *
 * `title`'s `1..200` bounds mirror the backend's own `Field(min_length=1,
 * max_length=200)` (`backlogg/lists/schemas.py`) exactly. `description`'s
 * 2000-char cap has no backend equivalent (`str | None` with no `Field`
 * constraints) — a UX-only choice, same rationale as `profileSchema.bio` in
 * `../settings/schemas.ts`. A 422 from the backend is still handled by both
 * dialogs as a fallback.
 */
export const listSchema = z.object({
  title: z.string().trim().min(1).max(200),
  description: z.string().trim().max(2000).optional(),
  isPublic: z.boolean(),
});

export type ListFormValues = z.infer<typeof listSchema>;
