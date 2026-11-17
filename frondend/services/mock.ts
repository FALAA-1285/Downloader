// Data demo dipakai saat NEXT_PUBLIC_API_BASE_URL belum diset.
// Semua nilai di sini adalah contoh dan ditandai sebagai "Mode demo" di UI.

import type { AdapterInfo, AnalyzeResult, MediaItem, MediaType, ServerConfig, SourceType } from "@/types";

const PLATFORMS: Array<{ type: SourceType; name: string; match: RegExp }> = [
  { type: "youtube", name: "YouTube", match: /(^|\.)(youtube\.com|youtu\.be)$/ },
  { type: "instagram", name: "Instagram", match: /(^|\.)instagram\.com$/ },
  { type: "tiktok", name: "TikTok", match: /(^|\.)tiktok\.com$/ },
  { type: "x", name: "X (Twitter)", match: /(^|\.)(x\.com|twitter\.com)$/ },
];

export function detectSource(domain: string): { type: SourceType; name: string } {
  const hit = PLATFORMS.find((p) => p.match.test(domain));
  return hit ? { type: hit.type, name: hit.name } : { type: "generic", name: "Website umum" };
}

function hash(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function rng(seed: number) {
  let s = seed || 1;
  return () => {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return ((s >>> 0) % 10000) / 10000;
  };
}

/** Pratinjau gambar demo: SVG lokal, tanpa request ke jaringan luar. */
export function demoImage(seed: number, w: number, h: number): string {
  const r = rng(seed);
  const hue = Math.floor(r() * 360);
  const hue2 = (hue + 40 + Math.floor(r() * 80)) % 360;
  const cx = Math.floor(r() * w);
  const cy = Math.floor(r() * h);
  const rad = Math.floor(Math.min(w, h) * (0.25 + r() * 0.35));
  const horizon = Math.floor(h * (0.55 + r() * 0.2));
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><rect width="${w}" height="${h}" fill="hsl(${hue} 45% 86%)"/><circle cx="${cx}" cy="${cy}" r="${rad}" fill="hsl(${hue2} 60% 62%)"/><rect y="${horizon}" width="${w}" height="${h - horizon}" fill="hsl(${hue} 30% 30%)"/></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const SLUG_WORDS = ["hero", "cover", "gallery", "inline", "figure", "banner", "detail", "thumb", "chart", "portrait"];

function titleFromUrl(u: URL): string {
  const seg = u.pathname.split("/").filter(Boolean).pop();
  if (!seg) return `Beranda ${u.hostname.replace(/^www\./, "")}`;
  const words = decodeURIComponent(seg).replace(/\.[a-z]+$/i, "").split(/[-_]+/).filter(Boolean);
  const t = words.join(" ");
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : "Halaman tanpa judul";
}

const SAMPLE_TEXT = `Konten web tersebar dalam berbagai format dan struktur. Sebagian halaman menyediakan tautan file langsung, sementara halaman lain menyajikan konten melalui struktur HTML, API resmi, atau streaming adaptif.

Dalam pratinjau ini, teks utama diekstrak dari elemen artikel. Elemen navigasi, iklan, dan boilerplate dikurangi agar yang tersisa adalah isi yang benar-benar dibaca orang.

Teks hasil ekstraksi dapat disalin langsung atau diekspor sebagai file TXT. Jika teks utama tidak terdeteksi, aplikasi akan memberi tahu alasannya alih-alih menampilkan halaman kosong.

Ini adalah data demo. Hubungkan backend FastAPI melalui variabel NEXT_PUBLIC_API_BASE_URL untuk melihat hasil analisis yang sebenarnya.`;

export function mockAnalyze(url: string, types: MediaType[]): AnalyzeResult {
  const u = new URL(url);
  const domain = u.hostname.replace(/^www\./, "");
  const source = detectSource(domain);
  const seed = hash(url);
  const r = rng(seed);
  const now = new Date().toISOString();
  const want = (t: MediaType) => types.length === 0 || types.includes(t);

  if (/\/(login|signin|account|private)/i.test(u.pathname)) {
    throw new Error("Halaman ini membutuhkan login. Konten di balik autentikasi tidak dianalisis.");
  }

  if (source.type !== "generic") {
    return {
      id: `demo-${seed.toString(16)}`,
      success: true,
      source: { type: source.type, domain, name: source.name },
      page: { url, title: null, description: null },
      media: [],
      text: null,
      warnings: [
        `Adapter ${source.name} masih dalam evaluasi. Platform yang dikenali tidak otomatis berarti kontennya dapat diunduh.`,
      ],
      analyzed_at: now,
    };
  }

  const media: MediaItem[] = [];

  if (want("image")) {
    const count = 6 + Math.floor(r() * 5);
    for (let i = 0; i < count; i++) {
      const landscape = r() > 0.3;
      const w = landscape ? 1600 : 900;
      const h = landscape ? 900 + Math.floor(r() * 200) : 1200;
      const ext = ["jpg", "webp", "png", "jpg", "gif"][Math.floor(r() * 5)];
      const failed = i === count - 2;
      const name = `${SLUG_WORDS[i % SLUG_WORDS.length]}-${String(i + 1).padStart(2, "0")}.${ext}`;
      media.push({
        id: `img-${i + 1}`,
        type: "image",
        filename: name,
        url: `${u.origin}/assets/images/${name}`,
        mime_type: ext === "jpg" ? "image/jpeg" : `image/${ext}`,
        size: failed ? null : Math.floor(80_000 + r() * 1_400_000),
        downloadable: !failed,
        reason: failed ? "Gambar tidak dapat diakses (HTTP 404)." : null,
        width: w,
        height: h,
        preview_url: failed ? null : demoImage(seed + i * 97, 320, Math.round((320 * h) / w)),
      });
    }
  }

  if (want("video")) {
    media.push(
      {
        id: "vid-1",
        type: "video",
        filename: "liputan-utama.mp4",
        url: `${u.origin}/media/liputan-utama.mp4`,
        mime_type: "video/mp4",
        size: Math.floor(18_000_000 + r() * 40_000_000),
        downloadable: true,
        width: 1920,
        height: 1080,
        duration: 94 + Math.floor(r() * 300),
        preview_url: demoImage(seed + 501, 320, 180),
      },
      {
        id: "vid-2",
        type: "video",
        filename: "cuplikan.webm",
        url: `${u.origin}/media/cuplikan.webm`,
        mime_type: "video/webm",
        size: null,
        downloadable: true,
        width: 1280,
        height: 720,
        duration: 31,
        preview_url: demoImage(seed + 733, 320, 180),
      },
      {
        id: "vid-3",
        type: "video",
        filename: "stream.m3u8",
        url: `${u.origin}/stream/master.m3u8`,
        mime_type: "application/vnd.apple.mpegurl",
        size: null,
        downloadable: false,
        reason: "Streaming dilindungi DRM. Aplikasi tidak memproses konten terproteksi.",
        duration: null,
      },
    );
  }

  if (want("subtitle")) {
    media.push(
      { id: "sub-1", type: "subtitle", filename: "liputan-utama.id.vtt", url: `${u.origin}/media/subs/id.vtt`, mime_type: "text/vtt", size: 14_220, downloadable: true, language: "Indonesia" },
      { id: "sub-2", type: "subtitle", filename: "liputan-utama.en.srt", url: `${u.origin}/media/subs/en.srt`, mime_type: "application/x-subrip", size: 13_870, downloadable: true, language: "English" },
      { id: "sub-3", type: "subtitle", filename: "liputan-utama.ja.vtt", url: `${u.origin}/media/subs/ja.vtt`, mime_type: "text/vtt", size: null, downloadable: true, language: "日本語" },
    );
  }

  return {
    id: `demo-${seed.toString(16)}`,
    success: true,
    source: { type: "generic", domain, name: "Website umum" },
    page: {
      url,
      title: titleFromUrl(u),
      description: `Ringkasan halaman dari ${domain}. Metadata diambil dari tag judul dan deskripsi.`,
      thumbnail: demoImage(seed + 1, 480, 270),
    },
    media,
    text: want("text")
      ? { title: titleFromUrl(u), content: SAMPLE_TEXT, word_count: SAMPLE_TEXT.split(/\s+/).length }
      : null,
    warnings: [],
    analyzed_at: now,
  };
}

export const MOCK_ADAPTERS: AdapterInfo[] = [
  { id: "generic", name: "Website umum", domains: ["*"], status: "active", note: "Analisis HTML: gambar, teks, video langsung, subtitle." },
  { id: "youtube", name: "YouTube", domains: ["youtube.com", "youtu.be"], status: "evaluating", note: "Menunggu metode integrasi resmi yang berizin." },
  { id: "instagram", name: "Instagram", domains: ["instagram.com"], status: "evaluating", note: "Konten privat dan konten di balik login tidak diakses." },
  { id: "tiktok", name: "TikTok", domains: ["tiktok.com"], status: "evaluating", note: "Bergantung pada API dan izin yang tersedia." },
  { id: "x", name: "X (Twitter)", domains: ["x.com", "twitter.com"], status: "evaluating", note: "Bergantung pada API dan izin yang tersedia." },
  { id: "streaming", name: "Situs streaming film", domains: ["—"], status: "disabled", note: "Hanya subtitle atau file yang eksplisit dapat diunduh. Tanpa bypass DRM." },
];

export const MOCK_CONFIG: ServerConfig = {
  max_download_size_mb: 200,
  download_timeout_seconds: 120,
  file_retention_hours: 24,
  storage_path: "/app/storage",
  version: "0.1.0",
};
