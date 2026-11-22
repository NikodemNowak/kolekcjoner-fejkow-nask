import { cn } from "@/lib/utils";

export function PageHeader({
  eyebrow,
  title,
  description,
  children,
  className,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0 space-y-1.5">
        {eyebrow && <div className="text-[13px] text-muted-foreground">{eyebrow}</div>}
        <h1 className="text-[22px] leading-tight font-semibold text-balance sm:text-[26px]">{title}</h1>
        {description && (
          <p className="max-w-3xl text-sm leading-relaxed text-pretty text-muted-foreground">{description}</p>
        )}
      </div>
      {children && <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function SectionTitle({
  title,
  hint,
  children,
  icon,
  className,
}: {
  title: React.ReactNode;
  hint?: React.ReactNode;
  children?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-2", className)}>
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold">
          {icon}
          {title}
        </h2>
        {hint && <p className="mt-0.5 text-[13px] leading-relaxed text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </div>
  );
}
