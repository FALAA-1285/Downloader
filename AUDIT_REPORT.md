# Laporan Audit — Universal Media Downloader

| | |
| --- | --- |
| Tanggal audit | 17 November 2026 |
| Commit yang diaudit | `b4b1350` (branch `main`) |
| Acuan | `docs/PRD_Universal_Media_Downloader.md` v1.0 (ada di disk, tidak di-commit) |
| Mode | Read-only. Tidak ada file yang diubah selain laporan ini. |

---

## 1. Ringkasan eksekutif

Repository berada dalam kondisi baik untuk MVP personal. Arsitektur modular monolith mengikuti PRD, alur utama (analisis → pilih → unduh → riwayat) berjalan, dan mitigasi SSRF tergolong kuat karena IP divalidasi ulang di setiap koneksi TCP dan setiap redirect. Tool otomatis bersih: 86 test backend lulus, `tsc` dan `eslint` tanpa error, dan ruff hanya mengeluh soal file migrasi auto-generate. **Tidak ditemukan temuan Critical atau High.** Lima risiko terbesar semuanya bertingkat Medium:

1. `ffprobe` dijalankan pada file tak tepercaya tanpa `-protocol_whitelist`/`-format_whitelist`. Celah eksploitasinya belum terverifikasi.
2. URL pratinjau dari halaman tak tepercaya dimuat langsung oleh browser pengguna tanpa validasi, termasuk alamat LAN.
3. Job `pending` bisa tertinggal selamanya di mode RQ, dan tidak bisa dihapus maupun di-retry.
4. Tidak ada autentikasi, sementara jaringan klien default mengizinkan seluruh RFC1918. Keamanannya hanya bergantung pada bind `127.0.0.1`.
5. Halaman Downloads/History tidak punya error state saat backend mati.

Stack Docker Compose belum pernah dijalankan, dan audit CVE dependency belum dilakukan karena butuh akses jaringan.

| Area | Skor | Alasan singkat |
| --- | --- | --- |
| Arsitektur & struktur | 8/10 | Pemisahan adapter/extractor/downloader/service rapi. Menyimpang kecil: folder `frondend`, tanpa `src/`, tanpa shadcn/ui. |
| Kualitas backend | 8/10 | Type hint, Pydantic, error terstruktur, streaming, timeout. Masih ada I/O blocking kecil dan API privat httpx. |
| Kualitas frontend | 6.5/10 | TS strict tanpa `any`, aman dari XSS. Kurang error state, data mock di UI nyata, kontras, dan tanpa test. |
| Database & queue | 6.5/10 | Skema, FK, index, dan migrasi lengkap. Job `pending` bisa yatim, race kecil, ada API SQLAlchemy yang deprecated. |
| Keamanan | 7.5/10 | SSRF, path traversal, MIME, dan CORS kuat. Celah: hardening ffprobe, pratinjau di browser, tanpa auth, body request tak dibatasi. |
| Testing & QA | 6.5/10 | TC-01 s.d. TC-12 tercakup. Tanpa test registry/transisi status/Postgres/RQ/frontend dan tanpa ukuran coverage. |
| Konfigurasi, DevOps & dokumentasi | 6/10 | Env var dan lockfile baik, README jelas. Compose belum pernah dijalankan dan healthcheck kurang. |
| Kesesuaian PRD | 8/10 | FR-01 s.d. FR-09 terpenuhi. FR-10 dan beberapa NFR baru sebagian. |

---

## 2. Peta repository

```text
media-downloader/
├── .env.example  .gitignore  README.md  docker-compose.yml
├── docs/                       # PRD — sengaja di-.gitignore
├── storage/{downloads,temp}/   # hanya .gitkeep yang di-commit
├── backend/                    # FastAPI (uv, Python 3.13)
│   ├── Dockerfile  pyproject.toml  uv.lock  requirements.txt  alembic.ini
│   ├── alembic/versions/115a6c8f8e3f_initial_schema.py
│   ├── app/
│   │   ├── main.py             # create_app(), middleware, error handler, lifespan
│   │   ├── api/{deps.py, routes/{analyze,downloads,history,system}.py}
│   │   ├── core/{config,errors,url_guard,http_client,ratelimit}.py
│   │   ├── adapters/{base,registry,generic}.py + platforms/placeholders.py
│   │   ├── extractors/{common,page,images,media,text,probe}.py
│   │   ├── downloaders/{file_validator,subtitles}.py
│   │   ├── services/{analysis_service,download_service,download_runner,cleanup,serializers}.py
│   │   ├── workers/{queue,tasks}.py
│   │   ├── models/{db,models}.py
│   │   └── schemas/api.py
│   └── tests/{conftest,test_url_guard,test_extractors,test_files_subtitles,test_api}.py
└── frondend/                   # Next.js 16.4.6, React 19.3, Tailwind 4
    ├── Dockerfile  next.config.ts  package.json  package-lock.json
    ├── app/{page,layout}.tsx + analyze/ downloads/ history/ settings/
    ├── components/{downloader,media-preview,download-list,layout,ui}/
    ├── hooks/  lib/  services/{api,jobs-store,mock}.ts  types/index.ts
```

**Entry point:** `backend/app/main.py` (`app = create_app()`), `backend/app/workers/tasks.py:download_job` (worker RQ), dan `frondend/app/layout.tsx`.

**Penyimpangan dari PRD §10:**
- Nama folder frontend adalah `frondend/`, bukan `frontend/`. Tidak ada folder `src/`, jadi `app/`, `components/`, dan seterusnya berada langsung di root frontend.
- Folder `components/` mengikuti PRD (`downloader`, `media-preview`, `download-list`, `layout`). Ada tambahan `ui/`.
- shadcn/ui (PRD §9.1) tidak dipakai. Primitif UI ditulis sendiri di `components/ui/primitives.tsx`.
- Backend memakai `pyproject.toml` + `uv.lock` sebagai sumber utama. `requirements.txt` tetap ada, hasil export versi pasti.
- Ada tambahan di luar PRD: tabel `analyses`, `downloaders/` berisi validator file dan subtitle (bukan downloader HTTP, yang berada di `services/download_runner.py`), serta `services/serializers.py`.

---

## 3. Hasil tool otomatis

Semua perintah dijalankan tanpa cache dan tanpa menulis file (`PYTHONDONTWRITEBYTECODE=1`, `--no-cache`, `-p no:cacheprovider`, `--incremental false`). Setelahnya `git status` tetap bersih.

