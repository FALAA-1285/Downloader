"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState, type FormEvent } from "react";
import { ArrowRight, ClipboardPaste, Link2, Loader2, TriangleAlert } from "lucide-react";
import type { MediaType } from "@/types";
import { checkUrl } from "@/lib/url";
import { cn } from "@/lib/utils";
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
          "focus-within:shadow-[0_0_0_4px_var(--ring),0_8px_24px_-12px_rgb(17_24_39/0.12)]",
          error ? "border-bad/60" : "border-line-strong focus-within:border-accent",
        )}
      >
        <Link2 className="size-[18px] shrink-0 text-muted" aria-hidden />
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
            "min-w-0 flex-1 bg-transparent font-mono text-ink outline-none placeholder:text-muted/70 focus-visible:outline-none",
            compact ? "h-9 text-[13px]" : "h-11 text-[14px] sm:text-[15px]",
          )}
        />
        <button
          type="button"
          onClick={paste}
          className="hidden h-9 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink sm:flex"
        >
          <ClipboardPaste className="size-3.5" aria-hidden />
          Tempel
        </button>
        <button
          type="submit"
          disabled={submitting}
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-[10px] bg-ink px-4 font-medium text-bg transition-colors hover:bg-ink/85 disabled:opacity-60",
            compact ? "h-9 text-[13px]" : "h-11 text-[15px]",
          )}
        >
          {submitting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
          Analisis
          {!submitting && <ArrowRight className="size-4" aria-hidden />}
        </button>
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
    </form>
  );
}
