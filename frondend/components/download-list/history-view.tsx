"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { History, Search, Trash2 } from "lucide-react";
import type { JobStatus, MediaType } from "@/types";
import { MEDIA_LABEL, STATUS_LABEL, cn, formatBytes, formatDate } from "@/lib/utils";
import { isExpired, removeJob, removeJobs, syncHistory, useJobs } from "@/services/jobs-store";
import { useNow } from "@/hooks/use-now";
import { Button, ButtonLink, Checkbox, EmptyState, PageHeader, StatusPill, TypeTag } from "@/components/ui/primitives";

const selectCls =
  "h-9 rounded-lg border border-line-strong bg-bg pl-3 pr-8 text-[13px] text-ink outline-none focus-visible:border-accent";

export function HistoryView() {
  const jobs = useJobs();
  const now = useNow();
  const [q, setQ] = useState("");
  const [type, setType] = useState<MediaType | "all">("all");
  const [status, setStatus] = useState<JobStatus | "all">("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const headRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    syncHistory().catch(() => {});
  }, []);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return jobs.filter(
      (j) =>
        (type === "all" || j.media_type === type) &&
        (status === "all" || j.status === status) &&
        (!needle || j.filename.toLowerCase().includes(needle) || j.source_url.toLowerCase().includes(needle)),
    );
  }, [jobs, q, type, status]);

  const deletable = rows.filter((r) => !["pending", "processing", "downloading"].includes(r.status)).map((r) => r.id);
  const picked = deletable.filter((id) => selected.has(id));
  const all = deletable.length > 0 && picked.length === deletable.length;

  useEffect(() => {
    if (headRef.current) headRef.current.indeterminate = picked.length > 0 && !all;
  }, [picked.length, all]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const filtering = q || type !== "all" || status !== "all";

  return (
    <div className="frame flex flex-1 flex-col">
      <PageHeader
        title="History"
        description="Catatan pekerjaan sebelumnya. Menghapus riwayat juga menghapus file sementaranya jika masih tersimpan."
      />

      <div className="flex flex-col gap-2 border-b border-line px-5 py-3 sm:flex-row sm:items-center sm:px-10">
        <label className="relative flex-1">
          <span className="sr-only">Cari URL atau nama file</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Cari URL atau nama file"
            className="h-9 w-full rounded-lg border border-line-strong bg-bg pl-9 pr-3 text-[13px] text-ink outline-none placeholder:text-muted focus-visible:border-accent"
          />
        </label>
        <div className="flex gap-2">
          <label className="flex-1 sm:flex-none">
            <span className="sr-only">Jenis media</span>
            <select value={type} onChange={(e) => setType(e.target.value as MediaType | "all")} className={cn(selectCls, "w-full")}>
              <option value="all">Semua jenis</option>
              {(["image", "video", "subtitle", "text"] as MediaType[]).map((t) => (
                <option key={t} value={t}>{MEDIA_LABEL[t]}</option>
              ))}
            </select>
          </label>
          <label className="flex-1 sm:flex-none">
            <span className="sr-only">Status</span>
            <select value={status} onChange={(e) => setStatus(e.target.value as JobStatus | "all")} className={cn(selectCls, "w-full")}>
              <option value="all">Semua status</option>
              {(Object.keys(STATUS_LABEL) as JobStatus[]).map((s) => (
                <option key={s} value={s}>{STATUS_LABEL[s]}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {picked.length > 0 && (
        <div className="flex items-center justify-between border-b border-line bg-accent-soft/50 px-5 py-2 text-[13px] sm:px-10">
          <span className="text-ink">{picked.length} riwayat dipilih</span>
          <Button
            size="sm"
            variant="danger"
            onClick={async () => {
              await removeJobs(picked);
              setSelected(new Set());
            }}
          >
            <Trash2 className="size-3.5" />
            Hapus {picked.length}
          </Button>
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState
          icon={<History className="size-5" />}
          title={filtering ? "Tidak ada yang cocok" : "Riwayat masih kosong"}
          action={!filtering ? <ButtonLink href="/" variant="primary">Analisis URL</ButtonLink> : undefined}
        >
          {filtering ? "Ubah kata kunci atau filter untuk melihat riwayat lain." : "Setiap unduhan dan ekspor teks akan tercatat di sini."}
        </EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-[12px] text-muted">
                <th className="w-12 py-2.5 pl-5 font-normal sm:pl-10">
                  <Checkbox
                    ref={headRef}
                    checked={all}
                    disabled={deletable.length === 0}
                    onChange={() => setSelected(all ? new Set() : new Set(deletable))}
                    aria-label="Pilih semua riwayat"
                  />
                </th>
                <th className="py-2.5 pl-3 font-normal">File</th>
                <th className="py-2.5 font-normal">Jenis</th>
                <th className="py-2.5 font-normal">Status</th>
                <th className="py-2.5 font-normal">Ukuran</th>
                <th className="py-2.5 font-normal">Dibuat</th>
                <th className="py-2.5 font-normal">Selesai</th>
                <th className="w-12 py-2.5 pr-5 sm:pr-10"><span className="sr-only">Aksi</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((j) => {
                const locked = !deletable.includes(j.id);
                const expired = j.status === "completed" && isExpired(j, now);
                return (
                  <tr key={j.id} className={cn("border-b border-line", selected.has(j.id) ? "bg-accent-soft/50" : "hover:bg-surface")}>
                    <td className="py-3 pl-5 sm:pl-10">
                      <Checkbox checked={selected.has(j.id)} disabled={locked} onChange={() => toggle(j.id)} aria-label={`Pilih ${j.filename}`} />
                    </td>
                    <td className="max-w-[320px] py-3 pl-3 pr-4">
                      <p className="truncate font-medium text-ink">{j.filename}</p>
                      <Link
                        href={`/analyze?url=${encodeURIComponent(j.source_url)}`}
                        className="block truncate font-mono text-[11px] text-muted hover:text-accent"
                        title={`Analisis ulang ${j.source_url}`}
                      >
                        {j.source_url}
                      </Link>
                    </td>
                    <td className="py-3"><TypeTag type={j.media_type} /></td>
                    <td className="py-3">{expired ? <StatusPill status="pending" label="Kedaluwarsa" /> : <StatusPill status={j.status} />}</td>
                    <td className="py-3 tabular-nums text-ink-2">{formatBytes(j.size_total)}</td>
                    <td className="whitespace-nowrap py-3 tabular-nums text-ink-2">{formatDate(j.created_at)}</td>
                    <td className="whitespace-nowrap py-3 tabular-nums text-ink-2">{formatDate(j.completed_at)}</td>
                    <td className="py-3 pr-5 sm:pr-10">
                      <button
                        type="button"
                        disabled={locked}
                        onClick={() => removeJob(j.id).catch(() => {})}
                        className="grid size-8 place-items-center rounded-md text-muted hover:bg-bad-bg hover:text-bad disabled:opacity-30"
                        aria-label={`Hapus riwayat ${j.filename}`}
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