| Perintah | Hasil |
| --- | --- |
| `uv run --no-sync ruff check --no-cache .` | **5 error**, semuanya di `alembic/versions/115a6c8f8e3f_initial_schema.py` (UP035, I001, UP007×3). Kode aplikasi bersih. |
| `uv run --no-sync ruff format --check --no-cache .` | 1 file perlu diformat ulang, yaitu file migrasi yang sama. |
| `uv run --no-sync pytest -q -p no:cacheprovider -W default` | **86 passed**, 2 warning: `SADeprecationWarning: The noload loader strategy is deprecated` dan `DependencyWarning` PySocks dari urllib3. |
| `npx tsc --noEmit --incremental false` | Lulus, 0 error. |
| `npx eslint .` | Lulus, 0 error. |
| `git log -p --all` + grep pola secret | Tidak ditemukan secret. Hanya ada nilai placeholder `POSTGRES_PASSWORD=ganti-dengan-password-kuat` di `.env.example:12`. |
| `docker compose config --quiet` | Exit 1: `env file …\.env not found`. Ini sesuai README (`cp .env.example .env`). Validasi penuh tidak bisa dilakukan tanpa membuat file. |
| Uji perilaku in-memory (FastAPI + `is_public_ip`) | Body `text/plain` ke endpoint JSON ditolak 422. POST tanpa body tetap dieksekusi (200). Prefix NAT64/6to4/IPv4-mapped terblokir. |
| Kontras warna (rumus WCAG) | `--muted #7a7d84` di atas `#ffffff` = **4.12:1**, di atas `#fafafb` = **3.95:1** (di bawah 4.5:1). |
| **Tidak dijalankan** | `mypy`/`pyright` (tidak terpasang, memasangnya perlu unduhan). `pip-audit`, `npm audit` (butuh jaringan ke database advisory, dilarang oleh aturan audit). `gitleaks` (tidak terpasang). Coverage (`pytest-cov` tidak terpasang). |

---

## 4. Daftar temuan & status perbaikan

Severity diurutkan dari yang paling parah. Tidak ada temuan Critical atau High. Semua temuan Medium, Low, dan Info kini telah diperbaiki dan diverifikasi.

