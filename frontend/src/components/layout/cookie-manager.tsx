"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import {
  dismissLegacyNotice,
  guessCookieDomain,
  normalizeDomain,
  removeCookieEntry,
  saveCookieEntry,
  useCookieEntries,
  useLegacyCookieNotice,
} from "@/lib/cookie-store";
import { Button } from "@/components/ui/button";

const inputCls =
  "w-full rounded-xl border border-line-strong bg-bg font-mono text-[12px] text-ink outline-none placeholder:text-muted-foreground/60 focus:border-brand focus:shadow-[0_0_0_3px_var(--ring-soft)]";

/** Kelola cookie sesi per domain. Cookie hanya dikirim ke domain pemiliknya (C-03). */
export function CookieManager() {
  const entries = useCookieEntries();
  const [domain, setDomain] = useState("");
  const [value, setValue] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const legacyNotice = useLegacyCookieNotice();
  const domains = Object.keys(entries).sort();

  function save() {
    try {
      const saved = saveCookieEntry(domain || guessCookieDomain(value) || "", value);
      setDomain("");
      setValue("");
      setMessage({ ok: true, text: `Cookie untuk ${saved} tersimpan di browser ini.` });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      {legacyNotice && (
        <div role="status" className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-[12px] text-ink-2">
          <span>Cookie lama yang dulu berlaku untuk semua situs telah dihapus demi keamanan. Tambahkan lagi per domain.</span>
          <button type="button" onClick={dismissLegacyNotice} className="shrink-0 text-muted-foreground hover:text-ink">
            Tutup
          </button>
        </div>
      )}

      {domains.length > 0 ? (
        <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line">
          {domains.map((d) => (
            <li key={d} className="flex items-center justify-between gap-3 px-4 py-2.5">
              <div className="min-w-0">
                <p className="truncate font-mono text-[13px] text-ink">{d}</p>
                <p className="text-[11px] text-muted-foreground">
                  Dikirim ke {d} dan subdomainnya · {entries[d].length.toLocaleString("id-ID")} karakter
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                onClick={() => removeCookieEntry(d)}
                className="text-muted-foreground hover:bg-bad-bg hover:text-bad"
                aria-label={`Hapus cookie ${d}`}
                title="Hapus"
              >
                <Trash2 className="size-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted-foreground">Belum ada cookie tersimpan.</p>
      )}

      <div className="space-y-2">
        <label htmlFor="cookie-domain" className="block text-[12px] font-medium text-ink">
          Domain
        </label>
        <input
          id="cookie-domain"
          value={domain}
          onChange={(e) => {
            setDomain(e.target.value);
            setMessage(null);
          }}
          placeholder={guessCookieDomain(value) ?? "instagram.com"}
          className={`${inputCls} h-9 px-3`}
          aria-invalid={domain !== "" && normalizeDomain(domain) === null}
        />
        <label htmlFor="cookie-value" className="block text-[12px] font-medium text-ink">
          Cookie
        </label>
        <textarea
          id="cookie-value"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setMessage(null);
          }}
          placeholder="Tempel cookies.txt (Netscape), JSON dari ekstensi, atau nama=nilai; nama2=nilai2"
          rows={4}
          className={`${inputCls} p-3`}
        />
        <p className="text-[11px] text-muted-foreground">
          Untuk cookies.txt atau JSON, domain diisi otomatis dari isinya bila dikosongkan.
        </p>
        <div className="flex items-center gap-3">
          <Button type="button" size="sm" onClick={save} disabled={!value.trim()}>
            Simpan cookie
          </Button>
          {message && (
            <span role="status" className={message.ok ? "text-[12px] text-ok" : "text-[12px] text-bad"}>
              {message.text}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
