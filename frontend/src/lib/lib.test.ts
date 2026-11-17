import { describe, expect, it } from "vitest";
import { checkUrl } from "./url";
import { cn, extFromName, formatBytes, formatDuration } from "./utils";

describe("checkUrl (FR-01, validasi sisi klien)", () => {
  it("menerima dan menormalisasi URL http/https", () => {
    const res = checkUrl("  https://Example.com/artikel#bagian ");
    expect(res).toEqual({ ok: true, url: "https://example.com/artikel", domain: "example.com" });
  });

  it.each([
    ["", "Tempel URL"],
    ["example.com/halaman", "https://"],
    ["ftp://example.com/a", "tidak didukung"],
    ["http://localhost:3000", "diblokir"],
    ["http://192.168.1.1/admin", "diblokir"],
    ["http://169.254.169.254/latest", "diblokir"],
    ["http://[::1]/", "diblokir"],
    ["http://intranet/", "Domain tidak lengkap"],
    ["https://user:pass@example.com/", "kredensial"],
  ])("menolak %s", (input, message) => {
    const res = checkUrl(input);
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.message).toContain(message);
  });
});

describe("utils", () => {
  it("cn menggabungkan kelas dan menyelesaikan konflik Tailwind", () => {
    expect(cn("bg-bg px-2", false, "bg-ink")).toBe("px-2 bg-ink");
    // Warna kustom tidak boleh dianggap ukuran font: keduanya harus tetap ada.
    expect(cn("text-ink", "text-[13px]")).toBe("text-ink text-[13px]");
    expect(cn("text-ink", "text-brand")).toBe("text-brand");
  });

  it("format ukuran dan durasi", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatDuration(94)).toBe("1:34");
    expect(extFromName("foto.webp")).toBe("WEBP");
  });
});
