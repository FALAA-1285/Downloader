// Popup — Universal Media Downloader Helper.
// Semua teks dari halaman (URL, judul) dirender dengan textContent, bukan innerHTML (M-08).

const DEFAULT_BASE = UMD_DEFAULTS.uiBase;
const ALL_URLS = { origins: ["<all_urls>"] };
const platformOf = umdPlatformOf;
let currentPlatform = null;

const $ = (id) => document.getElementById(id);

let statusTimer = null;
function setStatus(msg) {
  const node = $("statusText");
  node.textContent = msg;
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => {
    node.textContent = "Siap";
  }, 3500);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

async function getUiBase() {
  return (await umdGetSettings()).uiBase || DEFAULT_BASE;
}

function normalizeBase(value) {
  try {
    const u = new URL(value.trim());
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    return u.origin;
  } catch {
    return null;
  }
}

async function openAnalyze(url, referer) {
  // Tautan stream bertoken sering hanya dilayani bila Referer-nya halaman asal.
  chrome.tabs.create({ url: await umdAnalyzeUrl(url, referer) });
}

async function initOptions() {
  const settings = await umdGetSettings();
  $("optOverlay").checked = settings.overlayEnabled;
  $("optCapture").checked = settings.captureDownloads;
  $("optExts").value = settings.captureExtensions;
  $("optMinMB").value = String(settings.captureMinMB);
  $("captureOpts").hidden = !settings.captureDownloads;

  $("optOverlay").addEventListener("change", async (e) => {
    await chrome.storage.local.set({ overlayEnabled: e.target.checked });
    setStatus(e.target.checked ? "✓ Tombol unduh aktif (muat ulang tab)" : "Tombol unduh dimatikan");
  });
  $("optCapture").addEventListener("change", async (e) => {
    await chrome.storage.local.set({ captureDownloads: e.target.checked });
    $("captureOpts").hidden = !e.target.checked;
    setStatus(e.target.checked ? "✓ Unduhan browser dialihkan ke UMD" : "Unduhan browser tidak dialihkan");
  });
  $("optExts").addEventListener("change", async (e) => {
    const exts = e.target.value
      .split(",")
      .map((x) => x.trim().toLowerCase().replace(/^\./, ""))
      .filter((x) => /^[a-z0-9]{1,5}$/.test(x));
    e.target.value = exts.join(",");
    await chrome.storage.local.set({ captureExtensions: e.target.value });
    setStatus("✓ Jenis file disimpan");
  });
  $("optMinMB").addEventListener("change", async (e) => {
    const value = Math.max(0, Math.floor(Number(e.target.value) || 0));
    e.target.value = String(value);
    await chrome.storage.local.set({ captureMinMB: value });
    setStatus("✓ Ukuran minimum disimpan");
  });
}

let pageUrl = null;

/** Cookie tab dalam format Netscape cookies.txt (domain, path, secure, HttpOnly, kedaluwarsa). */
function toNetscape(cookies) {
  const lines = ["# Netscape HTTP Cookie File"];
  for (const c of cookies) {
    const domain = c.hostOnly ? c.domain : `.${c.domain.replace(/^\./, "")}`;
    lines.push(
      [
        `${c.httpOnly ? "#HttpOnly_" : ""}${domain}`,
        c.hostOnly ? "FALSE" : "TRUE",
        c.path || "/",
        c.secure ? "TRUE" : "FALSE",
        String(Math.floor(c.expirationDate || 0)),
        c.name,
        c.value,
      ].join("\t"),
    );
  }
  return lines.join("\n") + "\n";
}

function renderItems(items) {
  const list = $("mediaList");
  $("mediaCount").textContent = String(items.length);
  list.replaceChildren();

  if (items.length === 0) {
    const empty = el("div", "empty-state");
    if (currentPlatform) {
      empty.append(
        el("p", null, `${currentPlatform} didukung langsung — tidak perlu menangkap stream.`),
        el(
          "small",
          null,
          `${currentPlatform} memutar video dalam potongan-potongan terpisah, bukan satu tautan. ` +
            "Tekan “Buka di Web UI”: server akan mengambil video & audio kualitas terbaik secara utuh.",
        ),
      );
    } else {
      empty.append(
        el("p", null, "Belum ada stream terdeteksi."),
        el("small", null, "Putar video di tab ini (klik play), lalu buka kembali popup ini."),
      );
    }
    list.append(empty);
    return;
  }

  for (const item of items) {
    const row = el("div", "media-item");
    const header = el("div", "media-header");
    header.append(el("span", "media-tag", item.type));
    const urlEl = el("div", "media-url", item.url);
    urlEl.title = item.url;
    const actions = el("div", "media-actions");
    const copy = el("button", "btn-small btn-copy", "Salin URL");
    copy.addEventListener("click", async () => {
      await navigator.clipboard.writeText(item.url);
      setStatus("✓ URL stream disalin");
    });
    const send = el("button", "btn-small btn-download", "Unduh via UMD");
    send.addEventListener("click", () => openAnalyze(item.url, pageUrl));
    actions.append(copy, send);
    row.append(header, urlEl, actions);
    list.append(row);
  }
}

