"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { ArrowDownToLine, CircleCheck, Gauge, Loader2, TriangleAlert, X } from "lucide-react";
import type { AnalyzeResult, MediaItem } from "@/types";
import { formatBytes } from "@/lib/utils";
import { IS_DEMO } from "@/services/api";
import { startDownloads } from "@/services/jobs-store";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

// Batas kecepatan per unduhan (KB/s), seperti pengatur kecepatan di IDM/1DM.
const SPEED_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 0, label: "Tanpa batas" },
  { value: 256, label: "256 KB/s" },
  { value: 512, label: "512 KB/s" },
  { value: 1024, label: "1 MB/s" },
  { value: 2048, label: "2 MB/s" },
  { value: 5120, label: "5 MB/s" },
];

const fieldCls =
  "h-8 rounded-lg border border-line-strong bg-bg px-2 text-[12px] text-ink outline-none focus:border-brand";

/** Nilai `datetime-local` (waktu lokal) → ISO dengan zona waktu, atau null bila kosong/tidak valid. */
function toIsoWithZone(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

const isVtt = (item: MediaItem) =>
  item.type === "subtitle" && (item.mime_type === "text/vtt" || item.filename.toLowerCase().endsWith(".vtt"));

export function SelectionBar({
  result,
  items,
  onClear,
}: {
  result: AnalyzeResult;
  items: MediaItem[];
  onClear: () => void;
}) {
  const switchId = useId();
  const [busy, setBusy] = useState(false);
  const [toSrt, setToSrt] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const [scheduleLocal, setScheduleLocal] = useState("");
  const [speedKbps, setSpeedKbps] = useState(0);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);

  const known = items.reduce((sum, i) => sum + (i.size ?? 0), 0);
  const unknown = items.filter((i) => i.size == null).length;
  const vttCount = items.filter(isVtt).length;

  async function download() {
    const scheduledAt = toIsoWithZone(scheduleLocal);
    if (scheduleLocal && (!scheduledAt || new Date(scheduledAt).getTime() <= Date.now())) {
      setToast({ ok: false, text: "Waktu jadwal harus di masa depan." });
      return;
    }
    setBusy(true);
    setToast(null);
    try {
      const n = await startDownloads(result, items, toSrt && vttCount > 0 ? "srt" : "original", {
        scheduledAt,
        maxSpeedKbps: speedKbps || null,
      });
      onClear();
      const msg = scheduledAt
        ? `${n} unduhan dijadwalkan mulai ${new Date(scheduledAt).toLocaleString("id-ID")}.`
        : n <= 3
          ? `${n} unduhan dimulai. File akan otomatis tersimpan ke komputer saat selesai.`
          : `${n} unduhan dimulai di server. Anda dapat mengunduh seluruhnya sekaligus sebagai file ZIP di tab Downloads / Riwayat.`;
      setToast({ ok: true, text: msg });
      setTimeout(() => setToast(null), 6000);
    } catch (e) {
      // Pilihan tetap dipertahankan agar pengguna bisa mencoba lagi.
      setToast({ ok: false, text: (e as Error).message || "Gagal membuat pekerjaan unduhan." });
    } finally {
      setBusy(false);
    }
  }

  if (items.length === 0 && !toast) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-5 z-30 flex justify-center px-4" aria-live="polite">
      {items.length > 0 ? (
        <div className="pointer-events-auto w-full max-w-[560px] rounded-2xl border border-line-strong bg-bg shadow-window">
          {vttCount > 0 && (
            <div className="flex items-center gap-2.5 border-b border-line px-4 py-2 text-[13px]">
              <Switch id={switchId} checked={toSrt} onCheckedChange={setToSrt} disabled={IS_DEMO} />
              <Label htmlFor={switchId} className="text-[13px] font-normal text-ink-2">
                Konversi {vttCount} subtitle VTT ke SRT
                {IS_DEMO && <span className="text-muted-foreground"> (tidak tersedia di mode demo)</span>}
              </Label>
            </div>
          )}
          {showOptions && (
            <div className="flex flex-wrap items-end gap-3 border-b border-line px-4 py-2.5 text-[12px]">
              <label className="flex flex-col gap-1 text-ink-2">
                Jadwal mulai
                <input
                  type="datetime-local"
                  value={scheduleLocal}
                  onChange={(e) => setScheduleLocal(e.target.value)}
                  disabled={IS_DEMO}
                  className={fieldCls}
                />
              </label>
              <label className="flex flex-col gap-1 text-ink-2">
                Batas kecepatan
                <select
                  value={speedKbps}
                  onChange={(e) => setSpeedKbps(Number(e.target.value))}
                  disabled={IS_DEMO}
                  className={fieldCls}
                >
                  {SPEED_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              {scheduleLocal && (
                <button type="button" onClick={() => setScheduleLocal("")} className="pb-1.5 text-muted-foreground hover:text-ink">
                  Mulai sekarang saja
                </button>
              )}
              {IS_DEMO && <span className="pb-1.5 text-muted-foreground">Tidak tersedia di mode demo.</span>}
            </div>
          )}
          <div className="flex items-center gap-3 py-2 pl-4 pr-2">
            <div className="min-w-0 flex-1 text-[13px] text-ink-2">
              <b className="font-semibold text-ink">{items.length}</b> dipilih
              <span className="text-muted-foreground">
                {" "}
                · {formatBytes(known)}
                {unknown > 0 && ` + ${unknown} ukuran tidak diketahui`}
              </span>
            </div>
            <Button
              variant={scheduleLocal || speedKbps ? "outline" : "ghost"}
              size="icon"
              onClick={() => setShowOptions((v) => !v)}
              aria-expanded={showOptions}
              aria-label="Jadwal & batas kecepatan"
              title="Jadwal & batas kecepatan"
            >
              <Gauge />
            </Button>
            <Button variant="ghost" size="icon" onClick={onClear} aria-label="Batalkan pilihan">
              <X />
            </Button>
            <Button onClick={download} disabled={busy} className="text-[13px]">
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowDownToLine aria-hidden />}
              {scheduleLocal ? "Jadwalkan" : "Unduh"} {items.length} item
            </Button>
          </div>
          {toast && !toast.ok && (
            <p role="alert" className="flex items-start gap-2 border-t border-line px-4 py-2 text-[13px] text-bad">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              {toast.text}
            </p>
          )}
        </div>
      ) : toast?.ok ? (
        <div className="pointer-events-auto flex items-center gap-3 rounded-xl border border-line-strong bg-bg px-4 py-2.5 text-[13px] shadow-window">
          <CircleCheck className="size-4 text-ok" aria-hidden />
          <span className="text-ink">{toast.text}</span>
          <Link href="/downloads" className="font-medium text-brand hover:underline">
            Buka Downloads
          </Link>
        </div>
      ) : null}
    </div>
  );
}
