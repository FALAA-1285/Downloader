// Validasi sisi klien (FR-01). Ini hanya umpan balik cepat untuk pengguna —
// validasi keamanan yang sebenarnya (DNS, redirect, SSRF) tetap wajib di backend.

export type UrlCheck =
  | { ok: true; url: string; domain: string }
  | { ok: false; message: string };

const BLOCKED_HOSTS = new Set(["localhost", "0.0.0.0", "[::]", "[::1]", "metadata.google.internal"]);

function isPrivateIPv4(host: string): boolean {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return (
    a === 10 ||
    a === 127 ||
    a === 0 ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 100 && b >= 64 && b <= 127) ||
    a >= 224
  );
}

function isPrivateIPv6(host: string): boolean {
  if (!host.startsWith("[")) return false;
  const h = host.slice(1, -1).toLowerCase();
  return h === "::1" || h.startsWith("fc") || h.startsWith("fd") || h.startsWith("fe80") || h.startsWith("::ffff:");
}

export function checkUrl(raw: string): UrlCheck {
  const input = raw.trim();
  if (!input) return { ok: false, message: "Tempel URL halaman yang ingin dianalisis." };

  let parsed: URL;
  try {
    parsed = new URL(input);
  } catch {
    if (!/^[a-z][a-z0-9+.-]*:/i.test(input) && input.includes(".")) {
      return { ok: false, message: "URL perlu diawali https:// atau http://." };
    }
    return { ok: false, message: "Format URL tidak valid. Periksa kembali alamatnya." };
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { ok: false, message: `Skema ${parsed.protocol.replace(":", "")} tidak didukung. Gunakan http atau https.` };
  }

  const host = parsed.hostname.toLowerCase();
  if (
    BLOCKED_HOSTS.has(host) ||
    host.endsWith(".localhost") ||
    host.endsWith(".local") ||
    host.endsWith(".internal") ||
    isPrivateIPv4(host) ||
    isPrivateIPv6(host)
  ) {
    return { ok: false, message: "Alamat lokal atau jaringan internal diblokir demi keamanan." };
  }
  if (!host.includes(".")) {
    return { ok: false, message: "Domain tidak lengkap. Contoh: https://example.com/artikel" };
  }
  if (parsed.username || parsed.password) {
    return { ok: false, message: "URL berisi kredensial. Hapus bagian nama pengguna dan kata sandi." };
  }

  parsed.hash = "";
  return { ok: true, url: parsed.toString(), domain: host.replace(/^www\./, "") };
}
