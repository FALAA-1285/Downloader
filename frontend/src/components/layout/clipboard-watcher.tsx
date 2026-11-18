"use client";

// Pantau clipboard (ala 1DM/IDM): saat jendela UMD kembali difokuskan dan clipboard berisi URL
// baru, tawarkan untuk menganalisisnya. Opt-in dari Settings karena browser akan meminta izin
// membaca clipboard; isi clipboard tidak pernah disimpan atau dikirim tanpa klik pengguna.

import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { ClipboardPaste, X } from "lucide-react";
import { checkUrl } from "@/lib/url";
import { Button } from "@/components/ui/button";

const PREF_KEY = "umd.clipboardWatch";
const SEEN_KEY = "umd.clipboard.lastSeen";
const listeners = new Set<() => void>();

function readPref(): boolean {
  try {
    return localStorage.getItem(PREF_KEY) === "1";
  } catch {
    return false;
  }
}

export function setClipboardWatch(enabled: boolean) {
  try {
    if (enabled) localStorage.setItem(PREF_KEY, "1");
    else localStorage.removeItem(PREF_KEY);
  } catch {
    // localStorage diblokir: preferensi tidak tersimpan.
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useClipboardWatchPref(): boolean {
  return useSyncExternalStore(subscribe, readPref, () => false);
}

function wasSeen(url: string): boolean {
  try {
    return sessionStorage.getItem(SEEN_KEY) === url;
  } catch {
    return false;
  }
}

function markSeen(url: string) {
  try {
    sessionStorage.setItem(SEEN_KEY, url);
  } catch {
    // abaikan
  }
}

export function ClipboardWatcher() {
  const enabled = useClipboardWatchPref();
  const router = useRouter();
  const [found, setFound] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function check() {
      if (document.visibilityState !== "visible" || !document.hasFocus()) return;
      let text = "";
      try {
        text = (await navigator.clipboard.readText()).trim();
      } catch {
        return; // izin ditolak atau clipboard bukan teks
      }
      if (cancelled || !text || text.length > 2048 || /\s/.test(text)) return;
      const res = checkUrl(text);
      if (!res.ok || wasSeen(res.url)) return;
      // URL yang sedang dianalisis tidak perlu ditawarkan lagi.
      if (new URLSearchParams(window.location.search).get("url") === res.url) return;
      setFound(res.url);
    }

    void check();
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
    };
  }, [enabled]);

  if (!enabled || !found) return null;

  const dismiss = () => {
    markSeen(found);
    setFound(null);
  };

  return (
    <div
      role="status"
      className="fixed bottom-5 left-5 z-40 w-[min(380px,calc(100vw-2.5rem))] rounded-xl border border-line-strong bg-bg p-3 shadow-window"
    >
      <div className="flex items-start gap-2.5">
        <ClipboardPaste className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-ink">Tautan terdeteksi di clipboard</p>
          <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground" title={found}>
            {found}
          </p>
          <div className="mt-2 flex gap-2">
            <Button
              size="sm"
              onClick={() => {
                markSeen(found);
                setFound(null);
                router.push(`/analyze?${new URLSearchParams({ url: found }).toString()}`);
              }}
            >
              Analisis
            </Button>
            <Button size="sm" variant="ghost" onClick={dismiss}>
              Abaikan
            </Button>
          </div>
        </div>
        <button type="button" onClick={dismiss} aria-label="Tutup" className="text-muted-foreground hover:text-ink">
          <X className="size-4" />
        </button>
      </div>
    </div>
  );
}