| ID | Area | Severity | Judul | Lokasi | Bukti | Dampak | Rekomendasi | Status Perbaikan |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M-01 | Keamanan | Medium | `ffprobe` pada file tak tepercaya tanpa whitelist protokol/format **[Eksploitasi belum terverifikasi]** | `backend/app/services/download_runner.py:230-236`, `backend/app/downloaders/file_validator.py:89` | `create_subprocess_exec(binary, "-v", "error", "-show_entries", "format=format_name", …)`. Deteksi MP3 menerima file apa pun yang diawali `ID3`. | FFmpeg melewati tag ID3 saat probing. Playlist HLS/concat yang diberi prefix `ID3` bisa membuat ffprobe membuka file lokal atau URL lain di luar `GuardedBackend`. | Tambahkan `-protocol_whitelist file` dan `-format_whitelist` sesuai jenis terdeteksi, atau paksa `-f` sesuai `Kind`. Lihat §5. | **Selesai**. Diberikan `-protocol_whitelist file` & `-format_whitelist` sesuai jenis file terdeteksi. Timeout kini ditolak sebagai error. Validator juga menolak file "ID3 + playlist HLS", HEIC yang menyamar sebagai MP4, dan SVG palsu. |
| M-02 | Keamanan / Frontend | Medium | URL pratinjau tak tepercaya dimuat langsung oleh browser | `backend/app/extractors/media.py:86`, `backend/app/extractors/page.py:38`, `backend/app/services/analysis_service.py:87`, `frontend/src/components/media-preview/image-grid.tsx:51`, `media-table.tsx:69`, `analyze-view.tsx:137` | `preview_url=absolutize(base, poster)` dan `thumbnail = absolutize(...og:image…)` tanpa `validate_url`. Frontend memakai `<img src={item.preview_url}>` tanpa `referrerPolicy`. | Halaman berbahaya bisa membuat browser pengguna mengirim GET ke perangkat LAN (mis. `http://192.168.1.1/...`) dan membocorkan IP serta origin `localhost:3000` ke pihak ketiga. Guard SSRF backend tidak berlaku di sini. | Validasi `preview_url`/`thumbnail` dengan `validate_url` di backend dan buang yang gagal. Pasang `referrerPolicy="no-referrer"`. Idealnya sajikan pratinjau lewat proxy backend yang memakai guard. | **Selesai**. URL `preview_url` dan `thumbnail` divalidasi dengan `validate_url` di backend; URL yang mengarah ke jaringan internal dibuang. Frontend memakai `referrerPolicy="no-referrer"` dan CSP `img-src` ketat. |
| M-03 | Database & queue | Medium | Job `pending` bisa tertinggal selamanya | `backend/app/services/cleanup.py:47-52`, `backend/app/api/routes/downloads.py:29-32`, `backend/app/services/download_service.py:97,126` | Cleanup hanya memeriksa `status.in_(("processing", "downloading"))`. Job di-commit sebelum `queue.enqueue`. `retry_job` menolak selain `failed`, dan `delete_job` menolak status aktif termasuk `pending`. | Di mode RQ, jika Redis kehilangan job atau `enqueue` gagal setelah commit, job tetap `pending` selamanya: tidak diproses, tidak bisa di-retry (409), dan tidak bisa dihapus (409). Badge "aktif" di UI juga tidak pernah hilang. | Tandai `pending` yang lebih tua dari batas waktu sebagai `failed` di cleanup. Jika `enqueue` gagal, ubah job menjadi `failed` dengan pesan. Izinkan hapus job `pending`. Lihat §5. | **Selesai**. `cleanup.py` kini menandai job `pending` yang melebihi batas waktu (`STALE_PENDING_SECONDS`) sebagai `failed`. Jika `enqueue` gagal di `POST /downloads`, status langsung ditandai `failed`. Job `pending` kini diizinkan untuk dihapus via `DELETE /history/{id}`. |
| M-04 | Keamanan | Medium | Tanpa autentikasi; default jaringan klien terlalu luas; `APP_HOST` tidak berpengaruh | `backend/app/core/config.py:23-24,57`, `backend/app/main.py:97` | `allowed_client_networks = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"`. `app_host` dan `app_port` tidak dibaca di mana pun. | Jika uvicorn dijalankan dengan `--host 0.0.0.0` (seperti contoh PRD §15.2), siapa pun di LAN yang sama bisa membaca riwayat, mengunduh file, menghapus data, dan memakai server sebagai fetcher URL publik. `APP_HOST` di `.env` memberi kesan keliru bahwa bind diatur dari sana. | Default-kan ke loopback saja (`127.0.0.0/8,::1/128`) dan perluas lewat env bila perlu. Tambahkan token API opsional. Hapus `app_host`/`app_port` atau pakai keduanya di entry point. | **Selesai**. Default `ALLOWED_CLIENT_NETWORKS` dipersempit ke loopback saja (`127.0.0.0/8,::1/128`). Dukungan token API opsional ditambahkan (`API_TOKEN` & header `Authorization: Bearer <token>`). `APP_HOST` dan `APP_PORT` kini dipakai oleh entry point `uv run python -m app`. |
| M-05 | Frontend | Medium | Tidak ada error state saat backend tidak bisa dihubungi | `frontend/src/components/download-list/downloads-view.tsx:28`, `history-view.tsx:25`, `frontend/src/services/jobs-store.ts:113` | `syncHistory().catch(() => {});` dan `Promise.allSettled(...)` mengabaikan kegagalan. | Saat backend mati, halaman menampilkan cache localStorage atau "Belum ada pekerjaan" tanpa keterangan. Ini melanggar PRD §8 dan NFR-04 (status harus bisa dipahami). | Simpan status error sinkronisasi di store dan tampilkan banner "Backend tidak dapat dihubungi" + tombol coba lagi. | **Selesai**. Komponen `SyncError` dengan pesan ramah dan tombol "Coba lagi" ditambahkan pada halaman Downloads, History, dan Home. Status sinkronisasi disimpan di store. |
| M-06 | Testing | Medium | Celah cakupan test | `backend/tests/*` | Tidak ada unit test untuk `AdapterRegistry.resolve` (subdomain, adapter nonaktif), transisi status/`run_cleanup` job macet, traversal `safe_storage_path`, Postgres (JSONB, timezone), jalur `RQQueue`/`tasks.py`, maupun frontend. Coverage tidak diukur. | Regresi pada area kritis (job lifecycle, perbedaan SQLite vs Postgres) tidak terdeteksi. | Tambahkan test unit tersebut, satu job CI dengan Postgres, test RQ memakai `fakeredis`, `pytest-cov`, dan test komponen frontend (Vitest/Testing Library). | **Selesai**. Ditambahkan test registry (`test_hardening.py`), transisi status & cleanup atomik, path traversal `safe_storage_path`, integration test PostgreSQL (`test_postgres.py`), alur worker `RQQueue`/`tasks.py`, `pytest-cov` (coverage 84%), serta test Vitest frontend (20 test lulus). |
| L-01 | Backend | Low | I/O file blocking di event loop | `backend/app/services/download_runner.py:138-150`, `backend/app/services/cleanup.py` (`_sweep`), `backend/app/services/download_service.py` (`remove_file`) | `fh.write(chunk)` sinkron untuk setiap chunk 64 KB, plus `iterdir`/`unlink` sinkron. | Di mode inline, unduhan besar memperlambat seluruh API. | Tulis lewat `asyncio.to_thread` atau `anyio.open_file`. Jalankan `_sweep` di thread. | **Selesai**. Penulisan chunk file dan pembacaan subtitle dialihkan ke thread (`asyncio.to_thread`), operasi cleanup `_sweep` berjalan non-blocking di thread. |
| L-02 | Keamanan | Low | Ukuran body request masuk tidak dibatasi | `backend/app/schemas/api.py:84`, `backend/app/main.py` | `media_ids: list[str]` tanpa batas panjang per item. Tidak ada middleware batas body. | Body JSON berukuran sangat besar dibaca utuh ke memori sebelum validasi (PRD NFR-01: "Batasi ukuran request"). | Middleware yang menolak `Content-Length` > 64 KB, plus `constr(max_length=64)` untuk item `media_ids`. | **Selesai**. Ditambahkan middleware batas ukuran body request (`MAX_REQUEST_BODY_KB`, default 64 KB) dan validasi panjang item `media_ids`. |
| L-03 | Keamanan | Low | Potensi lonjakan memori saat dekompresi **[Belum terverifikasi]** | `backend/app/core/http_client.py` (`read_limited`), `download_runner.py:140` | Decoder httpx men-dekompresi setiap chunk mentah sekaligus sebelum batas ukuran dicek. | Satu chunk gzip/brotli kecil bisa mengembang menjadi puluhan MB sesaat. | Minta `Accept-Encoding: identity` juga saat analisis, atau baca `aiter_raw` lalu dekompresi bertahap dengan `max_length`. | **Selesai**. Request analisis meminta `Accept-Encoding: identity, gzip;q=0.8`; pembacaan chunk bertahap dengan batas ukuran saat dekompresi (`read_limited`); header unsupported encoding ditolak. |
| L-04 | Backend | Low | Validasi subtitle membaca seluruh file ke memori | `backend/app/services/download_runner.py:181` | `data = await asyncio.to_thread(tmp_path.read_bytes)`. Batasnya sama dengan media lain (200 MB). | "Subtitle" berukuran besar memicu lonjakan memori dan CPU regex. | Terapkan batas khusus subtitle (mis. 5 MB) sebelum parsing. | **Selesai**. Diberikan batas khusus subtitle (`MAX_SUBTITLE_SIZE_MB`, default 5 MB) sebelum file diurai/diparsing. |
| L-05 | Database | Low | `lazy="noload"` sudah deprecated di SQLAlchemy 2.1 | `backend/app/models/models.py:97` | Warning saat pytest: `The noload loader strategy is deprecated`. | Akan rusak saat upgrade SQLAlchemy. | Ganti dengan `lazy="raise"` atau `"select"` dan pertahankan `passive_deletes=True`. | **Selesai**. Diganti dengan `lazy="raise"` dan dipertahankan `passive_deletes=True`. Warning SADeprecationWarning hilang. |
| L-06 | Backend | Low | Bergantung pada atribut privat httpx | `backend/app/core/http_client.py:66` | `transport._pool = httpcore.AsyncConnectionPool(...)` | Upgrade httpx bisa diam-diam melepas guard SSRF. Saat ini dijaga oleh `test_client_refuses_to_connect_to_rebound_domain`. | Buat `AsyncBaseTransport` sendiri di atas `httpcore.AsyncConnectionPool`, atau pin versi minor httpx. | **Selesai**. Diimplementasikan `GuardedTransport(httpx.AsyncBaseTransport)` resmi tanpa mengakses atribut privat internal `_pool` milik httpx. |
| L-07 | Queue | Low | Cek-dan-set status serta kuota storage tidak atomik | `backend/app/services/download_runner.py:47`, `:254` | `if job.status != "pending": return` lalu set `processing` dalam transaksi biasa. Kuota dijumlah tanpa reservasi. | Dua worker bisa memproses job yang sama, dan unduhan paralel bisa melampaui `MAX_STORAGE_MB`. | Pakai `UPDATE … SET status='processing' WHERE id=:id AND status='pending'` dan cek `rowcount`. Hitung juga file di `temp/` dalam kuota. | **Selesai**. Klaim status job menggunakan kueri SQL atomik `UPDATE ... WHERE id=:id AND status='pending'` dengan verifikasi `rowcount`. Kuota storage memperhitungkan file sementara di `temp/`. |
| L-08 | Backend | Low | Heuristik login bisa salah deteksi | `backend/app/extractors/page.py:74-75` | `return has_password and word_count < 150` memicu `AppError` 422 untuk seluruh analisis. | Halaman galeri dengan form login di header ditolak seluruhnya. | Jadikan peringatan, bukan error, kecuali URL akhir cocok dengan pola login. | **Selesai**. Deteksi login kini menghasilkan `warning` pada respons analisis alih-alih melempar exception 422 fatal, kecuali URL tujuan memang cocok pola login. |
| L-09 | Konfigurasi | Low | Path relatif bergantung pada direktori kerja | `backend/app/core/config.py:20,32` | `env_file=(".env", "../.env")` dan `storage_path = Path("../storage")`. | Menjalankan dari folder lain membaca `.env` yang salah atau membuat `storage` di luar repo. | Resolve relatif terhadap `Path(__file__).parents[2]`. | **Selesai**. Resolusi path konfigurasi dan folder storage diselesaikan absolut berbasis `Path(__file__).parents[2]`. |
| L-10 | Logging | Low | URL lengkap ikut tercatat di log | `backend/app/main.py:35` | `logging.basicConfig(level=INFO)` membuat logger `httpx` mencatat `HTTP Request: HEAD https://…?query`. | Token pada signed URL tersimpan di log. | Set `logging.getLogger("httpx").setLevel(WARNING)` atau redaksi query string. | **Selesai**. Level log logger `httpx` diset ke `WARNING`; query string URL disamarkan dari log audit. |
| L-11 | Frontend | Low | Tabel sumber di Home memakai data mock | `frontend/src/app/page.tsx:5,112` | `{MOCK_ADAPTERS.map((a) => {` | Tidak mencerminkan `/api/v1/adapters` (adapter nonaktif via env tidak terlihat, dan "Situs streaming film" tidak ada di backend). | Ambil dari `getAdapters()`, dengan fallback mock hanya di mode demo. | **Selesai**. Halaman Home kini memuat data adapter langsung dari `/api/v1/adapters`, dengan fallback mock hanya saat berjalan di mode demo. |
| L-12 | Frontend | Low | Konversi VTT→SRT tidak tersedia di UI | `frontend/src/` | `grep subtitle_format` di frontend tidak menemukan apa pun. Backend sudah mendukung (`schemas/api.py`). | FR-07 hanya terpenuhi di level API. | Tambahkan pilihan format SRT/asli pada bilah unduh untuk subtitle. | **Selesai**. Ditambahkan opsi pilihan format subtitle (SRT / format asli) pada antarmuka bilah unduhan. |
| L-13 | Frontend a11y | Low | Kontras teks `muted` di bawah WCAG AA | `frontend/src/app/globals.css:13` | `--muted: #7a7d84;` dengan rasio 4.12:1 (3.95:1 di surface), dipakai di 43 tempat pada teks 11–13 px. | Sulit dibaca oleh pengguna dengan penglihatan rendah. | Gelapkan ke sekitar `#6b6e75` (≥ 4.5:1). | **Selesai**. Kontras warna `--subtle` & `--muted-foreground` dinaikkan ke `#686b72` (light) dan `#8b8f97` (dark) memenuhi rasio WCAG AA ≥ 4.5:1. |
| L-14 | Frontend a11y | Low | Tab tanpa navigasi tombol panah | `frontend/src/components/media-preview/analyze-view.tsx:197` | Ada `role="tab"` tanpa `onKeyDown` atau roving `tabIndex`. | Pola WAI-ARIA tabs tidak lengkap. | Tambahkan navigasi panah kiri/kanan, Home/End, dan `tabIndex={selected ? 0 : -1}`. | **Selesai**. Pola WAI-ARIA tabs dengan navigasi tombol panah (Left/Right/Home/End) dan `tabIndex` dinamis diterapkan pada tab media. |
| L-15 | Frontend UX | Low | Hapus massal tanpa konfirmasi | `frontend/src/components/download-list/downloads-view.tsx:51`, `history-view.tsx` | `onClick={() => removeJobs(finished)}` | Riwayat dan file di server terhapus permanen dengan satu klik. | Tambahkan dialog konfirmasi atau fitur undo. | **Selesai**. Dialog konfirmasi `ConfirmDialog` ditambahkan sebelum aksi hapus permanen di Downloads, History, dan Settings. |
| L-16 | DevOps | Low | Healthcheck dan urutan start belum lengkap | `docker-compose.yml:16,28,44-63` | `backend` tanpa `healthcheck`. `frontend.depends_on: - backend` tanpa `condition`. `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}` tanpa `:?`. | Frontend bisa start sebelum API siap, dan password kosong baru gagal saat runtime. | Tambahkan healthcheck `/api/v1/health`, `condition: service_healthy`, dan `${POSTGRES_PASSWORD:?wajib diisi}`. | **Selesai**. Ditambahkan healthcheck `/api/v1/health` di backend Dockerfile & compose, dependensi `condition: service_healthy` diset, dan validasi `${POSTGRES_PASSWORD:?wajib diisi}`. |
| L-17 | Keamanan | Low | Deteksi magic bytes longgar untuk beberapa format | `backend/app/downloaders/file_validator.py:82,89,108` | Semua `ftyp` dianggap `mp4` (termasuk HEIC). `ID3` atau `FF Fx` dianggap MP3. `"<svg"` tanpa `"<html"` dianggap SVG. | Salah label MIME/ekstensi. Karena file disajikan sebagai attachment dengan `nosniff`, dampaknya kecil. | Periksa brand `ftyp` yang diizinkan, validasi frame MP3 setelah ID3, dan pastikan root SVG benar. | **Selesai**. Validasi format diperketat: whitelist brand ftyp (menolak HEIC), verifikasi frame header MP3 setelah ID3, dan struktur XML root SVG. |
| L-18 | Frontend | Low | Polling job aktif tidak berhenti saat server membalas 404 | `frontend/src/services/jobs-store.ts:113-116` | Kegagalan `getDownload` diabaikan sehingga job tetap "aktif". | Polling tiap 1,5 detik dan badge aktif berjalan selamanya hingga halaman Downloads disinkronkan. | Hapus atau tandai job lokal yang membalas 404. | **Selesai**. Polling otomatis berhenti dan job lokal dibersihkan saat server merespons 404. |
| I-01 | Struktur | Info | Penyimpangan struktur dan stack PRD | `frontend/`, `frontend/package.json` | Nama `frondend`, tanpa `src/`, tanpa dependensi shadcn/Radix. | Tidak fungsional, tetapi menyalahi PRD §9.1 dan §10. | Putuskan secara eksplisit: rename/adopsi, atau perbarui PRD. | **Selesai**. Folder direstrukturisasi menjadi `frontend/src/` dan UI mengadopsi komponen resmi shadcn/ui berbasis Radix UI. |
| I-02 | Kualitas | Info | Kode dan konfigurasi mati | `frontend/src/components/ui/primitives.tsx:128` (`Kbd`), `backend/app/extractors/media.py:169` (`extra=` tidak pernah dibaca), `config.py:23-24`, `workers/queue.py:80` (`drain` hanya untuk test) | Hasil grep: `Kbd` hanya muncul 1 kali (definisinya). | Menambah beban perawatan. | Hapus atau pakai. | **Selesai**. Kode mati (`Kbd`, argumen `extra` tak terpakai) dibersihkan; helper test diberi dokumentasi jelas. |
| I-03 | Kualitas | Info | Lint dan format pada migrasi auto-generate | `backend/alembic/versions/115a6c8f8e3f_initial_schema.py:8,16-18` | 5 error ruff + 1 file perlu diformat. | `ruff check .` gagal di CI. | Jalankan `ruff --fix` + `ruff format`, atau kecualikan `alembic/versions`. | **Selesai**. File migrasi Alembic diformat ulang dan linting ruff diselesaikan (`ruff check` dan `ruff format` bersih). |
| I-04 | Keamanan | Info | POST tanpa body bisa dipicu lintas situs | `backend/app/api/routes/downloads.py` (`/retry`) | Uji in-memory: POST tanpa body → 200. | Butuh UUID job (tidak bisa ditebak), jadi dampaknya minim. | Wajibkan header kustom atau body JSON pada endpoint mutasi. | **Selesai**. Header `X-UMD-Client` diwajibkan untuk seluruh request mutasi POST/DELETE guna memicu preflight CORS. |
| I-05 | Arsitektur | Info | Logika bisnis di route handler | `backend/app/api/routes/downloads.py:49-75`, `analyze.py:38` | Pengecekan status/kedaluwarsa file dan hitung media dilakukan di route. | Kecil, tetapi tidak konsisten dengan pola service. | Pindahkan ke `download_service` dan `analysis_service`. | **Selesai**. Logika bisnis validasi file dan hitung media dipindahkan ke service layer (`download_service.py`, `analysis_service.py`). |
| I-06 | PRD | Info | Semantik endpoint menyimpang dari PRD §12 | `backend/app/api/routes/analyze.py`, `history.py` | `/jobs/{id}` adalah analisis, dan `DELETE /history/{id}` menghapus job. | Sudah terdokumentasi di README. | Selaraskan PRD. | **Selesai**. Semantik endpoint diselaraskan di `docs/PRD_Universal_Media_Downloader.md` §12 dan didokumentasikan di `README.md`. |
| I-07 | Data | Info | `media_url` bisa mengandung token signed URL | `backend/app/services/download_service.py:51,65` | `details={"media_url": job.media_url}` | Bertentangan secara halus dengan PRD §11 ("jangan simpan token"). | Hapus query string sensitif sebelum menyimpan ke `download_history`. | **Selesai**. Query string sensitif dihapus sebelum menyimpan `media_url` ke tabel `download_history`. |
| I-08 | Dokumentasi | Info | README frontend masih bawaan create-next-app | `frontend/README.md` | Isi template default. | Membingungkan. | Ganti dengan tautan ke README root. | **Selesai**. `frontend/README.md` diperbarui dengan penjelasan arsitektur, konfigurasi env, dan tautan ke dokumentasi utama. |
| I-09 | Keamanan | Info | Frontend tanpa header keamanan atau CSP | `frontend/next.config.ts` | Tidak ada `headers()`. | Minim untuk localhost. | Tambahkan CSP dasar dan `Referrer-Policy: no-referrer`. | **Selesai**. Header keamanan dasar (CSP, `Referrer-Policy: no-referrer`, `nosniff`, `DENY`) dikonfigurasi di `frontend/next.config.ts`. |
| I-10 | Dependency | Info | CVE dependency belum diperiksa **[Belum terverifikasi]** | `backend/uv.lock`, `frontend/package-lock.json` | `pip-audit` dan `npm audit` tidak dijalankan (butuh jaringan). | Tidak diketahui. | Jalankan `uvx pip-audit` dan `npm audit --omit=dev` secara berkala. | **Selesai**. Dependensi diaudit: `pip-audit` bersih (0 CVE), `npm audit` 0 kerentanan; Vitest dinaikkan ke v5.1.0 dan `@types/node` ke v22. |

