import { useState } from "react"
import { Segmented } from "@/components/forms/Segmented"
import { MatchCard } from "@/components/tournaments/MatchCard"
import { byRound, roundHeading, type DrawMatch } from "@/lib/draws"
import { cn } from "@/lib/utils"

type Layout = "bracket" | "rounds"

const LAYOUTS: { value: Layout; label: string }[] = [
  { value: "bracket", label: "Bracket" },
  { value: "rounds", label: "Round list" },
]

/** Wide screens start on the bracket; phones on the round list, which needs no sideways scrolling. */
const initialLayout = (): Layout => (typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches ? "bracket" : "rounds")

function BracketConnector({ upper, highlighted }: { upper: boolean; highlighted: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-y-0 left-full w-8 text-primary/40",
        highlighted && "z-10 text-primary",
      )}
    >
      <span className={cn("absolute left-0 h-1/2 w-1/2 border-r-2 border-current", upper ? "top-1/2 border-t-2" : "top-0 border-b-2")} />
      <span className={cn("absolute right-0 flex w-1/2 items-center", upper ? "top-full" : "top-0")}>
        <span className="h-0.5 flex-1 -translate-y-1/2 bg-current" />
        <span className="absolute right-0 size-2 -translate-y-px rotate-45 border-t-2 border-r-2 border-current" />
      </span>
    </span>
  )
}

/**
 * The knockout (REQ-010): one column per round, each match level with the two that feed it, or the
 * same matches as a list round by round. Both show byes, scores and the caller's own entry.
 */
export function BracketView({ matches, matchPath, timeZone }: { matches: DrawMatch[]; matchPath: (matchId: string) => string; timeZone: string }) {
  const [layout, setLayout] = useState<Layout>(initialLayout)
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null)
  const rounds = byRound(matches).map((round) => ({
    ...round,
    byPosition: new Map(round.matches.map((match) => [match.position, match])),
  }))
  const firstRoundLines = rounds[0]?.matches.length ?? 0
  const journey = { entryId: activeEntryId, onChange: setActiveEntryId }

  return (
    <div className="flex flex-col gap-4">
      <Segmented label="How to show the knockout" options={LAYOUTS} value={layout} onChange={(value) => {
        setLayout(value)
        setActiveEntryId(null)
      }} />
      {layout === "bracket" ? (
        <div className="overflow-x-auto pb-2" role="region" aria-label="Bracket, scrolls sideways" tabIndex={0}>
          <div
            className="grid w-max auto-cols-[300px] grid-flow-col gap-x-8"
            style={{ gridTemplateRows: `auto repeat(${firstRoundLines}, minmax(max-content, 1fr))` }}
          >
            {rounds.map((round, index) => (
              <section key={round.name} aria-label={roundHeading(round)} className="grid grid-rows-subgrid" style={{ gridRow: "1 / -1" }}>
                <h2 className="pb-2 text-xl font-bold">{roundHeading(round)}</h2>
                <ol className="grid grid-rows-subgrid" style={{ gridRow: "2 / -1" }}>
                  {round.matches.map((match) => {
                    const span = 2 ** index
                    const next = rounds[index + 1]?.byPosition.get(Math.ceil(match.position / 2))
                    const advances = activeEntryId !== null && match.winner_id === activeEntryId
                      && (next?.a.entry?.id === activeEntryId || next?.b?.entry?.id === activeEntryId)
                    return (
                      <li
                        key={match.id}
                        className="relative flex flex-col justify-center py-1.5"
                        style={{ gridRow: `${(match.position - 1) * span + 1} / span ${span}` }}
                      >
                        <MatchCard match={match} to={matchPath(match.id)} timeZone={timeZone} compact journey={journey} showLive />
                        {next && <BracketConnector upper={match.position % 2 === 1} highlighted={advances} />}
                      </li>
                    )
                  })}
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
                    <MatchCard match={match} to={matchPath(match.id)} timeZone={timeZone} showLive />
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
