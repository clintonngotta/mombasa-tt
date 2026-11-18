import { useState, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Hourglass, TriangleAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { Segmented } from "@/components/forms/Segmented"
import { SelectField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { drawKeys, OUTCOME_LABEL, type MatchDetail } from "@/lib/draws"
import { reservationKeys } from "@/lib/reservations"
import { correctResult, enterResult, gamesText, parseGames, resultKeys, SOURCE_LABEL, type OfficialResult, type Outcome } from "@/lib/results"
import { scoringKeys } from "@/lib/scoring"
import { tournamentKeys } from "@/lib/tournaments"

type Ids = { tournamentId: string; eventId: string; matchId: string }
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
  const parsed = outcome === "walkover" ? [] : parseGames(games)
  const names = { a: m.a.entry?.title ?? "First side", b: m.b?.entry?.title ?? "Second side" }
  const known = !!m.a.entry && !!m.b?.entry

  const save = useMutation({
    mutationFn: () => {
      const body = { winner_entry_id: (winner === "a" ? m.a.entry?.id : m.b?.entry?.id) ?? "", outcome, games: parsed ?? [], rubber_id: target.rubberId }
      return target.decided ? correctResult(ids.tournamentId, ids.eventId, ids.matchId, { ...body, reason: reason.trim() }) : enterResult(ids.tournamentId, ids.eventId, ids.matchId, body)
    },
    onSuccess: (fresh: MatchDetail) => {
      queryClient.setQueryData(drawKeys.match(ids.matchId), fresh)
      // A result moves the draw on, frees a table and can pause the event.
      void queryClient.invalidateQueries({ queryKey: drawKeys.event(ids.eventId) })
      void queryClient.invalidateQueries({ queryKey: tournamentKeys.detail(ids.tournamentId) })
      void queryClient.invalidateQueries({ queryKey: reservationKeys.board(ids.tournamentId) })
      void queryClient.invalidateQueries({ queryKey: scoringKeys.overview(ids.tournamentId) })
      void queryClient.invalidateQueries({ queryKey: resultKeys.corrections(ids.tournamentId) })
      setOpen(false)
      setReason("")
    },
  })

  function start(chosen: Target) {
    setTargetKey(chosen.key)
    setWinner(chosen.winner)
    setOutcome(chosen.outcome || "played")
    setGames(gamesText(chosen.games))
    save.reset()
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  const result = m.result
  const ready = !!winner && parsed !== null && (!target?.decided || !!reason.trim())
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
            <SelectField label="Result of" value={target.key} onChange={(e) => start(targets.find((candidate) => candidate.key === e.target.value) ?? targets[0])}>
              {targets.map((candidate) => (
                <option key={candidate.key} value={candidate.key}>
                  {candidate.label}
                  {candidate.decided ? " (correct it)" : ""}
                </option>
              ))}
            </SelectField>
          )}
          <div className="flex flex-col gap-2">
            <span className="font-semibold">Winner</span>
            <Segmented
              label="Winner"
              value={winner}
              onChange={setWinner}
              options={[
                { value: "a", label: names.a },
                { value: "b", label: names.b },
              ]}
            />
          </div>
          <SelectField label="How it ended" value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
            {(["played", "walkover", "retired"] as const).map((value) => (
              <option key={value} value={value}>
                {OUTCOME_LABEL[value]}
              </option>
            ))}
          </SelectField>
          {outcome !== "walkover" && !(m.tie && !target.rubberId) && (
            <Field
              label="Games"
              value={games}
              onChange={(e) => setGames(e.target.value)}
              placeholder="11-5 11-7 9-11 11-8"
              hint={`Points of each game, ${names.a}'s first. For a retirement, the games played so far.`}
              error={games.trim() && parsed === null ? "Write each game as two numbers, like 11-5." : fieldErrors.games}
            />
          )}
          {target.decided && (
            <Field label="Why is it corrected?" required maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="Kept with the result. The result it replaces stays in the history." error={fieldErrors.reason} />
          )}
          {target.decided && <p className="text-sm text-muted-foreground">If this changes who goes on and their next match has already started, the event is paused until you decide what happens to that match.</p>}
          {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={!ready || save.isPending}>
              {save.isPending ? "Saving…" : target.decided ? "Correct the result" : "Make it official"}
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
      <p>
        {version.winner_id === aId ? names.a : names.b} won{version.outcome !== "played" && ` (${OUTCOME_LABEL[version.outcome].toLowerCase()})`}
        {version.games.length > 0 && `: ${gamesText(version.games)}`}.
      </p>
      <p className="text-muted-foreground">
        {SOURCE_LABEL[version.source]}
        {version.recorded_by && ` by ${version.recorded_by}`}, {formatInstant(version.accepted_at, timeZone)}.{version.reason && ` Reason: ${version.reason}`}
      </p>
    </li>
  )
}