function fetchStoredMedia(tabId) {
  chrome.runtime.sendMessage({ action: "getCapturedMedia", tabId }, (response) => {
    renderItems((response && response.media) || []);
  });
}

async function scanTab(tab) {
  // Pindai elemen media & riwayat Resource Timing tab (izin activeTab, tanpa akses host permanen).
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: () => {
        const found = new Set();
        try {
          for (const e of performance.getEntriesByType("resource")) found.add(e.name);
        } catch {
          // Resource Timing tidak tersedia di frame ini.
        }
        document.querySelectorAll("video, audio, source, track").forEach((m) => {
          if (m.currentSrc) found.add(m.currentSrc);
          if (m.src) found.add(m.src);
        });
        return [...found].filter((u) => /^https?:/i.test(u));
      },
    });
    const urls = new Set();
    for (const frame of results || []) for (const u of frame.result || []) urls.add(u);
    if (urls.size) {
      chrome.runtime.sendMessage({ action: "addMediaDirect", tabId: tab.id, urls: [...urls] }, () =>
        fetchStoredMedia(tab.id),
      );
    }
  } catch (e) {
    console.debug("Pemindaian tab dilewati (halaman dibatasi):", e);
  }
}

async function refreshPermissionUi() {
  const granted = await chrome.permissions.contains(ALL_URLS);
  $("permissionBox").hidden = granted;
  $("btnRevoke").hidden = !granted;
  return granted;
}

document.addEventListener("DOMContentLoaded", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const base = await getUiBase();
  $("webLink").href = base;
  $("uiBase").value = base;
  await refreshPermissionUi();
  await initOptions();
  if (!tab) return;

  $("tabTitle").textContent = tab.title || "Tab aktif";
  $("tabUrl").textContent = tab.url || "—";
  currentPlatform = tab.url ? platformOf(tab.url) : null;
  pageUrl = tab.url || null;
  if (currentPlatform) $("btnAnalyzePage").textContent = `Unduh dari ${currentPlatform} via Web UI`;

  $("btnAnalyzePage").addEventListener("click", () => tab.url && openAnalyze(tab.url));

  $("btnGrant").addEventListener("click", async () => {
    const ok = await chrome.permissions.request(ALL_URLS);
    await refreshPermissionUi();
    setStatus(ok ? "✓ Diizinkan. Muat ulang tab lalu putar videonya." : "Izin tidak diberikan.");
  });

  $("btnRevoke").addEventListener("click", async () => {
    await chrome.permissions.remove(ALL_URLS);
    await refreshPermissionUi();
    setStatus("Izin penangkapan jaringan dicabut.");
  });

  $("btnSaveBase").addEventListener("click", async () => {
    const value = normalizeBase($("uiBase").value);
    if (!value) {
      setStatus("Alamat tidak valid. Contoh: http://localhost:3000");
      return;
    }
    await chrome.storage.local.set({ uiBase: value });
    $("webLink").href = value;
    $("uiBase").value = value;
    setStatus("✓ Alamat Web UI disimpan");
  });

  $("btnCopyCookies").addEventListener("click", async () => {
    if (!tab.url || !/^https?:/i.test(tab.url)) {
      setStatus("Tab ini tidak memiliki cookie situs.");
      return;
    }
    // Akses cookie diminta hanya untuk situs tab ini, saat tombol ditekan.
    const origin = `${new URL(tab.url).origin}/*`;
    const ok = await chrome.permissions.request({ origins: [origin] });
    if (!ok) {
      setStatus("Izin membaca cookie situs ini tidak diberikan.");
      return;
    }
    const cookies = await chrome.cookies.getAll({ url: tab.url });
    if (!cookies.length) {
      setStatus("Tidak ada cookie untuk situs ini.");
      return;
    }
    await navigator.clipboard.writeText(toNetscape(cookies));
    setStatus(`✓ ${cookies.length} cookie disalin. Tempel di Settings UMD.`);
  });

  renderItems([]);
  fetchStoredMedia(tab.id);
  if (tab.id && tab.url && /^https?:/i.test(tab.url)) await scanTab(tab);
});
