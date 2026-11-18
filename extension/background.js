// Background Service Worker untuk Universal Media Downloader Helper (Manifest V3)

const storageArea = chrome.storage.session || chrome.storage.local;

// Regex untuk mendeteksi stream video, subtitle, dan segmen
const STREAM_REGEX = /((\.m3u8|\.mpd|\.mp4|\.webm|\.mkv|\.mov|\.vtt|\.srt|\.ts|\.m4s)(\?|$|#)|(\/hls\/|\/manifest|\/playlist|master\.m3u8))/i;

const MEDIA_CONTENT_TYPES = [
  "application/x-mpegurl",
  "application/vnd.apple.mpegurl",
  "application/dash+xml",
  "video/mp4",
  "video/webm",
  "video/quicktime",
  "video/mp2t",
  "text/vtt",
  "application/x-subrip",
];

const PLAYER_HOSTS = [
  "cloudemb",
  "videonode",
  "streamtape",
  "upstream",
  "dood",
  "mixdrop",
  "fembed",
  "embed",
];

function isMedia(url, headers = []) {
  if (!url || url.startsWith("blob:") || url.startsWith("data:")) return false;
  if (STREAM_REGEX.test(url)) return true;

  try {
    const host = new URL(url).hostname.toLowerCase();
    if (PLAYER_HOSTS.some((p) => host.includes(p)) && url.includes("embed")) {
      return true;
    }
  } catch {}

  for (const h of headers) {
    if (h.name && h.name.toLowerCase() === "content-type") {
      const val = (h.value || "").toLowerCase().split(";")[0].trim();
      if (MEDIA_CONTENT_TYPES.includes(val) || val.startsWith("video/")) {
        return true;
      }
    }
  }
  return false;
}

function getMediaType(url, headers = []) {
  const clean = url.split("?")[0].toLowerCase();
  if (clean.includes(".m3u8") || clean.includes("hls")) return "HLS Stream (.m3u8)";
  if (clean.includes(".mpd") || clean.includes("dash")) return "DASH Stream (.mpd)";
  if (clean.includes(".vtt") || clean.includes(".srt")) return "Subtitle";
  if (clean.includes(".mp4")) return "MP4 Video";
  if (clean.includes(".webm")) return "WebM Video";
  if (clean.includes(".ts") || clean.includes(".m4s")) return "HLS/DASH Segment";

  for (const h of headers) {
    if (h.name && h.name.toLowerCase() === "content-type") {
      const val = (h.value || "").toLowerCase();
      if (val.includes("mpegurl")) return "HLS Stream (.m3u8)";
      if (val.includes("dash")) return "DASH Stream (.mpd)";
      if (val.includes("vtt") || val.includes("subrip")) return "Subtitle";
      if (val.includes("mp4")) return "MP4 Video";
      if (val.includes("mp2t")) return "HLS Segment (.ts)";
    }
  }
  return "Stream Video";
}

async function addMediaItem(tabId, url, headers = []) {
  if (tabId < 0 || !url) return;
  const key = `tab_${tabId}`;
  const res = await storageArea.get(key);
  const items = res[key] || [];

  if (items.some((i) => i.url === url)) return;

  const type = getMediaType(url, headers);
  // Jangan spam badge dengan ratusan segmen .ts/.m4s individual jika stream master .m3u8 sudah tertangkap
  const hasMaster = items.some((i) => i.url.includes(".m3u8"));
  if (hasMaster && (type.includes("Segment") || url.includes(".ts"))) {
    return;
  }

  items.push({
    url,
    type,
    timestamp: Date.now(),
  });

  await storageArea.set({ [key]: items });

  try {
    chrome.action.setBadgeText({ tabId, text: String(items.length) });
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#F97316" });
  } catch {}
}

// Tangkap sebelum request (cepat, tidak bergantung pada respons jaringan selesai)
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    const { tabId, url } = details;
    if (isMedia(url)) {
      addMediaItem(tabId, url);
    }
  },
  { urls: ["<all_urls>"] }
);

// Tangkap juga saat respons header diterima (memeriksa content-type)
chrome.webRequest.onResponseStarted.addListener(
  (details) => {
    const { tabId, url, responseHeaders } = details;
    if (isMedia(url, responseHeaders)) {
      addMediaItem(tabId, url, responseHeaders);
    }
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

// Bersihkan hanya saat tab ditutup
chrome.tabs.onRemoved.addListener((tabId) => {
  storageArea.remove(`tab_${tabId}`);
});

// Bersihkan hanya bila URL tab berpindah ke halaman lain (bukan reload atau hash change)
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) {
    storageArea.remove(`tab_${tabId}`);
    try {
      chrome.action.setBadgeText({ tabId, text: "" });
    } catch {}
  }
});

// Penangan pesan komunikasi dengan popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "getCapturedMedia") {
    const key = `tab_${request.tabId}`;
    storageArea.get(key).then((res) => {
      sendResponse({ media: res[key] || [] });
    });
    return true; // async
  }

  if (request.action === "getTabCookies") {
    chrome.cookies.getAll({ url: request.url }, (cookies) => {
      const cookieStr = (cookies || []).map((c) => `${c.name}=${c.value}`).join("; ");
      sendResponse({ cookies: cookieStr });
    });
    return true; // async
  }

  if (request.action === "addMediaDirect") {
    addMediaItem(request.tabId, request.url, request.headers || []).then(() => {
      sendResponse({ success: true });
    });
    return true; // async
  }

  if (request.action === "clearCapturedMedia") {
    storageArea.remove(`tab_${request.tabId}`).then(() => {
      try {
        chrome.action.setBadgeText({ tabId: request.tabId, text: "" });
      } catch {}
      sendResponse({ success: true });
    });
    return true; // async
  }
});
