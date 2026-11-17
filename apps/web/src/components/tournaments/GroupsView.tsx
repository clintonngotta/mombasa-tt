import { CircleCheck } from "lucide-react"
import { MatchCard, YouBadge } from "@/components/tournaments/MatchCard"
import { byRound, type Draw, type Standings } from "@/lib/draws"

/** Each group (REQ-010): who is in it, its fixtures round by round, and who has qualified so far. */
export function GroupsView({ draw, standings, matchPath, timeZone }: { draw: Draw; standings?: Standings; matchPath: (matchId: string) => string; timeZone: string }) {
  const single = draw.groups.length === 1
  return (
    <div className="flex flex-col gap-8">
      {draw.groups.map((group) => {
        const members = draw.places.filter((place) => place.group === group.number).sort((a, b) => (a.group_position ?? 0) - (b.group_position ?? 0))
        const table = standings?.groups.find((candidate) => candidate.number === group.number)
        const qualified = new Set(table?.rows.filter((row) => row.qualified).map((row) => row.entry.id))
        // An event that is one round robin is a single group: its name would add nothing.
        const name = single ? "Everybody plays everybody" : group.name
        const matches = draw.matches.filter((match) => match.stage === "group" && match.group === group.number)
        return (
          <section key={group.number} aria-label={name} className="flex flex-col gap-3">
            <h2 className="text-2xl font-bold">{name}</h2>
            <ol className="flex flex-col rounded-xl border bg-card">
              {members.map((place) => (
                <li key={place.entry.id} className="flex min-h-12 items-center gap-2 border-t px-3 py-2 first:border-t-0">
                  <span className="w-6 shrink-0 font-semibold tabular-nums text-muted-foreground">{place.group_position}</span>
                  <span className="min-w-0 flex-1 break-words">
                    {place.entry.title}
                    {place.seed && <span className="ml-1 text-sm text-muted-foreground">[{place.seed}]</span>}
                    {place.entry.mine && <YouBadge />}
                  </span>
                  {qualified.has(place.entry.id) && (
                    <span className="inline-flex shrink-0 items-center gap-1 text-sm font-semibold text-success">
                      <CircleCheck aria-hidden className="size-4" /> Qualified
                    </span>
                  )}
                </li>
              ))}
            </ol>
            {table && table.qualifiers > 0 && (
              <p className="text-sm text-muted-foreground">
                {table.qualifiers === 1 ? "The winner goes" : `The top ${table.qualifiers} go`} through to the knockout
                {table.complete ? "." : " once every match in the group is played."}
              </p>
            )}
            {byRound(matches).map((round) => (
              <section key={round.name} aria-label={`${name}: ${round.name}`} className="flex flex-col gap-2">
                <h3 className="text-xl font-bold">{round.name}</h3>
                <ol className="flex flex-col gap-2">
                  {round.matches.map((match) => (
                    <li key={match.id}>
                      <MatchCard match={match} to={matchPath(match.id)} timeZone={timeZone} />
                    </li>
                  ))}
                </ol>
              </section>
            ))}
          </section>
        )
      })}
      <p className="text-sm text-muted-foreground">Numbers in brackets are seeds. The Standings tab shows each table and how level entries are separated.</p>
    </div>
  )
}
