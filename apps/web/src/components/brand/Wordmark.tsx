import { cn } from "@/lib/utils"

/**
 * The Coast Loopas logo: the looped ball and the name in two tones. The mark is decorative here: the name
 * is right beside it. On a dark background pass `text-white [&>span]:text-brand-cyan`, which turns the
 * front arc and "loopas" cyan (both sit in direct child spans).
 */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center font-display text-xl font-bold tracking-tight text-brand-navy", className)}>
      <span className="mr-1.5 inline-flex text-brand-blue">
        <svg aria-hidden viewBox="58 138 296 146" className="h-7 w-auto shrink-0" fill="none" strokeLinecap="round" strokeWidth={14}>
          <path d="M70 250 Q150 110 250 190" stroke="#08b8f0" opacity={0.35} />
          <path d="M110 262 Q175 150 262 204" stroke="#08b8f0" opacity={0.65} />
          <path d="M152 272 Q200 190 272 220" stroke="currentColor" />
          <circle cx={312} cy={222} r={34} fill="#ffd859" stroke="#031539" strokeWidth={7} />
        </svg>
      </span>
      coast<span className="text-brand-blue">loopas</span>
    </span>
  )
}