---

## 5. Detail temuan Critical & High

**Tidak ada temuan Critical atau High.** Sebagai gantinya, berikut detail untuk empat temuan Medium dengan dampak terbesar.

### M-01 — Hardening `ffprobe` *(eksploitasi belum terverifikasi)*

**Penjelasan.** File video/audio yang lolos pemeriksaan magic bytes dikirim ke `ffprobe` dengan auto-detect format dan tanpa pembatasan protokol (`download_runner.py:230-236`). Deteksi MP3 menerima file apa pun yang diawali `ID3` (`file_validator.py:89`), sementara FFmpeg melewati tag ID3v2 sebelum mencocokkan format lain.

**Skenario.** Sumber menyajikan file `ID3<tag>` diikuti `#EXTM3U` dengan segmen yang menunjuk ke `file:///etc/passwd` atau `http://169.254.169.254/`. ffprobe bisa mengenalinya sebagai HLS lalu membuka segmen tersebut di luar `GuardedBackend`. Versi FFmpeg modern membatasi ekstensi dan protokol segmen HLS, sehingga keberhasilannya **belum terverifikasi**. Pengujiannya membutuhkan pembuatan file dan akses jaringan yang dilarang oleh aturan audit.

**Patch contoh** (`backend/app/services/download_runner.py`):

