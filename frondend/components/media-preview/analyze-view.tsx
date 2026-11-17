"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, CircleAlert, Globe, Info, RotateCcw, SearchX } from "lucide-react";
import type { AnalyzeResult, MediaItem, MediaType } from "@/types";
import { analyzeUrl } from "@/services/api";
import { checkUrl } from "@/lib/url";
import { MEDIA_LABEL, cn, formatRelative } from "@/lib/utils";
import { UrlForm } from "@/components/downloader/url-form";
import { Button, ButtonLink, EmptyState, TypeIcon } from "@/components/ui/primitives";
import { ImageGrid } from "./image-grid";
import { MediaTable } from "./media-table";
import { TextPanel } from "./text-panel";
import { SelectionBar } from "./selection-bar";

const TABS: MediaType[] = ["image", "video", "subtitle", "text"];
const VALID_TYPES = new Set<MediaType>(TABS);

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "done"; result: AnalyzeResult };

export function AnalyzeView() {
  const params = useSearchParams();
  const rawUrl = params.get("url") ?? "";
  const typesParam = params.get("types") ?? "";
  const types = useMemo(
    () => typesParam.split(",").filter((t): t is MediaType => VALID_TYPES.has(t as MediaType)),
    [typesParam],
  );
  const check = useMemo(() => checkUrl(rawUrl), [rawUrl]);
  const [attempt, setAttempt] = useState(0);

  if (!check.ok) {
    return (
      <Shell url={rawUrl} types={types}>
        <EmptyState
          icon={<CircleAlert className="size-5" />}
          title={rawUrl ? "URL tidak dapat dianalisis" : "Belum ada URL"}
          action={<ButtonLink href="/" variant="secondary"><ArrowLeft className="size-4" />Kembali ke Home</ButtonLink>}
        >
          {check.message}
        </EmptyState>
      </Shell>
    );
  }

  // `key` mereset seluruh state (hasil, tab, pilihan) saat URL, filter, atau percobaan berubah.
  return (
    <AnalyzeRun
      key={`${check.url}|${types.join()}|${attempt}`}
      url={check.url}
      types={types}
      onRetry={() => setAttempt((a) => a + 1)}
    />
  );
}

