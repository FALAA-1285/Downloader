"use client";

import { useId } from "react";
import type { MediaItem } from "@/types";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

export function SelectAllRow({
  items,
  selected,
  onSetMany,
}: {
  items: MediaItem[];
  selected: Set<string>;
  onSetMany: (ids: string[], on: boolean) => void;
}) {
  const id = useId();
  const available = items.filter((i) => i.downloadable).map((i) => i.id);
  const picked = available.filter((itemId) => selected.has(itemId)).length;
  const all = available.length > 0 && picked === available.length;
  const unavailable = items.length - available.length;

  return (
    <div className="mb-4 flex items-center justify-between gap-3 text-[13px]">
      <div className="flex items-center gap-2.5">
        <Checkbox
          id={id}
          checked={all ? true : picked > 0 ? "indeterminate" : false}
          disabled={available.length === 0}
          onCheckedChange={() => onSetMany(available, !all)}
        />
        <Label htmlFor={id} className="cursor-pointer text-[13px] font-normal text-ink-2">
          {all ? "Batalkan semua" : `Pilih semua yang tersedia (${available.length})`}
        </Label>
      </div>
      {unavailable > 0 && <span className="text-muted-foreground">{unavailable} tidak dapat diunduh</span>}
    </div>
  );
}
