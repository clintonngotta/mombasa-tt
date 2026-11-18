import { useState, type FormEvent } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, TriangleAlert } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { getScoringOverview, resolveConflict, SCORING_STATUS_LABEL, scoringKeys, type OpenSheet, type ScoreConflict, type ScoringOverview } from "@/lib/scoring"
import { getTournament, tournamentKeys } from "@/lib/tournaments"

const STEP: Record<OpenSheet["history"][number]["kind"], string> = {
  assigned: "Assigned to",
  unassigned: "Taken back from its umpire",
  device: "Opened on",
  take_over: "Taken over on",
}

type Sent = { type?: string; side?: string; player?: string }

/** A score event in a few words, without the score: only what the event itself says. */
function eventWords(event: unknown, a: string, b: string): string {
  const sent = (event ?? {}) as Sent
  const side = sent.side === "a" ? a : sent.side === "b" ? b : "?"
  switch (sent.type) {
    case "start":
      return "Match started"
    case "point":
      return `Point to ${side}`
    case "timeout":
      return `Time-out: ${side}`
    case "choose_server":
      return "First server chosen"
    case "undo":
      return "Undo"
    default:
      return "Unknown action"
  }
}

/**
 * Scoring in one tournament for its competition staff (REQ-013, REQ-015): matches being scored or
 * waiting for their umpire to confirm, who held each sheet on which device, and what devices wrote
 * that the server did not accept. A report never changes a score; this page is where it is read.
 */
