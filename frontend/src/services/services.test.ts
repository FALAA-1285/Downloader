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
