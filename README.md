# Universal Media Downloader

Aplikasi web pribadi untuk menganalisis URL, melihat media yang tersedia, lalu mengunduh
yang memang dapat diakses secara sah. Rujukan PRD (§) di kode dan dokumen ini mengacu pada dokumen PRD internal yang tidak disertakan di repo.

| Folder | Isi |
| --- | --- |
| `frondend/` | Next.js 16 + TypeScript + Tailwind CSS |
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
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Frontend — terminal 2
cd frondend
npm install
npm run dev                     # http://localhost:3000
```

Frontend membaca alamat backend dari `frondend/.env.local`:

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
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
cd backend
uv run pytest          # unit + integration test (SQLite, HTTP sumber di-mock, tanpa jaringan)
uv run ruff check .
```

## API (`/api/v1`)

| Method | Endpoint | Fungsi |
| --- | --- | --- |
| POST | `/analyze` | Menganalisis URL. Body: `{"url", "media_types": []}` |
| GET | `/jobs/{id}` | Ringkasan hasil analisis |
| GET | `/jobs/{id}/media` | Hasil analisis lengkap yang tersimpan |
| POST | `/downloads` | Membuat pekerjaan unduhan. Body: `{"analysis_id", "media_ids": [], "subtitle_format": "original"\|"srt"}` |
| GET | `/downloads/{id}` | Status dan progres |
| POST | `/downloads/{id}/retry` | Mengulang pekerjaan yang gagal |
| GET | `/downloads/{id}/file` | Mengunduh file hasil |
| GET | `/history` | Riwayat (`?status=&media_type=&q=`) |
| DELETE | `/history/{id}` | Menghapus riwayat beserta file sementaranya |
| GET | `/health`, `/adapters`, `/config` | Status sistem, adapter, dan konfigurasi |

Error selalu berbentuk `{"detail": {"code": "...", "message": "..."}}` dengan pesan berbahasa Indonesia.

Tiga endpoint tidak ada di tabel PRD §12 dan ditambahkan untuk kebutuhan frontend:
`/downloads/{id}/retry`, `/adapters`, dan `/config`. Tabel `analyses` juga ditambahkan (di luar
PRD §11) supaya pekerjaan unduhan hanya bisa dibuat dari media yang benar-benar ditemukan server,
bukan dari URL sembarang yang dikirim klien.

## Keamanan (NFR-01)

- **SSRF:** hanya http/https dan port dalam allowlist. Alamat lokal, privat, link-local, multicast,
  dan metadata cloud diblokir. IP tujuan diperiksa ulang **setiap kali koneksi TCP dibuka**,
  termasuk di setiap redirect, sehingga DNS rebinding tidak bisa lolos.
- Tidak memakai proxy dari environment, tidak meneruskan cookie atau kredensial ke domain lain.
- Batas ukuran halaman, ukuran file, total storage, timeout koneksi/baca/total, dan rate limit.
- Isi file divalidasi dengan magic bytes (bukan ekstensi atau header sumber). File di luar
  allowlist, termasuk executable, ditolak. Video/audio dicek dengan `ffprobe` bila tersedia.
- Nama file di disk dibuat server (UUID). File disimpan di luar web root dan hanya disajikan
  lewat `/downloads/{id}/file` sebagai attachment, dengan `nosniff` dan CSP sandbox.
- API hanya melayani klien dari `ALLOWED_CLIENT_NETWORKS` dan Host dari `ALLOWED_HOSTS`.
- File kedaluwarsa, file sementara yang tertinggal, pekerjaan macet, dan analisis lama
  dibersihkan otomatis setiap `CLEANUP_INTERVAL_SECONDS`.

Tidak ada bypass DRM, paywall, login, atau akun privat. Adapter YouTube, Instagram, TikTok, dan X
hanya mengenali domainnya dan berstatus *evaluasi* sampai ada integrasi resmi yang berizin.
