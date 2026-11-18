"use client";

import { useEffect, useState } from "react";
import { Archive, ArrowDownToLine } from "lucide-react";
import type { JobStatus } from "@/types";
import { downloadBatchAsZip, isExpired, removeJobs, syncHistory, useJobs } from "@/services/jobs-store";
import { useNow } from "@/hooks/use-now";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ButtonLink, EmptyState, PageHeader } from "@/components/ui/primitives";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { JobRow } from "./job-row";
import { SyncErrorAlert } from "./sync-error";

type Filter = "all" | "active" | "completed" | "failed";
// Tab "Berjalan" juga menampilkan unduhan yang dijeda agar mudah dilanjutkan.
const ACTIVE: JobStatus[] = ["pending", "processing", "downloading", "paused"];

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
  const [zipping, setZipping] = useState(false);

  useEffect(() => {
    void syncHistory();
  }, []);

  const matches = (f: Filter, status: JobStatus) =>
    f === "all" ? true : f === "active" ? ACTIVE.includes(status) : status === f;
  const count = (f: Filter) => jobs.filter((j) => matches(f, j.status)).length;
  const shown = jobs.filter((j) => matches(filter, j.status));
  const finished = jobs
    .filter((j) => j.status === "completed" || j.status === "failed" || j.status === "cancelled")
    .map((j) => j.id);
  const completed = jobs.filter((j) => j.status === "completed" && !isExpired(j, now)).map((j) => j.id);

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
          <div className="flex items-center gap-2">
            {completed.length > 0 && (
              <Button
                size="sm"
                variant="outline"
                disabled={zipping}
                className="gap-1.5 text-[12px]"
                onClick={async () => {
                  setZipping(true);
                  try {
                    await downloadBatchAsZip(completed);
                  } catch (e) {
                    alert((e as Error).message || "Gagal mengunduh ZIP");
                  } finally {
                    setZipping(false);
                  }
                }}
              >
                <Archive className="size-3.5" aria-hidden />
                Unduh Semua ({completed.length}) .ZIP
              </Button>
            )}
            {finished.length > 0 && (
              <ConfirmDialog
                title={`Hapus ${finished.length} pekerjaan yang sudah selesai?`}
                description="Riwayat pekerjaan yang selesai atau gagal, beserta file sementaranya di server, akan dihapus permanen."
                confirmLabel={`Hapus ${finished.length}`}
                onConfirm={() => removeJobs(finished)}
                trigger={
                  <Button size="sm" variant="ghost">
                    Bersihkan yang selesai
                  </Button>
                }
              />
            )}
          </div>
        }
      />

      <SyncErrorAlert className="mx-5 mt-4 w-auto sm:mx-10" />

      <Tabs value={filter} onValueChange={(v) => setFilter(v as Filter)} className="flex flex-1 flex-col gap-0">
        <div className="border-b border-line px-3 py-2 sm:px-8">
          <TabsList variant="line" aria-label="Filter status" className="overflow-x-auto">
            {FILTERS.map((f) => (
              <TabsTrigger key={f.id} value={f.id} className="gap-1.5 px-3 text-[13px]">
                {f.label}
                <span className="tabular-nums text-muted-foreground">{count(f.id)}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        {FILTERS.map((f) => (
          <TabsContent key={f.id} value={f.id} className="flex-1">
            {shown.length === 0 ? (
              <EmptyState
                icon={<ArrowDownToLine className="size-5" />}
                title={jobs.length === 0 ? "Belum ada pekerjaan unduhan" : "Tidak ada pekerjaan dengan status ini"}
                action={
                  jobs.length === 0 ? (
                    <ButtonLink href="/" variant="default">
                      Analisis URL
                    </ButtonLink>
                  ) : undefined
                }
              >
                {jobs.length === 0
                  ? "Analisis sebuah halaman, pilih media yang ingin disimpan, lalu tekan Unduh. Progresnya akan muncul di sini."
                  : "Pilih filter lain untuk melihat pekerjaan lainnya."}
              </EmptyState>
            ) : (
              <ul>
                {shown.map((j) => (
                  <JobRow key={j.id} job={j} now={now} />
                ))}
              </ul>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
