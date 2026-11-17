"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Archive, History, Search, Trash2 } from "lucide-react";
import type { JobStatus, MediaType } from "@/types";
import { MEDIA_LABEL, STATUS_LABEL, cn, formatBytes, formatDate } from "@/lib/utils";
import { downloadBatchAsZip, isExpired, removeJob, removeJobs, syncHistory, useJobs } from "@/services/jobs-store";
import { useNow } from "@/hooks/use-now";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { ButtonLink, EmptyState, PageHeader, StatusPill, TypeTag } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SyncErrorAlert } from "./sync-error";

const RUNNING: JobStatus[] = ["processing", "downloading"];

export function HistoryView() {
  const jobs = useJobs();
  const now = useNow();
  const [q, setQ] = useState("");
  const [type, setType] = useState<MediaType | "all">("all");
  const [status, setStatus] = useState<JobStatus | "all">("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [zipping, setZipping] = useState(false);

  useEffect(() => {
    void syncHistory();
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

  // Job yang sedang diproses tidak bisa dihapus; job antre (pending) boleh.
  const deletable = rows.filter((r) => !RUNNING.includes(r.status)).map((r) => r.id);
  const picked = deletable.filter((id) => selected.has(id));
  const all = deletable.length > 0 && picked.length === deletable.length;
  const headState = all ? true : picked.length > 0 ? "indeterminate" : false;

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
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Cari URL atau nama file"
            aria-label="Cari URL atau nama file"
            className="pl-9 text-[13px]"
          />
        </div>
        <div className="flex gap-2">
          <Select value={type} onValueChange={(v) => setType(v as MediaType | "all")}>
            <SelectTrigger aria-label="Jenis media" className="flex-1 text-[13px] sm:w-40 sm:flex-none">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua jenis</SelectItem>
              {(["image", "video", "audio", "subtitle", "text"] as MediaType[]).map((t) => (
                <SelectItem key={t} value={t}>
                  {MEDIA_LABEL[t]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={(v) => setStatus(v as JobStatus | "all")}>
            <SelectTrigger aria-label="Status" className="flex-1 text-[13px] sm:w-40 sm:flex-none">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Semua status</SelectItem>
              {(Object.keys(STATUS_LABEL) as JobStatus[]).map((s) => (
                <SelectItem key={s} value={s}>
                  {STATUS_LABEL[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <SyncErrorAlert className="mx-5 mt-4 w-auto sm:mx-10" />

      {picked.length > 0 && (
        <div className="flex items-center justify-between border-b border-line bg-brand-soft/50 px-5 py-2 text-[13px] sm:px-10">
          <span className="text-ink">{picked.length} riwayat dipilih</span>
          <div className="flex items-center gap-2">
            {rows.filter((r) => selected.has(r.id) && r.status === "completed" && !isExpired(r, now)).length > 0 && (
              <Button
                size="sm"
                variant="outline"
                disabled={zipping}
                className="gap-1.5 text-[12px]"
                onClick={async () => {
                  setZipping(true);
                  try {
                    const completedIds = rows
                      .filter((r) => selected.has(r.id) && r.status === "completed" && !isExpired(r, now))
                      .map((r) => r.id);
                    await downloadBatchAsZip(completedIds);
                  } catch (e) {
                    alert((e as Error).message || "Gagal mengunduh ZIP");
                  } finally {
                    setZipping(false);
                  }
                }}
              >
                <Archive className="size-3.5" aria-hidden />
                Unduh ZIP ({rows.filter((r) => selected.has(r.id) && r.status === "completed" && !isExpired(r, now)).length})
              </Button>
            )}
            <ConfirmDialog
              title={`Hapus ${picked.length} riwayat?`}
              description="Riwayat yang dipilih beserta file sementaranya di server akan dihapus permanen."
              confirmLabel={`Hapus ${picked.length}`}
              onConfirm={async () => {
                await removeJobs(picked);
                setSelected(new Set());
              }}
              trigger={
                <Button size="sm" variant="ghost-destructive">
                  <Trash2 aria-hidden />
                  Hapus {picked.length}
                </Button>
              }
            />
          </div>
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState
          icon={<History className="size-5" />}
          title={filtering ? "Tidak ada yang cocok" : "Riwayat masih kosong"}
          action={
            !filtering ? (
              <ButtonLink href="/" variant="default">
                Analisis URL
              </ButtonLink>
            ) : undefined
          }
        >
          {filtering
            ? "Ubah kata kunci atau filter untuk melihat riwayat lain."
            : "Setiap unduhan dan ekspor teks akan tercatat di sini."}
        </EmptyState>
      ) : (
        <Table className="min-w-[820px]">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-12 pl-5 sm:pl-10">
                <Checkbox
                  checked={headState}
                  disabled={deletable.length === 0}
                  onCheckedChange={() => setSelected(all ? new Set() : new Set(deletable))}
                  aria-label="Pilih semua riwayat"
                />
              </TableHead>
              <TableHead className="text-[12px] font-normal text-muted-foreground">File</TableHead>
              <TableHead className="text-[12px] font-normal text-muted-foreground">Jenis</TableHead>
              <TableHead className="text-[12px] font-normal text-muted-foreground">Status</TableHead>
              <TableHead className="text-[12px] font-normal text-muted-foreground">Ukuran</TableHead>
              <TableHead className="text-[12px] font-normal text-muted-foreground">Dibuat</TableHead>
              <TableHead className="text-[12px] font-normal text-muted-foreground">Selesai</TableHead>
              <TableHead className="w-12 pr-5 sm:pr-10">
                <span className="sr-only">Aksi</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((j) => {
              const locked = RUNNING.includes(j.status);
              const expired = j.status === "completed" && isExpired(j, now);
              return (
                <TableRow key={j.id} data-state={selected.has(j.id) ? "selected" : undefined} className={cn(selected.has(j.id) && "bg-brand-soft/50")}>
                  <TableCell className="pl-5 sm:pl-10">
                    <Checkbox
                      checked={selected.has(j.id)}
                      disabled={locked}
                      onCheckedChange={() => toggle(j.id)}
                      aria-label={`Pilih ${j.filename}`}
                    />
                  </TableCell>
                  <TableCell className="max-w-[320px] pr-4">
                    <p className="truncate font-medium text-ink">{j.filename}</p>
                    <Link
                      href={`/analyze?url=${encodeURIComponent(j.source_url)}`}
                      className="block truncate font-mono text-[11px] text-muted-foreground hover:text-brand"
                      title={`Analisis ulang ${j.source_url}`}
                    >
                      {j.source_url}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <TypeTag type={j.media_type} />
                  </TableCell>
                  <TableCell>
                    {expired ? <StatusPill status="pending" label="Kedaluwarsa" /> : <StatusPill status={j.status} />}
                  </TableCell>
                  <TableCell className="tabular-nums text-ink-2">{formatBytes(j.size_total)}</TableCell>
                  <TableCell className="tabular-nums text-ink-2">{formatDate(j.created_at)}</TableCell>
                  <TableCell className="tabular-nums text-ink-2">{formatDate(j.completed_at)}</TableCell>
                  <TableCell className="pr-5 sm:pr-10">
                    <ConfirmDialog
                      title="Hapus riwayat ini?"
                      description={
                        <>
                          Riwayat <b className="font-medium text-ink">{j.filename}</b> dan file sementaranya di server
                          akan dihapus permanen.
                        </>
                      }
                      confirmLabel="Hapus"
                      onConfirm={() => removeJob(j.id)}
                      trigger={
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          disabled={locked}
                          className="text-muted-foreground hover:bg-bad-bg hover:text-bad"
                          aria-label={`Hapus riwayat ${j.filename}`}
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      }
                    />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
