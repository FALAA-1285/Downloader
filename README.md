# Universal Media Downloader

Aplikasi web pribadi untuk menganalisis URL, melihat media yang tersedia, lalu mengunduh
yang memang dapat diakses secara sah. Rujukan PRD (§) di kode dan dokumen ini mengacu pada dokumen PRD internal yang tidak disertakan di repo.

| Folder | Isi |
| --- | --- |
| `frontend/` | Next.js 16 + TypeScript + Tailwind CSS + shadcn/ui (kode di `frontend/src/`) |
| `backend/` | FastAPI, HTTPX, BeautifulSoup4, trafilatura, SQLAlchemy, Alembic, RQ |
| `storage/` | File sementara hasil unduhan (tidak disajikan langsung) |

## Menjalankan secara lokal (Windows / Laragon)

Kebutuhan: Python 3.13+ dengan [uv](https://docs.astral.sh/uv/), Node.js, PostgreSQL (Laragon), FFmpeg (opsional, untuk validasi video/audio).

```bash
cp .env.example .env            # sesuaikan DATABASE_URL bila perlu

# Backend — terminal 1
cd backend
uv sync
uv run alembic upgrade head     # buat/perbarui tabel
uv run python -m app            # host/port dari APP_HOST/APP_PORT (default 127.0.0.1:8000)

# Frontend — terminal 2
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

Frontend membaca alamat backend dari `frontend/.env.local`:

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
# Opsional, harus sama dengan API_TOKEN di backend:
NEXT_PUBLIC_API_TOKEN=
```

Kosongkan atau hapus variabel itu untuk kembali ke **mode demo** (data contoh, tanpa backend).

Mode lokal memakai `QUEUE_BACKEND=inline`: unduhan diproses di dalam proses API karena worker
RQ tidak dapat berjalan di Windows. Dokumentasi API interaktif tersedia di http://localhost:8000/docs.

## Menjalankan dengan Docker Compose

Menjalankan seluruh layanan PRD §15.1: `frontend`, `backend`, `worker` (RQ), `redis`, `postgres`.

```bash
cp .env.example .env            # ganti POSTGRES_PASSWORD
docker compose up --build
```

Frontend di http://localhost:3000, API di http://localhost:8000. Semua port hanya dibuka di
`127.0.0.1`. Migrasi database dijalankan otomatis saat container backend mulai.

## Test

```bash
# Backend
cd backend
uv run pytest                          # unit + integration (SQLite, HTTP sumber di-mock, tanpa jaringan)
uv run pytest --cov                    # dengan laporan coverage
uv run ruff check . && uv run ruff format --check .
uvx pip-audit -r requirements.txt      # CVE dependency (butuh internet)

# Integration test terhadap PostgreSQL sungguhan (database khusus test, isinya dihapus):
TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5432/media_downloader_test uv run pytest -m postgres

# Frontend
cd frontend
npm test && npx tsc --noEmit && npm run lint
npm audit
```

Test `ffprobe` dilewati otomatis jika FFmpeg tidak terpasang.

## API (`/api/v1`)

| Method | Endpoint | Fungsi |
| --- | --- | --- |
| POST | `/analyze` | Menganalisis URL. Body: `{"url", "media_types": [], "cookies"?, "headers"?}` |
| GET | `/jobs/{id}` | Ringkasan hasil analisis |
| GET | `/jobs/{id}/media` | Hasil analisis lengkap yang tersimpan |
| POST | `/downloads` | Membuat pekerjaan unduhan. Body: `{"analysis_id", "media_ids": [], "subtitle_format": "original"\|"srt", "scheduled_at"?, "max_speed_kbps"?}` |
| GET | `/downloads/{id}` | Status dan progres |
| POST | `/downloads/status` | Status banyak job sekaligus. Body: `{"ids": []}` |
| POST | `/downloads/{id}/pause` | Menjeda job antre/berjalan (file parsial disimpan) |
| POST | `/downloads/{id}/resume` | Melanjutkan job yang dijeda, atau memulai job terjadwal sekarang |
| POST | `/downloads/{id}/cancel` | Membatalkan job dan menghapus file parsialnya |
| POST | `/downloads/{id}/retry` | Mengulang pekerjaan yang gagal atau dibatalkan |
| GET | `/downloads/{id}/file` | Mengunduh file hasil |
| POST | `/downloads/zip` | Membuat ZIP dari beberapa job selesai. Body: `{"job_ids": [], "zip_name"?}` → `{id, filename, …}` |
| GET | `/downloads/zip/{id}` | Mengunduh ZIP tersebut (sekali pakai, `?name=`) |
| GET | `/history` | Riwayat (`?status=&media_type=&q=`) |
| DELETE | `/history/{id}` | Menghapus riwayat beserta file sementaranya |
| GET | `/health`, `/adapters`, `/config` | Status sistem, adapter, dan konfigurasi |

Error selalu berbentuk `{"detail": {"code": "...", "message": "..."}}` dengan pesan berbahasa Indonesia.

Setiap `POST`/`DELETE` wajib membawa header `X-UMD-Client` (frontend mengirimnya otomatis). Header kustom
ini memaksa preflight CORS sehingga situs lain tidak bisa memicu aksi ke API lokal. Bila `API_TOKEN`
diisi, semua endpoint kecuali `/health` juga wajib membawa `Authorization: Bearer <token>`.

Tiga endpoint tidak ada di tabel PRD §12 dan ditambahkan untuk kebutuhan frontend:
`/downloads/{id}/retry`, `/adapters`, dan `/config`. Tabel `analyses` juga ditambahkan (di luar
PRD §11) supaya pekerjaan unduhan hanya bisa dibuat dari media yang benar-benar ditemukan server,
bukan dari URL sembarang yang dikirim klien.

## Fitur unduhan ala IDM/1DM

- **Multi-koneksi:** file ≥ `MULTI_CONNECTION_MIN_MB` dari server yang mendukung `Range` dipecah ke
  `DOWNLOAD_CONNECTIONS` koneksi paralel. Status segmen disimpan sehingga jeda/retry melanjutkan setiap
  segmen dari posisi terakhirnya; server tanpa `Range` otomatis memakai satu koneksi.
- **Batas kecepatan & jadwal:** per unduhan dari panel ⚙ di bilah pilihan (atau `max_speed_kbps` /
  `scheduled_at` di API). Job terjadwal berstatus `scheduled` dan diantrekan oleh penjadwal di proses API.
- **Kecepatan & sisa waktu** ditampilkan di halaman Downloads.
- **Pantau clipboard** (opt-in di Settings): tautan yang disalin ditawarkan untuk dianalisis.
- **Ekstensi:** tombol "Unduh video ini" di pemutar video, menu klik kanan, dan pengalihan unduhan browser
  (opt-in). Lihat `extension/README.md`.

## Keamanan (NFR-01)

- **SSRF:** hanya http/https dan port dalam allowlist. Alamat lokal, privat, link-local, multicast,
  dan metadata cloud diblokir. IP tujuan diperiksa ulang **setiap kali koneksi TCP dibuka**,
  termasuk di setiap redirect, sehingga DNS rebinding tidak bisa lolos.
- **yt-dlp dan Chromium (Playwright)** membuka koneksinya sendiri, jadi semua lalu lintas keduanya
  dilewatkan proxy penjaga lokal (`app/core/guard_proxy.py`) yang menerapkan aturan yang sama per
  koneksi (CONNECT/HTTP), termasuk URL segmen di dalam manifest HLS/DASH dan sub-resource halaman.
- **Cookie per domain:** cookie pengguna (cookies.txt, JSON, atau `nama=nilai`) diikat ke domainnya
  dan hanya dikirim ke host yang cocok. `Cookie`/`Authorization` dibuang saat redirect pindah host.
  Cookie tidak disimpan di hasil analisis dan dihapus dari job begitu job selesai/dibatalkan.
- Tidak memakai proxy dari environment.
- Batas ukuran halaman, ukuran file, total storage, timeout koneksi/baca/total, dan rate limit.
- Isi file divalidasi dengan magic bytes (bukan ekstensi atau header sumber). File di luar
  allowlist, termasuk executable, ditolak. Video/audio dicek dengan `ffprobe` bila tersedia.
- Nama file di disk dibuat server (UUID). File disimpan di luar web root dan hanya disajikan
  lewat `/downloads/{id}/file` sebagai attachment, dengan `nosniff` dan CSP sandbox.
- API hanya melayani klien dari `ALLOWED_CLIENT_NETWORKS` (default: hanya localhost) dan Host dari
  `ALLOWED_HOSTS`. Jangan membuka API ke LAN tanpa `API_TOKEN`. Ukuran body request dibatasi
  (`MAX_REQUEST_BODY_KB`).
- `ffprobe` dijalankan dengan `-protocol_whitelist file` dan `-format_whitelist` sesuai jenis file,
  sehingga tidak bisa membuka URL atau playlist yang dirujuk isi file.
- URL pratinjau yang mengarah ke jaringan internal dibuang di backend; frontend memuat pratinjau dengan
  `referrerPolicy="no-referrer"` dan CSP.
- Query string (yang bisa berisi token) tidak disimpan di log maupun riwayat setelah unduhan selesai.
- File kedaluwarsa, file sementara yang tertinggal, pekerjaan macet, dan analisis lama
  dibersihkan otomatis setiap `CLEANUP_INTERVAL_SECONDS`. Job antre yang tidak diambil worker dalam
  `STALE_PENDING_SECONDS` ditandai gagal, dan job gagal masuk antrean langsung ditandai gagal.

Tidak ada bypass DRM, paywall, login, atau akun privat. Adapter YouTube, Instagram, TikTok, dan X
hanya mengenali domainnya dan berstatus *evaluasi* sampai ada integrasi resmi yang berizin.
