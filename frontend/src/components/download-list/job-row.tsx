"use client";

import { useState } from "react";
import { CalendarClock, CircleStop, Download, Loader2, Pause, Play, RotateCcw, Trash2, TriangleAlert } from "lucide-react";
import { formatBytes, formatDate, formatEta, formatRelative, formatSpeed } from "@/lib/utils";
import {
  canFetchFile,
  cancelJob,
  isExpired,
  jobFileHref,
  pauseJob,
  removeJob,
  resumeJob,
  retryJob,
  saveJobFile,
  type StoredJob,
} from "@/services/jobs-store";
import { IS_DEMO } from "@/services/api";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Progress, StatusPill, TypeIcon } from "@/components/ui/primitives";

export function JobRow({ job, now }: { job: StoredJob; now: number }) {
  const [showError, setShowError] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const expired = job.status === "completed" && isExpired(job, now);
  const href = jobFileHref(job);
  // Job antre (`pending`) atau dijeda boleh dihapus; yang sedang diproses harus dijeda/dibatalkan dulu.
  const running = job.status === "processing" || job.status === "downloading";
  const active = running || job.status === "pending";
  const paused = job.status === "paused";
  const scheduled = job.status === "scheduled";
  const controllable = active || paused || scheduled;
  const speed = job.status === "downloading" ? formatSpeed(job.speed_bps) : null;
  const eta =
    job.status === "downloading" && job.size_total ? formatEta(job.size_total - job.size_downloaded, job.speed_bps) : null;

  const sizeLabel =
    job.status === "downloading"
      ? `${formatBytes(job.size_downloaded)} / ${job.size_total ? formatBytes(job.size_total) : "ukuran tidak diketahui"}`
      : formatBytes(job.size_total ?? (job.size_downloaded || null));

  async function run(action: () => Promise<unknown>) {
    setActionError(null);
    setBusy(true);
    try {
      await action();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="group border-b border-line last:border-b-0">
      <div className="grid grid-cols-[auto_1fr_auto] items-center gap-x-4 gap-y-2 px-5 py-4 sm:grid-cols-[auto_minmax(0,1fr)_200px_120px_auto] sm:px-6">
        <span
          className="grid size-9 place-items-center rounded-lg"
          style={{ background: `var(--tag-${job.media_type}-bg)`, color: `var(--tag-${job.media_type}-fg)` }}
        >
          <TypeIcon type={job.media_type} className="size-4" />
        </span>

        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-ink" title={job.filename}>
            {job.filename}
          </p>
          <p className="mt-0.5 truncate text-[12px] text-muted-foreground" title={job.source_url}>
            {job.source_domain} · {formatRelative(job.created_at, now)}
          </p>
        </div>

        <div className="col-span-2 col-start-2 row-start-2 sm:col-span-1 sm:col-start-auto sm:row-start-auto">
          {!active && !paused && !scheduled && (
            <div className="mb-1 sm:hidden">
              {expired ? <StatusPill status="pending" label="Kedaluwarsa" /> : <StatusPill status={job.status} />}
            </div>
          )}
          {active ? (
            <div>
              <Progress value={job.status === "downloading" ? job.progress : job.status === "pending" ? 0 : null} />
              <p className="mt-1.5 flex justify-between text-[12px] tabular-nums text-muted-foreground">
                <span>
                  {job.status === "downloading"
                    ? sizeLabel
                    : job.status === "pending"
                      ? "Dalam antrean"
                      : job.size_downloaded > 0
                        ? "Menggabungkan media…"
                        : "Menyiapkan unduhan…"}
                </span>
                {job.status === "downloading" && job.progress != null && <span>{job.progress}%</span>}
              </p>
              {(speed || eta || job.max_speed_kbps) && (
                <p className="mt-0.5 flex justify-between text-[11px] tabular-nums text-muted-foreground">
                  <span>
                    {speed ?? ""}
                    {job.max_speed_kbps ? ` (maks ${formatBytes(job.max_speed_kbps * 1024)}/s)` : ""}
                  </span>
                  {eta && <span>{eta}</span>}
                </p>
              )}
            </div>
          ) : scheduled ? (
            <p className="flex items-center gap-1.5 text-[12px] text-ink-2">
              <CalendarClock className="size-3.5 shrink-0 text-brand" aria-hidden />
              Mulai {job.scheduled_at ? formatDate(job.scheduled_at) : "sesuai jadwal"}
            </p>
          ) : paused ? (
            <div>
              <Progress value={job.progress} />
              <p className="mt-1.5 flex justify-between text-[12px] tabular-nums text-muted-foreground">
                <span>
                  Dijeda · {formatBytes(job.size_downloaded)}
                  {job.size_total ? ` / ${formatBytes(job.size_total)}` : ""}
                </span>
                {job.progress != null && <span>{job.progress}%</span>}
              </p>
            </div>
          ) : (
            <p className="text-[13px] tabular-nums text-ink-2">{sizeLabel}</p>
          )}
        </div>

        <div className="hidden sm:block">
          {expired ? <StatusPill status="pending" label="Kedaluwarsa" /> : <StatusPill status={job.status} />}
        </div>

        <div className="col-start-3 row-start-1 flex items-center justify-end gap-1 sm:col-start-auto sm:row-start-auto">
          {job.status === "completed" && !expired && href && (
            <Button asChild variant="outline" size="sm">
              <a href={href} download={job.filename}>
                <Download aria-hidden />
                Simpan
              </a>
            </Button>
          )}
          {job.status === "completed" && !expired && !href && canFetchFile(job) && (
            <Button
              variant="outline"
              size="sm"
              disabled={saving}
              onClick={async () => {
                setSaving(true);
                await run(() => saveJobFile(job));
                setSaving(false);
              }}
            >
              {saving ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
              Simpan
            </Button>
          )}
          {job.status === "completed" && !expired && !href && !canFetchFile(job) && IS_DEMO && (
            <span
              className="hidden px-2 text-[12px] text-muted-foreground sm:inline"
              title="Mode demo tidak menyimpan file video atau subtitle."
            >
              Demo: tanpa file
            </span>
          )}
          {active && (
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={busy}
              onClick={() => run(() => pauseJob(job.id))}
              aria-label={`Jeda ${job.filename}`}
              title="Jeda"
            >
              <Pause className="size-3.5" />
            </Button>
          )}
          {(paused || scheduled) && (
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={busy}
              onClick={() => run(() => resumeJob(job.id))}
              aria-label={`${scheduled ? "Mulai sekarang" : "Lanjutkan"} ${job.filename}`}
              title={scheduled ? "Mulai sekarang" : "Lanjutkan"}
            >
              <Play className="size-3.5" />
            </Button>
          )}
          {controllable && (
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={busy}
              onClick={() => run(() => cancelJob(job.id))}
              className="text-muted-foreground hover:bg-bad-bg hover:text-bad"
              aria-label={`Batalkan ${job.filename}`}
              title="Batalkan"
            >
              <CircleStop className="size-3.5" />
            </Button>
          )}
          {job.status === "cancelled" && (
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={busy}
              onClick={() => run(() => retryJob(job.id))}
              aria-label={`Mulai ulang ${job.filename}`}
              title="Mulai ulang"
            >
              <RotateCcw className="size-3.5" />
            </Button>
          )}
          {job.status === "failed" && (
            <>
              <Button
                variant="ghost-destructive"
                size="sm"
                onClick={() => setShowError((v) => !v)}
                aria-expanded={showError}
              >
                <TriangleAlert aria-hidden />
                Lihat error
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => run(() => retryJob(job.id))}
                aria-label={`Coba lagi ${job.filename}`}
                title="Coba lagi"
              >
                <RotateCcw className="size-3.5" />
              </Button>
            </>
          )}
          <ConfirmDialog
            title="Hapus pekerjaan ini?"
            description={
              <>
                Riwayat <b className="font-medium text-ink">{job.filename}</b> dan file sementaranya di server akan
                dihapus permanen.
              </>
            }
            confirmLabel="Hapus"
            onConfirm={() => removeJob(job.id)}
            trigger={
              <Button
                variant="ghost"
                size="icon-sm"
                disabled={running}
                className="text-muted-foreground hover:bg-bad-bg hover:text-bad"
                aria-label={`Hapus ${job.filename}`}
                title={running ? "Jeda atau batalkan dulu sebelum menghapus" : "Hapus pekerjaan"}
              >
                <Trash2 className="size-3.5" />
              </Button>
            }
          />
        </div>
      </div>

      {((showError && job.error_message) || actionError) && (
        <div
          role="alert"
          className="mx-5 mb-4 rounded-lg border border-bad/25 bg-bad-bg px-3.5 py-2.5 text-[13px] leading-relaxed text-bad sm:ml-[76px] sm:mr-6"
        >
          {actionError ?? job.error_message}
        </div>
      )}
    </li>
  );
}
