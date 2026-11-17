import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { FileText, Film, Image as ImageIcon, Music, Captions } from "lucide-react";
import type { JobStatus, MediaType } from "@/types";
import { MEDIA_LABEL, STATUS_LABEL, cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium transition-colors disabled:pointer-events-none disabled:opacity-45 select-none";

const variants: Record<Variant, string> = {
  primary: "bg-ink text-bg hover:bg-ink/85 shadow-[inset_0_1px_0_rgb(255_255_255/0.12)]",
  secondary: "bg-bg text-ink border border-line-strong hover:bg-surface-2 shadow-[0_1px_1px_rgb(0_0_0/0.04)]",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
  danger: "text-bad hover:bg-bad-bg",
};

const sizes: Record<Size, string> = {
  sm: "h-7 px-2.5 text-[13px] rounded-md",
  md: "h-9 px-3.5 text-sm rounded-lg",
  lg: "h-11 px-5 text-[15px] rounded-[10px]",
};

export function buttonClass(variant: Variant = "secondary", size: Size = "md", className?: string) {
  return cn(base, variants[variant], sizes[size], className);
}

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ComponentProps<"button"> & { variant?: Variant; size?: Size }) {
  return <button type="button" className={buttonClass(variant, size, className)} {...props} />;
}

export function ButtonLink({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant; size?: Size }) {
  return <Link className={buttonClass(variant, size, className)} {...props} />;
}

const TYPE_ICON: Record<MediaType, typeof FileText> = {
  image: ImageIcon,
  video: Film,
  subtitle: Captions,
  text: FileText,
  audio: Music,
};

export function TypeIcon({ type, className }: { type: MediaType; className?: string }) {
  const Icon = TYPE_ICON[type];
  return <Icon className={cn("size-3.5", className)} aria-hidden />;
}

export function TypeTag({ type, className }: { type: MediaType; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-[22px] items-center gap-1 rounded-md px-1.5 text-xs font-medium",
        className,
      )}
      style={{ background: `var(--tag-${type}-bg)`, color: `var(--tag-${type}-fg)` }}
    >
      <TypeIcon type={type} className="size-3" />
      {MEDIA_LABEL[type]}
    </span>
  );
}

const STATUS_STYLE: Record<JobStatus, string> = {
  pending: "bg-idle-bg text-idle",
  processing: "bg-run-bg text-run",
  downloading: "bg-run-bg text-run",
  completed: "bg-ok-bg text-ok",
  failed: "bg-bad-bg text-bad",
};

export function StatusPill({ status, label }: { status: JobStatus; label?: string }) {
  const live = status === "processing" || status === "downloading";
  return (
    <span className={cn("inline-flex h-[22px] items-center gap-1.5 rounded-full px-2 text-xs font-medium", STATUS_STYLE[status])}>
      <span className={cn("size-1.5 rounded-full bg-current", live && "animate-pulse")} aria-hidden />
      {label ?? STATUS_LABEL[status]}
    </span>
  );
}

export function Progress({ value, className }: { value: number | null; className?: string }) {
  return (
    <div
      className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-surface-2", className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value ?? undefined}
      aria-label={value == null ? "Progres tidak diketahui" : `${value}%`}
    >
      {value == null ? (
        <div className="indeterminate absolute inset-y-0 w-2/5 rounded-full bg-run/70" />
      ) : (
        <div className="h-full rounded-full bg-run transition-[width] duration-300" style={{ width: `${value}%` }} />
      )}
    </div>
  );
}

export function Checkbox({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      type="checkbox"
      className={cn(
        "ui-checkbox size-4 shrink-0 cursor-pointer appearance-none rounded-[5px] border border-line-strong bg-bg transition-colors",
        "checked:border-accent checked:bg-accent indeterminate:border-accent indeterminate:bg-accent",
        "disabled:cursor-not-allowed disabled:opacity-40",
        className,
      )}
      {...props}
    />
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-line-strong bg-surface px-1 font-sans text-[11px] text-muted">
      {children}
    </kbd>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 border-b border-line px-5 pb-8 pt-12 sm:flex-row sm:items-end sm:justify-between sm:px-10 sm:pt-16">
      <div className="max-w-xl">
        <h1 className="font-display text-[34px] font-semibold leading-[1.1] tracking-[-0.025em] text-ink sm:text-[40px]">{title}</h1>
        {description && <p className="mt-3 text-[15px] leading-relaxed text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-16 text-center">
      <div className="mb-4 grid size-11 place-items-center rounded-xl border border-line bg-surface text-muted">{icon}</div>
      <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
      {children && <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-ink-2">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
