"use client";

import { useEffect, useState } from "react";
import { ArrowDownToLine } from "lucide-react";
import type { JobStatus } from "@/types";
import { cn } from "@/lib/utils";
import { removeJobs, syncHistory, useJobs } from "@/services/jobs-store";
import { useNow } from "@/hooks/use-now";
import { Button, ButtonLink, EmptyState, PageHeader } from "@/components/ui/primitives";
import { JobRow } from "./job-row";

type Filter = "all" | "active" | "completed" | "failed";
const ACTIVE: JobStatus[] = ["pending", "processing", "downloading"];

const FILTERS: Array<{ id: Filter; label: string }> = [
  { id: "all", label: "Semua" },
  { id: "active", label: "Berjalan" },
  { id: "completed", label: "Selesai" },
  { id: "failed", label: "Gagal" },
];

export function DownloadsView() {
  const jobs = useJobs();
  const now = useNow();
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    syncHistory().catch(() => {});
  }, []);

  const count = (f: Filter) =>
    f === "all" ? jobs.length : f === "active" ? jobs.filter((j) => ACTIVE.includes(j.status)).length : jobs.filter((j) => j.status === f).length;

  const shown = jobs.filter((j) =>
    filter === "all" ? true : filter === "active" ? ACTIVE.includes(j.status) : j.status === filter,
  );
  const finished = jobs.filter((j) => j.status === "completed" || j.status === "failed").map((j) => j.id);

  return (
    <div className="frame flex flex-1 flex-col">
      <PageHeader
        title="Downloads"
        description={
          <>
            Status setiap pekerjaan unduhan. File hasil disimpan sementara di server dan dihapus otomatis sesuai
            kebijakan retensi (lihat Settings).
          </>
        }
        actions={
          finished.length > 0 && (
            <Button size="sm" variant="ghost" onClick={() => removeJobs(finished)}>
              Bersihkan yang selesai
            </Button>
          )
        }
      />

      <div className="flex gap-1 overflow-x-auto border-b border-line px-3 py-2 sm:px-8" role="toolbar" aria-label="Filter status">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            aria-pressed={filter === f.id}
            onClick={() => setFilter(f.id)}
            className={cn(
              "flex h-8 shrink-0 items-center gap-1.5 rounded-md px-3 text-[13px] transition-colors",
              filter === f.id ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:text-ink",
            )}
          >
            {f.label}
            <span className="tabular-nums text-muted">{count(f.id)}</span>
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <EmptyState
          icon={<ArrowDownToLine className="size-5" />}
          title={jobs.length === 0 ? "Belum ada pekerjaan unduhan" : "Tidak ada pekerjaan dengan status ini"}
          action={jobs.length === 0 ? <ButtonLink href="/" variant="primary">Analisis URL</ButtonLink> : undefined}
        >
          {jobs.length === 0
            ? "Analisis sebuah halaman, pilih media yang ingin disimpan, lalu tekan Unduh. Progresnya akan muncul di sini."
            : "Pilih filter lain untuk melihat pekerjaan lainnya."}
        </EmptyState>
      ) : (
        <ul className="flex-1">
          {shown.map((j) => (
            <JobRow key={j.id} job={j} now={now} />
          ))}
        </ul>
      )}
    </div>
  );
}
