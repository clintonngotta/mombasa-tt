import { useState, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, Hourglass } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { SearchSelect } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import { WinnerMark } from "@/components/tournaments/MatchCard"
import { UmpireControl } from "@/components/tournaments/UmpireControl"
import { drawKeys, gamesWon, OUTCOME_MARK, resetLineups, submitLineup, type DrawSide, type MatchDetail, type Rubber, type Tie } from "@/lib/draws"
import { tieSummary, type RubberKind } from "@/lib/tournaments"
import { cn } from "@/lib/utils"
import { EntryNames } from "@/components/tournaments/PlayerNames"

type Ids = { tournamentId: string; eventId: string; matchId: string }
type SideKey = "a" | "b"

const KIND_LABEL: Record<RubberKind, string> = { singles: "Singles", doubles: "Doubles" }

/**
 * A team tie (REQ-011): its format, each team's lineup until both are in, then the rubbers in playing
 * order with the two teams left and right. Lineups are handed in here; rubbers are scored by the umpire.
 */
export function TieView({ match, second, ids }: { match: MatchDetail; second: DrawSide; ids: Ids }) {
  const tie = match.tie as Tie
  const queryClient = useQueryClient()
  const settle = (fresh: MatchDetail) => {
    queryClient.setQueryData(drawKeys.match(ids.matchId), fresh)
    void queryClient.invalidateQueries({ queryKey: drawKeys.event(ids.eventId) })
  }
  const reset = useMutation({ mutationFn: () => resetLineups(ids.tournamentId, ids.eventId, ids.matchId), onSuccess: settle })
  const sides: { key: SideKey; side: DrawSide }[] = [
    { key: "a", side: match.a },
    { key: "b", side: second },
  ]

  return (
    <section aria-labelledby="tie-heading" className="flex flex-col gap-3">
      <h2 id="tie-heading" className="text-2xl font-bold">
        {tie.begun ? "Rubbers" : "Lineups"}
      </h2>
      <p className="text-sm text-muted-foreground">
        A tie of {tieSummary(tie.template, tie.wins_needed)}. Rubbers are played one at a time; once a team has {tie.wins_needed}, the rest are not played.
      </p>

      {!tie.begun && (
        <>
          <ul className="grid grid-cols-2 gap-3">
            {sides.map(({ key, side }) => (
              <li key={key} className={cn("flex flex-col gap-1 rounded-xl border bg-card p-3", key === "b" && "items-end text-right")}>
                <span className="font-semibold break-words">{side.entry ? <EntryNames entry={side.entry} exceptMatch={match.id} /> : side.awaiting}</span>
                <span className={cn("inline-flex items-center gap-1 text-sm font-semibold", tie[key].submitted ? "text-success" : "text-muted-foreground")}>
                  {tie[key].submitted ? <CircleCheck aria-hidden className="size-4" /> : <Hourglass aria-hidden className="size-4" />}
                  {tie[key].submitted ? "Lineup handed in" : "No lineup yet"}
                </span>
              </li>
            ))}
          </ul>
          {match.a.entry && second.entry ? (
            <p className="text-sm text-muted-foreground">Each captain names the team's players. A lineup stays with its own team until both are in; then the tie begins and they can't change.</p>
          ) : (
            <p className="text-sm text-muted-foreground">Lineups are handed in once both teams of this tie are known.</p>
          )}
          {sides.map(({ key, side }) => tie[key].can_submit && side.entry && <LineupForm key={`${key}-${tie[key].submitted_at}`} tie={tie} sideKey={key} entry={side.entry} ids={ids} onDone={settle} />)}
        </>
      )}

      {tie.begun && (
        <ol className="flex flex-col gap-2">
          {tie.rubbers.map((rubber) => (
            <RubberRow key={rubber.id} rubber={rubber} match={match} ids={ids} next={rubber.id === tie.rubbers.find((candidate) => candidate.status === "scheduled")?.id} />
          ))}
        </ol>
      )}
      {tie.can_reset && (
        <div className="flex flex-col gap-2 rounded-xl border border-brand-blue/30 bg-surface-selected p-3">
          <p className="text-sm">No rubber has been decided yet. As an organizer you can send both teams back to choose their lineups again.</p>
          {reset.isError && <FormAlert>{errorMessage(reset.error)}</FormAlert>}
          <Button variant="outline" className="self-start" disabled={reset.isPending} onClick={() => reset.mutate()}>
            {reset.isPending ? "Clearing…" : "Clear both lineups"}
          </Button>
        </div>
      )}
    </section>
  )
}

const names = (players: Rubber["a_players"]) => players.map((player) => player.display_name).join(" / ")

