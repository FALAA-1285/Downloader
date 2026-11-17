import { ShieldCheck } from "lucide-react";
import { UrlForm } from "@/components/downloader/url-form";
import { HeroPreview } from "@/components/downloader/hero-preview";
import { RecentDownloads } from "@/components/download-list/recent-downloads";
import { SupportedSources } from "@/components/downloader/supported-sources";
import { cn } from "@/lib/utils";

const STEPS = [
  { title: "Tempel URL", body: "Alamat diperiksa dulu: hanya http/https, dan alamat lokal atau jaringan internal ditolak." },
  { title: "Analisis", body: "Sumber dikenali, halaman diambil dengan batas waktu dan ukuran, lalu media di dalamnya didata." },
  { title: "Pilih", body: "Lihat pratinjau, format, dan ukuran. Item yang tidak bisa diunduh diberi alasan yang jelas." },
  { title: "Unduh", body: "Setiap item menjadi pekerjaan dengan status dan progres. File disimpan sementara lalu dibersihkan." },
];

export default function HomePage() {
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="dotgrid pointer-events-none absolute inset-x-0 top-0 h-[520px] opacity-60 [mask-image:linear-gradient(to_bottom,black,transparent)]" aria-hidden />
        <div className="frame relative px-5 pb-16 pt-16 sm:px-10 sm:pt-24">
          <div className="mx-auto max-w-[720px] text-center">
            <h1 className="font-display text-[40px] font-semibold leading-[1.04] tracking-[-0.035em] text-ink sm:text-[60px]">
              Tempel satu URL. Lihat semua media di dalamnya.
            </h1>
            <p className="mx-auto mt-5 max-w-[540px] text-[16px] leading-relaxed text-ink-2 sm:text-[17px]">
              Gambar, video langsung, subtitle, dan teks artikel dari halaman web — didata, dipratinjau, lalu diunduh yang
              memang boleh diunduh.
            </p>
          </div>

          <div className="mx-auto mt-10 max-w-[680px]">
            <UrlForm />
          </div>

          <div className="mt-16 sm:mt-20">
            <HeroPreview />
          </div>
        </div>
      </section>

      {/* Alur */}
      <section className="border-t border-line">
        <div className="frame px-5 py-16 sm:px-10 sm:py-20">
          <h2 className="max-w-md font-display text-[28px] font-semibold leading-tight tracking-[-0.025em] text-ink sm:text-[32px]">
            Empat langkah, tidak lebih.
          </h2>
          <ol className="mt-10 grid overflow-hidden rounded-xl border border-line sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li
                key={s.title}
                className={cn(
                  "bg-bg p-6",
                  i > 0 && "border-t border-line sm:border-t-0",
                  i % 2 === 1 && "sm:border-l",
                  i >= 2 && "sm:border-t lg:border-t-0",
                  i > 0 && "lg:border-l",
                )}
              >
                <span className="grid size-7 place-items-center rounded-full border border-line-strong text-[13px] font-semibold tabular-nums text-ink">
                  {i + 1}
                </span>
                <h3 className="mt-5 text-[15px] font-semibold text-ink">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Sumber & batasan */}
      <section className="border-t border-line">
        <div className="frame grid gap-12 px-5 py-16 sm:px-10 sm:py-20 lg:grid-cols-[1fr_1.15fr] lg:gap-16">
          <div>
            <h2 className="font-display text-[28px] font-semibold leading-tight tracking-[-0.025em] text-ink sm:text-[32px]">
              Jujur soal apa yang didukung.
            </h2>
            <p className="mt-4 max-w-md text-[15px] leading-relaxed text-ink-2">
              Website umum dianalisis lewat struktur HTML-nya. Platform besar hanya akan didukung jika ada jalur integrasi
              resmi yang berizin — dikenali bukan berarti bisa diunduh.
            </p>
            <ul className="mt-8 space-y-3.5 text-sm text-ink-2">
              {[
                "Tidak melewati DRM, paywall, login, atau akun privat.",
                "Tidak meneruskan cookie atau kredensial Anda ke situs lain.",
                "File disimpan sementara di server lokal, lalu dihapus otomatis.",
              ].map((t) => (
                <li key={t} className="flex gap-2.5">
                  <ShieldCheck className="mt-0.5 size-4 shrink-0 text-ink" aria-hidden />
                  {t}
                </li>
              ))}
            </ul>
          </div>

          <SupportedSources />
        </div>
      </section>

      {/* Unduhan terbaru */}
      <section className="border-t border-line">
        <div className="frame px-5 py-16 sm:px-10">
          <RecentDownloads />
        </div>
      </section>
    </>
  );
}
