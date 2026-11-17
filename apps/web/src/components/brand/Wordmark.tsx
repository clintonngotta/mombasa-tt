import { cn } from "@/lib/utils"

/** The crest and the name. The crest is decorative here: the name is right beside it. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center font-display text-xl font-bold tracking-tight text-brand-navy", className)}>
      <img src="/logo-mark.png" alt="" width={32} height={32} className="mr-2 size-8 shrink-0" />
      Coast<span className="text-brand-blue">&nbsp;TT</span>
    </span>
  )
}
