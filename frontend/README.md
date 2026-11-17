# Frontend — Universal Media Downloader

Next.js 16 (App Router) + TypeScript + Tailwind CSS 4 + [shadcn/ui](https://ui.shadcn.com) (Radix).
Panduan setup lengkap, arsitektur, dan API ada di [README root](../README.md).

## Menjalankan

```bash
npm install
npm run dev        # http://localhost:3000
```

Variabel di `.env.local`:

| Variabel | Fungsi |
| --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | Alamat backend, mis. `http://localhost:8000`. Kosong = **mode demo** (data contoh). |
| `NEXT_PUBLIC_API_TOKEN` | Opsional, harus sama dengan `API_TOKEN` backend. Ikut ter-bundle ke browser. |

## Perintah

```bash
npm run lint       # ESLint
npx tsc --noEmit   # type check
npm test           # Vitest (unit + komponen)
npm run build      # build produksi (output standalone untuk Docker)
```

## Struktur

```text
src/
├── app/                 # route: /, /analyze, /downloads, /history, /settings
├── components/
│   ├── ui/              # komponen shadcn/ui + primitives.tsx (TypeTag, StatusPill, ...)
│   ├── downloader/      # form URL, hero, daftar sumber
│   ├── media-preview/   # hasil analisis: tab, grid gambar, tabel media, teks
│   ├── download-list/   # downloads, history, baris job
│   └── layout/          # header, footer, tema, settings
├── hooks/  lib/  services/  types/
```

Menambah komponen shadcn: `npx shadcn@latest add <nama>`. Token warna shadcn (primary, muted, accent, ...)
dipetakan ke palet aplikasi di `src/app/globals.css`; warna biru aplikasi bernama `brand`.