function RubberRow({ rubber, match, next, ids }: { rubber: Rubber; match: MatchDetail; next: boolean; ids: Ids }) {
  const won = (side: SideKey) => rubber.status === "completed" && rubber.winner_id === (side === "a" ? match.a.entry?.id : match.b?.entry?.id)
  const games = gamesWon(rubber)
  const score = rubber.status === "not_played" ? "Not played" : rubber.status === "scheduled" ? "v" : rubber.outcome === "walkover" ? "W/O" : rubber.outcome === "disqualified" && rubber.games.length === 0 ? "DQ" : `${games.a}–${games.b}${OUTCOME_MARK[rubber.outcome]?.short ?? ""}`
  return (
    <li className={cn("flex flex-col gap-1.5 rounded-xl border bg-card px-3 py-2.5", rubber.status === "not_played" && "bg-muted text-muted-foreground")}>
      <span className="text-sm font-semibold text-muted-foreground">
        Rubber {rubber.position} · {KIND_LABEL[rubber.kind]}
        {next && <span className="ml-2 rounded bg-brand-cyan/20 px-1.5 text-brand-navy">Next to play</span>}
      </span>
      <span className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <span className={cn("min-w-0 break-words", won("a") && "font-bold")}>
          {names(rubber.a_players)}
          {won("a") && <WinnerMark />}
        </span>
        <span className={cn("font-display text-xl font-bold tabular-nums", rubber.status !== "completed" && "font-sans text-sm font-normal text-muted-foreground")}>{score}</span>
        <span className={cn("min-w-0 text-right break-words", won("b") && "font-bold")}>
          {names(rubber.b_players)}
          {won("b") && <WinnerMark />}
        </span>
      </span>
      {rubber.games.length > 0 && <span className="text-center text-sm tabular-nums text-muted-foreground">{rubber.games.map(([a, b]) => `${a}–${b}`).join(", ")}</span>}
      {rubber.status === "not_played" && <span className="text-sm">The tie was decided before this rubber's turn.</span>}
      {rubber.status === "scheduled" && (
        <span className="border-t pt-2">
          <UmpireControl scoring={rubber.scoring} ids={ids} rubberId={rubber.id} what={`rubber ${rubber.position}`} />
        </span>
      )}
    </li>
  )
}

/** One select per place in each rubber, from the team's own roster. A player may play several rubbers. */
function LineupForm({ tie, sideKey, entry, ids, onDone }: { tie: Tie; sideKey: SideKey; entry: NonNullable<DrawSide["entry"]>; ids: Ids; onDone: (fresh: MatchDetail) => void }) {
  const [picks, setPicks] = useState<string[][]>(() => tie.template.map((kind, index) => tie[sideKey].picks?.[index] ?? (kind === "doubles" ? ["", ""] : [""])))
  const save = useMutation({ mutationFn: () => submitLineup(ids.tournamentId, ids.eventId, ids.matchId, entry.id, picks), onSuccess: onDone })
  const complete = picks.every((players) => players.every(Boolean) && new Set(players).size === players.length)

  function choose(rubber: number, place: number, playerId: string) {
    setPicks(picks.map((players, index) => (index === rubber ? players.map((kept, i) => (i === place ? playerId : kept)) : players)))
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={onSubmit} aria-label={`Lineup for ${entry.title}`} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h3 className="text-xl font-bold">{tie[sideKey].submitted ? `Change ${entry.title}'s lineup` : `${entry.title}'s lineup`}</h3>
      <ol className="flex flex-col gap-3">
        {tie.template.map((kind, rubber) => (
          <li key={rubber} className="flex flex-col gap-1.5">
            <span className="text-sm font-semibold">
              Rubber {rubber + 1} · {KIND_LABEL[kind]}
            </span>
            <span className="grid gap-2 sm:grid-cols-2">
              {picks[rubber].map((chosen, place) => (
                <SearchSelect
                  key={place}
                  aria-label={`Rubber ${rubber + 1}${kind === "doubles" ? `, player ${place + 1}` : ""}`}
                  value={chosen}
                  onChange={(value) => choose(rubber, place, value)}
                  options={[
                    { value: "", label: "Choose a player" },
                    ...entry.players.map((player) => ({
                      value: player.id,
                      label: player.display_name,
                      disabled: picks[rubber].some((other, i) => i !== place && other === player.id),
                    })),
                  ]}
                />
              ))}
            </span>
          </li>
        ))}
      </ol>
      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <Button type="submit" size="lg" className="self-start" disabled={!complete || save.isPending}>
        {save.isPending ? "Handing in…" : tie[sideKey].submitted ? "Hand in the changed lineup" : "Hand in lineup"}
      </Button>
      <p className="text-sm text-muted-foreground">The other team sees only that your lineup is in, not who you picked, until theirs is in too.</p>
    </form>
  )
}
