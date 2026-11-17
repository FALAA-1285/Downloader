// Klien REST untuk backend FastAPI (PRD §12, base `/api/v1`).
// Tanpa NEXT_PUBLIC_API_BASE_URL, aplikasi berjalan dalam mode demo.

import {
  ApiError,
  type AdapterInfo,
  type AnalyzeResult,
  type DownloadJob,
  type MediaType,
  type ServerConfig,
  type SubtitleFormat,
} from "@/types";
import { MOCK_ADAPTERS, MOCK_CONFIG, mockAnalyze } from "./mock";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";
// Opsional; harus sama dengan API_TOKEN di backend. Nilai NEXT_PUBLIC_* ikut ter-bundle ke browser,
// jadi token ini hanya membatasi akses dari perangkat lain yang tidak memuat frontend ini.
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";
export const IS_DEMO = BASE === "";
const API = `${BASE}/api/v1`;
const ANALYZE_TIMEOUT_MS = 60_000;

/** Header untuk setiap request: penanda klien (wajib untuk POST/DELETE) dan token bila ada. */
function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "X-UMD-Client": "web" };
  if (TOKEN) headers.Authorization = `Bearer ${TOKEN}`;
  return headers;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 15_000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API}${path}`, {
      ...init,
      signal: init.signal ?? ctrl.signal,
      headers: { "Content-Type": "application/json", ...authHeaders(), ...init.headers },
      credentials: "omit",
    });
    if (!res.ok) {
      let message = `Permintaan gagal (HTTP ${res.status}).`;
      try {
        const body = await res.json();
        message = body.detail?.message ?? body.detail ?? body.message ?? message;
      } catch {
        // body bukan JSON; pakai pesan bawaan
      }
      throw new ApiError(String(message), res.status);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("Permintaan melewati batas waktu. Coba lagi.");
    }
    throw new ApiError("Backend tidak dapat dihubungi. Pastikan layanan FastAPI berjalan.");
  } finally {
    clearTimeout(timer);
  }
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function analyzeUrl(url: string, mediaTypes: MediaType[]): Promise<AnalyzeResult> {
  if (IS_DEMO) {
    await wait(1100 + Math.random() * 600);
    try {
      return mockAnalyze(url, mediaTypes);
    } catch (e) {
      throw new ApiError((e as Error).message, 422);
    }
  }
  return request<AnalyzeResult>(
    "/analyze",
    { method: "POST", body: JSON.stringify({ url, media_types: mediaTypes }) },
    ANALYZE_TIMEOUT_MS,
  );
}

export async function createDownloads(
  analysisId: string,
  mediaIds: string[],
  subtitleFormat: SubtitleFormat = "original",
): Promise<DownloadJob[]> {
  if (mediaIds.length <= 250) {
    return request<DownloadJob[]>("/downloads", {
      method: "POST",
      body: JSON.stringify({ analysis_id: analysisId, media_ids: mediaIds, subtitle_format: subtitleFormat }),
    });
  }
  const chunks: string[][] = [];
  for (let i = 0; i < mediaIds.length; i += 250) {
    chunks.push(mediaIds.slice(i, i + 250));
  }
  const results = await Promise.all(
    chunks.map((chunk) =>
      request<DownloadJob[]>("/downloads", {
        method: "POST",
        body: JSON.stringify({ analysis_id: analysisId, media_ids: chunk, subtitle_format: subtitleFormat }),
      }),
    ),
  );
  return results.flat();
}

export function retryDownload(jobId: string) {
  return request<DownloadJob>(`/downloads/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
}

export function getDownload(jobId: string) {
  return request<DownloadJob>(`/downloads/${encodeURIComponent(jobId)}`);
}

export function getHistory() {
  return request<DownloadJob[]>("/history");
}

export function deleteHistory(id: string) {
  return request<void>(`/history/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function fileUrl(jobId: string) {
  return `${API}/downloads/${encodeURIComponent(jobId)}/file`;
}

/** Tautan langsung hanya bisa dipakai bila tidak ada token (tautan tidak bisa membawa header). */
export const FILE_LINKS_NEED_FETCH = TOKEN !== "";

/** Mengunduh file hasil lewat fetch (dipakai saat token aktif), lalu menyimpannya di browser. */
export async function saveFileWithToken(jobId: string, filename: string): Promise<void> {
  const res = await fetch(fileUrl(jobId), { headers: authHeaders(), credentials: "omit" });
  if (!res.ok) {
    let message = `Gagal mengambil file (HTTP ${res.status}).`;
    try {
      message = (await res.json()).detail?.message ?? message;
    } catch {
      // abaikan
    }
    throw new ApiError(message, res.status);
  }
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export async function downloadZipFile(jobIds: string[], zipName = "media_downloads"): Promise<void> {
  const res = await fetch(`${API}/downloads/zip`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ job_ids: jobIds, zip_name: zipName }),
    credentials: "omit",
  });
  if (!res.ok) {
    let message = `Gagal mengemas file ZIP (HTTP ${res.status}).`;
    try {
      message = (await res.json()).detail?.message ?? message;
    } catch {
      // abaikan
    }
    throw new ApiError(message, res.status);
  }
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = href;
  a.download = `${zipName}.zip`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export async function getAdapters(): Promise<AdapterInfo[]> {
  if (IS_DEMO) return MOCK_ADAPTERS;
  return request<AdapterInfo[]>("/adapters");
}

export async function getConfig(): Promise<ServerConfig> {
  if (IS_DEMO) return MOCK_CONFIG;
  return request<ServerConfig>("/config");
}

export async function getHealth(): Promise<boolean> {
  if (IS_DEMO) return true;
  try {
    await request("/health", {}, 4000);
    return true;
  } catch {
    return false;
  }
}
