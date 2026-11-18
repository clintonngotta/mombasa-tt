import { useId, useState } from "react"
import { Segmented } from "@/components/forms/Segmented"
import { SearchSelect } from "@/components/forms/SelectField"
import { MatchCard } from "@/components/tournaments/MatchCard"
import { dayOf, formatDay } from "@/lib/dates"
import { isMine, matchLabel, type Draw, type DrawMatch } from "@/lib/draws"

type StatusFilter = "all" | "to_play" | "finished"

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "to_play", label: "To play" },
  { value: "finished", label: "Finished" },
]

const EVERYONE = ""
const MINE = "mine"

/** Matches with a time first, earliest first; then the order matches are played in. */
function inPlayingOrder(a: DrawMatch, b: DrawMatch) {
  if (!a.scheduled_at !== !b.scheduled_at) return a.scheduled_at ? -1 : 1
  if (a.scheduled_at && b.scheduled_at && a.scheduled_at !== b.scheduled_at) return new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime()
  if (a.stage !== b.stage) return a.stage === "group" ? -1 : 1
  return a.round - b.round || (a.group ?? 0) - (b.group ?? 0) || a.position - b.position
}

/**
 * Every match of the event by day (REQ-010) with its table and where it stands, filtered by status
 * and by entry. Days and times are the venue's. Byes aren't matches, so they aren't listed.
 */
export function ScheduleView({ draw, matchPath, timeZone }: { draw: Draw; matchPath: (matchId: string) => string; timeZone: string }) {
  const [show, setShow] = useState<StatusFilter>("all")
  const [who, setWho] = useState(EVERYONE)
  const whoId = useId()
  const entries = draw.places.map((place) => place.entry).sort((a, b) => a.title.localeCompare(b.title))
  const playing = entries.some((entry) => entry.mine)
  const matches = draw.matches
    .filter((match) => match.b !== null)
    .filter((match) => show === "all" || (show === "finished") === (match.status === "completed"))
    .filter((match) => who === EVERYONE || (who === MINE ? isMine(match) : match.a.entry?.id === who || match.b?.entry?.id === who))
    .sort(inPlayingOrder)

  const days = new Map<string, DrawMatch[]>()
  for (const match of matches) {
    const key = match.scheduled_at ? dayOf(match.scheduled_at, timeZone) : ""
    days.set(key, [...(days.get(key) ?? []), match])
  }
  // Days in order, then the matches nobody has given a time yet.
  const sections = [...days.entries()].sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)))
  const scheduled = draw.matches.some((match) => match.scheduled_at)

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-3">
        <Segmented label="Which matches" options={STATUS_FILTERS} value={show} onChange={setShow} />
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor={whoId} className="text-sm font-semibold">
            Player or team
          </label>
          <SearchSelect
            id={whoId}
            value={who}
            onChange={setWho}
            options={[
              { value: EVERYONE, label: "Everyone" },
              ...(playing ? [{ value: MINE, label: "My matches" }] : []),
              ...entries.map((entry) => ({ value: entry.id, label: entry.title })),
            ]}
          />
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        {scheduled ? "Times are the venue's local time and are estimates only: a match starts when its table and players are free." : "The organizers haven't given the matches times or tables yet. They are listed in playing order."}
      </p>
      {matches.length === 0 && <p className="text-muted-foreground">No matches fit these filters.</p>}
      {sections.map(([day, list]) => (
        <section key={day || "unscheduled"} aria-label={day ? formatDay(day) : "No time given yet"} className="flex flex-col gap-2">
          <h2 className="text-xl font-bold">{day ? formatDay(day) : scheduled ? "No time given yet" : "Matches"}</h2>
          <ol className="flex flex-col gap-2">
            {list.map((match) => (
              <li key={match.id}>
                <MatchCard match={match} to={matchPath(match.id)} heading={matchLabel(match, draw.groups)} timeZone={timeZone} />
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  )
}
