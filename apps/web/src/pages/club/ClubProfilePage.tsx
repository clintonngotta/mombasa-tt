import type { ReactNode } from "react"
import { Link, useLocation, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Building2, CalendarDays, Clock, Lock, MapPin, Trophy, UsersRound } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { PlaceDirections } from "@/components/forms/PlaceFinderFields"
import { JoinStatus } from "@/components/clubs/JoinStatus"
import { OrganizationGallery } from "@/components/clubs/OrganizationGallery"
import { buttonVariants } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { KIND_LABEL, SIDE, clubKeys, getClubProfile, requestToJoin, sideOf, useJoinState, type Side, type TrainingHour } from "@/lib/clubs"
import { WEEKDAYS } from "@/lib/coaching"
import { countryName } from "@/lib/geography"
import { SCOPE_LABEL } from "@/lib/tournaments"

const dateLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-KE", { weekday: "short", day: "numeric", month: "short", year: "numeric" })
const time = (value: string) => value.slice(0, 5)

/** A club or team as a player sees it before joining: where it is, what it is about, when it trains and
 * its coming tournaments. Members, training plans and everything else stay inside it. `side` is the finder
 * the player came from; once loaded, the organization's own kind decides the wording. */
export function ClubProfilePage({ side: from = "club" }: { side?: Side }) {
  const { id = "" } = useParams()
  const { state } = useLocation()
  const queryClient = useQueryClient()
  const profile = useQuery({ queryKey: clubKeys.profile(id), queryFn: () => getClubProfile(id) })
  const joinState = useJoinState()
  const join = useMutation({
    mutationFn: () => requestToJoin(id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.all }),
  })
  const side = profile.data ? sideOf(profile.data.kind) : from
  const { path, noun } = SIDE[side]
  const back = (state as { from?: string } | null)?.from ?? `${path}/find`

  if (profile.isPending) return <p className="text-muted-foreground">Loading {noun}…</p>
  if (profile.isError) {
    return (
      <div className="flex max-w-[720px] flex-col gap-4">
        <BackLink to={back}>Find a {noun}</BackLink>
        <FormAlert>{errorMessage(profile.error, `We couldn't load this ${noun}.`)}</FormAlert>
      </div>
    )
  }

  const club = profile.data
  const membership = joinState.of(club.id)
  const place = [...new Set([club.town, club.region, countryName(club.country)])].filter(Boolean).join(", ")
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={back}>Find a {noun}</BackLink>

      <header className="flex flex-wrap items-start gap-4">
        <span className="flex size-14 shrink-0 items-center justify-center rounded-xl bg-surface-selected">
          {side === "team" ? <UsersRound aria-hidden className="size-7 text-brand-blue" /> : <Building2 aria-hidden className="size-7 text-brand-blue" />}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h1 className="text-[32px] leading-9 font-bold">{club.name}</h1>
          <p className="flex items-center gap-1 text-muted-foreground">
            <MapPin aria-hidden className="size-4" /> {place} · {KIND_LABEL[club.kind]}
          </p>
        </div>
        <div className="flex items-center gap-2 self-center">
          <JoinStatus state={membership} name={club.name} busy={join.isPending} onJoin={() => join.mutate()} />
          {membership === "member" && (
            <Link to={path} className={buttonVariants({ variant: "outline" })}>
              Open {noun}
            </Link>
          )}
        </div>
      </header>
      {join.isError && <FormAlert>{errorMessage(join.error, "We couldn't send that join request.")}</FormAlert>}
      {joinState.failed && <FormAlert>We couldn't check whether you've joined, so join requests are paused. Try again shortly.</FormAlert>}
      {membership === "pending" && <p className="text-sm text-muted-foreground">The {noun}'s staff will approve or decline your request.</p>}

      {club.description && <p className="whitespace-pre-line">{club.description}</p>}
      <OrganizationGallery orgId={club.id} />

      <Section title={side === "team" ? "Where it's based" : "Where it plays"} icon={<MapPin aria-hidden className="size-5 text-brand-blue" />}>
        <PlaceDirections place={club} />
        {club.venues.length === 0 && !club.directions && <p className="text-muted-foreground">{place || `The ${noun} hasn't added its location yet.`}</p>}
        {club.venues.length > 0 && (
          <ul className="flex flex-col gap-2">
            {club.venues.map((venue) => (
              <li key={venue.id} className="rounded-xl border bg-card p-4">
                <p className="font-semibold">{venue.name}</p>
                <p className="text-sm text-muted-foreground">{[venue.address, venue.town].filter(Boolean).join(", ")}</p>
                <PlaceDirections place={venue} className="mt-1" />
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Training hours" icon={<Clock aria-hidden className="size-5 text-brand-blue" />}>
        {club.training_hours.length === 0 ? (
          <p className="text-muted-foreground">The {noun} hasn't published its training hours.</p>
        ) : (
          <>
            <TrainingTimetable hours={club.training_hours} />
            <p className="text-sm text-muted-foreground">Times are local ({club.timezone}).</p>
          </>
        )}
      </Section>

      <Section title="Upcoming tournaments" icon={<Trophy aria-hidden className="size-5 text-brand-blue" />}>
        {club.upcoming_tournaments.length === 0 ? (
          <p className="text-muted-foreground">No tournaments announced.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {club.upcoming_tournaments.map((t) => (
              <li key={t.id}>
                <Link to={`/tournaments/${t.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border bg-card p-4 outline-none hover:bg-surface-selected focus-visible:ring-3 focus-visible:ring-ring/50">
                  <span className="flex-1 font-semibold">{t.name}</span>
                  {t.status === "in_progress" && <span className="text-sm font-semibold text-destructive">Live</span>}
                  <span className="flex items-center gap-1 text-sm text-muted-foreground">
                    <CalendarDays aria-hidden className="size-4" />
                    {t.starts_on === t.ends_on ? dateLabel(t.starts_on) : `${dateLabel(t.starts_on)} – ${dateLabel(t.ends_on)}`}
                  </span>
                  <span className="basis-full text-sm text-muted-foreground">
                    {SCOPE_LABEL[t.scope]}
                    {t.venue_name && ` · ${t.venue_name}`}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {membership !== "member" && (
        <p className="flex items-center gap-2 border-t pt-4 text-sm text-muted-foreground">
          <Lock aria-hidden className="size-4 shrink-0" />
          Members, training plans and drills are shared once the {noun} accepts you.
        </p>
      )}
    </div>
  )
}

function Section({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  const id = `section-${title.toLowerCase().replace(/\W+/g, "-")}`
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="flex items-center gap-2 text-xl font-bold">
        {icon} {title}
      </h2>
      {children}
    </section>
  )
}

/** One row per training day, Monday first, with every slot that day. */
function TrainingTimetable({ hours }: { hours: TrainingHour[] }) {
  const days = WEEKDAYS.map((day, weekday) => ({ day, slots: hours.filter((h) => h.weekday === weekday) })).filter((d) => d.slots.length)
  return (
    <dl className="divide-y rounded-xl border bg-card">
      {days.map(({ day, slots }) => (
        <div key={day} className="grid gap-1 p-4 sm:grid-cols-[8rem_1fr]">
          <dt className="font-semibold">{day}</dt>
          <dd className="flex flex-col gap-1">
            {slots.map((slot) => (
              <span key={slot.id}>
                <span className="font-medium tabular-nums">
                  {time(slot.starts)}–{time(slot.ends)}
                </span>
                {[slot.label, slot.venue_name].filter(Boolean).length > 0 && (
                  <span className="text-muted-foreground"> · {[slot.label, slot.venue_name].filter(Boolean).join(" · ")}</span>
                )}
              </span>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  )
}
