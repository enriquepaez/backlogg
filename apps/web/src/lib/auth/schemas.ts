import { z } from "zod";
import type { FieldValues, Path, UseFormSetError } from "react-hook-form";

/**
 * Client-side mirror of the backend's `UserCreate` (`docs/api.md`: `/v1/auth/register`)
 * and `UserLogin` (`/v1/auth/login`) constraints — kept free of `server-only`
 * imports so both `register-form.tsx` and `login-form.tsx` ("use client") can
 * import it directly. The backend remains the source of truth (this only
 * catches the common cases before a round trip; a 422 from the backend is
 * still handled by the forms as a fallback).
 */

/** `username`: `^[a-zA-Z0-9_-]+$`, 3-50 chars (`UserCreate` in `packages/api-client/openapi.json`). */
export const usernameSchema = z
  .string()
  .trim()
  .min(3)
  .max(50)
  .regex(/^[a-zA-Z0-9_-]+$/);

/** `password`: 8-255 chars for registration (`UserCreate`). */
export const passwordSchema = z.string().min(8).max(255);

export const registerSchema = z.object({
  username: usernameSchema,
  email: z.string().trim().min(3).max(255).email(),
  password: passwordSchema,
  // Optional in `UserCreate` (`string | null`). An empty input is treated as
  // "not provided" by `register-form.tsx` before this is sent to the BFF, but
  // the schema itself still needs to accept `""` since that's react-hook-form's
  // default value for an untouched text input.
  displayName: z.string().trim().max(255).optional(),
});

export type RegisterFormValues = z.infer<typeof registerSchema>;

/**
 * `UserLogin` has no format/length constraints beyond "required" — this only
 * catches empty submissions before hitting the backend (which would answer
 * 422 for the same reason).
 */
export const loginSchema = z.object({
  username: z.string().trim().min(1),
  password: z.string().min(1),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

/**
 * Client-side mirror of `ForgotPasswordRequest` (`docs/api.md`:
 * `POST /v1/auth/password/forgot`) — an email format check before the
 * request is sent. The backend answers `202` unconditionally regardless of
 * this format check (no enumeration either way), so this only avoids a
 * pointless round trip for an obviously malformed input.
 */
export const forgotPasswordSchema = z.object({
  email: z.string().trim().min(3).max(255).email(),
});

export type ForgotPasswordFormValues = z.infer<typeof forgotPasswordSchema>;

/**
 * Client-side mirror of `ResetPasswordRequest` (`docs/api.md`:
 * `POST /v1/auth/password/reset`) — reuses `passwordSchema` (min 8) for
 * `new_password`, the same constraint the backend enforces.
 */
export const resetPasswordSchema = z.object({
  password: passwordSchema,
});

export type ResetPasswordFormValues = z.infer<typeof resetPasswordSchema>;

/**
 * Applies every top-level field failure from a zod validation error to a
 * react-hook-form `setError`, using the field name itself as the error
 * `message`.
 *
 * This is a deliberate stand-in for `@hookform/resolvers/zod` (not part of
 * this feature's added dependencies — see `frontend_feature_list.json`'s
 * FE-13 scope, which only calls for `react-hook-form` and `zod`): rather than
 * surfacing zod's own English default messages, each form looks up the
 * user-facing, localized copy from `Auth.<form>.errors.<field>` using this
 * same field name as the i18n key (see `register-form.tsx` / `login-form.tsx`).
 */
export function applyZodFieldErrors<T extends FieldValues>(
  error: z.ZodError<T>,
  setError: UseFormSetError<T>,
): void {
  const seen = new Set<string>();
  for (const issue of error.issues) {
    const field = issue.path[0];
    if (typeof field !== "string" || seen.has(field)) {
      continue;
    }
    seen.add(field);
    setError(field as Path<T>, { type: "manual", message: field });
  }
}
