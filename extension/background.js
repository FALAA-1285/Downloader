// Background Service Worker untuk Universal Media Downloader Helper

const capturedMedia = new Map(); // tabId -> Array of media items

const MEDIA_REGEX = /\.(m3u8|mpd|mp4|webm|mkv|mov|vtt|srt)(\?.*)?$/i;
const MEDIA_CONTENT_TYPES = [
  "application/x-mpegurl",
  "application/vnd.apple.mpegurl",
  "application/dash+xml",
  "video/mp4",
  "video/webm",
  "video/quicktime",
  "text/vtt",
  "application/x-subrip",
];

function isMedia(url, headers = []) {
  if (MEDIA_REGEX.test(url)) return true;
  for (const h of headers) {
    if (h.name.toLowerCase() === "content-type") {
      const val = h.value.toLowerCase().split(";")[0].trim();
      if (MEDIA_CONTENT_TYPES.includes(val) || val.startsWith("video/")) {
        return true;
      }
    }
  }
  return false;
}

function getMediaType(url, headers = []) {
  const clean = url.split("?")[0].toLowerCase();
  if (clean.endsWith(".m3u8")) return "HLS Stream";
  if (clean.endsWith(".mpd")) return "DASH Stream";
  if (clean.endsWith(".vtt") || clean.endsWith(".srt")) return "Subtitle";
  if (clean.endsWith(".mp4")) return "MP4 Video";
  if (clean.endsWith(".webm")) return "WebM Video";
  for (const h of headers) {
    if (h.name.toLowerCase() === "content-type") {
      const val = h.value.toLowerCase();
      if (val.includes("mpegurl")) return "HLS Stream";
      if (val.includes("dash")) return "DASH Stream";
      if (val.includes("vtt") || val.includes("subrip")) return "Subtitle";
      if (val.includes("mp4")) return "MP4 Video";
    }
  }
  return "Media";
}

// Sniff respons jaringan
chrome.webRequest.onResponseStarted.addListener(
  (details) => {
    const { tabId, url, responseHeaders } = details;
    if (tabId < 0 || !url || url.startsWith("blob:") || url.startsWith("data:")) return;

    if (isMedia(url, responseHeaders)) {
      if (!capturedMedia.has(tabId)) {
        capturedMedia.set(tabId, []);
      }
      const list = capturedMedia.get(tabId);
      if (!list.some((item) => item.url === url)) {
        const type = getMediaType(url, responseHeaders);
        list.push({
          url,
          type,
          timestamp: Date.now(),
        });
        // Perbarui badge jumlah media pada icon ekstensi
        chrome.action.setBadgeText({ tabId, text: String(list.length) });
        chrome.action.setBadgeBackgroundColor({ tabId, color: "#F97316" });
      }
    }
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

// Bersihkan memori saat tab ditutup atau berpindah halaman
chrome.tabs.onRemoved.addListener((tabId) => {
  capturedMedia.delete(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    capturedMedia.delete(tabId);
    chrome.action.setBadgeText({ tabId, text: "" });
  }
});

// Penangan pesan komunikasi dengan popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "getCapturedMedia") {
    const media = capturedMedia.get(request.tabId) || [];
    sendResponse({ media });
    return true;
  }

  if (request.action === "getTabCookies") {
    chrome.cookies.getAll({ url: request.url }, (cookies) => {
      const cookieStr = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
      sendResponse({ cookies: cookieStr });
    });
    return true;
  }

  if (request.action === "clearCapturedMedia") {
    capturedMedia.delete(request.tabId);
    chrome.action.setBadgeText({ tabId: request.tabId, text: "" });
    sendResponse({ success: true });
    return true;
  }
});
