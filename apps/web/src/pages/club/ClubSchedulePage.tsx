import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CalendarDays, CalendarPlus, ChevronRight, Dumbbell, PartyPopper, Trophy } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { errorMessage } from "@/lib/api"
import { activityKeys, getSchedule, scheduleCalendarUrl, type ScheduleItem, type ScheduleKind, type When } from "@/lib/activities"
import { useActiveMembership } from "@/lib/clubs"
import { ROW } from "@/lib/clubAdmin"
import { DEFAULT_TIME_ZONE, formatInstant } from "@/lib/dates"
import { cn } from "@/lib/utils"
import { OrganizationName } from "@/components/clubs/KindBadge"

const KINDS: { value: ScheduleKind; label: string }[] = [
  { value: "activity", label: "Activities" },
  { value: "tournament", label: "Tournaments" },
  { value: "training", label: "Training" },
]
const ICON = { activity: PartyPopper, tournament: Trophy, training: Dumbbell }

/** The club schedule for its members (REQ-039): activities, tournaments and training sessions in date
 * order, in the club's timezone, with a calendar file to add it all to a phone. */
export function ClubSchedulePage() {
  const { active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const timeZone = active?.organization.timezone ?? DEFAULT_TIME_ZONE
  const [when, setWhen] = useState<When>("upcoming")
  const [kinds, setKinds] = useState<ScheduleKind[]>(KINDS.map((k) => k.value))
  const schedule = useQuery({ queryKey: activityKeys.schedule(orgId, when, kinds), queryFn: () => getSchedule(orgId, when, kinds), enabled: !!orgId && kinds.length > 0 })

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Club schedule</h1>
        {active && <p className="flex flex-wrap items-center gap-x-1 text-muted-foreground"><OrganizationName organization={active.organization} /> · times in {timeZone}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Which dates" className="flex rounded-lg border bg-card p-1">
          {(["upcoming", "past"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={when === value}
              onClick={() => setWhen(value)}
              className={cn("h-12 rounded-md px-4 font-semibold text-muted-foreground capitalize outline-none focus-visible:ring-3 focus-visible:ring-ring/50", when === value && "bg-surface-selected text-brand-blue")}
            >
              {value}
            </button>
          ))}
        </div>
        {orgId && (
          <a href={scheduleCalendarUrl(orgId, when, kinds)} download="club-schedule.ics" className={buttonVariants({ variant: "outline" })}>
            <CalendarPlus aria-hidden className="size-5" /> Add to calendar
          </a>
        )}
      </div>
      <ChoiceGroup legend="Show" multiple columns={3} options={KINDS} value={kinds} onChange={setKinds} />
      {schedule.isError && <FormAlert>{errorMessage(schedule.error, "We couldn't load the schedule.")}</FormAlert>}
      {schedule.isSuccess && schedule.data.length === 0 && <p className="text-muted-foreground">Nothing {when === "upcoming" ? "coming up" : "in the past"}.</p>}
      <ul className="flex flex-col gap-2">
        {(schedule.data ?? []).map((item) => (
          <li key={`${item.kind}-${item.id}`}>
            <Item item={item} orgId={orgId} timeZone={timeZone} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function Item({ item, orgId, timeZone }: { item: ScheduleItem; orgId: string; timeZone: string }) {
  const Icon = ICON[item.kind] ?? CalendarDays
  const to = item.kind === "activity" ? `/activities/${orgId}/${item.id}` : item.kind === "tournament" ? `/tournaments/${item.id}` : null
  const body = (
    <>
      <Icon aria-hidden className="size-5 text-brand-blue" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={cn("truncate font-semibold", item.cancelled && "line-through")}>{item.title}</span>
        <span className="text-sm text-muted-foreground">
          {item.kind === "tournament" ? formatInstant(item.starts_at, timeZone).replace(/,? \d\d:\d\d$/, "") : formatInstant(item.starts_at, timeZone)} · {item.detail}
          {item.place && ` · ${item.place}`}
        </span>
        {item.cancelled && <span className="text-sm font-semibold">Cancelled</span>}
      </span>
      {to && <ChevronRight aria-hidden className="size-5 text-muted-foreground" />}
    </>
  )
  return to ? (
    <Link to={to} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
      {body}
    </Link>
  ) : (
    <div className={ROW}>{body}</div>
  )
}
