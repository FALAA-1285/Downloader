"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, Moon, Sun, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useJobs } from "@/services/jobs-store";
import { setTheme, useResolvedTheme } from "./theme";
import { Logo } from "./logo";

const NAV = [
  { href: "/", label: "Home" },
  { href: "/downloads", label: "Downloads" },
  { href: "/history", label: "History" },
  { href: "/settings", label: "Settings" },
] as const;

export function SiteHeader() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const theme = useResolvedTheme();
  const jobs = useJobs();
  const active = jobs.filter((j) => j.status === "pending" || j.status === "processing" || j.status === "downloading").length;

  const isCurrent = (href: string) => (href === "/" ? pathname === "/" || pathname.startsWith("/analyze") : pathname.startsWith(href));

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg/80 backdrop-blur-md">
      <div className="frame flex h-14 items-center justify-between gap-4 border-x-0 px-4 sm:px-6 lg:border-x">
        <Link href="/" className="flex items-center gap-2.5 rounded-md" onClick={() => setOpen(false)}>
          <Logo />
          <span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Media Downloader</span>
        </Link>

        <nav className="hidden items-center gap-0.5 md:flex" aria-label="Navigasi utama">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isCurrent(item.href) ? "page" : undefined}
              className={cn(
                "relative flex h-8 items-center gap-1.5 rounded-md px-3 text-sm transition-colors",
                isCurrent(item.href) ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:text-ink",
              )}
            >
              {item.label}
              {item.href === "/downloads" && active > 0 && (
                <span className="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-brand px-1 text-[11px] font-semibold text-white">
                  {active}
                </span>
              )}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? "Gunakan tema terang" : "Gunakan tema gelap"}
          >
            {theme === "dark" ? <Sun /> : <Moon />}
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="md:hidden"
            aria-label={open ? "Tutup menu" : "Buka menu"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X /> : <Menu />}
          </Button>
        </div>
      </div>

      {open && (
        <nav className="border-t border-line bg-bg px-4 py-2 md:hidden" aria-label="Navigasi seluler">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              aria-current={isCurrent(item.href) ? "page" : undefined}
              className={cn(
                "flex h-10 items-center justify-between rounded-md px-3 text-[15px]",
                isCurrent(item.href) ? "bg-surface-2 font-medium text-ink" : "text-ink-2",
              )}
            >
              {item.label}
              {item.href === "/downloads" && active > 0 && <span className="text-xs text-brand">{active} aktif</span>}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}