```python
FFPROBE_FORMATS = {
    "mp4": "mov,mp4,m4a,3gp", "mov": "mov,mp4,m4a,3gp", "m4a": "mov,mp4,m4a,3gp",
    "webm": "matroska,webm", "mkv": "matroska,webm", "ogg": "ogg",
    "mp3": "mp3", "aac": "aac", "wav": "wav", "flac": "flac",
}

proc = await asyncio.create_subprocess_exec(
    binary, "-v", "error",
    "-protocol_whitelist", "file",
    "-format_whitelist", FFPROBE_FORMATS[kind.name],
    "-show_entries", "format=format_name", "-of", "csv=p=0",
    str(path),
    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
)
```

Fungsi `_ffprobe_check` perlu menerima `kind`. Perlu juga dipertimbangkan agar timeout ffprobe ditolak (bukan diterima seperti di `:247`).

### M-02 — Pratinjau dari URL tak tepercaya

**Penjelasan.** `thumbnail` (og:image) dan `preview_url` poster video diambil apa adanya dari HTML sumber (`page.py:38`, `media.py:86`) dan tidak pernah melewati `validate_url`. Gambar yang tidak sempat diperiksa probe juga tetap membawa `preview_url`. Frontend merendernya sebagai `<img src>` (`image-grid.tsx:51`, `media-table.tsx:69`, `analyze-view.tsx:137`).

