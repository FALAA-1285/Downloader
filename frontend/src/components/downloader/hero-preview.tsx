import { Check, Globe, Lock } from "lucide-react";
import type { MediaType } from "@/types";
import { TypeTag } from "@/components/ui/primitives";

// Ilustrasi statis alur analisis. Bukan data nyata — hanya memperlihatkan bentuk hasil.
const ROWS: Array<{ type: MediaType; name: string; fmt: string; size: string; ok: boolean; note?: string; sel?: boolean }> = [
  { type: "image", name: "cover-01.jpg", fmt: "JPG · 1600×900", size: "412 KB", ok: true, sel: true },
  { type: "image", name: "gallery-02.webp", fmt: "WebP · 1200×800", size: "188 KB", ok: true, sel: true },
  { type: "video", name: "liputan-utama.mp4", fmt: "MP4 · 1080p · 2:34", size: "38,2 MB", ok: true, sel: true },
  { type: "subtitle", name: "liputan-utama.id.vtt", fmt: "VTT · Indonesia", size: "14 KB", ok: true },
  { type: "text", name: "Teks artikel", fmt: "1.284 kata", size: "8 KB", ok: true },
  { type: "video", name: "stream.m3u8", fmt: "HLS", size: "—", ok: false, note: "DRM" },
];

export function HeroPreview() {
  return (
    <div className="relative mx-auto w-full max-w-[1000px]">
      <div className="overflow-hidden rounded-2xl border border-line-strong bg-bg shadow-window">
        {/* Bilah alamat */}
        <div className="flex items-center gap-3 border-b border-line bg-surface px-4 py-2.5">
          <div className="flex gap-1.5" aria-hidden>
            <span className="size-2.5 rounded-full bg-line-strong" />
            <span className="size-2.5 rounded-full bg-line-strong" />
            <span className="size-2.5 rounded-full bg-line-strong" />
          </div>
          <div className="relative flex min-w-0 flex-1 items-center gap-2 overflow-hidden rounded-md border border-line bg-bg px-2.5 py-1">
            <Lock className="size-3 shrink-0 text-muted-foreground" aria-hidden />
            <span className="truncate font-mono text-[12px] text-ink-2">https://majalah.example/2026/liputan-pameran-arsip-kota</span>
            <span className="scanbar pointer-events-none absolute inset-y-0 left-0 w-1/4 bg-gradient-to-r from-transparent via-brand/15 to-transparent" aria-hidden />
          </div>
        </div>

        {/* Ringkasan sumber */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-md border border-line bg-surface">
              <Globe className="size-3.5 text-ink-2" aria-hidden />
            </span>
            <div className="leading-tight">
              <div className="text-[13px] font-medium text-ink">Liputan pameran arsip kota</div>
              <div className="text-[12px] text-muted-foreground">majalah.example · Website umum</div>
            </div>
          </div>
          <div className="ml-auto hidden items-center gap-4 text-[12px] text-ink-2 sm:flex">
            <span><b className="font-semibold text-ink">9</b> gambar</span>
            <span><b className="font-semibold text-ink">2</b> video</span>
            <span><b className="font-semibold text-ink">3</b> subtitle</span>
            <span><b className="font-semibold text-ink">1</b> teks</span>
          </div>
        </div>

        {/* Tabel hasil */}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-[13px]">
            <thead>
              <tr className="border-b border-line text-[12px] text-muted-foreground">
                <th className="w-10 py-2 pl-4 font-normal sm:pl-5"><span className="sr-only">Pilih</span></th>
                <th className="py-2 font-normal">Nama</th>
                <th className="py-2 font-normal">Jenis</th>
                <th className="py-2 font-normal">Format</th>
                <th className="py-2 font-normal">Ukuran</th>
                <th className="py-2 pr-5 text-right font-normal">Status</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r, i) => (
                <tr
                  key={r.name}
                  className="row-in border-b border-line last:border-b-0"
                  style={{ animationDelay: `${500 + i * 140}ms` }}
                >
                  <td className="py-2.5 pl-4 sm:pl-5">
                    <span
                      className={
                        r.sel
                          ? "grid size-4 place-items-center rounded-[5px] bg-brand text-white"
                          : "block size-4 rounded-[5px] border border-line-strong"
                      }
                      aria-hidden
                    >
                      {r.sel && <Check className="size-3" strokeWidth={3} />}
                    </span>
                  </td>
                  <td className={r.ok ? "py-2.5 font-medium text-ink" : "py-2.5 text-muted-foreground line-through decoration-line-strong"}>{r.name}</td>
                  <td className="py-2.5"><TypeTag type={r.type} /></td>
                  <td className="py-2.5 text-ink-2">{r.fmt}</td>
                  <td className="py-2.5 tabular-nums text-ink-2">{r.size}</td>
                  <td className="py-2.5 pr-5 text-right">
                    {r.ok ? (
                      <span className="text-[12px] text-ok">Dapat diunduh</span>
                    ) : (
                      <span className="text-[12px] text-muted-foreground">Dilewati · {r.note}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Bilah aksi */}
        <div className="row-in flex items-center justify-between gap-3 border-t border-line bg-surface px-4 py-2.5 sm:px-5" style={{ animationDelay: "1500ms" }}>
          <span className="text-[13px] text-ink-2"><b className="font-semibold text-ink">3</b> dipilih · 38,8 MB</span>
          <span className="inline-flex h-8 items-center rounded-lg bg-ink px-3 text-[13px] font-medium text-bg">Unduh 3 item</span>
        </div>
      </div>
    </div>
  );
}
