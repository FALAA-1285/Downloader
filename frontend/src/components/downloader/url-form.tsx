"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState, type FormEvent } from "react";
import { ArrowRight, ChevronDown, ChevronUp, ClipboardPaste, KeyRound, Link2, Loader2, TriangleAlert } from "lucide-react";
import type { MediaType } from "@/types";
import { checkUrl } from "@/lib/url";
import { cn } from "@/lib/utils";
import { cookiesForUrl, normalizeDomain, saveCookieEntry, useCookieEntries } from "@/lib/cookie-store";
import { Button } from "@/components/ui/button";
import { TypeIcon } from "@/components/ui/primitives";

const TYPES: Array<{ id: MediaType; label: string }> = [
  { id: "image", label: "Gambar" },
  { id: "video", label: "Video" },
  { id: "subtitle", label: "Subtitle" },
  { id: "text", label: "Teks" },
];

export function UrlForm({
  defaultUrl = "",
  defaultTypes = [],
  compact = false,
}: {
  defaultUrl?: string;
  defaultTypes?: MediaType[];
  compact?: boolean;
}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const errorId = useId();
  const [url, setUrl] = useState(defaultUrl);
  const [types, setTypes] = useState<MediaType[]>(defaultTypes);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [customCookies, setCustomCookies] = useState("");
  // Berlangganan perubahan cookie agar label "Aktif" ikut diperbarui.
  useCookieEntries();
  const targetDomain = normalizeDomain(checkUrl(url).ok ? url : null);
  const hasSavedCookies = targetDomain ? cookiesForUrl(`https://${targetDomain}/`) !== null : false;

  function toggle(t: MediaType) {
    setTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const res = checkUrl(url);
    if (!res.ok) {
      setError(res.message);
      inputRef.current?.focus();
      return;
    }
    if (customCookies.trim()) {
      // Cookie hanya berlaku untuk domain URL ini (dan subdomainnya), bukan untuk semua situs.
      const domain = normalizeDomain(res.url);
      if (domain) saveCookieEntry(domain.replace(/^www\./, ""), customCookies);
      setCustomCookies("");
    }
    setError(null);
    setSubmitting(true);
    const qs = new URLSearchParams({ url: res.url });
    if (types.length && types.length < TYPES.length) qs.set("types", types.join(","));
    router.push(`/analyze?${qs.toString()}`);
    // Reset setelah navigasi agar tombol tidak terkunci jika URL sama.
    setTimeout(() => setSubmitting(false), 1200);
  }

  async function paste() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        setUrl(text.trim());
        setError(null);
        inputRef.current?.focus();
      }
    } catch {
      inputRef.current?.focus();
    }
  }

  const allActive = types.length === 0 || types.length === TYPES.length;

  return (
    <form onSubmit={submit} noValidate className="w-full">
      <div
        className={cn(
          "group flex items-center gap-2 rounded-2xl border bg-bg p-1.5 pl-4 transition-shadow",
          "shadow-[0_1px_2px_rgb(0_0_0/0.04),0_8px_24px_-12px_rgb(17_24_39/0.12)]",
          "focus-within:shadow-[0_0_0_4px_var(--ring-soft),0_8px_24px_-12px_rgb(17_24_39/0.12)]",
          error ? "border-bad/60" : "border-line-strong focus-within:border-brand",
        )}
      >
        <Link2 className="size-[18px] shrink-0 text-muted-foreground" aria-hidden />
        <label htmlFor="url-input" className="sr-only">
          URL halaman
        </label>
        <input
          ref={inputRef}
          id="url-input"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="https://example.com/artikel"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            if (error) setError(null);
          }}
          aria-invalid={!!error}
          aria-describedby={error ? errorId : undefined}
          className={cn(
            "min-w-0 flex-1 bg-transparent font-mono text-ink outline-none placeholder:text-muted-foreground/70 focus-visible:outline-none",
            compact ? "h-9 text-[13px]" : "h-11 text-[14px] sm:text-[15px]",
          )}
        />
        <Button type="button" variant="ghost" onClick={paste} className="hidden text-[13px] sm:inline-flex">
          <ClipboardPaste className="size-3.5" aria-hidden />
          Tempel
        </Button>
        <Button type="submit" disabled={submitting} size={compact ? "default" : "lg"} className={cn(compact && "text-[13px]")}>
          {submitting ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Analisis
          {!submitting && <ArrowRight aria-hidden />}
        </Button>
      </div>

      {error && (
        <p id={errorId} role="alert" className="mt-2.5 flex items-center gap-1.5 pl-1 text-left text-[13px] text-bad">
          <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
          {error}
        </p>
      )}

      <fieldset className={cn("flex flex-wrap items-center gap-1.5", compact ? "mt-3" : "mt-4 justify-center")}>
        <legend className="sr-only">Jenis konten yang dicari</legend>
        <button
          type="button"
          aria-pressed={allActive}
          onClick={() => setTypes([])}
          className={cn(
            "h-8 rounded-full border px-3 text-[13px] transition-colors",
            allActive ? "border-ink bg-ink text-bg" : "border-line-strong bg-bg text-ink-2 hover:text-ink",
          )}
        >
          Semua
        </button>
        {TYPES.map((t) => {
          const on = !allActive && types.includes(t.id);
          return (
            <button
              key={t.id}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(t.id)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
                on ? "border-transparent" : "border-line-strong bg-bg text-ink-2 hover:text-ink",
              )}
              style={on ? { background: `var(--tag-${t.id}-bg)`, color: `var(--tag-${t.id}-fg)` } : undefined}
            >
              <TypeIcon type={t.id} />
              {t.label}
            </button>
          );
        })}
      </fieldset>

      <div className={cn("mt-3 flex flex-col items-center", compact && "mt-2")}>
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground transition-colors hover:text-ink"
        >
          <KeyRound className="size-3.5" aria-hidden />
          <span>Opsi Sesi / Cookie Login</span>
          {hasSavedCookies || customCookies ? (
            <span className="rounded bg-brand-soft px-1.5 py-0.5 text-[10px] font-medium text-brand">Aktif</span>
          ) : null}
          {showAdvanced ? <ChevronUp className="size-3" aria-hidden /> : <ChevronDown className="size-3" aria-hidden />}
        </button>
        {showAdvanced && (
          <div className="mt-2.5 w-full max-w-xl rounded-xl border border-line-strong bg-surface p-3 text-left">
            <label htmlFor="custom-cookies-input" className="block text-[12px] font-medium text-ink">
              Cookie sesi untuk {targetDomain ? <span className="font-mono">{targetDomain.replace(/^www\./, "")}</span> : "domain URL ini"}
            </label>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Format Netscape cookies.txt, JSON, atau <span className="font-mono">nama=nilai;</span>. Cookie hanya dikirim
              ke domain ini dan subdomainnya. {hasSavedCookies && "Cookie tersimpan untuk domain ini sudah aktif; isi baru akan menggantikannya."}{" "}
              Kelola semua cookie di Settings.
            </p>
            <textarea
              id="custom-cookies-input"
              value={customCookies}
              onChange={(e) => setCustomCookies(e.target.value)}
              placeholder="sessionid=xyz123; csrftoken=abc; atau tempel cookies.txt"
              rows={2}
              className="mt-2 w-full rounded-lg border border-line bg-bg p-2 font-mono text-[11px] text-ink outline-none placeholder:text-muted-foreground/60 focus:border-brand"
            />
          </div>
        )}
      </div>
    </form>
  );
}
