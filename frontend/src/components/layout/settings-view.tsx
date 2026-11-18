"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Ban, CircleCheck, Clock, Monitor, Moon, Sun } from "lucide-react";
import type { AdapterInfo, ServerConfig } from "@/types";
import { IS_DEMO, getAdapters, getConfig, getHealth } from "@/services/api";
import { removeJobs, useJobs } from "@/services/jobs-store";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/primitives";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { setTheme, useThemePref, type ThemePref } from "./theme";

const THEMES: Array<{ id: ThemePref; label: string; icon: typeof Sun }> = [
  { id: "light", label: "Terang", icon: Sun },
  { id: "dark", label: "Gelap", icon: Moon },
  { id: "system", label: "Ikuti sistem", icon: Monitor },
];

const ADAPTER_STATUS = {
  active: { label: "Aktif", icon: CircleCheck, cls: "text-ok" },
  evaluating: { label: "Evaluasi", icon: Clock, cls: "text-ink-2" },
  disabled: { label: "Nonaktif", icon: Ban, cls: "text-muted-foreground" },
} as const;

function Section({ title, description, children }: { title: string; description: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-6 border-b border-line px-5 py-10 sm:px-10 lg:grid-cols-[280px_1fr] lg:gap-12">
      <div>
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{description}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function Field({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col gap-1 border-b border-line px-4 py-3.5 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-sm text-ink">{label}</p>
        {hint && <p className="font-mono text-[11px] text-muted-foreground">{hint}</p>}
      </div>
      <p className="text-sm font-medium tabular-nums text-ink">{value}</p>
    </div>
  );
}

export function SettingsView() {
  const pref = useThemePref();
  const jobs = useJobs();
  const [config, setConfig] = useState<ServerConfig | null>(null);
  const [adapters, setAdapters] = useState<AdapterInfo[] | null>(null);
  const [health, setHealth] = useState<"checking" | "up" | "down">("checking");
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    getConfig().then(setConfig).catch(() => setLoadError(true));
    getAdapters().then(setAdapters).catch(() => setLoadError(true));
    getHealth().then((ok) => setHealth(ok ? "up" : "down"));
  }, []);

  const finishedIds = jobs.filter((j) => j.status === "completed" || j.status === "failed").map((j) => j.id);

  return (
    <div className="frame flex flex-1 flex-col">
      <PageHeader title="Settings" description="Tampilan aplikasi dan konfigurasi server yang sedang berlaku." />

      <Section title="Tema" description="Pilihan tersimpan di browser ini.">
        <RadioGroup
          value={pref}
          onValueChange={(v) => setTheme(v as ThemePref)}
          aria-label="Tema"
          className="grid max-w-md grid-cols-3 gap-2"
        >
          {THEMES.map((t) => (
            <Label
              key={t.id}
              htmlFor={`theme-${t.id}`}
              className={cn(
                "flex cursor-pointer flex-col items-center gap-2 rounded-xl border px-3 py-4 text-[13px] font-normal transition-colors",
                pref === t.id
                  ? "border-brand bg-brand-soft/60 font-medium text-ink shadow-[0_0_0_3px_var(--ring-soft)]"
                  : "border-line-strong text-ink-2 hover:bg-surface",
              )}
            >
              <RadioGroupItem id={`theme-${t.id}`} value={t.id} className="sr-only" />
              <t.icon className="size-4" aria-hidden />
              {t.label}
            </Label>
          ))}
        </RadioGroup>
      </Section>

      <Section
        title="Server"
        description={
          <>
            Nilai ini diatur lewat environment variable backend dan hanya bisa dilihat di sini.
            {IS_DEMO && " Saat ini menampilkan nilai default dari PRD karena backend belum terhubung."}
          </>
        }
      >
        <div className="mb-3 flex items-center gap-2 text-[13px]">
          <span
            className={cn(
              "size-2 rounded-full",
              health === "up" ? "bg-ok" : health === "down" ? "bg-bad" : "animate-pulse bg-idle",
            )}
            aria-hidden
          />
          <span className="text-ink-2">
            {IS_DEMO
              ? "Mode demo — backend belum dikonfigurasi"
              : health === "up"
                ? "Backend terhubung"
                : health === "down"
                  ? "Backend tidak dapat dihubungi"
                  : "Memeriksa koneksi…"}
          </span>
        </div>
        <div className="overflow-hidden rounded-xl border border-line">
          {config ? (
            <>
              <Field label="Batas ukuran file" value={`${config.max_download_size_mb} MB`} hint="MAX_DOWNLOAD_SIZE_MB" />
              <Field label="Batas waktu unduhan" value={`${config.download_timeout_seconds} detik`} hint="DOWNLOAD_TIMEOUT_SECONDS" />
              <Field label="Retensi file sementara" value={`${config.file_retention_hours} jam`} hint="FILE_RETENTION_HOURS" />
              <Field label="Lokasi penyimpanan" value={<code className="font-mono text-[13px]">{config.storage_path}</code>} hint="STORAGE_PATH" />
              {config.queue_backend && (
                <Field label="Backend Antrean" value={<span className="uppercase">{config.queue_backend}</span>} />
              )}
              {config.yt_dlp_version && (
                <Field label="Versi yt-dlp" value={`v${config.yt_dlp_version}`} hint="Ekstraktor Media Sosial" />
              )}
              {config.ffmpeg_version && (
                <Field label="Versi FFmpeg" value={config.ffmpeg_version} hint="Pengolah Video & Audio DASH" />
              )}
            </>
          ) : (
            <p className="px-4 py-6 text-sm text-ink-2">{loadError ? "Konfigurasi server tidak dapat dimuat." : "Memuat konfigurasi…"}</p>
          )}
        </div>
      </Section>

      <Section title="Adapter sumber" description="Adapter khusus hanya diaktifkan jika tersedia metode integrasi yang sah dan stabil.">
        <div className="overflow-hidden rounded-xl border border-line">
          {adapters?.map((a) => {
            const s = ADAPTER_STATUS[a.status];
            return (
              <div key={a.id} className="flex items-start justify-between gap-4 border-b border-line px-4 py-3.5 last:border-b-0">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">{a.name}</p>
                  <p className="mt-0.5 text-[13px] text-muted-foreground">{a.note}</p>
                </div>
                <span className={cn("inline-flex shrink-0 items-center gap-1.5 text-[13px] font-medium", s.cls)}>
                  <s.icon className="size-3.5" aria-hidden />
                  {s.label}
                </span>
              </div>
            );
          }) ?? <p className="px-4 py-6 text-sm text-ink-2">{loadError ? "Daftar adapter tidak dapat dimuat." : "Memuat adapter…"}</p>}
        </div>
      </Section>

      <Section
        title="Riwayat"
        description={
          IS_DEMO
            ? "Riwayat demo tersimpan di browser ini."
            : "Menghapus riwayat juga menghapus file sementaranya di server. File yang sudah Anda simpan tidak terpengaruh."
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <ConfirmDialog
            title={`Hapus ${finishedIds.length} riwayat selesai?`}
            description="Semua riwayat yang selesai atau gagal, beserta file sementaranya di server, akan dihapus permanen."
            confirmLabel={`Hapus ${finishedIds.length}`}
            onConfirm={() => removeJobs(finishedIds)}
            trigger={
              <Button variant="outline" disabled={finishedIds.length === 0}>
                Hapus semua riwayat selesai
              </Button>
            }
          />
          <span className="text-[13px] text-muted-foreground">{jobs.length} catatan tersimpan</span>
        </div>
      </Section>

      <Section title="Tentang" description="Universal Media Downloader — aplikasi web pribadi.">
        <div className="overflow-hidden rounded-xl border border-line">
          <Field label="Versi aplikasi" value={config?.version ?? "—"} />
          <Field label="Versi frontend" value="0.1.0" />
          <Field
            label="API"
            value={<code className="font-mono text-[13px]">{IS_DEMO ? "demo" : process.env.NEXT_PUBLIC_API_BASE_URL}</code>}
            hint="NEXT_PUBLIC_API_BASE_URL"
          />
          <Field
            label="Token API"
            value={process.env.NEXT_PUBLIC_API_TOKEN ? "Dikirim" : "Tidak dipakai"}
            hint="NEXT_PUBLIC_API_TOKEN"
          />
        </div>
      </Section>
    </div>
  );
}
