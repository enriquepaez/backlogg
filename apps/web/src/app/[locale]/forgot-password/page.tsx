import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { ForgotPasswordForm } from "@/components/forgot-password-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";

/** OG metadata for `/forgot-password` (FE-16), same shape as `/login`'s `generateMetadata` (FE-13). */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/forgot-password">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.forgotPassword" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

export default async function ForgotPasswordPage({
  params,
}: PageProps<"/[locale]/forgot-password">) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Auth.forgotPassword");

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-8 px-6 py-16">
      <Card>
        <CardHeader>
          <CardTitle>{t("heading")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          <ForgotPasswordForm />
          <p className="text-sm text-muted-foreground">
            <Link
              href="/login"
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              {t("backToLogin")}
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
