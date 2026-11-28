import { useState, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Hourglass, TriangleAlert, Trophy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { drawKeys, OUTCOME_LABEL, type MatchDetail } from "@/lib/draws"
import { reservationKeys } from "@/lib/reservations"
import { correctResult, enterResult, gamesText, parseGames, resultKeys, SOURCE_LABEL, walkOverEntry, type EntryWalkovers, type OfficialResult, type Outcome } from "@/lib/results"
import { scoringKeys } from "@/lib/scoring"
import { tournamentKeys } from "@/lib/tournaments"
import { cn } from "@/lib/utils"

type Ids = { tournamentId: string; eventId: string; matchId: string }

/** Why a walkover is awarded (REQ-043); the referee picks one, and it is kept in the match-day log. */
const WALKOVER_REASONS = ["No-show after the grace period", "Withdrew before the start", "Injured before the start"]
type Target = { key: string; label: string; rubberId: string | null; decided: boolean; winner: "a" | "b" | ""; outcome: Outcome | ""; games: number[][] }

/** What a result can be recorded for: the match itself, or for a tie its rubbers and the tie as a whole. */
function targetsOf(m: MatchDetail): Target[] {
  const side = (winnerId: string | null) => (winnerId ? (winnerId === m.a.entry?.id ? "a" : "b") : "")
  const whole: Target = { key: "match", label: m.tie ? "The whole tie (a team didn't play or couldn't go on)" : "This match", rubberId: null, decided: m.status === "completed", winner: side(m.winner_id), outcome: m.outcome, games: m.games }
  if (!m.tie) return [whole]
  const next = m.tie.rubbers.find((rubber) => rubber.status === "scheduled")
  const rubbers = m.tie.rubbers
    .filter((rubber) => rubber.status === "completed" || rubber.id === next?.id)
    .map((rubber): Target => ({ key: rubber.id, label: `Rubber ${rubber.position}`, rubberId: rubber.id, decided: rubber.status === "completed", winner: side(rubber.winner_id), outcome: rubber.outcome, games: rubber.games }))
  // A decided tie is corrected through its rubbers; an undecided one can also be awarded as a whole.
  return m.status === "completed" ? rubbers : [...rubbers, whole]
}

/**
 * The official result and, for competition staff, entering or correcting it (REQ-015). A correction
 * never erases anything: the earlier result stays in the history with who changed it and why.
 */
export function ResultControl({ match: m, ids, timeZone }: { match: MatchDetail; ids: Ids; timeZone: string }) {
  const queryClient = useQueryClient()
  const targets = targetsOf(m)
  const [open, setOpen] = useState(false)
  const [targetKey, setTargetKey] = useState("")
  const target = targets.find((candidate) => candidate.key === targetKey) ?? targets[0]
  const [winner, setWinner] = useState<"a" | "b" | "">("")
  const [outcome, setOutcome] = useState<Outcome>("played")
  const [games, setGames] = useState("")
  const [reason, setReason] = useState("")
  const [why, setWhy] = useState(WALKOVER_REASONS[0])
  // A no-show loses every match they have left in the event, not only this one (user request, 2026-11-28).
  const [everyMatch, setEveryMatch] = useState(false)
  const [given, setGiven] = useState<EntryWalkovers | null>(null)
  const parsed = outcome === "walkover" ? [] : parseGames(games)
  const wholeTie = !!m.tie && !target?.rubberId
  // Walkovers and disqualifications are the referee's alone (decision D5); the server says so too.
  const outcomes: Outcome[] = [...(wholeTie ? [] : (["played"] as const)), "retired", ...(m.can_award_walkover ? (["walkover", "disqualified"] as const) : [])]
  const names = { a: m.a.entry?.title ?? "First side", b: m.b?.entry?.title ?? "Second side" }
  const known = !!m.a.entry && !!m.b?.entry

  function refresh() {
    // A result moves the draw on, frees a table and can pause the event.
    void queryClient.invalidateQueries({ queryKey: drawKeys.event(ids.eventId) })
    void queryClient.invalidateQueries({ queryKey: tournamentKeys.detail(ids.tournamentId) })
    void queryClient.invalidateQueries({ queryKey: reservationKeys.board(ids.tournamentId) })
    void queryClient.invalidateQueries({ queryKey: scoringKeys.overview(ids.tournamentId) })
    void queryClient.invalidateQueries({ queryKey: resultKeys.corrections(ids.tournamentId) })
  }

  const loser = winner === "a" ? m.b?.entry : winner === "b" ? m.a.entry : undefined
  const walkAll = useMutation({
    mutationFn: () => walkOverEntry(ids.tournamentId, ids.eventId, loser?.id ?? "", why),
    onSuccess: (shown) => {
      void queryClient.invalidateQueries({ queryKey: drawKeys.match(ids.matchId) })
      refresh()
      setGiven(shown)
      setOpen(false)
    },
  })

  const save = useMutation({
    mutationFn: () => {
      const body = { winner_entry_id: (winner === "a" ? m.a.entry?.id : m.b?.entry?.id) ?? "", outcome, games: parsed ?? [], rubber_id: target.rubberId }
      return target.decided
        ? correctResult(ids.tournamentId, ids.eventId, ids.matchId, { ...body, reason: reason.trim() })
        : enterResult(ids.tournamentId, ids.eventId, ids.matchId, { ...body, reason: outcome === "walkover" ? why : "" })
    },
    onSuccess: (fresh: MatchDetail) => {
      queryClient.setQueryData(drawKeys.match(ids.matchId), fresh)
      refresh()
      setOpen(false)
      setReason("")
    },
  })

  function start(chosen: Target) {
    setTargetKey(chosen.key)
    setWinner(chosen.winner)
    // A whole tie is never "played" here: it is awarded when a team didn't play or couldn't go on.
    const fallback = m.tie && !chosen.rubberId ? (m.can_award_walkover ? "walkover" : "retired") : "played"
    setOutcome(chosen.outcome || fallback)
    setGames(gamesText(chosen.games))
    setEveryMatch(false)
    setGiven(null)
    save.reset()
    walkAll.reset()
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (allOfThem) walkAll.mutate()
    else save.mutate()
  }

  const result = m.result
  const ready = !!winner && parsed !== null && (!target?.decided || !!reason.trim())
  // Only for a walkover still to give on the match (or the whole tie), not on one rubber.
  const canWalkAll = outcome === "walkover" && !!target && !target.decided && !target.rubberId && !!loser
  const allOfThem = canWalkAll && everyMatch
  const pending = save.isPending || walkAll.isPending
  const failed = save.isError ? save.error : walkAll.isError ? walkAll.error : null
  const fieldErrors = save.error instanceof ApiError ? save.error.fieldErrors() : {}

  return (
    <div className="flex flex-col gap-3">
      {m.held_for_correction && (
        <p className="flex items-start gap-2 font-semibold text-warning">
          <TriangleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />
          <span>An earlier result was corrected, which puts one side of this match in question. Nothing more is played or scored here until the organizers decide.</span>
        </p>
      )}
      {result ? (
        <p>
          {SOURCE_LABEL[result.source]}
          {result.recorded_by && ` by ${result.recorded_by}`}, {formatInstant(result.accepted_at, timeZone)}.{result.version > 1 && ` This is version ${result.version} of the result.`}
          {result.processing && (
            <span className="mt-1 flex items-center gap-1 text-sm text-muted-foreground">
              <Hourglass aria-hidden className="size-4 shrink-0" /> What follows from it is still being worked out.
            </span>
          )}
        </p>
      ) : (
        <p className="text-muted-foreground">No official result yet.</p>
      )}

      {given && <WalkoversGiven given={given} />}

      {m.can_record_result && known && targets.length > 0 && !m.held_for_correction && !open && (
        <Button
          variant="outline"
          className="self-start"
          onClick={() => {
            start(targets[0])
            setOpen(true)
          }}
        >
          {targets[0].decided ? "Correct a result" : "Record a result"}
        </Button>
      )}

      {open && target && (
        <form onSubmit={onSubmit} className="flex flex-col gap-4 rounded-lg border bg-card p-3" noValidate>
          {targets.length > 1 && (
            <SelectField
              label="Result of"
              value={target.key}
              onChange={(key) => start(targets.find((candidate) => candidate.key === key) ?? targets[0])}
              options={targets.map((candidate) => ({
                value: candidate.key,
                label: candidate.label + (candidate.decided ? " (correct it)" : ""),
              }))}
            />
          )}
          <div className="flex flex-col gap-2">
            <span className="font-semibold">Winner</span>
            {/* The two sides stay left and right, and long names wrap inside their half (REQ-002). */}
            <div role="group" aria-label="Winner" className="grid grid-cols-2 gap-2">
              {(["a", "b"] as const).map((side) => (
                <button
                  key={side}
                  type="button"
                  aria-pressed={winner === side}
                  onClick={() => setWinner(side)}
                  className={cn(
                    "flex min-h-12 min-w-0 items-center gap-2 rounded-lg border bg-card px-3 py-2 font-semibold break-words text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    side === "b" && "flex-row-reverse text-right",
                    winner === side && "border-brand-blue bg-surface-selected text-brand-blue"
                  )}
                >
                  {winner === side && <Trophy aria-hidden className="size-5 shrink-0" />}
                  <span className="min-w-0">{names[side]}</span>
                </button>
              ))}
            </div>
          </div>
          <SelectField
            label="How it ended"
            value={outcome}
            onChange={(value) => setOutcome(value as Outcome)}
            options={outcomes.map((value) => ({ value, label: OUTCOME_LABEL[value] }))}
            hint={m.can_award_walkover ? undefined : "Only the referee awards a walkover or a disqualification."}
          />
          {outcome === "walkover" && !target.decided && (
            <SelectField label="Why a walkover" value={why} onChange={setWhy} options={WALKOVER_REASONS.map((value) => ({ value, label: value }))} hint="Kept in the match-day log. A walkover records no game scores." />
          )}
          {canWalkAll && (
            <label className="flex items-start gap-3">
              <input type="checkbox" className="mt-0.5 size-5 shrink-0 accent-brand-blue" checked={everyMatch} onChange={(e) => setEveryMatch(e.target.checked)} />
              <span>
                <span className="font-semibold">Every match {loser.title} has left in this event</span>
                <span className="block text-sm text-muted-foreground">Each of their opponents wins by walkover, with the same reason. Matches already being scored are left as they are.</span>
              </span>
            </label>
          )}
          {outcome !== "walkover" && !wholeTie && (
            <Field
              label="Games"
              value={games}
              onChange={(e) => setGames(e.target.value)}
              placeholder="11-5 11-7 9-11 11-8"
              hint={`Points of each game, ${names.a}'s first. For a retirement or a disqualification, the games played so far (none before play).`}
              error={games.trim() && parsed === null ? "Write each game as two numbers, like 11-5." : fieldErrors.games}
            />
          )}
          {target.decided && (
            <Field label="Why is it corrected?" required maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="Kept with the result. The result it replaces stays in the history." error={fieldErrors.reason} />
          )}
          {target.decided && <p className="text-sm text-muted-foreground">If this changes who goes on and their next match has already started, the event is paused until you decide what happens to that match.</p>}
          {failed && <FormAlert>{errorMessage(failed)}</FormAlert>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={!ready || pending}>
              {pending ? "Saving…" : target.decided ? "Correct the result" : allOfThem ? "Give every walkover" : "Make it official"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {m.result_history.length > 1 && (
        <details className="text-sm">
          <summary className="min-h-12 cursor-pointer py-3 font-semibold text-brand-blue">History of this result</summary>
          <ol className="flex flex-col gap-2">
            {m.result_history.map((version) => (
              <Version key={version.id} version={version} names={names} aId={m.a.entry?.id} timeZone={timeZone} />
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}

function Version({ version, names, aId, timeZone }: { version: OfficialResult; names: { a: string; b: string }; aId?: string; timeZone: string }) {
  const state = version.struck_out ? "struck out, to be played again" : version.current ? "stands" : "replaced"
  return (
    <li className="rounded-lg border bg-card p-3">
      <p className="font-semibold">
        {version.rubber ? `Rubber ${version.rubber}, version ${version.version}` : `Version ${version.version}`} ({state})
      </p>
      <p className="grid grid-cols-[1fr_auto_1fr] items-start gap-2">
        <Side name={names.a} won={version.winner_id === aId} />
        <span className="text-muted-foreground">v</span>
        <Side name={names.b} won={version.winner_id !== aId} right />
      </p>
      <p>
        {version.outcome !== "played" && `${OUTCOME_LABEL[version.outcome]}. `}
        {version.games.length > 0 && `Games: ${gamesText(version.games)}.`}
      </p>
      <p className="text-muted-foreground">
        {SOURCE_LABEL[version.source]}
        {version.recorded_by && ` by ${version.recorded_by}`}, {formatInstant(version.accepted_at, timeZone)}.{version.reason && ` Reason: ${version.reason}`}
      </p>
    </li>
  )
}

function Side({ name, won, right }: { name: string; won: boolean; right?: boolean }) {
  return (
    <span className={cn("flex min-w-0 flex-col", right && "items-end text-right")}>
      <span className={cn("min-w-0 break-words", won && "font-semibold")}>{name}</span>
      {won && (
        <span className="flex items-center gap-1 text-sm font-semibold text-success">
          <Trophy aria-hidden className="size-4 shrink-0" /> Won
        </span>
      )}
    </span>
  )
}

/** What a walkover in every remaining match did: how many were given, and those left as they were. */
function WalkoversGiven({ given }: { given: EntryWalkovers }) {
  const count = given.awarded.length
  return (
    <div className="flex flex-col gap-1 rounded-lg border bg-card p-3" role="status">
      <p className="font-semibold">{count === 0 ? "No walkovers were given." : count === 1 ? "1 walkover given." : `${count} walkovers given.`}</p>
      {given.awarded.length > 0 && <p className="text-sm text-muted-foreground">To {given.awarded.map((item) => `${item.opponent} (${item.label})`).join(", ")}.</p>}
      {given.skipped.length > 0 && (
        <ul className="text-sm text-muted-foreground">
          {given.skipped.map((item) => (
            <li key={item.match_id}>
              Left as it was: {item.opponent ? `against ${item.opponent}` : "a match"} ({item.label}). {item.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
