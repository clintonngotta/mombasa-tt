import { cn } from "@/lib/utils"

/** The full Coast Loopas logo with its tagline, as chosen in the brand profile: `primary` on light
 * backgrounds, `reversed` (white and cyan, transparent) on navy and other dark ones. Headers that are too
 * short for the tagline use `Wordmark`. */
export function Logo({ variant = "primary", className }: { variant?: "primary" | "reversed"; className?: string }) {
  return <img src={`/brand/logo-${variant}.png`} alt="Coast Loopas: Coast Table Tennis" width={720} height={444} decoding="async" className={cn("h-24 w-auto", className)} />
}
