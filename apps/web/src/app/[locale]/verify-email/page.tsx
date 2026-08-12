import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { VerifyEmailStatus } from "@/components/verify-email-status";

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** OG metadata for `/verify-email` (FE-15), same shape as `/login`'s `generateMetadata` (FE-13). */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/verify-email">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.verifyEmail" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

/**
 * Destination of the email-verification link the backend sends
 * (`docs/api.md`: `POST /v1/auth/verify/request`, built from `APP_BASE_URL`
 * — see `docs/architecture.md`'s account-recovery feature for how that env
 * var is wired, unchanged by this feature).
 *
 * The token is read here (a Server Component, via the `searchParams` prop —
 * the same pattern `/search`'s page uses for `q`/`type`/`page`) rather than
 * with `useSearchParams` in the client component below, so no `Suspense`
 * boundary is needed and the token is available for the very first render.
 * All the actual confirm-call/state logic lives in `VerifyEmailStatus`
 * (`"use client"`, since firing the (non-idempotent) `POST` needs an effect).
 */
export default async function VerifyEmailPage({
  params,
  searchParams,
}: PageProps<"/[locale]/verify-email">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const token = firstValue(query.token);

  const t = await getTranslations("Auth.verifyEmail");

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-8 px-6 py-16">
      <Card>
        <CardHeader>
          <CardTitle>{t("heading")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <VerifyEmailStatus token={token} />
        </CardContent>
      </Card>
    </div>
  );
}
