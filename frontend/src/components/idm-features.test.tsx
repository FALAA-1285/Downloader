import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { formatEta, formatSpeed } from "@/lib/utils";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
  push.mockReset();
});

describe("format kecepatan & sisa waktu", () => {
  it("menampilkan kecepatan dan ETA seperti IDM", () => {
    expect(formatSpeed(1536 * 1024)).toMatch(/MB\/s$/);
    expect(formatSpeed(0)).toBeNull();
    expect(formatEta(30 * 1024 * 1024, 1024 * 1024)).toBe("sisa 30 dtk");
    expect(formatEta(300 * 1024 * 1024, 1024 * 1024)).toBe("sisa 5 mnt");
    expect(formatEta(100, null)).toBeNull();
  });
});

describe("opsi unduhan terjadwal & batas kecepatan", () => {
  it("mengirim scheduled_at dan max_speed_kbps ke backend", async () => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
    const fetchMock = vi.fn(async () => new Response("[]", { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const api = await import("@/services/api");
    await api.createDownloads("an-1", ["m-1"], "original", undefined, undefined, {
      scheduledAt: "2030-01-01T00:00:00.000Z",
      maxSpeedKbps: 512,
    });
    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
    expect(body.scheduled_at).toBe("2030-01-01T00:00:00.000Z");
    expect(body.max_speed_kbps).toBe(512);
    vi.unstubAllEnvs();
  });
});

describe("pantau clipboard", () => {
  async function mount(clipboardText: string) {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { readText: vi.fn(async () => clipboardText) } });
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    const mod = await import("./layout/clipboard-watcher");
    return mod;
  }

  it("tidak membaca clipboard bila belum diaktifkan", async () => {
    const { ClipboardWatcher } = await mount("https://video.example/watch/1");
    await act(async () => {
      render(<ClipboardWatcher />);
    });
    expect(screen.queryByText("Tautan terdeteksi di clipboard")).toBeNull();
  });

  it("menawarkan analisis untuk URL baru lalu tidak mengulanginya setelah diabaikan", async () => {
    const { ClipboardWatcher, setClipboardWatch } = await mount("https://video.example/watch/1");
    setClipboardWatch(true);
    await act(async () => {
      render(<ClipboardWatcher />);
    });
    expect(await screen.findByText("Tautan terdeteksi di clipboard")).toBeTruthy();

    fireEvent.click(screen.getByText("Analisis"));
    expect(push).toHaveBeenCalledWith("/analyze?url=https%3A%2F%2Fvideo.example%2Fwatch%2F1");

    // URL yang sama tidak ditawarkan lagi saat jendela difokuskan kembali.
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(screen.queryByText("Tautan terdeteksi di clipboard")).toBeNull();
  });

  it("mengabaikan teks yang bukan URL", async () => {
    const { ClipboardWatcher, setClipboardWatch } = await mount("halo apa kabar");
    setClipboardWatch(true);
    await act(async () => {
      render(<ClipboardWatcher />);
    });
    expect(screen.queryByText("Tautan terdeteksi di clipboard")).toBeNull();
  });
});
