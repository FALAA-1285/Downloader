/**
 * Komponen khusus aplikasi yang dibangun di atas shadcn/ui (Badge, Progress, buttonVariants).
 * Komponen dasar (Button, Checkbox, Tabs, ...) diimpor langsung dari `@/components/ui/*`.
 */
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import type { VariantProps } from "class-variance-authority";
import { Captions, FileText, Film, Image as ImageIcon, Music } from "lucide-react";
import type { JobStatus, MediaType } from "@/types";
import { MEDIA_LABEL, STATUS_LABEL, cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Progress as ProgressBar } from "@/components/ui/progress";

/** Link bergaya tombol (shadcn `buttonVariants` pada next/link). */
export function ButtonLink({
  variant = "outline",
  size,
  className,
  ...props
}: ComponentProps<typeof Link> & VariantProps<typeof buttonVariants>) {
  return <Link className={cn(buttonVariants({ variant, size }), className)} {...props} />;
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
    <Badge
      variant="outline"
      className={cn("h-[22px] gap-1 rounded-md border-transparent px-1.5 text-xs font-medium", className)}
      style={{ background: `var(--tag-${type}-bg)`, color: `var(--tag-${type}-fg)` }}
    >
      <TypeIcon type={type} className="size-3" />
      {MEDIA_LABEL[type]}
    </Badge>
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
    <Badge
      variant="outline"
      className={cn("h-[22px] gap-1.5 rounded-full border-transparent px-2 text-xs font-medium", STATUS_STYLE[status])}
    >
      <span className={cn("size-1.5 rounded-full bg-current", live && "animate-pulse")} aria-hidden />
      {label ?? STATUS_LABEL[status]}
    </Badge>
  );
}

/** Progres nyata bila diketahui; animasi tak tentu bila ukuran total tidak diketahui (PRD §12.3). */
export function Progress({ value, className }: { value: number | null; className?: string }) {
  if (value == null) {
    return (
      <div
        className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Progres tidak diketahui"
      >
        <div className="indeterminate absolute inset-y-0 w-2/5 rounded-full bg-run/70" />
      </div>
    );
  }
  return (
    <ProgressBar
      value={value}
      aria-label={`${value}%`}
      className={cn("h-1.5 bg-muted [&>[data-slot=progress-indicator]]:bg-run", className)}
    />
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
      <div className="mb-4 grid size-11 place-items-center rounded-xl border border-line bg-surface text-muted-foreground">{icon}</div>
      <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
      {children && <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-ink-2">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
