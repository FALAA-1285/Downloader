"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowDownToLine, CircleCheck, Loader2, TriangleAlert, X } from "lucide-react";
import type { AnalyzeResult, MediaItem } from "@/types";
import { formatBytes } from "@/lib/utils";
import { startDownloads } from "@/services/jobs-store";

export function SelectionBar({ result, items, onClear }: { result: AnalyzeResult; items: MediaItem[]; onClear: () => void }) {
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);

  const known = items.reduce((sum, i) => sum + (i.size ?? 0), 0);
  const unknown = items.filter((i) => i.size == null).length;

  async function download() {
    setBusy(true);
    try {
      const n = await startDownloads(result, items);
      onClear();
      setToast({ ok: true, text: `${n} pekerjaan unduhan dibuat` });
    } catch (e) {
      setToast({ ok: false, text: (e as Error).message || "Gagal membuat pekerjaan unduhan." });
    } finally {
      setBusy(false);
      setTimeout(() => setToast(null), 5000);
    }
  }

  if (items.length === 0 && !toast) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-5 z-30 flex justify-center px-4" aria-live="polite">
      {items.length > 0 ? (
        <div className="pointer-events-auto flex w-full max-w-[560px] items-center gap-3 rounded-2xl border border-line-strong bg-bg py-2 pl-4 pr-2 shadow-window">
          <div className="min-w-0 flex-1 text-[13px] text-ink-2">
            <b className="font-semibold text-ink">{items.length}</b> dipilih
            <span className="text-muted">
              {" "}· {formatBytes(known)}
              {unknown > 0 && ` + ${unknown} ukuran tidak diketahui`}
            </span>
          </div>
          <button
            type="button"
            onClick={onClear}
            className="grid size-9 place-items-center rounded-lg text-ink-2 hover:bg-surface-2 hover:text-ink"
            aria-label="Batalkan pilihan"
          >
            <X className="size-4" />
          </button>
          <button
            type="button"
            onClick={download}
            disabled={busy}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-ink px-3.5 text-[13px] font-medium text-bg hover:bg-ink/85 disabled:opacity-60"
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowDownToLine className="size-4" />}
            Unduh {items.length} item
          </button>
        </div>
      ) : toast ? (
        <div className="pointer-events-auto flex items-center gap-3 rounded-xl border border-line-strong bg-bg px-4 py-2.5 text-[13px] shadow-window">
          {toast.ok ? <CircleCheck className="size-4 text-ok" /> : <TriangleAlert className="size-4 text-bad" />}
          <span className="text-ink">{toast.text}</span>
          {toast.ok && (
            <Link href="/downloads" className="font-medium text-accent hover:underline">
              Buka Downloads
            </Link>
          )}
        </div>
      ) : null}
    </div>
  );
}
