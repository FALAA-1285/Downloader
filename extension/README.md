# Universal Media Downloader — Browser Extension Helper

Ekstensi browser resmi pendamping **Universal Media Downloader (UMD)** untuk Google Chrome, Microsoft Edge, Brave, dan Mozilla Firefox.

## Fitur Utama
1. **Penyadapan Lalu Lintas Jaringan (*Network Sniffing*)**:
   - Otomatis menangkap tautan video `.m3u8` (HLS), `.mpd` (DASH), `.mp4`, `.webm`, dan subtitle `.vtt` / `.srt` saat Anda memutar video di tab browser apa pun.
   - Angka badge pada ikon ekstensi menunjukkan jumlah stream yang terdeteksi.
2. **Kirim 1-Klik ke Universal Media Downloader**:
   - Langsung membuka Web UI (`http://localhost:3000/analyze?url=...`) dengan URL stream yang dipilih.
3. **Pengekspor Cookie Sesi**:
   - Tombol **"Salin Cookie Sesi"** untuk menyalin cookie login aktif dari tab saat ini, sehingga Anda bisa mengunduh konten privat / akun berbayar dengan mudah.

---

## Cara Memasang Ekstensi (Google Chrome / Edge / Brave)

1. Buka browser Chromium pilihan Anda (Chrome, Edge, Brave, Opera).
2. Buka halaman ekstensi:
   - **Chrome**: `chrome://extensions`
   - **Edge**: `edge://extensions`
   - **Brave**: `brave://extensions`
3. Aktifkan **Mode Pengembang (*Developer Mode*)** di pojok kanan atas.
4. Klik tombol **Muat yang belum dibongkar (*Load unpacked*)**.
5. Pilih folder:
   ```text
   C:\Software\laragon-6.0.0\www\media-downloader\extension
   ```
6. Ekstensi **Universal Media Downloader Helper** siap digunakan!

---

## Cara Menggunakan

1. Buka situs video apa pun (IDLIX, YouTube, portal streaming, situs berita, dsb.).
2. Putar video selama 2–3 detik agar browser mulai memuat pecahan media.
3. Klik ikon ekstensi di pojok kanan atas browser Anda.
4. Anda akan melihat daftar stream yang tertangkap (`HLS Stream`, `MP4`, `Subtitle`).
5. Klik **"Unduh via UMD"** atau **"Salin URL"** untuk mengunduh melalui Universal Media Downloader.