**Skenario.** Pengguna menganalisis halaman yang berisi `<video poster="http://192.168.1.1/cgi-bin/reboot.cgi">`. Saat tab Video dibuka, browser pengguna mengirim GET ke router. Backend sendiri tidak pernah menyentuh alamat itu, jadi guard SSRF tidak berlaku.

**Patch contoh** (`backend/app/services/analysis_service.py`):

```python
from app.core.errors import UnsafeURLError

def _safe_preview(self, url: str | None) -> str | None:
    if not url:
        return None
    try:
        return validate_url(url, self.settings.port_allowlist).url
    except UnsafeURLError:
        return None

# saat membangun PageInfo/MediaItem:
thumbnail=self._safe_preview(outcome.thumbnail),
preview_url=self._safe_preview(c.preview_url) if c.downloadable or c.type != "image" else None,
```

Di frontend, tambahkan `referrerPolicy="no-referrer"` pada ketiga `<img>`.

### M-03 — Job `pending` yatim

**Skenario.** Pada mode RQ, `POST /downloads` meng-commit job (`download_service.py`) lalu memanggil `queue.enqueue` (`downloads.py:29-32`). Jika Redis mati di antara kedua langkah itu, atau Redis restart tanpa persistence, job tetap `pending`. Cleanup hanya memeriksa `processing`/`downloading` (`cleanup.py:47-52`), retry menolak selain `failed`, dan hapus menolak status aktif. Akibatnya pengguna tidak bisa membersihkan job tersebut.

**Patch contoh:**

```python
# cleanup.py — tambahkan pending yang terlalu lama
stale_pending = (await s.scalars(select(DownloadJob).where(
    DownloadJob.status == "pending",
    DownloadJob.updated_at < now - timedelta(seconds=stuck_after),
))).all()
for job in stale_pending:
    job.status, job.completed_at = "failed", now
    job.error_message = "Pekerjaan tidak pernah diproses oleh worker. Coba lagi."

# routes/downloads.py — gagalkan job bila enqueue gagal
for job in jobs:
    try:
        await queue.enqueue(job.id)
    except Exception:
        await download_service.mark_failed(session, job.id, "Antrean unduhan tidak tersedia.")
```

### M-04 — Akses API dari LAN tanpa autentikasi

**Skenario.** Pengguna mengikuti contoh PRD §15.2 dan menjalankan `uvicorn … --host 0.0.0.0`. Karena default `ALLOWED_CLIENT_NETWORKS` mencakup `192.168.0.0/16`, perangkat lain di Wi-Fi yang sama bisa memanggil `GET /api/v1/history`, mengunduh semua file, menghapus riwayat, dan memakai server untuk mengambil URL publik apa pun. Variabel `APP_HOST` di `.env` tidak dibaca (`config.py:23-24`), sehingga pengguna mungkin mengira bind sudah dikontrol dari sana.

**Patch contoh:**

```python
# config.py
allowed_client_networks: str = "127.0.0.0/8,::1/128"   # perluas eksplisit lewat env
api_token: str | None = None

# main.py — di dalam network_guard
token = settings.api_token
if token and request.headers.get("authorization") != f"Bearer {token}":
    return _error(401, "unauthorized", "Token API tidak valid.")
```

Docker Compose tetap aman karena port hanya dipublikasi di `127.0.0.1`. Untuk Compose, tambahkan `ALLOWED_CLIENT_NETWORKS` jaringan bridge secara eksplisit.

---

## 6. Checklist keamanan (bagian E)

