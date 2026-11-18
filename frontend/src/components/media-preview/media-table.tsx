"use client";

import { useState } from "react";
import { Ban, Play } from "lucide-react";
import type { MediaItem } from "@/types";
import { cn, extFromName, formatBytes, formatDuration } from "@/lib/utils";
import { Checkbox } from "@/components/ui/checkbox";
import { TypeIcon } from "@/components/ui/primitives";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SelectAllRow } from "./select-all";

/** Tabel untuk video, audio, dan subtitle. */
export function MediaTable({
  items,
  selected,
  onToggle,
  onSetMany,
}: {
  items: MediaItem[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onSetMany: (ids: string[], on: boolean) => void;
}) {
  const isSub = items[0]?.type === "subtitle";
  const head = "text-[12px] font-normal text-muted-foreground";

  return (
    <div>
      <SelectAllRow items={items} selected={selected} onSetMany={onSetMany} />
      <div className="overflow-hidden rounded-xl border border-line">
        <Table className="min-w-[640px]">
          <TableHeader className="bg-surface">
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-12 pl-4">
                <span className="sr-only">Pilih</span>
              </TableHead>
              <TableHead className={head}>Nama file</TableHead>
              <TableHead className={head}>Format</TableHead>
              <TableHead className={head}>{isSub ? "Bahasa" : "Durasi"}</TableHead>
              <TableHead className={head}>Ukuran</TableHead>
              <TableHead className={cn(head, "pr-4")}>Ketersediaan</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <Row key={item.id} item={item} checked={selected.has(item.id)} onToggle={() => onToggle(item.id)} />
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function Row({ item, checked, onToggle }: { item: MediaItem; checked: boolean; onToggle: () => void }) {
  const [broken, setBroken] = useState(false);
  const id = `sel-${item.id}`;
  return (
    <TableRow
      data-state={checked ? "selected" : undefined}
      className={cn(checked ? "bg-brand-soft/60 hover:bg-brand-soft/60" : !item.downloadable && "hover:bg-transparent")}
    >
      <TableCell className="pl-4">
        <Checkbox
          id={id}
          checked={checked}
          disabled={!item.downloadable}
          onCheckedChange={onToggle}
          aria-label={`Pilih ${item.filename}`}
        />
      </TableCell>
      <TableCell className="pr-4">
        <label
          htmlFor={id}
          className={cn("flex items-center gap-3", item.downloadable ? "cursor-pointer" : "cursor-not-allowed")}
        >
          {item.type === "video" ? (
            <span className="relative grid h-9 w-16 shrink-0 place-items-center overflow-hidden rounded-md border border-line bg-surface-2">
              {item.preview_url && !broken ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={item.preview_url}
                  alt=""
                  referrerPolicy="no-referrer"
                  onError={() => setBroken(true)}
                  className="absolute inset-0 size-full object-cover"
                />
              ) : null}
              <Play className="relative size-3.5 fill-current text-white drop-shadow" aria-hidden />
            </span>
          ) : (
            <span
              className="grid size-9 shrink-0 place-items-center rounded-md"
              style={{ background: `var(--tag-${item.type}-bg)`, color: `var(--tag-${item.type}-fg)` }}
            >
              <TypeIcon type={item.type} className="size-4" />
            </span>
          )}
          <span className="min-w-0">
            <span className={cn("block truncate font-medium", item.downloadable ? "text-ink" : "text-muted-foreground")}>
              {item.filename}
            </span>
            <span className="block max-w-[320px] truncate font-mono text-[11px] text-muted-foreground" title={item.url}>
              {item.url}
            </span>
          </span>
        </label>
      </TableCell>
      <TableCell className="text-ink-2">
        {extFromName(item.filename, item.mime_type, item.type)}
        {item.height ? <span className="text-muted-foreground"> · {item.height}p</span> : null}
      </TableCell>
      <TableCell className="tabular-nums text-ink-2">
        {item.type === "subtitle" ? (item.language ?? "—") : formatDuration(item.duration)}
      </TableCell>
      <TableCell className="tabular-nums text-ink-2">
        {item.size == null ? <span className="text-muted-foreground">Tidak diketahui</span> : formatBytes(item.size)}
      </TableCell>
      <TableCell className="whitespace-normal pr-4">
        {item.downloadable ? (
          <span className="text-[13px] text-ok">Dapat diunduh</span>
        ) : (
          <span className="inline-flex items-start gap-1.5 text-[13px] text-muted-foreground">
            <Ban className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span className="max-w-[220px]">{item.reason ?? "Tidak dapat diunduh."}</span>
          </span>
        )}
      </TableCell>
    </TableRow>
  );
}
