import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";
import type { JobStatus, MediaType } from "@/types";

// Warna kustom (ink, brand, ...) perlu didaftarkan agar tailwind-merge tahu `text-ink`
// adalah warna, bukan ukuran font, dan tidak membuang `text-[13px]` di sebelahnya.
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      color: [
        "bg", "surface", "surface-2", "line", "line-strong", "ink", "ink-2", "brand", "brand-soft",
        "ok", "ok-bg", "bad", "bad-bg", "run", "run-bg", "idle", "idle-bg",
      ],
    },
  },
});

/** Utilitas shadcn/ui: gabungkan kelas kondisional dan selesaikan konflik Tailwind. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const dateFmt = new Intl.DateTimeFormat("id-ID", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dateFmt.format(new Date(iso));
}

export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const diff = Math.round((now - new Date(iso).getTime()) / 1000);
  if (diff < 45) return "baru saja";
  if (diff < 3600) return `${Math.round(diff / 60)} menit lalu`;
  if (diff < 86400) return `${Math.round(diff / 3600)} jam lalu`;
  return formatDate(iso);
}

export const MEDIA_LABEL: Record<MediaType, string> = {
  image: "Gambar",
  video: "Video",
  subtitle: "Subtitle",
  text: "Teks",
  audio: "Audio",
};

export const STATUS_LABEL: Record<JobStatus, string> = {
  pending: "Menunggu",
  processing: "Diproses",
  downloading: "Mengunduh",
  completed: "Selesai",
  failed: "Gagal",
};

export function extFromName(name: string): string {
  const m = /\.([a-z0-9]{1,5})$/i.exec(name);
  return m ? m[1].toUpperCase() : "—";
}
