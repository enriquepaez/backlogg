import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { AccountProfileForm } from "@/components/account-profile-form";
import { AccountVerificationStatus } from "@/components/account-verification-status";
import { DeleteAccountDialog } from "@/components/delete-account-dialog";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { redirect } from "@/i18n/navigation";
import { getCurrentUser } from "@/lib/api-fetch";

/** OG metadata for `/settings` (FE-17), same shape as `/login`'s `generateMetadata` (FE-13). */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/settings">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.settings" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    // Private, per-account page — never worth indexing, unlike the public
    // catalog/profile pages this app otherwise optimizes for SEO.
    robots: { index: false, follow: false },
    openGraph: { title, description, type: "website" },
  };
}

/**
 * Account settings (FE-17): edit profile, see/verify email status, delete
 * account. `proxy.ts` already redirects unauthenticated requests to
 * `/settings` away at the edge (`lib/auth/protected-routes.ts` lists it), but
 * that check only looks at cookie PRESENCE, not validity — this page still
 * calls `getCurrentUser()` itself (the real, server-side session check) and
 * redirects to `/login` on `null`, same defense-in-depth the docs describe
 * for every private route.
 */
export default async function SettingsPage({ params }: PageProps<"/[locale]/settings">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const user = await getCurrentUser();
  if (!user) {
    redirect({ href: "/login", locale });
    return;
  }

  const t = await getTranslations("Settings");

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-8 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("heading")}</h1>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("profile.heading")}</CardTitle>
          <CardDescription>{t("profile.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <AccountProfileForm
            initial={{
              displayName: user.display_name,
              bio: user.bio,
              avatarUrl: user.avatar_url,
            }}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("verification.heading")}</CardTitle>
        </CardHeader>
        <CardContent>
          <AccountVerificationStatus emailVerified={user.email_verified} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("deleteAccount.sectionHeading")}</CardTitle>
          <CardDescription>{t("deleteAccount.sectionDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <DeleteAccountDialog username={user.username} />
        </CardContent>
      </Card>
    </div>
  );
}
