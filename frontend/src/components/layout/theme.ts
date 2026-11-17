"use client";

import { useSyncExternalStore } from "react";

export type ThemePref = "light" | "dark" | "system";
const KEY = "umd.theme";
const listeners = new Set<() => void>();

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function apply(pref: ThemePref) {
  const dark = pref === "dark" || (pref === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function setTheme(pref: ThemePref) {
  try {
    localStorage.setItem(KEY, pref);
  } catch {}
  apply(pref);
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  const mq = matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    if (read() === "system") apply("system");
    l();
  };
  mq.addEventListener("change", onChange);
  return () => {
    listeners.delete(l);
    mq.removeEventListener("change", onChange);
  };
}

export function useThemePref(): ThemePref {
  return useSyncExternalStore(subscribe, read, () => "system");
}

/** Tema yang benar-benar aktif (light/dark). */
export function useResolvedTheme(): "light" | "dark" {
  return useSyncExternalStore(
    subscribe,
    () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light"),
    () => "light",
  );
}
