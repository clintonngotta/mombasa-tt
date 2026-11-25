import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { ChevronRight, CircleCheckBig, Clock, Trophy, Users, UserRound, type LucideIcon } from "lucide-react"
import { buttonVariants } from "@/components/ui/button"
import { Wordmark } from "@/components/brand/Wordmark"
import { clearOnboardingDraft, readReturn, useOnboardingDraft } from "@/lib/onboarding"
import type { Goal } from "@/lib/profile"
import { cn } from "@/lib/utils"

type NextAction = { to: string; icon: LucideIcon; title: string; description: string; goals: Goal[] }

// Real destinations only; ordering follows the goals the player picked.
const ACTIONS: NextAction[] = [
  { to: "/tournaments", icon: Trophy, title: "Find a tournament", description: "Browse open events and enter", goals: ["compete", "rating"] },
  { to: "/club", icon: Users, title: "Explore clubs", description: "Search for clubs and venues near you", goals: ["find_club", "organize"] },
  { to: "/profile", icon: UserRound, title: "Finish your profile", description: "Add details and choose what's public", goals: [] },
]

export function CompletionPage() {
  const [draft] = useOnboardingDraft()
  // Snapshot before clearing so the summary survives the cleanup.
  const [{ profile, goals, joinRequests }] = useState(draft)
  // Signed up on the way somewhere, such as an event to enter: that is the way on (TASK-035).
  const [returnTo] = useState(readReturn)

  useEffect(() => clearOnboardingDraft(), [])

  const actions = [...ACTIONS].sort(
    (a, b) => Number(b.goals.some((g) => goals.includes(g))) - Number(a.goals.some((g) => goals.includes(g)))
  )
  const firstName = profile.display_name.trim().split(/\s+/)[0]

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <header className="flex h-14 items-center px-4 sm:px-8">
        <Wordmark />
      </header>
      <main className="mx-auto flex w-full max-w-[640px] flex-1 flex-col gap-8 px-4 pt-6 pb-10">
        <div className="flex flex-col gap-3">
          <CircleCheckBig aria-hidden className="size-12 text-success" />
          <h1 className="text-[32px] leading-9 font-bold">{firstName ? `You're set up, ${firstName}` : "You're set up"}</h1>
          <p className="text-muted-foreground">Your player profile is ready. Results and ratings will build up as you play.</p>
        </div>

        {joinRequests.length > 0 && (
          <section className="flex flex-col gap-3">
            <h2 className="text-xl">Join requests</h2>
            <ul className="flex flex-col gap-2">
              {joinRequests.map((club) => (
                <li key={club.id} className="flex items-center justify-between gap-3 rounded-xl border bg-card p-4">
                  <span className="font-semibold">{club.name}</span>
                  <span className="flex items-center gap-1 text-sm font-semibold text-warning">
                    <Clock aria-hidden className="size-4" /> Waiting for staff approval
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="flex flex-col gap-3">
          <h2 className="text-xl">What next</h2>
          <ul className="flex flex-col gap-2">
            {actions.map(({ to, icon: Icon, title, description }) => (
              <li key={to}>
                <Link
                  to={to}
                  className="flex items-center gap-3 rounded-xl border bg-card p-4 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <span className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-surface-selected">
                    <Icon aria-hidden className="size-6 text-brand-blue" />
                  </span>
                  <span className="flex flex-1 flex-col">
                    <span className="font-semibold">{title}</span>
                    <span className="text-sm text-muted-foreground">{description}</span>
                  </span>
                  <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <Link to={returnTo ?? "/home"} className={cn(buttonVariants({ size: "lg" }), "mt-auto")}>
          {returnTo ? "Continue where you left off" : "Go to Home"}
        </Link>
      </main>
    </div>
  )
}