function AnalyzeRun({ url, types, onRetry }: { url: string; types: MediaType[]; onRetry: () => void }) {
  const check = { url };
  const [state, setState] = useState<State>({ kind: "loading" });
  const [tab, setTab] = useState<MediaType | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    analyzeUrl(url, types)
      .then((result) => !cancelled && setState({ kind: "done", result }))
      .catch((e: Error) => !cancelled && setState({ kind: "error", message: e.message }));
    return () => {
      cancelled = true;
    };
  }, [url, types]);

  if (state.kind === "loading") return <AnalyzeSkeleton url={check.url} types={types} />;

  if (state.kind === "error") {
    return (
      <Shell url={check.url} types={types}>
        <EmptyState
          icon={<CircleAlert className="size-5 text-bad" />}
          title="Analisis tidak berhasil"
          action={
            <div className="flex gap-2">
              <Button onClick={onRetry}><RotateCcw className="size-4" />Coba lagi</Button>
              <ButtonLink href="/" variant="ghost">Gunakan URL lain</ButtonLink>
            </div>
          }
        >
          {state.message}
        </EmptyState>
      </Shell>
    );
  }

  const { result } = state;
  const byType = (t: MediaType) => result.media.filter((m) => m.type === t);
  const counts: Record<MediaType, number> = {
    image: byType("image").length,
    video: byType("video").length,
    subtitle: byType("subtitle").length,
    text: result.text?.content ? 1 : 0,
    audio: byType("audio").length,
  };
  const searched = (t: MediaType) => types.length === 0 || types.includes(t);
  const tabs: MediaType[] = counts.audio > 0 ? [...TABS.slice(0, 2), "audio", ...TABS.slice(2)] : TABS;
  const firstTab = tabs.find((t) => counts[t] > 0) ?? "image";
  const current = tab ?? firstTab;
  const total = result.media.length + counts.text;

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const setMany = (ids: string[], on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
      return next;
    });
  const selectedItems = result.media.filter((m) => selected.has(m.id));
  const currentItems: MediaItem[] = byType(current);

  return (
    <Shell url={check.url} types={types}>
      {/* Ringkasan sumber */}
      <div className="grid gap-6 border-b border-line px-5 py-8 sm:px-10 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <div className="flex min-w-0 gap-4">
          {result.page.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={result.page.thumbnail} alt="" className="hidden h-[72px] w-[128px] shrink-0 rounded-lg border border-line object-cover sm:block" />
          ) : (
            <div className="hidden h-[72px] w-[128px] shrink-0 place-items-center rounded-lg border border-line bg-surface sm:grid">
              <Globe className="size-5 text-muted" aria-hidden />
            </div>
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-[13px] text-ink-2">
              <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-1.5 py-0.5 text-[12px] font-medium text-ink">
                <Globe className="size-3" aria-hidden />
                {result.source.name ?? result.source.type}
              </span>
              <span>{result.source.domain}</span>
              <span className="text-muted">· dianalisis {formatRelative(result.analyzed_at)}</span>
            </div>
            <h1 className="mt-2 font-display text-[26px] font-semibold leading-tight tracking-[-0.025em] text-ink sm:text-[30px]">
              {result.page.title ?? "Judul halaman tidak tersedia"}
            </h1>
            {result.page.description && <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-2">{result.page.description}</p>}
          </div>
        </div>
        <dl className="flex gap-6 text-sm md:justify-end">
          {tabs.map((t) => (
            <div key={t} className={cn(!searched(t) && "opacity-40")}>
              <dt className="text-[12px] text-muted">{MEDIA_LABEL[t]}</dt>
              <dd className="font-display text-[22px] font-semibold tabular-nums text-ink">{searched(t) ? counts[t] : "—"}</dd>
            </div>
          ))}
        </dl>
      </div>

      {result.warnings.length > 0 && (
        <div className="border-b border-line px-5 py-4 sm:px-10">
          {result.warnings.map((w) => (
            <p key={w} className="flex gap-2 rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[13px] leading-relaxed text-ink-2">
              <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
              {w}
            </p>
          ))}
        </div>
      )}

      {total === 0 ? (
        <EmptyState
          icon={<SearchX className="size-5" />}
          title="Tidak ada media yang dapat diakses"
          action={<ButtonLink href="/">Coba URL lain</ButtonLink>}
        >
          {result.source.type !== "generic"
            ? `Belum ada metode integrasi resmi untuk ${result.source.name ?? result.source.domain}, jadi halaman ini tidak dianalisis.`
            : "Halaman ini tidak memuat gambar, video langsung, subtitle, atau teks utama yang bisa dianalisis — atau kontennya dimuat lewat JavaScript yang belum didukung."}
        </EmptyState>
      ) : (
        <>
          {/* Tab */}
          <div className="sticky top-14 z-20 border-b border-line bg-bg/90 backdrop-blur-md">
            <div role="tablist" aria-label="Jenis media" className="flex gap-1 overflow-x-auto px-3 sm:px-8">
              {tabs.map((t) => (
                <button
                  key={t}
                  role="tab"
                  type="button"
                  id={`tab-${t}`}
                  aria-selected={current === t}
                  aria-controls={`panel-${t}`}
                  onClick={() => setTab(t)}
                  className={cn(
                    "relative flex h-11 shrink-0 items-center gap-2 px-3 text-sm transition-colors",
                    current === t ? "font-medium text-ink" : "text-ink-2 hover:text-ink",
                  )}
                >
                  <TypeIcon type={t} />
                  {MEDIA_LABEL[t]}
                  <span className={cn("rounded-full px-1.5 text-[11px] tabular-nums", current === t ? "bg-ink text-bg" : "bg-surface-2 text-muted")}>
                    {searched(t) ? counts[t] : "—"}
                  </span>
                  {current === t && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-ink" aria-hidden />}
                </button>
              ))}
            </div>
          </div>

          <div role="tabpanel" id={`panel-${current}`} aria-labelledby={`tab-${current}`} className="flex-1 px-5 pb-32 pt-6 sm:px-10">
            {!searched(current) ? (
              <EmptyState
                icon={<TypeIcon type={current} className="size-5" />}
                title={`${MEDIA_LABEL[current]} tidak dicari`}
                action={
                  <ButtonLink href={`/analyze?url=${encodeURIComponent(check.url)}`}>Analisis semua jenis</ButtonLink>
                }
              >
                Analisis ini hanya mencari {types.map((t) => MEDIA_LABEL[t].toLowerCase()).join(", ")}.
              </EmptyState>
            ) : current === "text" ? (
              <TextPanel result={result} />
            ) : currentItems.length === 0 ? (
              <EmptyState icon={<TypeIcon type={current} className="size-5" />} title={`Tidak ada ${MEDIA_LABEL[current].toLowerCase()} ditemukan`}>
                {current === "video"
                  ? "Tidak ada elemen video atau tautan file video langsung yang dapat diakses di halaman ini."
                  : current === "subtitle"
                    ? "Tidak ada elemen track atau file subtitle yang tersedia secara terbuka."
                    : "Tidak ada gambar yang terdeteksi dari img, srcset, atau metadata halaman."}
              </EmptyState>
            ) : current === "image" ? (
              <ImageGrid items={currentItems} selected={selected} onToggle={toggle} onSetMany={setMany} />
            ) : (
              <MediaTable items={currentItems} selected={selected} onToggle={toggle} onSetMany={setMany} />
            )}
          </div>
        </>
      )}

      <SelectionBar result={result} items={selectedItems} onClear={() => setSelected(new Set())} />
    </Shell>
  );
}

function Shell({ url, types, children }: { url: string; types: MediaType[]; children: React.ReactNode }) {
  return (
    <div className="frame flex flex-1 flex-col">
      <div className="flex flex-col gap-3 border-b border-line bg-surface px-5 py-4 sm:flex-row sm:items-start sm:px-10">
        <Link href="/" className="inline-flex h-9 shrink-0 items-center gap-1.5 text-[13px] text-ink-2 hover:text-ink">
          <ArrowLeft className="size-4" aria-hidden />
          Home
        </Link>
        <div className="min-w-0 flex-1">
          <UrlForm key={url + types.join()} defaultUrl={url} defaultTypes={types} compact />
        </div>
      </div>
      {children}
    </div>
  );
}

export function AnalyzeSkeleton({ url = "", types = [] }: { url?: string; types?: MediaType[] }) {
  return (
    <Shell url={url} types={types}>
      <div className="border-b border-line px-5 py-8 sm:px-10" aria-busy="true" aria-live="polite">
        <div className="flex gap-4">
          <div className="hidden h-[72px] w-[128px] shrink-0 animate-pulse rounded-lg bg-surface-2 sm:block" />
          <div className="flex-1 space-y-3 pt-1">
            <div className="h-3.5 w-48 animate-pulse rounded bg-surface-2" />
            <div className="h-6 w-2/3 max-w-md animate-pulse rounded bg-surface-2" />
            <div className="h-3.5 w-1/2 max-w-sm animate-pulse rounded bg-surface-2" />
          </div>
        </div>
        <div className="relative mt-8 h-1 overflow-hidden rounded-full bg-surface-2">
          <div className="scanbar absolute inset-y-0 w-1/4 rounded-full bg-accent/60" />
        </div>
        <p className="mt-3 text-[13px] text-ink-2">
          Menganalisis halaman{url ? <> <span className="font-mono text-[12px] text-muted">{url}</span></> : null}…
        </p>
      </div>
      <div className="grid grid-cols-2 gap-4 px-5 py-6 sm:grid-cols-3 sm:px-10 lg:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="aspect-[4/3] animate-pulse rounded-xl bg-surface-2" />
        ))}
      </div>
    </Shell>
  );
}
