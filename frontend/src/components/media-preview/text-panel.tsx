"use client";

import { useState } from "react";
import { Check, Copy, FileDown, FileQuestion } from "lucide-react";
import type { AnalyzeResult } from "@/types";
import { recordTextExport } from "@/services/jobs-store";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/primitives";

function slugify(s: string) {
  return (
    s
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/[\s_]+/g, "-")
      .slice(0, 60) || "teks-halaman"
  );
}

export function TextPanel({ result }: { result: AnalyzeResult }) {
  const [copied, setCopied] = useState(false);
  const [exported, setExported] = useState(false);
  const text = result.text;

  if (!text?.content) {
    return (
      <EmptyState icon={<FileQuestion className="size-5" />} title="Teks utama tidak terdeteksi">
        Halaman ini tidak memiliki elemen artikel yang jelas, atau isinya dimuat dengan JavaScript setelah halaman terbuka.
      </EmptyState>
    );
  }

  const fullText = `${text.title ?? ""}\n\n${text.content}\n\nSumber: ${result.page.url}\n`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(fullText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {}
  }

  function exportTxt() {
    const blob = new Blob([fullText], { type: "text/plain;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const filename = `${slugify(text?.title ?? result.source.domain)}.txt`;
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    a.click();
    // Data URL disimpan agar file bisa disimpan lagi dari halaman Downloads.
    const reader = new FileReader();
    reader.onload = () => recordTextExport(result, filename, blob.size, String(reader.result));
    reader.readAsDataURL(blob);
    setTimeout(() => URL.revokeObjectURL(href), 1000);
    setExported(true);
    setTimeout(() => setExported(false), 1800);
  }

  return (
    <div className="mx-auto max-w-[720px]">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <p className="text-[13px] tabular-nums text-ink-2">
          {text.word_count.toLocaleString("id-ID")} kata · navigasi dan iklan sudah dikurangi
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={copy} aria-live="polite">
            {copied ? <Check className="size-3.5 text-ok" /> : <Copy className="size-3.5" />}
            {copied ? "Tersalin" : "Salin teks"}
          </Button>
          <Button size="sm" onClick={exportTxt}>
            {exported ? <Check className="size-3.5" /> : <FileDown className="size-3.5" />}
            {exported ? "Diekspor" : "Ekspor TXT"}
          </Button>
        </div>
      </div>
      <article>
        {text.title && <h2 className="font-display text-[24px] font-semibold leading-snug tracking-[-0.02em] text-ink">{text.title}</h2>}
        <div className="mt-4 space-y-4 text-[16px] leading-[1.7] text-ink-2">
          {text.content.split(/\n{2,}/).map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </div>
      </article>
    </div>
  );
}
