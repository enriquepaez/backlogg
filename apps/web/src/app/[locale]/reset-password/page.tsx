import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ResetPasswordStatus } from "@/components/reset-password-status";

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** OG metadata for `/reset-password` (FE-16), same shape as `/verify-email`'s `generateMetadata` (FE-15). */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/reset-password">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.resetPassword" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

/**
 * Destination of the password-reset link the backend sends
 * (`docs/api.md`: `POST /v1/auth/password/forgot`, built from `APP_BASE_URL` —
 * same env var `/verify-email` relies on, unchanged by this feature).
 *
 * The token is read here (a Server Component, via the `searchParams` prop —
 * same pattern as `/verify-email`'s page) rather than with `useSearchParams`
 * in the client component below, so no `Suspense` boundary is needed and the
 * token is available for the very first render. All the actual form/state
 * logic lives in `ResetPasswordStatus` (`"use client"`).
 */
export default async function ResetPasswordPage({
  params,
  searchParams,
}: PageProps<"/[locale]/reset-password">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const token = firstValue(query.token);

  const t = await getTranslations("Auth.resetPassword");

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-8 px-6 py-16">
      <Card>
        <CardHeader>
          <CardTitle>{t("heading")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <ResetPasswordStatus token={token} />
        </CardContent>
      </Card>
    </div>
  );
}
