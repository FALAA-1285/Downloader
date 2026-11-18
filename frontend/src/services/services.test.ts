import { afterEach, describe, expect, it, vi } from "vitest";

/** Memuat ulang modul dengan backend "nyata" (bukan mode demo) dan fetch tiruan. */
async function loadWithBackend(fetchImpl: typeof fetch, token = "") {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
  vi.stubEnv("NEXT_PUBLIC_API_TOKEN", token);
  vi.stubGlobal("fetch", vi.fn(fetchImpl));
  const api = await import("./api");
  const store = await import("./jobs-store");
  return { api, store, fetchMock: globalThis.fetch as unknown as ReturnType<typeof vi.fn> };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(async () => {
  (await import("@testing-library/react")).cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("api", () => {
  it("mengirim header klien, token, dan format subtitle", async () => {
    const { api, fetchMock } = await loadWithBackend(async () => json([]), "rahasia");
    await api.createDownloads("analysis-1", ["sub-1"], "srt");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(url).toBe("http://api.test/api/v1/downloads");
    expect(headers["X-UMD-Client"]).toBe("web");
    expect(headers.Authorization).toBe("Bearer rahasia");
    expect(JSON.parse(init.body as string)).toEqual({
      analysis_id: "analysis-1",
      media_ids: ["sub-1"],
      subtitle_format: "srt",
    });
    expect(api.FILE_LINKS_NEED_FETCH).toBe(true);
  });

  it("memakai pesan error dari backend", async () => {
    const { api } = await loadWithBackend(async () =>
      json({ detail: { code: "url_blocked", message: "Alamat lokal diblokir." } }, 400),
    );
    await expect(api.analyzeUrl("http://x.example", [])).rejects.toMatchObject({
      message: "Alamat lokal diblokir.",
      status: 400,
    });
  });
});

describe("jobs-store", () => {
  it("menyimpan error sinkronisasi saat backend mati, lalu menghapusnya saat pulih (M-05)", async () => {
    let up = false;
    const { store } = await loadWithBackend(async () => {
      if (!up) throw new TypeError("Failed to fetch");
      return json([]);
    });
    const errors: Array<string | null> = [];
    const { renderHook } = await import("@testing-library/react");
    const { result } = renderHook(() => store.useSyncError());

    expect(await store.syncHistory()).toBe(false);
    errors.push(result.current);
    up = true;
    expect(await store.syncHistory()).toBe(true);
    errors.push(result.current);

    expect(errors[0]).toContain("Backend tidak dapat dihubungi");
    expect(errors[1]).toBeNull();
  });

  it("hanya membuang job yang benar-benar terhapus di server", async () => {
    const job = (id: string) => ({
      id,
      status: "completed",
      progress: 100,
      filename: `${id}.png`,
      media_type: "image",
      source_url: "https://a.example/",
      source_domain: "a.example",
      size_downloaded: 1,
      size_total: 1,
      error_message: null,
      created_at: "2026-11-17T00:00:00Z",
      completed_at: "2026-11-17T00:00:01Z",
      expires_at: null,
    });
    const { store } = await loadWithBackend(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/history") && !init?.method) return json([job("a"), job("b")]);
      if (url.endsWith("/history/b")) return json({ detail: { message: "gagal" } }, 500);
      return new Response(null, { status: 204 });
    });
    await store.syncHistory();

    await expect(store.removeJobs(["a", "b"])).rejects.toThrow("1 riwayat gagal dihapus");
    const { renderHook } = await import("@testing-library/react");
    const { result } = renderHook(() => store.useJobs());
    expect(result.current.map((j) => j.id)).toEqual(["b"]);
  });
});

describe("cookie per domain (C-03)", () => {
  it("hanya mengirim cookie milik domain URL yang dianalisis", async () => {
    const { api, fetchMock } = await loadWithBackend(async () => json({}));
    const cookies = await import("@/lib/cookie-store");
    cookies.__resetCookieCache();
    cookies.saveCookieEntry("instagram.com", "sessionid=ig");

    await api.analyzeUrl("https://www.instagram.com/p/abc/", []);
    await api.analyzeUrl("https://evil.example/page", []);
    await api.createDownloads("an-1", ["m-1"], "original", undefined, "https://instagram.com/reel/x");

    const bodies = fetchMock.mock.calls.map(([, init]) => JSON.parse((init as RequestInit).body as string));
    expect(bodies[0].cookies).toBe("sessionid=ig");
    expect(bodies[1].cookies).toBeUndefined();
    expect(bodies[2].cookies).toBe("sessionid=ig");
  });

  it("menghapus cookie global lama dan menebak domain dari cookies.txt", async () => {
    localStorage.setItem("umd_session_cookies", "sid=lama");
    const cookies = await import("@/lib/cookie-store");
    cookies.__resetCookieCache();
    expect(cookies.readCookieEntries()).toEqual({});
    expect(localStorage.getItem("umd_session_cookies")).toBeNull();
    expect(cookies.guessCookieDomain("#HttpOnly_.www.example.com\tTRUE\t/\tTRUE\t0\tsid\tx")).toBe("example.com");
    expect(cookies.normalizeDomain("https://Sub.Example.com:8080/x")).toBe("sub.example.com");
    expect(cookies.normalizeDomain("bukan domain")).toBeNull();
  });
});

describe("kontrol unduhan & polling", () => {
  const remoteJob = (id: string, status: string) => ({
    id,
    status,
    progress: null,
    filename: `${id}.mp4`,
    media_type: "video",
    source_url: "https://a.example/",
    source_domain: "a.example",
    size_downloaded: 0,
    size_total: null,
    error_message: null,
    created_at: "2026-11-17T00:00:00Z",
    completed_at: null,
    expires_at: null,
  });

  it("menjeda, melanjutkan, dan membatalkan lewat endpoint khusus", async () => {
    const { store, fetchMock } = await loadWithBackend(async (input) => {
      const url = String(input);
      if (url.endsWith("/history")) return json([remoteJob("a", "downloading")]);
      const action = url.split("/").pop();
      const status = { pause: "paused", resume: "pending", cancel: "cancelled" }[action as string] ?? "pending";
      return json(remoteJob("a", status));
    });
    await store.syncHistory();
    await store.pauseJob("a");
    await store.resumeJob("a");
    await store.cancelJob("a");
    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(urls.slice(1)).toEqual([
      "http://api.test/api/v1/downloads/a/pause",
      "http://api.test/api/v1/downloads/a/resume",
      "http://api.test/api/v1/downloads/a/cancel",
    ]);
    const { renderHook } = await import("@testing-library/react");
    expect(renderHook(() => store.useJobs()).result.current[0].status).toBe("cancelled");
  });

  it("ZIP dibuat di server lalu diunduh lewat tautan biasa (H-05)", async () => {
    const { api, fetchMock } = await loadWithBackend(async () =>
      json({ id: "f".repeat(32), filename: "koleksi.zip", size: 10, file_count: 2, skipped: 0 }, 201),
    );
    const clicks: string[] = [];
    const spy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.href);
    });
    const meta = await api.downloadZipFile(["a", "b"], "koleksi");
    spy.mockRestore();
    expect(meta.file_count).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(1); // tanpa token: tidak ada fetch blob
    expect(clicks[0]).toBe(`http://api.test/api/v1/downloads/zip/${"f".repeat(32)}?name=koleksi.zip`);
  });
});
