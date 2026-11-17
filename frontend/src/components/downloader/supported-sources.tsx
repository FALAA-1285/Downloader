"use client";

import { useEffect, useState } from "react";
import { Ban, CircleCheck, Clock, Globe } from "lucide-react";
import type { AdapterInfo } from "@/types";
import { cn } from "@/lib/utils";
import { IS_DEMO, getAdapters } from "@/services/api";
import { MOCK_ADAPTERS } from "@/services/mock";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const STATUS_COPY = {
  active: { label: "Aktif", icon: CircleCheck, cls: "text-ok" },
  evaluating: { label: "Evaluasi", icon: Clock, cls: "text-ink-2" },
  disabled: { label: "Nonaktif", icon: Ban, cls: "text-muted-foreground" },
} as const;

type State = { kind: "loading" } | { kind: "ready"; adapters: AdapterInfo[]; fallback: boolean };

/** Status adapter dari backend (`/api/v1/adapters`); data contoh hanya di mode demo atau saat backend mati. */
export function SupportedSources() {
  const [state, setState] = useState<State>(
    IS_DEMO ? { kind: "ready", adapters: MOCK_ADAPTERS, fallback: false } : { kind: "loading" },
  );

  useEffect(() => {
    if (IS_DEMO) return;
    let cancelled = false;
    getAdapters()
      .then((adapters) => !cancelled && setState({ kind: "ready", adapters, fallback: false }))
      .catch(() => !cancelled && setState({ kind: "ready", adapters: MOCK_ADAPTERS, fallback: true }));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <Table>
        <TableCaption className="sr-only">Status dukungan sumber</TableCaption>
        <TableHeader className="bg-surface">
          <TableRow className="hover:bg-transparent">
            <TableHead className="px-5 text-[12px] font-normal text-muted-foreground">Sumber</TableHead>
            <TableHead className="px-5 text-[12px] font-normal text-muted-foreground">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {state.kind === "loading"
            ? Array.from({ length: 4 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell className="px-5 py-3.5">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="mt-2 h-3 w-56" />
                  </TableCell>
                  <TableCell className="px-5 py-3.5">
                    <Skeleton className="h-4 w-16" />
                  </TableCell>
                </TableRow>
              ))
            : state.adapters.map((a) => {
                const s = STATUS_COPY[a.status];
                return (
                  <TableRow key={a.id} className="hover:bg-transparent">
                    <TableCell className="whitespace-normal px-5 py-3.5 align-top">
                      <div className="flex items-center gap-2 font-medium text-ink">
                        {a.id === "generic" && <Globe className="size-3.5 text-ink-2" aria-hidden />}
                        {a.name}
                      </div>
                      <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{a.note}</p>
                    </TableCell>
                    <TableCell className="px-5 py-3.5 align-top">
                      <span className={cn("inline-flex items-center gap-1.5 text-[13px] font-medium", s.cls)}>
                        <s.icon className="size-3.5" aria-hidden />
                        {s.label}
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
        </TableBody>
      </Table>
      {state.kind === "ready" && state.fallback && (
        <p className="border-t border-line bg-surface px-5 py-2.5 text-[12px] text-muted-foreground">
          Backend tidak dapat dihubungi; menampilkan daftar bawaan, bukan status server saat ini.
        </p>
      )}
    </div>
  );
}
