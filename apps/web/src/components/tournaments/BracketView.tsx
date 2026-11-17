import { useState } from "react"
import { Segmented } from "@/components/forms/Segmented"
import { MatchCard } from "@/components/tournaments/MatchCard"
import { byRound, roundHeading, type DrawMatch } from "@/lib/draws"

type Layout = "bracket" | "rounds"

const LAYOUTS: { value: Layout; label: string }[] = [
  { value: "bracket", label: "Bracket" },
  { value: "rounds", label: "Round list" },
]

/** Wide screens start on the bracket; phones on the round list, which needs no sideways scrolling. */
const initialLayout = (): Layout => (typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches ? "bracket" : "rounds")

/**
 * The knockout (REQ-010): one column per round, each match level with the two that feed it, or the
 * same matches as a list round by round. Both show byes, scores and the caller's own entry.
 */
export function BracketView({ matches, matchPath, timeZone }: { matches: DrawMatch[]; matchPath: (matchId: string) => string; timeZone: string }) {
  const [layout, setLayout] = useState<Layout>(initialLayout)
  const rounds = byRound(matches)
  const firstRoundLines = rounds[0]?.matches.length ?? 0

  return (
    <div className="flex flex-col gap-4">
      <Segmented label="How to show the knockout" options={LAYOUTS} value={layout} onChange={setLayout} />
      {layout === "bracket" ? (
        <div className="overflow-x-auto pb-2" role="region" aria-label="Bracket, scrolls sideways" tabIndex={0}>
          <div className="flex w-max gap-6">
            {rounds.map((round, index) => (
              <section key={round.name} aria-label={roundHeading(round)} className="flex w-[300px] flex-col gap-2">
                <h2 className="text-xl font-bold">{roundHeading(round)}</h2>
                {/* Each round's matches span twice the rows of the round before, so a match sits between its feeders. */}
                <ol className="grid flex-1 gap-y-3" style={{ gridTemplateRows: `repeat(${firstRoundLines}, minmax(max-content, 1fr))` }}>
                  {round.matches.map((match) => (
                    <li key={match.id} className="flex flex-col justify-center" style={{ gridRow: `span ${2 ** index}` }}>
                      <MatchCard match={match} to={matchPath(match.id)} timeZone={timeZone} compact />
                    </li>
                  ))}
                </ol>
              </section>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {rounds.map((round) => (
            <section key={round.name} aria-label={roundHeading(round)} className="flex flex-col gap-2">
              <h2 className="text-xl font-bold">{roundHeading(round)}</h2>
              <ol className="flex flex-col gap-2">
                {round.matches.map((match) => (
                  <li key={match.id}>
                    <MatchCard match={match} to={matchPath(match.id)} timeZone={timeZone} />
                  </li>
                ))}
              </ol>
            </section>
          ))}
        </div>
      )}
      <p className="text-sm text-muted-foreground">Numbers in brackets are seeds. A bye goes through without playing.</p>
    </div>
  )
}
