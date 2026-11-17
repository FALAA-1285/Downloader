"use client";

import { useState } from "react";
import { ImageOff } from "lucide-react";
import type { MediaItem } from "@/types";
import { cn, extFromName, formatBytes } from "@/lib/utils";
import { Checkbox } from "@/components/ui/primitives";
import { SelectAllRow } from "./select-all";

export function ImageGrid({
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
  return (
    <div>
      <SelectAllRow items={items} selected={selected} onSetMany={onSetMany} />
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4">
        {items.map((item) => (
          <ImageCard key={item.id} item={item} checked={selected.has(item.id)} onToggle={() => onToggle(item.id)} />
        ))}
      </ul>
    </div>
  );
}

function ImageCard({ item, checked, onToggle }: { item: MediaItem; checked: boolean; onToggle: () => void }) {
  const [broken, setBroken] = useState(false);
  const showPreview = item.preview_url && !broken;
  const id = `sel-${item.id}`;

  return (
    <li
      className={cn(
        "group relative overflow-hidden rounded-xl border bg-bg transition-[border-color,box-shadow]",
        checked ? "border-accent shadow-[0_0_0_3px_var(--ring)]" : "border-line hover:border-line-strong",
        !item.downloadable && "opacity-75",
      )}
    >
      <label htmlFor={id} className={cn("block", item.downloadable ? "cursor-pointer" : "cursor-not-allowed")}>
        <div className="relative aspect-[4/3] overflow-hidden border-b border-line bg-surface-2">
          {showPreview ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={item.preview_url!}
              alt={item.filename}
              loading="lazy"
              onError={() => setBroken(true)}
              className="size-full object-cover"
            />
          ) : (
            <div className="grid size-full place-items-center text-muted">
              <div className="flex flex-col items-center gap-1.5 text-[12px]">
                <ImageOff className="size-5" aria-hidden />
                Pratinjau tidak tersedia
              </div>
            </div>
          )}
          <span className="absolute left-2.5 top-2.5 rounded-md bg-bg/90 p-1 shadow-sm backdrop-blur">
            <Checkbox id={id} checked={checked} disabled={!item.downloadable} onChange={onToggle} aria-label={`Pilih ${item.filename}`} />
          </span>
          <span className="absolute right-2.5 top-2.5 rounded-md bg-bg/90 px-1.5 py-0.5 text-[11px] font-medium text-ink-2 backdrop-blur">
            {extFromName(item.filename)}
          </span>
        </div>
        <div className="px-3 py-2.5">
          <p className="truncate text-[13px] font-medium text-ink" title={item.url}>
            {item.filename}
          </p>
          {item.downloadable ? (
            <p className="mt-0.5 text-[12px] tabular-nums text-muted">
              {item.width && item.height ? `${item.width}×${item.height} · ` : ""}
              {formatBytes(item.size)}
            </p>
          ) : (
            <p className="mt-0.5 text-[12px] text-bad">{item.reason ?? "Tidak dapat diunduh."}</p>
          )}
        </div>
      </label>
    </li>
  );
}
