import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { RegisterForm } from "@/components/register-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";

/** OG metadata for `/register` (FE-13), same shape as `/search`'s `generateMetadata` (FE-11). */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/register">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.register" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

export default async function RegisterPage({ params }: PageProps<"/[locale]/register">) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Auth.register");

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-8 px-6 py-16">
      <Card>
        <CardHeader>
          <CardTitle>{t("heading")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          <RegisterForm />
          <p className="text-sm text-muted-foreground">
            {t("haveAccount")}{" "}
            <Link
              href="/login"
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              {t("loginLink")}
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
