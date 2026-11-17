"use client";

import { useEffect, useRef } from "react";
import type { MediaItem } from "@/types";
import { Checkbox } from "@/components/ui/primitives";

export function SelectAllRow({
  items,
  selected,
  onSetMany,
}: {
  items: MediaItem[];
  selected: Set<string>;
  onSetMany: (ids: string[], on: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const available = items.filter((i) => i.downloadable).map((i) => i.id);
  const picked = available.filter((id) => selected.has(id)).length;
  const all = available.length > 0 && picked === available.length;
  const some = picked > 0 && !all;
  const unavailable = items.length - available.length;

  useEffect(() => {
    if (ref.current) ref.current.indeterminate = some;
  }, [some]);

  return (
    <div className="mb-4 flex items-center justify-between gap-3 text-[13px]">
      <label className="flex cursor-pointer items-center gap-2.5 text-ink-2">
        <Checkbox ref={ref} checked={all} disabled={available.length === 0} onChange={() => onSetMany(available, !all)} />
        {all ? "Batalkan semua" : `Pilih semua yang tersedia (${available.length})`}
      </label>
      {unavailable > 0 && <span className="text-muted">{unavailable} tidak dapat diunduh</span>}
    </div>
  );
}
