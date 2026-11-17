// Kontrak data mengikuti PRD §12 (API /api/v1).

export type MediaType = "image" | "video" | "subtitle" | "text" | "audio";

export type JobStatus =
  | "pending"
  | "processing"
  | "downloading"
  | "completed"
  | "failed";

export type SubtitleFormat = "original" | "srt";

export type SourceType =
  | "generic"
  | "youtube"
  | "instagram"
  | "facebook"
  | "tiktok"
  | "x"
  | "social_other"
  | string;

export interface MediaItem {
  id: string;
  type: MediaType;
  filename: string;
  url: string;
  mime_type: string | null;
  /** Ukuran dalam byte. `null` jika tidak diketahui — jangan diestimasi. */
  size: number | null;
  downloadable: boolean;
  /** Alasan umum jika item tidak dapat diunduh. */
  reason?: string | null;
  width?: number | null;
  height?: number | null;
  duration?: number | null;
  language?: string | null;
  preview_url?: string | null;
}

export interface AnalyzeResult {
  /** ID analisis di server; dipakai saat membuat pekerjaan unduhan. */
  id: string;
  success: boolean;
  source: { type: SourceType; domain: string; name?: string };
  page: {
    url: string;
    final_url?: string | null;
    title: string | null;
    description: string | null;
    thumbnail?: string | null;
  };
  media: MediaItem[];
  text: { title: string | null; content: string | null; word_count: number } | null;
  warnings: string[];
  analyzed_at: string;
}

export interface DownloadJob {
  id: string;
  status: JobStatus;
  /** Persentase 0–100, atau `null` jika ukuran total tidak diketahui. */
  progress: number | null;
  filename: string;
  media_type: MediaType;
  source_url: string;
  source_domain: string;
  size_downloaded: number;
  size_total: number | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  expires_at: string | null;
}

export interface AdapterInfo {
  id: string;
  name: string;
  domains: string[];
  status: "active" | "evaluating" | "disabled";
  note: string;
}

export interface ServerConfig {
  max_download_size_mb: number;
  download_timeout_seconds: number;
  file_retention_hours: number;
  storage_path: string;
  version: string;
  queue_backend?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
  }
}
