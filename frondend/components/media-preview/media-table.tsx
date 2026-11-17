"use client";

import { useState } from "react";
import { Ban, Play } from "lucide-react";
import type { MediaItem } from "@/types";
import { cn, extFromName, formatBytes, formatDuration } from "@/lib/utils";
import { Checkbox, TypeIcon } from "@/components/ui/primitives";
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

  return (
    <div>
      <SelectAllRow items={items} selected={selected} onSetMany={onSetMany} />
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-line bg-surface text-[12px] text-muted">
              <th className="w-12 py-2.5 pl-4 font-normal"><span className="sr-only">Pilih</span></th>
              <th className="py-2.5 font-normal">Nama file</th>
              <th className="py-2.5 pr-4 font-normal">Format</th>
              <th className="py-2.5 pr-4 font-normal">{isSub ? "Bahasa" : "Durasi"}</th>
              <th className="py-2.5 pr-4 font-normal">Ukuran</th>
              <th className="py-2.5 pr-4 font-normal">Ketersediaan</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <Row key={item.id} item={item} checked={selected.has(item.id)} onToggle={() => onToggle(item.id)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Row({ item, checked, onToggle }: { item: MediaItem; checked: boolean; onToggle: () => void }) {
  const [broken, setBroken] = useState(false);
  const id = `sel-${item.id}`;
  return (
    <tr
      className={cn(
        "border-b border-line transition-colors last:border-b-0",
        checked ? "bg-accent-soft/60" : item.downloadable && "hover:bg-surface",
      )}
    >
      <td className="py-3 pl-4">
        <Checkbox id={id} checked={checked} disabled={!item.downloadable} onChange={onToggle} aria-label={`Pilih ${item.filename}`} />
      </td>
      <td className="py-3 pr-4">
        <label htmlFor={id} className={cn("flex items-center gap-3", item.downloadable ? "cursor-pointer" : "cursor-not-allowed")}>
          {item.type === "video" ? (
            <span className="relative grid h-9 w-16 shrink-0 place-items-center overflow-hidden rounded-md border border-line bg-surface-2">
              {item.preview_url && !broken ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={item.preview_url} alt="" onError={() => setBroken(true)} className="absolute inset-0 size-full object-cover" />
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
            <span className={cn("block truncate font-medium", item.downloadable ? "text-ink" : "text-muted")}>{item.filename}</span>
            <span className="block max-w-[320px] truncate font-mono text-[11px] text-muted" title={item.url}>
              {item.url}
            </span>
          </span>
        </label>
      </td>
      <td className="py-3 pr-4 text-ink-2">
        {extFromName(item.filename)}
        {item.height ? <span className="text-muted"> · {item.height}p</span> : null}
      </td>
      <td className="py-3 pr-4 tabular-nums text-ink-2">{item.type === "subtitle" ? (item.language ?? "—") : formatDuration(item.duration)}</td>
      <td className="py-3 pr-4 tabular-nums text-ink-2">{item.size == null ? <span className="text-muted">Tidak diketahui</span> : formatBytes(item.size)}</td>
      <td className="py-3 pr-4">
        {item.downloadable ? (
          <span className="text-[13px] text-ok">Dapat diunduh</span>
        ) : (
          <span className="inline-flex items-start gap-1.5 text-[13px] text-muted">
            <Ban className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span className="max-w-[220px]">{item.reason ?? "Tidak dapat diunduh."}</span>
          </span>
        )}
      </td>
    </tr>
  );
}
