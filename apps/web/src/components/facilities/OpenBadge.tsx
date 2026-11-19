import { cn } from "@/lib/utils"

/** Open or closed at this moment, by the facility's own clock. Text, not colour alone. */
export function OpenBadge({ open, className }: { open: boolean; className?: string }) {
  return (
    <span className={cn("shrink-0 rounded-full px-3 py-1 text-sm font-semibold", open ? "bg-success/15 text-success" : "bg-muted text-muted-foreground", className)}>
      {open ? "Open now" : "Closed"}
    </span>
  )
}
