// Klien REST untuk backend FastAPI (PRD §12, base `/api/v1`).
// Tanpa NEXT_PUBLIC_API_BASE_URL, aplikasi berjalan dalam mode demo.

import { ApiError, type AdapterInfo, type AnalyzeResult, type DownloadJob, type MediaType, type ServerConfig } from "@/types";
import { MOCK_ADAPTERS, MOCK_CONFIG, mockAnalyze } from "./mock";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";
export const IS_DEMO = BASE === "";
const API = `${BASE}/api/v1`;
const ANALYZE_TIMEOUT_MS = 30_000;

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 15_000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API}${path}`, {
      ...init,
      signal: init.signal ?? ctrl.signal,
      headers: { "Content-Type": "application/json", ...init.headers },
      credentials: "omit",
    });
    if (!res.ok) {
      let message = `Permintaan gagal (HTTP ${res.status}).`;
      try {
        const body = await res.json();
        message = body.detail?.message ?? body.detail ?? body.message ?? message;
      } catch {}
      throw new ApiError(String(message), res.status);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("Analisis melewati batas waktu. Coba lagi atau gunakan URL lain.");
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

export function createDownloads(analysisId: string, mediaIds: string[]) {
  return request<DownloadJob[]>("/downloads", {
    method: "POST",
    body: JSON.stringify({ analysis_id: analysisId, media_ids: mediaIds }),
  });
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
