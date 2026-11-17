"use client";

import Link from "next/link";
import { Inbox } from "lucide-react";
import { useJobs } from "@/services/jobs-store";
import { useNow } from "@/hooks/use-now";
import { JobRow } from "./job-row";

export function RecentDownloads() {
  const jobs = useJobs();
  const now = useNow();
  const recent = jobs.slice(0, 5);

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-bg">
      <div className="flex items-center justify-between border-b border-line px-5 py-3 sm:px-6">
        <h3 className="text-sm font-semibold text-ink">Unduhan terbaru</h3>
        {jobs.length > 0 && (
          <Link href="/downloads" className="text-[13px] text-ink-2 hover:text-ink">
            Lihat semua ({jobs.length})
          </Link>
        )}
      </div>
      {recent.length === 0 ? (
        <div className="flex items-center gap-3 px-6 py-8 text-sm text-ink-2">
          <Inbox className="size-4 text-muted" aria-hidden />
          Belum ada unduhan. Analisis sebuah URL di atas, lalu pilih media yang ingin disimpan.
        </div>
      ) : (
        <ul>
          {recent.map((j) => (
            <JobRow key={j.id} job={j} now={now} />
          ))}
        </ul>
      )}
    </div>
  );
}