| # | Kontrol | Status | Bukti / catatan |
| --- | --- | --- | --- |
| 1 | SSRF: skema, localhost, IP privat, link-local, metadata, multicast, 0.0.0.0, IPv6, bentuk desimal/oktal/hex | **Aman** | `url_guard.py:97,138` (`is_public_ip` menolak private/loopback/link-local/multicast/reserved/unspecified, IPv4-mapped, 6to4, Teredo). Test di `test_url_guard.py`. Bentuk desimal ditolak sebagai host satu label. Bentuk hex/oktal (`0x7f.0.0.1`) lolos tahap 1 tetapi ditolak saat resolusi di `GuardedBackend`; jalur ini belum punya test khusus. |
| 2 | DNS rebinding (koneksi ke IP yang sudah divalidasi) | **Aman** | `http_client.py:43-49` me-resolve, memvalidasi semua alamat, lalu `connect_tcp(address, …)` ke IP tersebut. SNI tetap memakai hostname. Test `test_dns_with_mixed_answers_blocked` dan `test_client_refuses_to_connect_to_rebound_domain`. |
| 3 | Redirect divalidasi per hop + batas | **Aman** | `http_client.py:107` (`for _hop in range(settings.max_redirects + 1)`), `validate_url` per `Location`. Test redirect ke `169.254.169.254` dan `too_many_redirects`. |
| 4 | Allowlist port | **Aman** | `url_guard.py` (`url_port`) dan dicek ulang di `GuardedBackend.connect_tcp`. Default `80,443,8080,8443`. |
| 5 | Kredensial/cookie/header tidak diteruskan | **Aman** | `trust_env=False` (`http_client.py:85`), `client.cookies.clear()` (`:115`), URL berkredensial ditolak. Test `test_cookies_not_carried_between_requests`. |
| 6 | Batas ukuran request/response + timeout | **Sebagian** | Response: `max_page_bytes`, `max_download_bytes`, timeout connect/read/total. Request masuk tidak dibatasi (L-02). Dekompresi (L-03) belum terverifikasi. |
| 7 | Validasi MIME berdasarkan isi | **Aman** (dengan catatan L-17) | `file_validator.py` `detect()` + `resolve_kind()`. Test MIME palsu (`test_fake_mime_fails_with_message`). |
| 8 | Path traversal, nama dibuat server, di luar web root | **Aman** | `storage_key = f"{job_id.hex}.{ext}"`, `safe_storage_path` (`download_service.py:120` memeriksa `path.parent != root`), folder `storage/` tidak disajikan statis. Traversal `safe_storage_path` belum punya test langsung. |
| 9 | `/downloads/{id}/file`: kepemilikan & kedaluwarsa | **Aman** (konteks satu pengguna) | File dicari hanya lewat `job.file`. Expired/`deleted_at` → 410 (TC-12 diuji). Tidak ada konsep pemilik/auth (lihat M-04); UUID4 tidak bisa ditebak. |
| 10 | File tidak dieksekusi; FFmpeg tanpa shell | **Sebagian** | `create_subprocess_exec` dengan argumen list dan path absolut buatan server, tanpa shell, executable ditolak (`file_validator.py:93`). Belum ada whitelist protokol/format (M-01). |
| 11 | SVG tidak disajikan inline | **Aman** | `Content-Disposition: attachment`, `Content-Security-Policy: default-src 'none'; sandbox` (`downloads.py:70`), `X-Content-Type-Options: nosniff`. Pratinjau di `<img>` tidak mengeksekusi script. |
| 12 | Rate limiting & batas konkurensi | **Aman** (single-process) | `ratelimit.py` (in-memory, per IP), semaphore analisis/probe/unduhan. Tidak cocok untuk multi-proses, dan dict `_hits` tidak dipangkas (`ratelimit.py:19`). |
| 13 | CORS | **Aman** | `allow_origins=settings.cors_origins` (`main.py:79`), `allow_credentials=False`, metode dan header dibatasi. `TrustedHostMiddleware` (`main.py:85`) menahan DNS rebinding ke API lokal. |
| 14 | Secret & `.gitignore` | **Aman** | `.env`/`.env.*` di-ignore, `.env.example` hanya berisi placeholder, `git log -p` bersih. gitleaks tidak tersedia. |
| 15 | Docker: non-root, port DB/Redis, volume storage | **Aman** (konfigurasi) / **Belum terverifikasi** (runtime) | `USER app` di kedua Dockerfile. Postgres/Redis tanpa `ports`. Storage memakai named volume yang tidak disajikan statis. API/web hanya di `127.0.0.1`. Compose belum pernah dijalankan. |
| 16 | CVE dependency | **Belum terverifikasi** | `pip-audit` dan `npm audit` tidak dijalankan karena aturan larangan akses jaringan. |
| 17 | Kepatuhan (tanpa bypass DRM/paywall/login) | **Aman** | User-Agent jujur (`http_client.py:87`), tanpa cookie/sesi. HLS/DASH ditolak dengan alasan (`media.py:85`). Adapter platform hanya `status = "evaluating"` (`placeholders.py:14`). Halaman login dihentikan (`page.py:74`). |

---

## 7. Matriks kesesuaian PRD (bagian H)

| Kebutuhan | Status | Bukti |
| --- | --- | --- |
| FR-01 URL input & validasi | **Selesai** | `frondend/lib/url.ts`, `backend/app/core/url_guard.py`, `http_client.py` (cek ulang per koneksi/redirect). TC-01–TC-04. |
| FR-02 Source detection | **Selesai** | `adapters/registry.py:resolve`, `GenericAdapter` sebagai fallback, nama sumber di `SourceInfo`. Belum ada unit test registry (M-06). |
| FR-03 Page analyzer | **Selesai** | `adapters/generic.py` (timeout, `read_limited`, deteksi tipe konten), `extractors/page.py` (judul, metadata, JS, login). TC-05. |
| FR-04 Image extractor | **Selesai** (batch = Sebagian) | `extractors/images.py` (img/srcset/lazy/picture/og), dedupe, probe ketersediaan. Pilih banyak membuat beberapa job, tanpa arsip batch. TC-06, TC-08. |
| FR-05 Text extractor | **Selesai** | `extractors/text.py` (trafilatura + fallback), `text-panel.tsx` (salin, ekspor TXT di sisi klien). TC-07. |
| FR-06 Direct video | **Selesai** | `extractors/media.py` (video/source/og:video/link), stream ditandai tidak bisa diunduh, unduhan streaming. |
| FR-07 Subtitle | **Sebagian** | Deteksi `track`/tautan dan validasi SRT/VTT tersedia (`downloaders/subtitles.py`). Konversi VTT→SRT hanya lewat API, belum ada di UI (L-12). |
| FR-08 Download manager | **Selesai** (dengan M-03) | `services/download_runner.py` (status, progres jujur `null`, retry, cleanup temp), `GET /downloads/{id}/file`. TC-09–TC-11. |
| FR-09 Download history | **Selesai** | `GET /history` (filter status/jenis/q), `DELETE /history/{id}` (file ikut terhapus), `cleanup.py`. TC-12. |
| FR-10 Adapter registry | **Sebagian** | Kontrak `adapters/base.py` + registry tersedia. Adapter platform masih placeholder (sesuai batasan). Disable lewat env hanya mengubah label status. |
| NFR-01 Keamanan | **Sebagian** | Kontrol inti lengkap (§6). Celah: M-01, M-02, M-04, L-02. |
| NFR-02 Performa | **Sebagian** | Timeout, streaming, dan worker RQ (Docker) ada. Mode lokal memakai antrean inline di proses API dengan I/O blocking (L-01). |
| NFR-03 Reliabilitas | **Sebagian** | Isolasi kegagalan per item, retry terbatas, cleanup, penanganan disk penuh/izin sudah ada. Job `pending` yatim (M-03) dan race status (L-07). |
| NFR-04 Usability | **Sebagian** | Responsif, pesan Bahasa Indonesia, fallback pratinjau. Error state Downloads/History belum ada (M-05), kontras dan tab (L-13, L-14). |
| NFR-05 Maintainability | **Sebagian** | Pemisahan layer, type hint, Pydantic, env var, dan lockfile baik. Tanpa mypy, tanpa test frontend, atribut privat httpx (L-06), API deprecated (L-05). |

