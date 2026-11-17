"use client";

import { useState } from "react";
import { Download, RotateCcw, Trash2, TriangleAlert } from "lucide-react";
import { formatBytes, formatRelative, cn } from "@/lib/utils";
import { isExpired, jobFileHref, removeJob, retryJob, type StoredJob } from "@/services/jobs-store";
import { IS_DEMO } from "@/services/api";
import { Progress, StatusPill, TypeIcon } from "@/components/ui/primitives";

export function JobRow({ job, now }: { job: StoredJob; now: number }) {
  const [showError, setShowError] = useState(false);
  const [busy, setBusy] = useState(false);
  const expired = job.status === "completed" && isExpired(job, now);
  const href = jobFileHref(job);
  const active = job.status === "pending" || job.status === "processing" || job.status === "downloading";

  const sizeLabel =
    job.status === "downloading"
      ? `${formatBytes(job.size_downloaded)} / ${job.size_total ? formatBytes(job.size_total) : "ukuran tidak diketahui"}`
      : formatBytes(job.size_total ?? (job.size_downloaded || null));

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
          <p className="mt-0.5 truncate text-[12px] text-muted" title={job.source_url}>
            {job.source_domain} · {formatRelative(job.created_at, now)}
          </p>
        </div>

        <div className="col-span-2 col-start-2 row-start-2 sm:col-span-1 sm:col-start-auto sm:row-start-auto">
          {!active && (
            <div className="mb-1 sm:hidden">
              {expired ? <StatusPill status="pending" label="Kedaluwarsa" /> : <StatusPill status={job.status} />}
            </div>
          )}
          {active ? (
            <div>
              <Progress value={job.status === "downloading" ? job.progress : job.status === "pending" ? 0 : null} />
              <p className="mt-1.5 flex justify-between text-[12px] tabular-nums text-muted">
                <span>{job.status === "downloading" ? sizeLabel : job.status === "pending" ? "Dalam antrean" : "Memvalidasi sumber…"}</span>
                {job.status === "downloading" && job.progress != null && <span>{job.progress}%</span>}
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
          {job.status === "completed" && !expired && (
            href ? (
              <a
                href={href}
                download={job.filename}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line-strong px-2.5 text-[13px] font-medium text-ink hover:bg-surface-2"
              >
                <Download className="size-3.5" aria-hidden />
                Simpan
              </a>
            ) : (
              <span className="hidden px-2 text-[12px] text-muted sm:inline" title="Mode demo tidak menyimpan file video atau subtitle.">
                {IS_DEMO ? "Demo: tanpa file" : ""}
              </span>
            )
          )}
          {job.status === "failed" && (
            <>
              <button
                type="button"
                onClick={() => setShowError((v) => !v)}
                aria-expanded={showError}
                className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] text-bad hover:bg-bad-bg"
              >
                <TriangleAlert className="size-3.5" aria-hidden />
                Lihat error
              </button>
              <button
                type="button"
                onClick={() => retryJob(job.id).catch(() => {})}
                className="grid size-8 place-items-center rounded-md text-ink-2 hover:bg-surface-2 hover:text-ink"
                aria-label={`Coba lagi ${job.filename}`}
              >
                <RotateCcw className="size-3.5" />
              </button>
            </>
          )}
          <button
            type="button"
            disabled={busy || active}
            onClick={async () => {
              setBusy(true);
              try {
                await removeJob(job.id);
              } catch {
                setBusy(false);
              }
            }}
            className={cn(
              "grid size-8 place-items-center rounded-md text-muted transition-colors hover:bg-bad-bg hover:text-bad disabled:opacity-30",
            )}
            aria-label={`Hapus ${job.filename}`}
            title={active ? "Tunggu hingga pekerjaan selesai" : "Hapus pekerjaan"}
          >
            <Trash2 className="size-3.5" />
          </button>
        </div>
      </div>

      {showError && job.error_message && (
        <div className="mx-5 mb-4 rounded-lg border border-bad/25 bg-bad-bg px-3.5 py-2.5 text-[13px] leading-relaxed text-bad sm:ml-[76px] sm:mr-6">
          {job.error_message}
        </div>
      )}
    </li>
  );
}
