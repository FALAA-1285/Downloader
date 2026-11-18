document.addEventListener("DOMContentLoaded", async () => {
  const tabTitle = document.getElementById("tabTitle");
  const tabUrl = document.getElementById("tabUrl");
  const mediaCount = document.getElementById("mediaCount");
  const mediaList = document.getElementById("mediaList");
  const btnAnalyzePage = document.getElementById("btnAnalyzePage");
  const btnCopyCookies = document.getElementById("btnCopyCookies");
  const statusText = document.getElementById("statusText");

  function setStatus(msg) {
    statusText.textContent = msg;
    setTimeout(() => {
      statusText.textContent = "Siap";
    }, 3500);
  }

  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!activeTab) return;

  tabTitle.textContent = activeTab.title || "Tab aktif";
  tabUrl.textContent = activeTab.url || "—";

  btnAnalyzePage.addEventListener("click", () => {
    const webUrl = `http://localhost:3000/analyze?url=${encodeURIComponent(activeTab.url)}`;
    chrome.tabs.create({ url: webUrl });
  });

  btnCopyCookies.addEventListener("click", () => {
    chrome.runtime.sendMessage({ action: "getTabCookies", url: activeTab.url }, (res) => {
      if (res && res.cookies) {
        navigator.clipboard.writeText(res.cookies).then(() => {
          setStatus("✓ Cookie berhasil disalin! Tempel di Settings UMD.");
        });
      } else {
        setStatus("Tidak ada cookie untuk domain ini");
      }
    });
  });

  function renderItems(items) {
    mediaCount.textContent = String(items.length);

    if (items.length === 0) {
      mediaList.innerHTML = `
        <div class="empty-state">
          <p>Belum ada stream terdeteksi.</p>
          <small>Coba putar video di halaman (klik play), lalu buka kembali popup ini.</small>
        </div>
      `;
      return;
    }

    mediaList.innerHTML = "";
    items.forEach((item) => {
      const el = document.createElement("div");
      el.className = "media-item";
      el.innerHTML = `
        <div class="media-header">
          <span class="media-tag">${item.type}</span>
        </div>
        <div class="media-url" title="${item.url}">${item.url}</div>
        <div class="media-actions">
          <button class="btn-small btn-copy">Salin URL</button>
          <button class="btn-small btn-download">Unduh via UMD</button>
        </div>
      `;

      el.querySelector(".btn-copy").addEventListener("click", () => {
        navigator.clipboard.writeText(item.url).then(() => {
          setStatus("✓ URL stream disalin!");
        });
      });

      el.querySelector(".btn-download").addEventListener("click", () => {
        const webUrl = `http://localhost:3000/analyze?url=${encodeURIComponent(item.url)}`;
        chrome.tabs.create({ url: webUrl });
      });

      mediaList.appendChild(el);
    });
  }

  function fetchStoredMedia() {
    chrome.runtime.sendMessage({ action: "getCapturedMedia", tabId: activeTab.id }, (response) => {
      const items = (response && response.media) || [];
      renderItems(items);
    });
  }

  // 1. Tampilkan media yang sudah tersimpan di background service worker
  fetchStoredMedia();

  // 2. Pindai DOM dan Resource Timing tab aktif secara langsung
  if (activeTab.id && activeTab.url && !activeTab.url.startsWith("chrome://")) {
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: activeTab.id, allFrames: true },
        func: () => {
          const found = [];
          const STREAM_PATTERN = /((\.m3u8|\.mpd|\.mp4|\.webm|\.mkv|\.mov|\.vtt|\.srt|\.ts|\.m4s)(\?|$|#)|(\/hls\/|\/manifest|\/playlist|master\.m3u8))/i;

          // Riwayat request jaringan yang sudah dipanggil oleh tab ini sejak awal dimuat
          try {
            const entries = performance.getEntriesByType("resource");
            for (const e of entries) {
              if (e.name && STREAM_PATTERN.test(e.name)) {
                found.push(e.name);
              }
            }
          } catch {}

          // Elemen video/audio/iframe di dalam DOM tab
          try {
            document.querySelectorAll("video, audio").forEach((v) => {
              if (v.currentSrc) found.push(v.currentSrc);
              if (v.src) found.push(v.src);
            });
            document.querySelectorAll("source").forEach((s) => {
              if (s.src) found.push(s.src);
            });
            document.querySelectorAll("iframe").forEach((f) => {
              const src = f.src || f.getAttribute("data-src") || "";
              if (src && (STREAM_PATTERN.test(src) || src.includes("embed") || src.includes("player") || src.includes("videonode") || src.includes("cloudemb"))) {
                found.push(src);
              }
            });
            document.querySelectorAll("track").forEach((t) => {
              if (t.src) found.push(t.src);
            });
          } catch {}

          return found.filter((u) => u && !u.startsWith("blob:") && !u.startsWith("data:"));
        },
      });

      if (results && results.length > 0) {
        const directUrls = new Set();
        results.forEach((frame) => {
          if (frame.result && Array.isArray(frame.result)) {
            frame.result.forEach((u) => directUrls.add(u));
          }
        });

        // Daftarkan ke background
        for (const u of directUrls) {
          chrome.runtime.sendMessage({
            action: "addMediaDirect",
            tabId: activeTab.id,
            url: u,
          });
        }

        // Segarkan tampilan daftar media di popup
        setTimeout(fetchStoredMedia, 300);
      }
    } catch (e) {
      console.debug("Script injection bypassed on restricted tab:", e);
    }
  }
});
