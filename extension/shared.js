// Kode bersama popup & background (dimuat lewat <script> / importScripts).

/* exported UMD_DEFAULTS, UMD_PLATFORMS, umdPlatformOf, umdGetSettings, umdAnalyzeUrl */

const UMD_DEFAULTS = {
  uiBase: "http://localhost:3000",
  overlayEnabled: true,
  captureDownloads: false,
  captureExtensions: "zip,rar,7z,iso,exe,msi,apk,dmg,pdf,mp4,mkv,avi,mov,mp3,flac,m4a",
  captureMinMB: 1,
};

// Platform yang diunduh langsung oleh backend lewat yt-dlp (sama dengan adapter di backend).
// Situs ini memutar video dalam potongan-potongan, jadi yang dikirim ke UMD adalah URL halamannya.
const UMD_PLATFORMS = {
  "youtube.com": "YouTube",
  "youtu.be": "YouTube",
  "youtube-nocookie.com": "YouTube",
  "instagram.com": "Instagram",
  "facebook.com": "Facebook",
  "fb.watch": "Facebook",
  "tiktok.com": "TikTok",
  "x.com": "X",
  "twitter.com": "X",
  "threads.net": "Threads",
  "reddit.com": "Reddit",
  "pinterest.com": "Pinterest",
  "vimeo.com": "Vimeo",
  "twitch.tv": "Twitch",
  "dailymotion.com": "Dailymotion",
  "soundcloud.com": "SoundCloud",
};

function umdPlatformOf(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    const match = Object.keys(UMD_PLATFORMS).find((d) => host === d || host.endsWith(`.${d}`));
    return match ? UMD_PLATFORMS[match] : null;
  } catch {
    return null;
  }
}

async function umdGetSettings() {
  const stored = await chrome.storage.local.get(Object.keys(UMD_DEFAULTS));
  return { ...UMD_DEFAULTS, ...stored };
}

/** URL halaman analisis Web UI untuk `url`, dengan halaman asal sebagai Referer bila berbeda. */
async function umdAnalyzeUrl(url, referer) {
  const { uiBase } = await umdGetSettings();
  const qs = new URLSearchParams({ url });
  if (referer && referer !== url && /^https?:/i.test(referer)) qs.set("referer", referer);
  return `${uiBase}/analyze?${qs.toString()}`;
}