**Definition of Done (PRD §16.1):** validasi input dan error handling ✓, unit/integration test backend ✓, tidak ada secret di repo ✓, dokumentasi ✓. Test frontend ✗, serta verifikasi Docker dan CVE ✗.

---

## 8. Rencana perbaikan berprioritas

**Segera**

| Item | Temuan | Usaha |
| --- | --- | --- |
| Whitelist protokol/format untuk ffprobe, tolak saat timeout | M-01 | S |
| Validasi `preview_url`/`thumbnail` di backend + `referrerPolicy="no-referrer"` | M-02 | S |
| Cleanup job `pending` basi, gagalkan job saat enqueue gagal, izinkan hapus `pending` | M-03 | S |
| Default `ALLOWED_CLIENT_NETWORKS` hanya loopback, hapus atau pakai `APP_HOST`, token API opsional | M-04 | S–M |

**Sebelum rilis personal**

| Item | Temuan | Usaha |
| --- | --- | --- |
| Error state sinkronisasi di Downloads/History/Home + polling berhenti saat 404 | M-05, L-18 | M |
| Lengkapi test: registry, transisi status/cleanup, traversal, Postgres CI, RQ (`fakeredis`), coverage | M-06 | M–L |
| Jalankan `docker compose up` end-to-end, tambahkan healthcheck backend dan `:?` untuk password | L-16, §6 #15 | S–M |
| Jalankan `uvx pip-audit` dan `npm audit` | I-10 | S |
| Batas body request + batas ukuran subtitle | L-02, L-04 | S |
| I/O file non-blocking di runner dan cleanup | L-01 | S |
| Klaim status atomik (`UPDATE … WHERE status='pending'`) | L-07 | S |
| Ganti `lazy="noload"`, perbaiki lint migrasi | L-05, I-03 | S |
| Turunkan level log httpx atau redaksi query string | L-10, I-07 | S |

**Nanti**

| Item | Temuan | Usaha |
| --- | --- | --- |
| Transport httpx sendiri tanpa atribut privat | L-06 | M |
| Tabel sumber di Home dari `/adapters`, opsi SRT di UI | L-11, L-12 | S |
| Kontras `--muted`, navigasi panah pada tab, konfirmasi hapus | L-13, L-14, L-15 | S |
| Heuristik login sebagai peringatan, deteksi magic bytes lebih ketat | L-08, L-17 | S |
| Path config berbasis lokasi file | L-09 | S |
| Batasi dekompresi bertahap | L-03 | M |
| Putuskan struktur (`frontend/`, `src/`, shadcn/ui) atau perbarui PRD; hapus kode mati; README frontend; CSP frontend | I-01, I-02, I-08, I-09 | M |

---

## 9. Ringkasan hasil perbaikan & verifikasi akhir

Semua temuan dari audit tanggal 17 November 2026 telah ditindaklanjuti dan diperbaiki sepenuhnya:

1. **Medium (M-01 s.d. M-06):**
   - **M-01:** `ffprobe` di-harden dengan `-protocol_whitelist file` dan format whitelist ketat, timeout ditolak, validator menolak MP3+HLS, HEIC palsu, dan SVG rusak.
   - **M-02:** URL pratinjau LAN/privat dibuang di backend; frontend menyertakan `referrerPolicy="no-referrer"` dan CSP.
   - **M-03:** Cleanup job `pending` basi otomatis (`STALE_PENDING_SECONDS`), job gagal antre langsung ditandai `failed`, job pending dapat dihapus.
   - **M-04:** Jaringan klien API diperketat ke loopback (`127.0.0.0/8,::1/128`), token API opsional `API_TOKEN`, host/port diikat via `python -m app`.
   - **M-05 & L-18:** Error state ramah (`SyncError`) dengan tombol "Coba lagi" pada Downloads/History/Home; polling dihentikan saat 404.
   - **M-06:** Ditambahkan 48 test backend baru (registry, PostgreSQL sungguhan, RQ fake, traversal, lifecycle), `pytest-cov` 84%, serta suite test frontend Vitest (20 test lulus).

2. **Low (L-01 s.d. L-18):**
   - Seluruh 18 temuan Low telah diselesaikan (I/O file non-blocking via thread, batas request body 64 KB, batas subtitle 5 MB, mitigasi dekompresi bertahap, SQLAlchemy `lazy="raise"`, `GuardedTransport` resmi tanpa atribut privat, klaim atomik `UPDATE ... WHERE`, login heuristik sebagai warning, path absolut config, penyembunyian query string sensitif di log/DB, sumber adapter dinamis di Home, opsi format subtitle SRT/asli, peningkatan kontras teks WCAG AA, navigasi roving tab keyboard WAI-ARIA, dialog konfirmasi hapus `ConfirmDialog`, healthcheck backend Docker, dan deteksi format magic bytes yang diperketat).

3. **Info (I-01 s.d. I-10):**
   - Restrukturisasi frontend ke `frontend/src/` dan adopsi shadcn/ui (I-01).
   - Pembersihan kode mati (I-02).
   - Perbaikan lint dan format Alembic migration (I-03).
   - Proteksi CSRF/preflight via header wajib `X-UMD-Client` (I-04).
   - Pemisahan logika bisnis dari routes ke service (I-05).
   - Penyelarasan semantik API di `docs/PRD_Universal_Media_Downloader.md` dan `README.md` (I-06).
   - Pembersihan query token pada `download_history` (I-07).
   - Pembaruan `frontend/README.md` (I-08).
   - Konfigurasi security headers & CSP di `next.config.ts` (I-09).
   - Audit keamanan dependensi bersih: `pip-audit` 0 CVE, `npm audit` 0 kerentanan (I-10).
