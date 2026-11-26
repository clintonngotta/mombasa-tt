import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, PartyPopper } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { activityKeys, KIND_LABEL, listMyEvents, type Activity } from "@/lib/activities"
import { ROW } from "@/lib/clubAdmin"
import { DEFAULT_TIME_ZONE, formatInstant } from "@/lib/dates"
import { cn } from "@/lib/utils"

const why = (event: Activity) => (event.audience === "open" ? "Open to all players" : event.audience === "reps" ? "For representatives" : "You're invited")

function EventRow({ event }: { event: Activity }) {
  return (
    <li>
      <Link to={`/activities/${event.organization.id}/${event.id}`} className={cn(ROW, "flex-nowrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
        <PartyPopper aria-hidden className="size-5 shrink-0 text-brand-blue" />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate font-semibold">{event.title}</span>
          <span className="text-sm text-muted-foreground">
            {formatInstant(event.starts_at, DEFAULT_TIME_ZONE)} · {KIND_LABEL[event.kind ?? "other"]} · {event.organization.name}
          </span>
          <span className="text-sm text-muted-foreground">
            {why(event)}
            {event.my_answer === "going" ? (event.my_waitlisted ? " · you're on the waiting list" : " · you're going") : event.my_answer === "maybe" ? " · you said maybe" : ""}
          </span>
        </span>
        <ChevronRight aria-hidden className="size-5 shrink-0 text-muted-foreground" />
      </Link>
    </li>
  )
}

// Other people publish these, so ask the server each time rather than show a saved list.
const useMyEvents = () => useQuery({ queryKey: activityKeys.myEvents, queryFn: listMyEvents, staleTime: 0 })

/** The next few events that invite you, on Home. Hidden when there are none. */
export function EventsForYou() {
  const events = useMyEvents()
  if (!events.data?.length) return null
  return (
    <section aria-labelledby="events-for-you-heading" className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="events-for-you-heading" className="text-xl font-bold">
          Events for you
        </h2>
        {events.data.length > 3 && (
          <Link to="/invited" className="font-semibold text-brand-blue underline-offset-4 hover:underline">
            See all {events.data.length}
          </Link>
        )}
      </div>
      <ul className="flex flex-col gap-2">
        {events.data.slice(0, 3).map((event) => (
          <EventRow key={event.id} event={event} />
        ))}
      </ul>
    </section>
  )
}

/** Workshops, clinics, award nights and open days you can go to (REQ-046): those you were named for,
 * those for representatives when you are one, and those open to every player. */
export function InvitedEventsPage() {
  const events = useMyEvents()
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/home">Home</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Events for you</h1>
        <p className="text-muted-foreground">Workshops, clinics, award nights and open days you can go to. Your club's own activities are on its schedule.</p>
      </div>
      {events.isPending && <p className="text-muted-foreground">Loading…</p>}
      {events.isError && <FormAlert>{errorMessage(events.error, "We couldn't load the events.")}</FormAlert>}
      {events.isSuccess && events.data.length === 0 && <p className="text-muted-foreground">Nothing coming up yet.</p>}
      <ul className="flex flex-col gap-2">
        {events.data?.map((event) => (
          <EventRow key={event.id} event={event} />
        ))}
      </ul>
    </div>
  )
}
