# Universal Media Downloader — Browser Extension Helper

Ekstensi pendamping **Universal Media Downloader (UMD)** untuk browser berbasis Chromium (Chrome, Edge, Brave).

## Fitur Utama
1. **Penangkapan tautan media dari lalu lintas jaringan** (setelah Anda mengizinkannya):
   - Menangkap manifest `.m3u8` (HLS), `.mpd` (DASH), file `.mp4`/`.webm`, dan subtitle `.vtt`/`.srt` saat video diputar.
   - Segmen individual (`.ts`, `.m4s`) diabaikan karena tidak berguna diunduh satu per satu.
   - Angka badge pada ikon menunjukkan jumlah tautan yang tertangkap di tab tersebut.
2. **Kirim 1-klik ke UMD**: membuka Web UI (`<alamat Web UI>/analyze?url=...`) dengan tautan yang dipilih.
3. **Salin cookies.txt**: menyalin cookie situs di tab aktif dalam format Netscape (lengkap dengan domain, path,
   secure, HttpOnly, dan kedaluwarsa). Tempel di **Settings → Kredensial Sesi & Cookie** pada UMD; domainnya
   terisi otomatis dan cookie hanya dikirim ke domain tersebut.
4. **Tombol "Unduh video ini"** di pojok pemutar video (muncul saat kursor di atas video). UMD memilih
   sumber terbaik: URL halaman untuk YouTube/Instagram/TikTok/dll., file video langsung bila ada, atau
   manifest HLS/DASH yang tertangkap untuk pemutar MediaSource (`blob:`).
5. **Menu klik kanan:** "Unduh media ini / tautan ini dengan UMD" dan "Analisis halaman ini dengan UMD".
6. **Alihkan unduhan browser ke UMD** (nonaktif secara bawaan): unduhan dengan jenis file dan ukuran
   minimum yang Anda tentukan dibatalkan di browser lalu dibuka di UMD (multi-koneksi, bisa dijeda).
   Unduhan yang membutuhkan login atau form POST mungkin gagal di UMD; tambahkan cookie domainnya di Settings.

Konten yang dilindungi DRM atau enkripsi pemutar tidak didukung.

## Izin

| Izin | Kapan dipakai |
|---|---|
| `activeTab`, `scripting` | Memindai elemen `<video>`/`<track>` dan riwayat Resource Timing di tab aktif saat popup dibuka. |
| `webRequest` + akses host **opsional** (`<all_urls>`) | Menangkap tautan media dari lalu lintas jaringan dan menampilkan tombol unduh di pemutar video. Tidak aktif sampai Anda menekan **Izinkan akses situs** di popup, dan bisa dicabut di **Pengaturan** popup. |
| `cookies` | Hanya saat menekan **Salin cookies.txt**; izin akses diminta khusus untuk situs tab itu. |
| `storage` | Menyimpan daftar tautan per tab (dihapus saat tab ditutup/berpindah halaman) dan pengaturan. |
| `contextMenus` | Menu klik kanan "Unduh dengan UMD". |
| `downloads` | Hanya dipakai bila **Alihkan unduhan browser ke UMD** diaktifkan. |

Tombol di pemutar video adalah content script yang baru didaftarkan setelah akses situs diizinkan,
dan bisa dimatikan di **Pengaturan** popup.

## Cara Memasang (Chrome / Edge / Brave)

1. Buka halaman ekstensi (`chrome://extensions`, `edge://extensions`, atau `brave://extensions`).
2. Aktifkan **Mode Pengembang (Developer Mode)**.
3. Klik **Muat yang belum dibongkar (Load unpacked)** dan pilih folder `extension` di repositori ini.

## Cara Menggunakan

1. Buka popup ekstensi. Bila UMD tidak berjalan di `http://localhost:3000`, ubah alamatnya di **Pengaturan**.
2. Tekan **Izinkan akses situs** (sekali saja), muat ulang tab, lalu putar videonya beberapa detik.
3. Buka popup lagi: pilih **Unduh via UMD** atau **Salin URL** pada tautan yang tertangkap.
