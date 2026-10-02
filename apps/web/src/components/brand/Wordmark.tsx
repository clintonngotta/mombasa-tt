import { cn } from "@/lib/utils"

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-display text-xl font-bold tracking-tight text-brand-navy", className)}>
      mombasa<span className="text-brand-blue">-tt</span>
    </span>
  )
}
