import Link from "next/link";
import { IS_DEMO } from "@/services/api";

export function DemoBanner() {
  if (!IS_DEMO) return null;
  return (
    <div className="border-b border-line bg-surface">
      <p className="frame border-x-0 px-4 py-2 text-center text-[13px] text-ink-2 sm:px-6 lg:border-x">
        <span className="mr-1.5 inline-block rounded bg-brand-soft px-1.5 py-px text-xs font-medium text-brand">Mode demo</span>
        Hasil analisis dan unduhan adalah data contoh. Set <code className="font-mono text-[12px] text-ink">NEXT_PUBLIC_API_BASE_URL</code> untuk
        menghubungkan backend.{" "}
        <Link href="/settings" className="font-medium text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink">
          Lihat pengaturan
        </Link>
      </p>
    </div>
  );
}
