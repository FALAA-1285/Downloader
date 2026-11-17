"use client";

// Store pekerjaan unduhan di sisi klien.
// - Mode backend: membuat job lewat POST /downloads lalu polling GET /downloads/{id}.
// - Mode demo: mensimulasikan transisi status agar alur UI bisa dicoba tanpa backend.
// - Kegagalan sinkronisasi dengan backend disimpan sebagai `syncError` agar UI bisa menampilkannya.

import { useSyncExternalStore } from "react";
import { ApiError, type AnalyzeResult, type DownloadJob, type MediaItem, type SubtitleFormat } from "@/types";
import {
  FILE_LINKS_NEED_FETCH,
  IS_DEMO,
  createDownloads,
  deleteHistory,
  fileUrl,
  getDownload,
  getHistory,
  retryDownload,
  saveFileWithToken,
} from "./api";
import { MOCK_CONFIG } from "./mock";

export type StoredJob = DownloadJob & {
  demo_href?: string | null;
  _target?: number;
  _speed?: number;
  _fail?: boolean;
  _t?: number;
};

const KEY = "umd.jobs.v1";
const EMPTY: StoredJob[] = [];
let jobs: StoredJob[] = EMPTY;
let loaded = false;
let ticker: ReturnType<typeof setInterval> | null = null;
let syncError: string | null = null;
const listeners = new Set<() => void>();
const autoSaveIds = new Set<string>();
const downloadQueue: StoredJob[] = [];
let isDrainingQueue = false;

/** Pekerjaan yang hanya ada di browser (mis. ekspor TXT), bukan di server. */
const isLocal = (j: { id: string }) => j.id.startsWith("job-");
const isActive = (j: DownloadJob) => j.status === "pending" || j.status === "processing" || j.status === "downloading";

export function triggerBrowserDownload(j: StoredJob) {
  if (typeof window === "undefined") return;
  const href = jobFileHref(j);
  if (href) {
    const a = document.createElement("a");
    a.href = href;
    a.download = j.filename;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      try {
        document.body.removeChild(a);
      } catch {
        // abaikan
      }
    }, 150);
  } else if (canFetchFile(j)) {
    void saveJobFile(j);
  }
}

function enqueueBrowserDownload(j: StoredJob) {
  downloadQueue.push(j);
  if (!isDrainingQueue) {
    void drainDownloadQueue();
  }
}

async function drainDownloadQueue() {
  if (isDrainingQueue) return;
  isDrainingQueue = true;
  try {
    while (downloadQueue.length > 0) {
      const j = downloadQueue.shift();
      if (j) {
        triggerBrowserDownload(j);
        // Beri jeda 350ms antar unduhan agar browser tidak mencegat multi-download
        await new Promise((resolve) => setTimeout(resolve, 350));
      }
    }
  } finally {
    isDrainingQueue = false;
  }
}

function load() {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      jobs = JSON.parse(raw) as StoredJob[];
      jobs.forEach((j) => {
        if (isActive(j)) autoSaveIds.add(j.id);
      });
    }
  } catch {
    jobs = [];
  }
}

function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify(jobs));
  } catch {
    // localStorage penuh atau diblokir: data tetap ada di memori
  }
}

function notify() {
  listeners.forEach((l) => l());
}

function setSyncError(message: string | null) {
  if (syncError === message) return;
  syncError = message;
  notify();
}

function set(next: StoredJob[]) {
  jobs = next;
  persist();
  notify();
  ensureTicker();
}

function ensureTicker() {
  const any = jobs.some(isActive);
  if (any && !ticker && listeners.size > 0) {
    ticker = setInterval(IS_DEMO ? tickDemo : tickRemote, IS_DEMO ? 400 : 1500);
  } else if ((!any || listeners.size === 0) && ticker) {
    clearInterval(ticker);
    ticker = null;
  }
}

