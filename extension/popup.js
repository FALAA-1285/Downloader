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
    }, 3000);
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
          setStatus("✓ Cookie berhasil disalin!");
        });
      } else {
        setStatus("Tidak ada cookie untuk domain ini");
      }
    });
  });

  chrome.runtime.sendMessage({ action: "getCapturedMedia", tabId: activeTab.id }, (response) => {
    const items = (response && response.media) || [];
    mediaCount.textContent = String(items.length);

    if (items.length === 0) {
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
  });
});
