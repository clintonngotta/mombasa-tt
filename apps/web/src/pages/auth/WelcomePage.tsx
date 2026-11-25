import { Link } from "react-router-dom"
import { CalendarClock, ClipboardCheck, TrendingUp } from "lucide-react"
import { buttonVariants } from "@/components/ui/button"
import { Wordmark } from "@/components/brand/Wordmark"
import { cn } from "@/lib/utils"

const HIGHLIGHTS = [
  { icon: CalendarClock, text: "Know when and which table you're called to" },
  { icon: ClipboardCheck, text: "Score matches that survive a lost connection" },
  { icon: TrendingUp, text: "Keep every result and rating in one record" },
]

export function WelcomePage() {
  return (
    <div className="flex min-h-dvh flex-col bg-brand-navy text-white">
      <header className="flex h-14 items-center px-4 sm:px-8">
        <Wordmark className="text-white [&>span]:text-brand-cyan" />
      </header>

      <main className="mx-auto flex w-full max-w-[440px] flex-1 flex-col justify-end gap-10 px-4 pt-10 pb-10 sm:justify-center">
        <div className="flex flex-col gap-4">
          <p className="font-display text-lg font-semibold tracking-wide text-brand-gold uppercase">Table tennis, organised</p>
          <h1 className="text-5xl leading-[1.05] font-bold">Run the club. Play the match. Keep the record.</h1>
        </div>

        <ul className="flex flex-col gap-4">
          {HIGHLIGHTS.map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-center gap-3 text-white/90">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-white/10">
                <Icon aria-hidden className="size-5 text-brand-cyan" />
              </span>
              {text}
            </li>
          ))}
        </ul>

        <div className="flex flex-col gap-3">
          <Link to="/signup" className={cn(buttonVariants({ size: "lg" }), "bg-brand-gold text-brand-navy hover:bg-brand-gold/90")}>
            Create an account
          </Link>
          <Link
            to="/login"
            className={cn(buttonVariants({ size: "lg", variant: "outline" }), "border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white")}
          >
            Log in
          </Link>
          <p className="text-center text-white/80">
            <Link to="/tournaments" className="font-semibold text-white underline">
              Browse tournaments
            </Link>{" "}
            ·{" "}
            <Link to="/help" className="font-semibold text-white underline">
              Help
            </Link>
          </p>
        </div>
      </main>
    </div>
  )
}
