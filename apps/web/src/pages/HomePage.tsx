import { Link } from "react-router-dom"
import { ChevronRight, CircleHelp, Medal, Plus, Users, Warehouse, type LucideIcon } from "lucide-react"
import { LiveNow, MyEntries } from "@/components/tournaments/TournamentLists"
import { can, useActiveMembership } from "@/lib/clubs"
import { AddEmailPrompt } from "@/components/profile/AddEmailPrompt"
import { useMe } from "@/lib/session"
import { EventsForYou } from "@/pages/club/InvitedEventsPage"
import { SquadPlacesToAnswer } from "@/pages/club/SquadPages"
import { FeedbackAsked } from "@/pages/tournaments/FeedbackAnswerPage"

type Action = { to: string; icon: LucideIcon; title: string; description: string }

/** Home: the few things people come to do, one tap each, then what is on now and what they've entered. */
export function HomePage() {
  const me = useMe()
  const { memberships, active, all } = useActiveMembership()
  const organizer = !!active && !active.managedOnly && can(active, "competitions.manage")
  const inAClub = all.some((m) => !m.managedOnly)

  const actions: Action[] = [
    { to: "/tournaments", icon: Medal, title: "Tournaments", description: "Enter one, or follow the live scores and results" },
    // Until the memberships arrive (or signed out, when they never do) the tile doesn't guess.
    inAClub || (me.isSuccess && memberships.isPending)
      ? { to: "/club", icon: Users, title: "Your club", description: "Sessions, members and news" }
      : { to: "/club/find", icon: Users, title: "Join a club", description: "Search by city, or see clubs near you" },
    { to: "/facilities", icon: Warehouse, title: "Find a place to play", description: "Halls with tables near you, and which are open now" },
    organizer
      ? { to: "/club/tournaments/new", icon: Plus, title: "Create a tournament", description: `Organized by ${active.organization.name}` }
      : { to: "/help#run-a-tournament", icon: Plus, title: "Run a tournament", description: "What you need, in three steps" },
    { to: "/help", icon: CircleHelp, title: "Help", description: "How things work, step by step" },
  ]

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">{me.data ? `Hello, ${me.data.display_name}` : "Welcome"}</h1>
        <p className="text-muted-foreground">What would you like to do?</p>
      </div>

      <nav aria-label="Shortcuts" className="grid gap-3 sm:grid-cols-2">
        {actions.map(({ to, icon: Icon, title, description }) => (
          <Link
            key={title}
            to={to}
            className="flex items-center gap-3 rounded-xl border bg-card p-4 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <span className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-surface-selected">
              <Icon aria-hidden className="size-6 text-brand-blue" />
            </span>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">{title}</span>
              <span className="text-sm text-muted-foreground">{description}</span>
            </span>
            <ChevronRight aria-hidden className="size-5 shrink-0 text-muted-foreground" />
          </Link>
        ))}
      </nav>

      <AddEmailPrompt />
      {me.isSuccess && <SquadPlacesToAnswer />}
      {me.isSuccess && <FeedbackAsked />}
      {me.isSuccess && <EventsForYou />}
      <LiveNow />
      <MyEntries />
    </div>
  )
}
