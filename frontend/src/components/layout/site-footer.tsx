import Link from "next/link";
import { Logo } from "./logo";

export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="frame flex flex-col gap-6 px-5 py-10 sm:flex-row sm:items-start sm:justify-between sm:px-10">
        <div className="max-w-sm">
          <div className="flex items-center gap-2.5">
            <Logo size={20} />
            <span className="text-sm font-semibold text-ink">Universal Media Downloader</span>
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">
            Aplikasi pribadi untuk localhost atau jaringan tepercaya. Hanya mengunduh konten yang dapat diakses secara sah —
            tanpa bypass DRM, paywall, atau login.
          </p>
        </div>
        <nav className="grid grid-cols-2 gap-x-12 gap-y-2 text-[13px]" aria-label="Tautan footer">
          <Link className="text-ink-2 hover:text-ink" href="/">Analisis URL</Link>
          <Link className="text-ink-2 hover:text-ink" href="/history">Riwayat</Link>
          <Link className="text-ink-2 hover:text-ink" href="/downloads">Unduhan</Link>
          <Link className="text-ink-2 hover:text-ink" href="/settings">Pengaturan</Link>
        </nav>
      </div>
    </footer>
  );
}
