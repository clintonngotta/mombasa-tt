import { byRound, roundHeading, sideWon, type Draw, type DrawMatch, type DrawSide } from "@/lib/draws"
import { EntryNames } from "@/components/tournaments/PlayerNames"

function Side({ side, won, matchId }: { side: DrawSide; won: boolean; matchId: string }) {
  if (!side.entry) return <span className="text-muted-foreground italic">{side.awaiting}</span>
  return (
    <span className={won ? "font-bold" : undefined}>
      <EntryNames entry={side.entry} exceptMatch={matchId} />
      {side.seed && <span className="ml-1 text-sm font-normal text-muted-foreground">[{side.seed}]</span>}
      {won && <span className="sr-only"> (winner)</span>}
    </span>
  )
}

/** The two sides left and right, never one above the other (REQ-002). */
function MatchLine({ match }: { match: DrawMatch }) {
  const won = (side: DrawSide) => sideWon(match, side)
  return (
    <li className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-lg border bg-card px-3 py-2">
      <span className="min-w-0 break-words">
        <Side side={match.a} won={won(match.a)} matchId={match.id} />
      </span>
      <span className="text-sm text-muted-foreground">{match.b ? "v" : "–"}</span>
      <span className="min-w-0 text-right break-words">
        {match.b ? <Side side={match.b} won={won(match.b)} matchId={match.id} /> : <span className="font-semibold text-muted-foreground">Bye</span>}
      </span>
    </li>
  )
}

function Rounds({ matches, label }: { matches: DrawMatch[]; label: string }) {
  return (
    <div className="flex flex-col gap-3">
      {byRound(matches).map((round) => (
        <section key={round.name} aria-label={`${label}: ${roundHeading(round)}`} className="flex flex-col gap-2">
          <h4 className="font-semibold">{roundHeading(round)}</h4>
          <ol className="flex flex-col gap-2">
            {round.matches.map((match) => (
              <MatchLine key={match.id} match={match} />
            ))}
          </ol>
        </section>
      ))}
    </div>
  )
}

/** A draw as a list: groups with their numbers and rounds, then the knockout round by round. */
export function DrawView({ draw }: { draw: Draw }) {
  const knockout = draw.matches.filter((match) => match.stage === "knockout")
  return (
    <div className="flex flex-col gap-6">
      {draw.groups.map((group) => {
        const members = draw.places.filter((place) => place.group === group.number).sort((a, b) => (a.group_position ?? 0) - (b.group_position ?? 0))
        // An event that is one round robin is a single group: its name would add nothing.
        const name = draw.groups.length > 1 ? group.name : "Everybody plays everybody"
        return (
          <section key={group.number} aria-label={name} className="flex flex-col gap-3">
            <h3 className="text-xl font-bold">{name}</h3>
            <ol className="flex flex-col gap-1">
              {members.map((place) => (
                <li key={place.entry.id} className="flex gap-2">
                  <span className="w-6 shrink-0 text-right font-semibold tabular-nums text-muted-foreground">{place.group_position}</span>
                  <span className="min-w-0 break-words">
                    <EntryNames entry={place.entry} />
                    {place.seed && <span className="ml-1 text-sm text-muted-foreground">[{place.seed}]</span>}
                  </span>
                </li>
              ))}
            </ol>
            <Rounds matches={draw.matches.filter((match) => match.stage === "group" && match.group === group.number)} label={name} />
          </section>
        )
      })}
      {knockout.length > 0 && (
        <section aria-label="Knockout" className="flex flex-col gap-3">
          <h3 className="text-xl font-bold">Knockout</h3>
          <Rounds matches={knockout} label="Knockout" />
        </section>
      )}
      <p className="text-sm text-muted-foreground">Numbers in brackets are seeds. A bye goes through without playing. Drawn under rules {draw.rules_version}, draw number {draw.rng_seed}.</p>
    </div>
  )
}
