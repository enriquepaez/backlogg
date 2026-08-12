import { z } from "zod";

/**
 * Client-side mirror of the backend's `UserUpdate` (`docs/api.md`:
 * `PATCH /v1/users/me`), kept free of `server-only` imports so
 * `account-profile-form.tsx` ("use client") can import it directly — same
 * split as `lib/auth/schemas.ts`.
 *
 * The backend itself imposes NO length/format constraints on `UserUpdate`
 * (`backlogg/users/schemas.py`: plain `str | None` fields) — `display_name`'s
 * 255-char cap here is borrowed from `UserCreate` (the same column), and
 * `bio`'s 2000-char cap and `avatar_url`'s URL-format check are UX-only
 * choices with no backend equivalent, not a mirrored constraint. A 422 from
 * the backend is still handled by `account-profile-form.tsx` as a fallback.
 */
export const profileSchema = z.object({
  displayName: z.string().trim().max(255).optional(),
  bio: z.string().trim().max(2000).optional(),
  avatarUrl: z
    .string()
    .trim()
    .max(2048)
    .optional()
    .refine((value) => !value || isHttpUrl(value), { message: "avatarUrl" }),
});

export type ProfileFormValues = z.infer<typeof profileSchema>;

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}
