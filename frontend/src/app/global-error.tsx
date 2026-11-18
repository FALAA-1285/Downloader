"use client";

// Cadangan terakhir bila layout utama sendiri gagal dirender. Tidak memakai komponen/tema
// aplikasi karena justru bagian itu yang mungkin rusak.

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="id">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, background: "#fff", color: "#111" }}>
        <main style={{ maxWidth: 480, margin: "15vh auto", padding: "0 16px", textAlign: "center" }}>
          <h1 style={{ fontSize: 20, marginBottom: 8 }}>Aplikasi mengalami kesalahan</h1>
          <p style={{ color: "#555", fontSize: 14, lineHeight: 1.5 }}>
            Muat ulang halaman untuk mencoba lagi.{error.digest ? ` Kode: ${error.digest}` : ""}
          </p>
          <button
            type="button"
            onClick={reset}
            style={{ marginTop: 16, padding: "8px 16px", borderRadius: 8, border: "1px solid #ccc", cursor: "pointer" }}
          >
            Coba lagi
          </button>
        </main>
      </body>
    </html>
  );
}
