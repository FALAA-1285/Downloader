"use client";

// Cookie sesi per domain (temuan audit C-03).
// Dulu satu string cookie global dikirim ke SETIAP situs yang dianalisis, sehingga cookie
// login situs A ikut terkirim ke situs B. Sekarang cookie disimpan per domain dan hanya
// dikirim bila host URL sama dengan domain itu atau subdomainnya. Backend tetap membatasi
// lagi per host/redirect, jadi ini lapisan pertama, bukan satu-satunya.

import { useSyncExternalStore } from "react";

const KEY = "umd.cookies.v2";
/** Kunci lama (satu cookie global). Dihapus saat pertama dibaca karena domainnya tidak diketahui. */
const LEGACY_KEY = "umd_session_cookies";

export type CookieEntries = Record<string, string>;

const EMPTY: CookieEntries = {};
let cache: CookieEntries | null = null;
let legacyDropped = false;
const listeners = new Set<() => void>();

const HOST_RE = /^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;

/** "https://www.Example.com/x" → "www.example.com"; ".example.com" → "example.com"; tidak valid → null. */
export function normalizeDomain(input: string | null | undefined): string | null {
  if (!input) return null;
  let value = input.trim().toLowerCase();
  if (!value) return null;
  if (value.includes("://")) {
    try {
      value = new URL(value).hostname;
    } catch {
      return null;
    }
  }
  value = value.split("/")[0].split(":")[0].replace(/^\.+/, "").replace(/\.+$/, "");
  return HOST_RE.test(value) ? value : null;
}

function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return null;
  }
}

function read(): CookieEntries {
  if (cache) return cache;
  if (typeof window === "undefined") return EMPTY;
  try {
    if (localStorage.getItem(LEGACY_KEY) !== null) {
      localStorage.removeItem(LEGACY_KEY);
      legacyDropped = true;
    }
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : {};
    cache =
      parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? Object.fromEntries(
            Object.entries(parsed as Record<string, unknown>).filter(
              ([d, v]) => normalizeDomain(d) === d && typeof v === "string" && v.trim() !== "",
            ) as Array<[string, string]>,
          )
        : {};
  } catch {
    cache = {};
  }
  return cache;
}

function write(next: CookieEntries) {
  cache = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // localStorage penuh/diblokir: tetap berlaku di memori sampai halaman ditutup.
  }
  listeners.forEach((l) => l());
}

export function readCookieEntries(): CookieEntries {
  return read();
}

export function saveCookieEntry(domain: string, value: string): string {
  const d = normalizeDomain(domain);
  if (!d) throw new Error("Domain tidak valid. Contoh: instagram.com");
  if (!value.trim()) throw new Error("Cookie masih kosong.");
  write({ ...read(), [d]: value.trim() });
  return d;
}

export function removeCookieEntry(domain: string) {
  const next = { ...read() };
  delete next[domain];
  write(next);
}

/** Cookie untuk URL: entri domain terpanjang yang cocok (host sama atau subdomainnya). */
export function cookiesForUrl(url: string): string | null {
  const host = hostOf(url);
  if (!host) return null;
  const entries = read();
  const match = Object.keys(entries)
    .filter((d) => host === d || host.endsWith(`.${d}`))
    .sort((a, b) => b.length - a.length)[0];
  return match ? entries[match] : null;
}

/** Menebak domain dari isi cookie (kolom domain Netscape atau field `domain` JSON). */
export function guessCookieDomain(text: string): string | null {
  const trimmed = text.trim();
  if (trimmed.startsWith("[")) {
    try {
      const arr = JSON.parse(trimmed) as Array<{ domain?: string }>;
      const found = arr.map((c) => normalizeDomain(c?.domain)).find(Boolean);
      return found ?? null;
    } catch {
      return null;
    }
  }
  for (const line of trimmed.split(/\r?\n/)) {
    const clean = line.replace(/^#HttpOnly_/, "");
    if (!clean || clean.startsWith("#")) continue;
    const cols = clean.split("\t");
    if (cols.length >= 7) {
      const d = normalizeDomain(cols[0]);
      if (d) return d.replace(/^www\./, "");
    }
  }
  return null;
}

/** Apakah cookie global lama baru saja dihapus (untuk pemberitahuan di Settings). */
function legacySnapshot(): boolean {
  read();
  return legacyDropped;
}

export function dismissLegacyNotice() {
  legacyDropped = false;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      cache = null;
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useCookieEntries(): CookieEntries {
  return useSyncExternalStore(subscribe, read, () => EMPTY);
}

export function useLegacyCookieNotice(): boolean {
  return useSyncExternalStore(subscribe, legacySnapshot, () => false);
}

/** Hanya untuk test. */
export function __resetCookieCache() {
  cache = null;
  legacyDropped = false;
}
