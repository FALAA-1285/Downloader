"use client";

import { useSyncExternalStore } from "react";

// Jam bersama untuk label waktu relatif ("2 menit lalu"), diperbarui setiap 15 detik.
let now = 0;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

function subscribe(l: () => void) {
  listeners.add(l);
  if (!timer) {
    timer = setInterval(() => {
      now = Date.now();
      listeners.forEach((f) => f());
    }, 15_000);
  }
  return () => {
    listeners.delete(l);
    if (listeners.size === 0 && timer) {
      clearInterval(timer);
      timer = null;
    }
  };
}

function getSnapshot() {
  if (!now) now = Date.now();
  return now;
}

export function useNow(): number {
  return useSyncExternalStore(subscribe, getSnapshot, () => 0);
}
