// Background service worker — Universal Media Downloader Helper (Manifest V3).
//
// - Akses host bersifat opsional (M-08): penangkapan jaringan hanya aktif setelah pengguna
//   mengizinkannya dari popup, dan izin bisa dicabut kapan saja.
// - State disimpan di chrome.storage.session sehingga tetap ada saat service worker di-suspend.
// - Penulisan per tab diserialkan agar request yang datang bersamaan tidak saling menimpa.

importScripts("shared.js");

const storageArea = chrome.storage.session || chrome.storage.local;
const MAX_ITEMS_PER_TAB = 200;
const ALL_URLS = { origins: ["<all_urls>"] };
const OVERLAY_SCRIPT_ID = "umd-overlay";

// Manifest/playlist & file media utuh. Segmen (.ts/.m4s) sengaja tidak ditangkap: tidak berguna
// diunduh satu per satu, dan pola ".ts" juga cocok dengan file TypeScript di situs pengembang.
const MEDIA_REGEX = /\.(m3u8|mpd|mp4|webm|mkv|mov|vtt|srt)(\?|#|$)/i;

const MEDIA_CONTENT_TYPES = [
  "application/x-mpegurl",
  "application/vnd.apple.mpegurl",
  "application/dash+xml",
  "text/vtt",
  "application/x-subrip",
];

function contentTypeOf(headers) {
  for (const h of headers || []) {
    if (h.name && h.name.toLowerCase() === "content-type") {
      return (h.value || "").toLowerCase().split(";")[0].trim();
    }
  }
  return "";
}

// Potongan stream platform (YouTube/googlevideo, dll.): bukan file utuh, video & audio terpisah,
// dan bertanda tangan sementara. Platform ini diunduh lewat URL halamannya (yt-dlp di backend).
const PLATFORM_SEGMENT_REGEX = /^https?:\/\/[^/]*\.(googlevideo\.com|ytimg\.com)\/|\/videoplayback\?/i;

function isMedia(url, headers) {
  if (!url || !/^https?:/i.test(url)) return false;
  if (PLATFORM_SEGMENT_REGEX.test(url)) return false;
  if (MEDIA_REGEX.test(url)) return true;
  const ct = contentTypeOf(headers);
  return MEDIA_CONTENT_TYPES.includes(ct) || (ct.startsWith("video/") && ct !== "video/mp2t");
}

function mediaType(url, headers) {
  const clean = url.split(/[?#]/)[0].toLowerCase();
  const ct = contentTypeOf(headers);
  if (clean.endsWith(".m3u8") || ct.includes("mpegurl")) return "HLS Stream (.m3u8)";
  if (clean.endsWith(".mpd") || ct.includes("dash")) return "DASH Stream (.mpd)";
  if (clean.endsWith(".vtt") || clean.endsWith(".srt") || ct.includes("vtt") || ct.includes("subrip")) return "Subtitle";
  if (clean.endsWith(".webm") || ct.includes("webm")) return "WebM Video";
  if (clean.endsWith(".mp4") || ct.includes("mp4")) return "MP4 Video";
  return "Video";
}

const stripHash = (url) => (url || "").split("#")[0];
const tabKey = (tabId) => `tab_${tabId}`;

// Antrean penulisan per tab (get → ubah → set tidak atomik).
const writeQueues = new Map();
function withTabLock(tabId, fn) {
  const prev = writeQueues.get(tabId) || Promise.resolve();
  const next = prev.then(fn, fn).finally(() => {
    if (writeQueues.get(tabId) === next) writeQueues.delete(tabId);
  });
  writeQueues.set(tabId, next);
  return next;
}

async function readTab(tabId) {
  const res = await storageArea.get(tabKey(tabId));
  const value = res[tabKey(tabId)];
  // Format lama (array) dianggap kosong.
  return value && Array.isArray(value.items) ? value : { page: null, items: [] };
}

function setBadge(tabId, count) {
  chrome.action.setBadgeText({ tabId, text: count ? String(count) : "" }).catch(() => {});
  if (count) chrome.action.setBadgeBackgroundColor({ tabId, color: "#F97316" }).catch(() => {});
}

function addMediaItem(tabId, url, headers) {
  if (tabId < 0 || !url) return Promise.resolve();
  return withTabLock(tabId, async () => {
    const state = await readTab(tabId);
    if (state.items.some((i) => i.url === url) || state.items.length >= MAX_ITEMS_PER_TAB) return;
    state.items.push({ url, type: mediaType(url, headers), timestamp: Date.now() });
    await storageArea.set({ [tabKey(tabId)]: state });
    setBadge(tabId, state.items.length);
  });
}

function clearTab(tabId) {
  return withTabLock(tabId, async () => {
    await storageArea.remove(tabKey(tabId));
    setBadge(tabId, 0);
  });
}

// Listener didaftarkan di top level agar tetap aktif setelah service worker dibangunkan ulang.
// Event hanya diterima untuk host yang sudah diizinkan pengguna.
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (isMedia(details.url)) addMediaItem(details.tabId, details.url);
  },
  { urls: ["<all_urls>"] },
);

chrome.webRequest.onResponseStarted.addListener(
  (details) => {
    if (isMedia(details.url, details.responseHeaders)) addMediaItem(details.tabId, details.url, details.responseHeaders);
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"],
);

chrome.tabs.onRemoved.addListener((tabId) => {
  storageArea.remove(tabKey(tabId));
  writeQueues.delete(tabId);
});

// Bersihkan saat tab berpindah ke halaman lain. Perubahan hash (#...) atau reload ke URL yang
// sama tidak menghapus daftar.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!changeInfo.url) return;
  const page = stripHash(changeInfo.url);
  withTabLock(tabId, async () => {
    const state = await readTab(tabId);
    if (state.page === page) return;
    await storageArea.set({ [tabKey(tabId)]: { page, items: [] } });
    setBadge(tabId, 0);
  });
});

