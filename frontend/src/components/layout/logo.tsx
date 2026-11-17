export function Logo({ size = 22 }: { size?: number }) {
  // Tanda: bingkai URL dengan panah turun — "tempel alamat, ambil isinya".
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className="shrink-0">
      <rect x="1" y="1" width="22" height="22" rx="6.5" fill="var(--ink)" />
      <path d="M7 7.5h10" stroke="var(--bg)" strokeWidth="1.8" strokeLinecap="round" opacity="0.55" />
      <path d="M12 10.5v6.2M9.2 14l2.8 2.8 2.8-2.8" stroke="var(--bg)" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
