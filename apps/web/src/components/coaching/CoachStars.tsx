import { Star } from "lucide-react"
import { cn } from "@/lib/utils"

/** A coach's star rating from players who trained with them: the average and how many rated. */
export function CoachStars({ average, count, className }: { average: number | null | undefined; count: number | undefined; className?: string }) {
  if (average == null || !count) return null
  return (
    <span className={cn("inline-flex items-center gap-1 text-sm", className)}>
      <Star aria-hidden className="size-4 fill-brand-gold text-brand-gold" />
      <span className="font-semibold tabular-nums">{average.toFixed(1)}</span>
      <span className="sr-only">out of 5 stars,</span>
      <span className="text-muted-foreground">
        ({count} {count === 1 ? "rating" : "ratings"})
      </span>
    </span>
  )
}

/** Five stars to pick from. `value` is the player's current rating, or null. */
export function StarPicker({ value, onChange, disabled }: { value: number | null; onChange: (stars: number) => void; disabled?: boolean }) {
  return (
    <div role="radiogroup" aria-label="Your rating" className="flex gap-1">
      {[1, 2, 3, 4, 5].map((stars) => (
        <button
          key={stars}
          type="button"
          role="radio"
          aria-checked={value === stars}
          aria-label={`${stars} ${stars === 1 ? "star" : "stars"}`}
          disabled={disabled}
          onClick={() => onChange(stars)}
          className="flex size-12 items-center justify-center rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
        >
          <Star aria-hidden className={cn("size-8", value != null && stars <= value ? "fill-brand-gold text-brand-gold" : "text-muted-foreground")} />
        </button>
      ))}
    </div>
  )
}
