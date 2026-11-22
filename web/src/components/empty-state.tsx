import { CircleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

export function EmptyState({
  title,
  text,
  icon,
  className,
  children,
}: {
  title: string;
  text?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card px-6 py-12 text-center", className)}>
      <span className="text-muted-foreground">{icon ?? <CircleAlert className="size-5" strokeWidth={1.75} />}</span>
      <p className="text-sm font-medium">{title}</p>
      {text && <p className="max-w-md text-[13px] text-pretty text-muted-foreground">{text}</p>}
      {children}
    </div>
  );
}
