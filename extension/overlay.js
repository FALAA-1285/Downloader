// Content script: tombol "Unduh video ini" di atas pemutar video (ala IDM/1DM).
// Hanya didaftarkan setelah pengguna mengizinkan akses situs dari popup, dan bisa dimatikan
// di Pengaturan popup. Elemen dibuat di Shadow DOM agar tidak terpengaruh/memengaruhi CSS situs.

(() => {
  if (window.__umdOverlayLoaded) return;
  window.__umdOverlayLoaded = true;

  const MIN_WIDTH = 200;
  const MIN_HEIGHT = 120;

  let host = null;
  let button = null;
  let label = null;
  let target = null;
  let hideTimer = null;

  function ensureButton() {
    if (button) return button;
    host = document.createElement("umd-download-overlay");
    host.style.cssText = "position:fixed;top:0;left:0;width:0;height:0;z-index:2147483647;";
    const root = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `
      button {
        position: fixed; display: none; align-items: center; gap: 6px;
        padding: 6px 10px; border: 0; border-radius: 8px; cursor: pointer;
        font: 600 12px/1 -apple-system, "Segoe UI", Roboto, sans-serif;
        color: #fff; background: rgba(9, 9, 11, .85); box-shadow: 0 2px 10px rgba(0,0,0,.35);
      }
      button:hover { background: #f97316; }
      button svg { width: 14px; height: 14px; }
    `;
    button = document.createElement("button");
    button.type = "button";
    button.title = "Unduh dengan Universal Media Downloader";
    button.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>';
    label = document.createElement("span");
    label.textContent = "Unduh video ini";
    button.append(label);
    button.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    button.addEventListener("mouseleave", scheduleHide);
    button.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!target) return;
      const src = target.currentSrc || target.src || "";
      chrome.runtime.sendMessage({ action: "overlayDownload", src, frameUrl: location.href });
      label.textContent = "✓ Dikirim ke UMD";
      setTimeout(hide, 1200);
    });
    root.append(style, button);
    document.documentElement.append(host);
    return button;
  }

  function place() {
    if (!target || !button) return;
    const r = target.getBoundingClientRect();
    if (r.width < MIN_WIDTH || r.height < MIN_HEIGHT || r.bottom < 0 || r.top > innerHeight) {
      hide();
      return;
    }
    button.style.top = `${Math.max(r.top + 10, 4)}px`;
    button.style.left = `${Math.min(r.right - 10, innerWidth - 4)}px`;
    button.style.transform = "translateX(-100%)";
  }

  function show(video) {
    if (document.fullscreenElement) return;
    clearTimeout(hideTimer);
    target = video;
    const b = ensureButton();
    label.textContent = "Unduh video ini";
    b.style.display = "inline-flex";
    place();
  }

  function hide() {
    if (button) button.style.display = "none";
    target = null;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, 600);
  }

  // Delegasi event: bekerja juga untuk <video> yang ditambahkan belakangan oleh situs SPA.
  document.addEventListener(
    "mouseover",
    (e) => {
      const el = e.target;
      const video = el instanceof HTMLVideoElement ? el : el?.closest?.("video");
      if (video) show(video);
      else if (target && !target.contains(el)) {
        // Banyak pemutar menaruh lapisan kontrol di atas <video>; cek posisi kursor.
        const r = target.getBoundingClientRect();
        const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
        if (!inside) scheduleHide();
      } else if (!target) {
        // Kursor di atas lapisan kontrol yang menutupi video.
        for (const v of document.querySelectorAll("video")) {
          const r = v.getBoundingClientRect();
          if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
            show(v);
            break;
          }
        }
      }
    },
    { passive: true, capture: true },
  );
  addEventListener("scroll", place, { passive: true, capture: true });
  addEventListener("resize", place, { passive: true });
  document.addEventListener("fullscreenchange", hide);
})();