// ---------------------------------------------------------------------------------------------
// Kirim ke UMD: memilih sumber terbaik untuk sebuah video
// ---------------------------------------------------------------------------------------------

/**
 * Sumber terbaik untuk dikirim ke UMD:
 * 1. Platform yang didukung yt-dlp (YouTube, dll.) → URL halaman.
 * 2. `src` video berupa file http(s) biasa → URL itu.
 * 3. Video MediaSource (`blob:`) → manifest HLS/DASH terakhir yang tertangkap di tab ini.
 * 4. Selain itu → URL halaman (backend merender & menyadap halamannya).
 */
async function pickSource(tabId, tabUrl, src) {
  if (tabUrl && umdPlatformOf(tabUrl)) return tabUrl;
  if (src && /^https?:/i.test(src) && !PLATFORM_SEGMENT_REGEX.test(src)) return src;
  if (tabId >= 0) {
    const { items } = await readTab(tabId);
    const manifests = items.filter((i) => /HLS|DASH/.test(i.type));
    const videos = items.filter((i) => /Video/.test(i.type));
    const best = manifests.at(-1) || videos.at(-1);
    if (best) return best.url;
  }
  return tabUrl;
}

async function sendToUmd(url, referer) {
  if (!url || !/^https?:/i.test(url)) return;
  chrome.tabs.create({ url: await umdAnalyzeUrl(url, referer) });
}

// ---------------------------------------------------------------------------------------------
// #2 Tombol "Unduh video ini" (content script, hanya setelah izin situs diberikan)
// ---------------------------------------------------------------------------------------------

async function syncOverlayRegistration() {
  const [{ overlayEnabled }, granted, registered] = await Promise.all([
    umdGetSettings(),
    chrome.permissions.contains(ALL_URLS),
    chrome.scripting.getRegisteredContentScripts({ ids: [OVERLAY_SCRIPT_ID] }),
  ]);
  const want = overlayEnabled && granted;
  if (want && registered.length === 0) {
    await chrome.scripting.registerContentScripts([
      {
        id: OVERLAY_SCRIPT_ID,
        js: ["overlay.js"],
        matches: ["http://*/*", "https://*/*"],
        excludeMatches: ["http://localhost/*", "http://127.0.0.1/*"],
        allFrames: true,
        runAt: "document_idle",
      },
    ]);
  } else if (!want && registered.length > 0) {
    await chrome.scripting.unregisterContentScripts({ ids: [OVERLAY_SCRIPT_ID] });
  }
}