function tickDemo() {
  const now = Date.now();
  let changed = false;
  const next = jobs.map((j) => {
    if (!isActive(j)) return j;
    changed = true;
    const age = now - (j._t ?? now);
    if (j.status === "pending" && age > 700) return { ...j, status: "processing" as const, _t: now };
    if (j.status === "processing" && age > 900) return { ...j, status: "downloading" as const, _t: now };
    if (j.status !== "downloading") return j;

    const target = j.size_total ?? j._target ?? 1_000_000;
    const downloaded = Math.min(target, j.size_downloaded + (j._speed ?? 400_000));
    if (j._fail && downloaded / target > 0.42) {
      return {
        ...j,
        status: "failed" as const,
        error_message: "Server sumber menolak permintaan (HTTP 403). Coba lagi nanti atau periksa apakah file masih tersedia.",
        completed_at: new Date().toISOString(),
      };
    }
    if (downloaded >= target) {
      const done = new Date();
      const doneJob = {
        ...j,
        status: "completed" as const,
        progress: 100,
        size_downloaded: target,
        size_total: target,
        completed_at: done.toISOString(),
        expires_at: new Date(done.getTime() + MOCK_CONFIG.file_retention_hours * 3600_000).toISOString(),
      };
      if (autoSaveIds.has(j.id)) {
        autoSaveIds.delete(j.id);
        enqueueBrowserDownload(doneJob);
      }
      return doneJob;
    }
    return {
      ...j,
      size_downloaded: downloaded,
      progress: j.size_total ? Math.floor((downloaded / j.size_total) * 100) : null,
    };
  });
  if (changed) set(next);
}

let polling = false;
let consecutiveFailures = 0;

async function tickRemote() {
  if (polling) return;
  polling = true;
  try {
    const active = jobs.filter((j) => isActive(j) && !isLocal(j));
    if (active.length === 0) {
      consecutiveFailures = 0;
      setSyncError(null);
      return;
    }
    const updates = await Promise.allSettled(active.map((j) => getDownload(j.id)));
    const byId = new Map<string, Partial<StoredJob>>();
    let networkError: string | null = null;
    updates.forEach((u, i) => {
      if (u.status === "fulfilled") {
        byId.set(u.value.id, u.value);
      } else if (u.reason instanceof ApiError && u.reason.status === 404) {
        // Job sudah tidak ada di server: hentikan polling untuk job ini.
        byId.set(active[i].id, {
          status: "failed",
          error_message: "Pekerjaan tidak ditemukan di server (mungkin sudah dihapus atau database direset).",
        });
      } else {
        networkError = (u.reason as Error)?.message ?? "Backend tidak dapat dihubungi.";
      }
    });
    if (byId.size > 0) {
      consecutiveFailures = 0;
      setSyncError(null);
      const nextJobs = jobs.map((j) => (byId.has(j.id) ? { ...j, ...byId.get(j.id)! } : j));
      nextJobs.forEach((j) => {
        if (autoSaveIds.has(j.id) && j.status === "completed") {
          autoSaveIds.delete(j.id);
          enqueueBrowserDownload(j);
        }
      });
      set(nextJobs);
    } else {
      consecutiveFailures++;
      if (consecutiveFailures >= 2) {
        setSyncError(networkError);
      }
    }
  } finally {
    polling = false;
  }
}

function subscribe(l: () => void) {
  load();
  listeners.add(l);
  ensureTicker();
  return () => {
    listeners.delete(l);
    ensureTicker();
  };
}

function getSnapshot() {
  load();
  return jobs;
}

export function useJobs(): StoredJob[] {
  return useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);
}

/** Pesan error sinkronisasi terakhir dengan backend, atau null bila terakhir berhasil. */
export function useSyncError(): string | null {
  return useSyncExternalStore(
    subscribe,
    () => syncError,
    () => null,
  );
}

let uid = 0;
const newId = () => `job-${Date.now().toString(36)}-${(uid++).toString(36)}`;

export async function startDownloads(
  result: AnalyzeResult,
  items: MediaItem[],
  subtitleFormat: SubtitleFormat = "original",
): Promise<number> {
  load();
  const now = new Date().toISOString();
  if (!IS_DEMO) {
    const created = await createDownloads(
      result.id,
      items.map((i) => i.id),
      subtitleFormat,
    );
    created.forEach((j) => {
      if (j.status === "completed") {
        enqueueBrowserDownload(j);
      } else {
        autoSaveIds.add(j.id);
      }
    });
    set([...created, ...jobs]);
    return created.length;
  }
  const created: StoredJob[] = items.map((item, idx) => {
    const target = item.size ?? Math.floor(2_000_000 + Math.random() * 6_000_000);
    return {
      id: newId(),
      status: "pending",
      progress: item.size ? 0 : null,
      filename: item.filename,
      media_type: item.type,
      source_url: result.page.url,
      source_domain: result.source.domain,
      size_downloaded: 0,
      size_total: item.size,
      error_message: null,
      created_at: now,
      completed_at: null,
      expires_at: null,
      demo_href: item.type === "image" ? item.preview_url : null,
      _target: target,
      _speed: Math.max(60_000, Math.floor(target / (6 + Math.random() * 14))),
      _fail: /\.gif$/.test(item.filename) && idx % 2 === 1,
      _t: Date.now() + idx * 250,
    };
  });
  created.forEach((j) => autoSaveIds.add(j.id));
  set([...created, ...jobs]);
  return created.length;
}

