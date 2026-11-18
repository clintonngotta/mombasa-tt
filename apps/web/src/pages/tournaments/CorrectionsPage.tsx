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
import { drawKeys } from "@/lib/draws"
import { reservationKeys } from "@/lib/reservations"
import { getCorrections, resolveCorrection, resultKeys, type Resolution } from "@/lib/results"
import { getTournament, tournamentKeys } from "@/lib/tournaments"

const PROGRESS: Record<Resolution["progress"], string> = {
  decided: "has already been played and decided",
  on_table: "is on a table",
  being_scored: "is being scored",
}

/**
 * Corrected results that reach into later play (REQ-015). When a correction changes who should be in
 * a match that had already started, nobody is swapped silently: the event is paused and the
 * organizers choose here between keeping that match as played and putting the right entry in.
 */
export function CorrectionsPage() {
  const { id = "" } = useParams()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const corrections = useQuery({ queryKey: resultKeys.corrections(id), queryFn: () => getCorrections(id), staleTime: 0 })
  const refused = corrections.error instanceof ApiError && (corrections.error.status === 403 || corrections.error.status === 404)
  const t = tournament.data
  const waiting = corrections.data?.filter((one) => !one.resolved_at) ?? []
  const settled = corrections.data?.filter((one) => one.resolved_at) ?? []

  return (
    <div className="flex max-w-[900px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      <header className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Corrections</h1>
        <p className="text-muted-foreground">Matches that had started with an entry a corrected result says should not be there. An event stays paused, with no match sent to a table, until each is decided.</p>
      </header>
      {(corrections.isPending || (tournament.isPending && !corrections.isError)) && <p className="text-muted-foreground">Loading…</p>}
      {refused && <AccessLost />}
      {corrections.isError && !refused && <FormAlert>{errorMessage(corrections.error, "We couldn't load the corrections.")}</FormAlert>}
      {corrections.data && t && (
        <>
          <section aria-labelledby="waiting-heading" className="flex flex-col gap-3">
            <h2 id="waiting-heading" className="text-2xl font-bold">
              Waiting for your decision
            </h2>
            {waiting.length === 0 ? (
              <p className="flex items-center gap-2 text-muted-foreground">
                <CircleCheck aria-hidden className="size-5 text-success" /> Nothing is waiting. No event is paused.
              </p>
            ) : (
              <ul className="flex flex-col gap-3">
                {waiting.map((one) => (
                  <Waiting key={one.id} tournamentId={id} resolution={one} timeZone={t.timezone} />
                ))}
              </ul>
            )}
          </section>
          {settled.length > 0 && (
            <section aria-labelledby="settled-heading" className="flex flex-col gap-3">
              <h2 id="settled-heading" className="text-2xl font-bold">
                Decided
              </h2>
              <ul className="flex flex-col gap-3">
                {settled.map((one) => (
                  <li key={one.id} className="flex flex-col gap-2 rounded-xl border bg-card p-4">
                    <Heading resolution={one} />
                    <p className="flex items-start gap-2 text-sm">
                      <CircleCheck aria-hidden className="mt-0.5 size-5 shrink-0 text-success" />
                      <span>
                        {one.choice === "keep" ? `Kept as played, with ${one.old_entry}` : one.new_entry ? `${one.new_entry} put in for ${one.old_entry}; what was played was struck out` : `${one.old_entry} taken out; what was played was struck out`}
                        . Decided by {one.resolved_by || "staff"}, {formatInstant(one.resolved_at!, t.timezone)}: {one.note}
                      </span>
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}

/** The match in question, its two sides left and right (REQ-002). */
function Heading({ resolution: one }: { resolution: Resolution }) {
  return (
    <>
      <p className="text-sm font-semibold text-muted-foreground">
        {one.event_name} · {one.label}
      </p>
      <p className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 font-semibold">
        <span className="min-w-0 break-words">{one.a || "To be decided"}</span>
        <span className="text-sm font-normal text-muted-foreground">v</span>
        <span className="min-w-0 text-right break-words">{one.b || "To be decided"}</span>
      </p>
    </>
  )
}

function Waiting({ tournamentId, resolution: one, timeZone }: { tournamentId: string; resolution: Resolution; timeZone: string }) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState("")
  const decide = useMutation({
    mutationFn: (choice: "keep" | "replace") => resolveCorrection(tournamentId, one.id, choice, note.trim()),
    onSuccess: (fresh: Resolution[]) => {
      queryClient.setQueryData(resultKeys.corrections(tournamentId), fresh)
      void queryClient.invalidateQueries({ queryKey: tournamentKeys.detail(tournamentId) })
      void queryClient.invalidateQueries({ queryKey: drawKeys.event(one.event_id) })
      void queryClient.invalidateQueries({ queryKey: drawKeys.match(one.match_id) })
      void queryClient.invalidateQueries({ queryKey: reservationKeys.board(tournamentId) })
    },
  })
  const should = one.new_entry ? `${one.new_entry} should be there now` : "that place is open again until an earlier match is replayed"

  return (
    <li className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <Heading resolution={one} />
      <p className="flex items-start gap-2 font-semibold text-warning">
        <TriangleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />
        <span>
          This match {PROGRESS[one.progress]} with {one.old_entry}, but after a correction {should}.
        </span>
      </p>
      <p className="text-sm">
        Corrected{one.corrected_by && ` by ${one.corrected_by}`}, {formatInstant(one.created_at, timeZone)}: {one.reason}
      </p>
      <form onSubmit={(e: FormEvent) => e.preventDefault()} className="flex flex-col gap-3" noValidate>
        <Field label="What was agreed" required maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} hint="Kept on record with your decision. For example: referee and both players agreed to replay." />
        {decide.isError && <FormAlert>{errorMessage(decide.error)}</FormAlert>}
        <div className="flex flex-wrap gap-2">
          <Button type="button" disabled={!note.trim() || decide.isPending} onClick={() => decide.mutate("keep")}>
            Keep the match as played
          </Button>
          <Button type="button" variant="destructive" disabled={!note.trim() || decide.isPending} onClick={() => decide.mutate("replace")}>
            {one.new_entry ? `Put ${one.new_entry} in and replay` : `Take ${one.old_entry} out and replay`}
          </Button>
          <Link to={`/tournaments/${tournamentId}/events/${one.event_id}/matches/${one.match_id}`} className={buttonVariants({ variant: "outline" })}>
            Open the match
          </Link>
        </div>
        <p className="text-sm text-muted-foreground">Replaying takes the match off its table and strikes out its score and result. They are kept on record, not deleted.</p>
      </form>
    </li>
  )
}