chrome.permissions.onAdded.addListener(() => syncOverlayRegistration().catch(console.debug));
chrome.permissions.onRemoved.addListener(() => syncOverlayRegistration().catch(console.debug));
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "overlayEnabled" in changes) syncOverlayRegistration().catch(console.debug);
});

// ---------------------------------------------------------------------------------------------
// #3 Menu klik kanan "Unduh dengan UMD"
// ---------------------------------------------------------------------------------------------

function createMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "umd-media", title: "Unduh media ini dengan UMD", contexts: ["video", "audio", "image"] });
    chrome.contextMenus.create({ id: "umd-link", title: "Unduh tautan ini dengan UMD", contexts: ["link"] });
    chrome.contextMenus.create({ id: "umd-page", title: "Analisis halaman ini dengan UMD", contexts: ["page", "frame"] });
  });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const pageUrl = info.pageUrl || tab?.url;
  let target;
  if (info.menuItemId === "umd-media") target = await pickSource(tab?.id ?? -1, pageUrl, info.srcUrl);
  else if (info.menuItemId === "umd-link") target = info.linkUrl;
  else target = info.frameUrl || pageUrl;
  await sendToUmd(target, pageUrl);
});

// ---------------------------------------------------------------------------------------------
// #4 Tangkap unduhan browser dan alihkan ke UMD (opt-in)
// ---------------------------------------------------------------------------------------------

function extOf(name) {
  const m = /\.([a-z0-9]{1,5})$/i.exec((name || "").split(/[?#]/)[0]);
  return m ? m[1].toLowerCase() : "";
}

async function isOwnUmdUrl(url) {
  try {
    const u = new URL(url);
    const { uiBase } = await umdGetSettings();
    // File hasil unduhan UMD sendiri (Web UI/API lokal) jangan ditangkap ulang.
    return ["localhost", "127.0.0.1", "[::1]"].includes(u.hostname) || u.origin === new URL(uiBase).origin;
  } catch {
    return true;
  }
}

chrome.downloads.onCreated.addListener(async (item) => {
  const settings = await umdGetSettings();
  if (!settings.captureDownloads || item.byExtensionId === chrome.runtime.id) return;
  const url = item.finalUrl || item.url;
  if (!/^https?:/i.test(url) || (await isOwnUmdUrl(url))) return;
  const allowed = String(settings.captureExtensions)
    .split(",")
    .map((x) => x.trim().toLowerCase().replace(/^\./, ""))
    .filter(Boolean);
  const ext = extOf(item.filename) || extOf(url);
  if (!ext || !allowed.includes(ext)) return;
  const size = item.totalBytes > 0 ? item.totalBytes : item.fileSize;
  if (size > 0 && size < Number(settings.captureMinMB) * 1024 * 1024) return;

  try {
    await chrome.downloads.cancel(item.id);
    await chrome.downloads.erase({ id: item.id });
  } catch (e) {
    console.debug("gagal membatalkan unduhan browser:", e);
    return;
  }
  await sendToUmd(url, item.referrer || undefined);
});

chrome.runtime.onInstalled.addListener(() => {
  createMenus();
  syncOverlayRegistration().catch(console.debug);
});
chrome.runtime.onStartup.addListener(() => syncOverlayRegistration().catch(console.debug));

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;

  // Dari content script overlay (tombol di atas video).
  if (request.action === "overlayDownload" && sender.tab) {
    pickSource(sender.tab.id, sender.tab.url, request.src).then((url) => sendToUmd(url, sender.tab.url));
    return false;
  }

  // Perintah lain hanya dari popup ekstensi ini.
  if (sender.tab) return false;

  if (request.action === "getCapturedMedia") {
    readTab(request.tabId).then((state) => sendResponse({ media: state.items }));
    return true;
  }
  if (request.action === "addMediaDirect") {
    const urls = Array.isArray(request.urls) ? request.urls : [request.url];
    Promise.all(urls.filter((u) => isMedia(u)).map((u) => addMediaItem(request.tabId, u))).then(() =>
      sendResponse({ success: true }),
    );
    return true;
  }
  if (request.action === "clearCapturedMedia") {
    clearTab(request.tabId).then(() => sendResponse({ success: true }));
    return true;
  }
  return false;
});