export function ScoringOverviewPage() {
  const { id = "" } = useParams()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const overview = useQuery({ queryKey: scoringKeys.overview(id), queryFn: () => getScoringOverview(id), refetchInterval: 20_000, staleTime: 0 })
  const refused = overview.error instanceof ApiError && (overview.error.status === 403 || overview.error.status === 404)
  const t = tournament.data
  const open = overview.data?.conflicts.filter((conflict) => !conflict.resolved_at) ?? []
  const closed = overview.data?.conflicts.filter((conflict) => conflict.resolved_at) ?? []

  return (
    <div className="flex max-w-[900px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      <header className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Scoring</h1>
        <p className="text-muted-foreground">Tables and players in use, results waiting for their umpire, and anything a device scored that didn't reach the official score.</p>
      </header>
      {(overview.isPending || (tournament.isPending && !overview.isError)) && <p className="text-muted-foreground">Loading…</p>}
      {tournament.isError && !refused && <FormAlert>{errorMessage(tournament.error, "We couldn't load this tournament.")}</FormAlert>}
      {refused && <AccessLost />}
      {overview.isError && !refused && <FormAlert>{errorMessage(overview.error, "We couldn't load the scoring page.")}</FormAlert>}
      {overview.data && t && (
        <>
          <section aria-labelledby="conflicts-heading" className="flex flex-col gap-3">
            <h2 id="conflicts-heading" className="text-2xl font-bold">
              Not accepted from a device
            </h2>
            {open.length === 0 ? (
              <p className="flex items-center gap-2 text-muted-foreground">
                <CircleCheck aria-hidden className="size-5 text-success" /> Nothing waiting. Every device's actions are in the official scores.
              </p>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">
                  These actions were scored on a device after the match had been given to another umpire or device, or after the score had moved on. They are not in the official score. Check with the umpire and the players; if the
                  official score is wrong, reassign the match so it can be put right, then record what you did.
                </p>
                <ul className="flex flex-col gap-3">
                  {open.map((conflict) => (
                    <Conflict key={conflict.id} tournamentId={id} conflict={conflict} timeZone={t.timezone} />
                  ))}
                </ul>
              </>
            )}
          </section>

          <section aria-labelledby="tables-heading" className="flex flex-col gap-3">
            <h2 id="tables-heading" className="text-2xl font-bold">
              On the tables
            </h2>
            {overview.data.reservations.length === 0 ? (
              <p className="text-muted-foreground">No match is on a table.</p>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">A table and its players stay held until the umpire confirms the result or the match is called back, however long ago it finished.</p>
                <ul className="flex flex-col gap-3">
                  {overview.data.reservations.map((held) => (
                    <li key={held.id} className="flex flex-col gap-2 rounded-xl border bg-card p-4">
                      <p className="text-sm font-semibold text-muted-foreground">
                        {held.table} · {held.event_name}
                      </p>
                      <p className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 font-semibold">
                        <span className="min-w-0 break-words">{held.a}</span>
                        <span className="text-sm font-normal text-muted-foreground">v</span>
                        <span className="min-w-0 text-right break-words">{held.b}</span>
                      </p>
                      <p className="text-sm">
                        Since {formatInstant(held.since, t.timezone)}. Held: {held.table}
                        {held.people.length > 0 && `, ${held.people.join(", ")}`}.
                        {held.overrides.length > 0 && ` Sent with ${held.overrides.map((name) => (name === "check_in" ? "check-in" : "rest")).join(" and ")} set aside: ${held.override_reason}`}
                      </p>
                      <Link to={`/tournaments/${id}/events/${held.event_id}/matches/${held.match_id}`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
                        Open the match
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <section aria-labelledby="sheets-heading" className="flex flex-col gap-3">
            <h2 id="sheets-heading" className="text-2xl font-bold">
              Being scored or waiting for confirmation
            </h2>
            {overview.data.sheets.length === 0 ? (
              <p className="text-muted-foreground">No match is being scored right now.</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {overview.data.sheets.map((sheet) => (
                  <Sheet key={sheet.sheet.scorecard_id} tournamentId={id} sheet={sheet} timeZone={t.timezone} />
                ))}
              </ul>
            )}
          </section>

          {closed.length > 0 && (
            <section aria-labelledby="closed-heading" className="flex flex-col gap-3">
              <h2 id="closed-heading" className="text-2xl font-bold">
                Dealt with
              </h2>
              <ul className="flex flex-col gap-3">
                {closed.map((conflict) => (
                  <Conflict key={conflict.id} tournamentId={id} conflict={conflict} timeZone={t.timezone} />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}

const matchPath = (tournamentId: string, sheet: OpenSheet["sheet"]) => `/tournaments/${tournamentId}/events/${sheet.event_id}/matches/${sheet.match_id}`

/** The two sides left and right (REQ-002), with what is between them. */
function Sides({ sheet, middle }: { sheet: OpenSheet["sheet"]; middle: string }) {
  return (
    <p className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 font-semibold">
      <span className="min-w-0 break-words">{sheet.a}</span>
      <span className="font-display text-xl tabular-nums">{middle}</span>
      <span className="min-w-0 text-right break-words">{sheet.b}</span>
    </p>
  )
}

function Sheet({ tournamentId, sheet, timeZone }: { tournamentId: string; sheet: OpenSheet; timeZone: string }) {
  const waiting = sheet.status === "finished"
  const games = sheet.games.map(([a, b]) => `${a}–${b}`).join(", ")
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="text-sm font-semibold text-muted-foreground">
        {sheet.sheet.event_name} · {sheet.sheet.label}
      </p>
      <Sides sheet={sheet.sheet} middle={waiting ? "finished" : `${sheet.points[0]}–${sheet.points[1]}`} />
      {games && <p className="text-center text-sm tabular-nums text-muted-foreground">Games: {games}</p>}
      <p className={waiting ? "flex items-start gap-2 font-semibold text-warning" : "text-sm"}>
        {waiting && <TriangleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />}
        <span>
          {SCORING_STATUS_LABEL[sheet.status]}. Umpire: {sheet.umpire || "nobody"}
          {sheet.device_label && ` on ${sheet.device_label}`}.{sheet.last_event_at && ` Last action ${formatInstant(sheet.last_event_at, timeZone)}.`}
          {waiting && " The result isn't official, and the draw doesn't move on, until the umpire confirms it."}
        </span>
      </p>
      <details className="text-sm">
        <summary className="min-h-12 cursor-pointer py-3 font-semibold text-brand-blue">Who has held this match</summary>
        <ol className="flex flex-col gap-1">
          {sheet.history.map((step, index) => (
            <li key={index}>
              {formatInstant(step.created_at, timeZone)}: {STEP[step.kind]} {step.kind === "assigned" ? step.umpire : step.kind === "unassigned" ? "" : `${step.device_label || "a device"} (${step.umpire})`}
              {step.kind !== "device" && step.kind !== "take_over" && step.actor && ` by ${step.actor}`}, after {step.revision} {step.revision === 1 ? "action" : "actions"}.
            </li>
          ))}
        </ol>
      </details>
      <Link to={matchPath(tournamentId, sheet.sheet)} className={buttonVariants({ variant: "outline", className: "self-start" })}>
        Open the match to reassign it
      </Link>
    </li>
  )
}

function Conflict({ tournamentId, conflict, timeZone }: { tournamentId: string; conflict: ScoreConflict; timeZone: string }) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState("")
  const resolve = useMutation({
    mutationFn: () => resolveConflict(tournamentId, conflict.id, note.trim()),
    onSuccess: (fresh: ScoringOverview) => queryClient.setQueryData(scoringKeys.overview(tournamentId), fresh),
  })
  const official = new Map(conflict.accepted.map((kept) => [kept.sequence, kept.event]))
  const { a, b } = conflict.sheet

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    resolve.mutate()
  }

  return (
    <li className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <p className="text-sm font-semibold text-muted-foreground">
        {conflict.sheet.event_name} · {conflict.sheet.label}
      </p>
      <Sides sheet={conflict.sheet} middle="v" />
      <p className="text-sm">
        Reported by {conflict.reported_by || "a former umpire"}
        {conflict.device_label && ` from ${conflict.device_label}`}, {formatInstant(conflict.created_at, timeZone)}.
      </p>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">What the device scored and what the official score holds at the same places</caption>
          <thead className="text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">Action no.</th>
              <th scope="col" className="px-3 py-2 font-semibold">On the device (not accepted)</th>
              <th scope="col" className="px-3 py-2 font-semibold">Official score</th>
            </tr>
          </thead>
          <tbody>
            {conflict.events.map((sent, index) => (
              <tr key={index} className="border-t">
                <td className="px-3 py-2 tabular-nums">{sent.sequence}</td>
                <td className="px-3 py-2">{eventWords(sent.event, a, b)}</td>
                <td className="px-3 py-2">{official.has(sent.sequence) ? eventWords(official.get(sent.sequence), a, b) : "Nothing at this place"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {conflict.resolved_at ? (
        <p className="flex items-start gap-2 text-sm">
          <CircleCheck aria-hidden className="mt-0.5 size-5 shrink-0 text-success" />
          <span>
            Dealt with by {conflict.resolved_by || "staff"}, {formatInstant(conflict.resolved_at, timeZone)}: {conflict.resolution}
          </span>
        </p>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-3" noValidate>
          <Field
            label="What was done about it"
            required
            maxLength={300}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            hint="For example: both players agree with the official score. This is kept on record with the report."
            error={resolve.error instanceof ApiError ? resolve.error.fieldErrors().note : undefined}
          />
          {resolve.isError && !(resolve.error instanceof ApiError && resolve.error.fieldErrors().note) && <FormAlert>{errorMessage(resolve.error)}</FormAlert>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={!note.trim() || resolve.isPending}>
              {resolve.isPending ? "Saving…" : "Mark as dealt with"}
            </Button>
            <Link to={matchPath(tournamentId, conflict.sheet)} className={buttonVariants({ variant: "outline" })}>
              Open the match
            </Link>
          </div>
        </form>
      )}
    </li>
  )
}