/** Ekspor teks dicatat sebagai pekerjaan selesai agar muncul di riwayat. */
export function recordTextExport(result: AnalyzeResult, filename: string, size: number, href: string) {
  load();
  const now = new Date();
  set([
    {
      id: newId(),
      status: "completed",
      progress: 100,
      filename,
      media_type: "text",
      source_url: result.page.url,
      source_domain: result.source.domain,
      size_downloaded: size,
      size_total: size,
      error_message: null,
      created_at: now.toISOString(),
      completed_at: now.toISOString(),
      expires_at: null,
      demo_href: href,
    },
    ...jobs,
  ]);
}

export async function retryJob(id: string) {
  autoSaveIds.add(id);
  if (!IS_DEMO) {
    const updated = await retryDownload(id);
    set(jobs.map((j) => (j.id === id ? { ...j, ...updated } : j)));
    return;
  }
  set(
    jobs.map((j) =>
      j.id === id
        ? { ...j, status: "pending", error_message: null, size_downloaded: 0, progress: j.size_total ? 0 : null, completed_at: null, _fail: false, _t: Date.now() }
        : j,
    ),
  );
}

export async function removeJob(id: string) {
  if (!IS_DEMO && !isLocal({ id })) await deleteHistory(id);
  set(jobs.filter((j) => j.id !== id));
}

/** Menghapus beberapa job. Hanya yang berhasil dihapus di server yang dibuang dari daftar. */
export async function removeJobs(ids: string[]): Promise<number> {
  const drop = new Set(ids.filter((id) => IS_DEMO || isLocal({ id })));
  if (!IS_DEMO) {
    const remote = ids.filter((id) => !isLocal({ id }));
    const results = await Promise.allSettled(remote.map((id) => deleteHistory(id)));
    results.forEach((r, i) => r.status === "fulfilled" && drop.add(remote[i]));
  }
  set(jobs.filter((j) => !drop.has(j.id)));
  const failed = ids.length - drop.size;
  if (failed > 0) throw new ApiError(`${failed} riwayat gagal dihapus. Coba lagi.`);
  return drop.size;
}

/** Sinkronkan riwayat dari server. Mengembalikan false bila gagal (lihat `useSyncError`). */
export async function syncHistory(): Promise<boolean> {
  if (IS_DEMO) return true;
  load();
  try {
    const remote: StoredJob[] = await getHistory();
    const local = jobs.filter(isLocal);
    set([...remote, ...local].sort((a, b) => b.created_at.localeCompare(a.created_at)));
    setSyncError(null);
    return true;
  } catch (err) {
    setSyncError((err as Error).message || "Backend tidak dapat dihubungi.");
    return false;
  }
}

export function isExpired(j: DownloadJob, now = Date.now()) {
  return j.expires_at != null && new Date(j.expires_at).getTime() < now;
}

/** URL file hasil untuk tautan langsung, atau null (tidak tersedia, atau butuh token → `saveJobFile`). */
export function jobFileHref(j: StoredJob): string | null {
  if (j.status !== "completed" || isExpired(j)) return null;
  if (IS_DEMO || isLocal(j)) return j.demo_href ?? null;
  return FILE_LINKS_NEED_FETCH ? null : fileUrl(j.id);
}

/** Apakah file job bisa disimpan lewat fetch (saat token API aktif). */
export function canFetchFile(j: StoredJob): boolean {
  return !IS_DEMO && !isLocal(j) && FILE_LINKS_NEED_FETCH && j.status === "completed" && !isExpired(j);
}

export function saveJobFile(j: StoredJob): Promise<void> {
  return saveFileWithToken(j.id, j.filename);
}
