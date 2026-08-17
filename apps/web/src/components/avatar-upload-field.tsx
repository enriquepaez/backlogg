"use client";

import { type ChangeEvent, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const MAX_BYTES = 5 * 1024 * 1024;

type Status = "idle" | "uploading" | "removing";
type FieldError = "invalidType" | "tooLarge" | "unauthorized" | "unavailable" | "generic" | null;

type AvatarUploadResponse = { avatar_url?: string | null };

/**
 * File-upload counterpart to the plain-URL `avatarUrl` input in
 * `account-profile-form.tsx` (FE-31). Talks to `POST`/`DELETE
 * /api/users/me/avatar` (the BFF proxy for the feature-51 backend endpoint),
 * never to `PATCH /v1/users/me` — the two mechanisms are independent, this
 * one just needs to keep the parent's `avatarUrl` state in sync via
 * `onUpdated` so the plain-URL input and the nav (`router.refresh()`, done
 * by the parent) reflect whichever mechanism last won.
 *
 * Upload progress needs real byte-level events, which `fetch` cannot
 * report — only `XMLHttpRequest`'s `upload.onprogress` can, hence the raw
 * XHR call here instead of the `fetch` used everywhere else in this app.
 */
export function AvatarUploadField({
  avatarUrl,
  onUpdated,
}: {
  avatarUrl: string | null;
  onUpdated: (avatarUrl: string | null) => void;
}) {
  const t = useTranslations("Settings.profile.avatar");
  const inputRef = useRef<HTMLInputElement>(null);

  const [preview, setPreview] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<FieldError>(null);

  const displayUrl = preview ?? avatarUrl;

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    // Reset so picking the same (rejected) file again still fires `onChange`.
    event.target.value = "";
    if (!file) {
      return;
    }

    if (!ACCEPTED_TYPES.includes(file.type)) {
      setError("invalidType");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("tooLarge");
      return;
    }

    setError(null);
    upload(file);
  }

  function upload(file: File) {
    const objectUrl = URL.createObjectURL(file);
    setPreview(objectUrl);
    setStatus("uploading");
    setProgress(0);

    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/users/me/avatar");
    xhr.upload.onprogress = (progressEvent) => {
      if (progressEvent.lengthComputable) {
        setProgress(Math.round((progressEvent.loaded / progressEvent.total) * 100));
      }
    };
    xhr.onload = () => {
      setStatus("idle");
      URL.revokeObjectURL(objectUrl);
      setPreview(null);

      if (xhr.status === 200) {
        let nextAvatarUrl: string | null = null;
        try {
          nextAvatarUrl = (JSON.parse(xhr.responseText) as AvatarUploadResponse).avatar_url ?? null;
        } catch {
          nextAvatarUrl = null;
        }
        onUpdated(nextAvatarUrl);
        toast.success(t("uploadSuccess"));
        return;
      }

      if (xhr.status === 401) {
        setError("unauthorized");
        return;
      }
      if (xhr.status === 413) {
        setError("tooLarge");
        return;
      }
      if (xhr.status === 422) {
        setError("invalidType");
        return;
      }
      if (xhr.status === 503) {
        setError("unavailable");
        return;
      }
      setError("generic");
    };
    xhr.onerror = () => {
      setStatus("idle");
      URL.revokeObjectURL(objectUrl);
      setPreview(null);
      setError("generic");
    };
    xhr.send(formData);
  }

  async function handleRemove() {
    setStatus("removing");
    setError(null);

    let response: Response;
    try {
      response = await fetch("/api/users/me/avatar", { method: "DELETE" });
    } catch {
      setStatus("idle");
      setError("generic");
      return;
    }

    setStatus("idle");

    if (response.status === 204) {
      onUpdated(null);
      toast.success(t("removeSuccess"));
      return;
    }
    if (response.status === 401) {
      setError("unauthorized");
      return;
    }
    setError("generic");
  }

  const errorMessage =
    error === "invalidType"
      ? t("errors.invalidType")
      : error === "tooLarge"
        ? t("errors.tooLarge")
        : error === "unauthorized"
          ? t("unauthorized")
          : error === "unavailable"
            ? t("errors.unavailable")
            : error === "generic"
              ? t("errors.generic")
              : null;

  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium">{t("heading")}</span>

      <div className="flex items-center gap-3">
        {displayUrl ? (
          // Same rationale as `user-nav.tsx`: avatar hosts (own upload or an
          // arbitrary pasted URL) aren't in `next/image`'s remotePatterns.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={displayUrl} alt="" className="size-14 rounded-full object-cover" />
        ) : (
          <span
            aria-hidden="true"
            className="flex size-14 items-center justify-center rounded-full bg-muted"
          />
        )}

        <div className="flex flex-col gap-2">
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={status === "uploading"}
              onClick={() => inputRef.current?.click()}
            >
              {avatarUrl ? t("changeFile") : t("chooseFile")}
            </Button>
            {avatarUrl ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={status !== "idle"}
                onClick={handleRemove}
              >
                {status === "removing" ? t("removing") : t("remove")}
              </Button>
            ) : null}
          </div>

          {status === "uploading" ? (
            <div className="flex items-center gap-2">
              <progress aria-label={t("progressLabel")} value={progress} max={100} className="h-2 w-32" />
              <span className="text-xs text-muted-foreground">{t("uploading")}</span>
            </div>
          ) : null}
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES.join(",")}
        onChange={handleFileChange}
        aria-label={t("chooseFile")}
        className="sr-only"
      />

      <p
        role={errorMessage ? "alert" : undefined}
        className={`text-sm ${errorMessage ? "text-destructive" : "invisible"}`}
      >
        {errorMessage ?? " "}
      </p>

      <p className="text-xs text-muted-foreground">{t("orPasteUrl")}</p>
    </div>
  );
}
