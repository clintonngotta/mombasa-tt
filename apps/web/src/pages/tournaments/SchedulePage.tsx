import { useMemo, useState } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { TriangleAlert } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { fromZonedInput, toZonedInput } from "@/lib/dates"
import { checkSchedule, conflictsOf, getSchedule, keepSchedule, recommendSchedule, scheduleKeys, type Problem, type Schedule, type Slot } from "@/lib/schedule"
import { getTournament, tournamentKeys } from "@/lib/tournaments"

type Draft = { table_id: string; local: string }
type Drafts = Record<string, Draft>

const fromRows = (schedule: Schedule, timeZone: string): Drafts =>
  Object.fromEntries(schedule.rows.map((row) => [row.match_id, { table_id: row.table_id ?? "", local: toZonedInput(row.scheduled_at, timeZone) }]))

/**
 * The day schedule for a tournament's competition staff (TASK-099). The app recommends a start and a
 * table for every match still to be played; the organizers change any of them, check, and keep it.
 * The server refuses a schedule where a table, a player or a round's order wouldn't work.
 */
export function SchedulePage() {
  const { id = "" } = useParams()
  const queryClient = useQueryClient()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const schedule = useQuery({ queryKey: scheduleKeys.detail(id), queryFn: () => getSchedule(id) })
  const refused = schedule.error instanceof ApiError && (schedule.error.status === 403 || schedule.error.status === 404)
  const timeZone = tournament.data?.timezone ?? "Africa/Nairobi"

  // Only what the organizers changed; everything else shows as kept.
  const [edits, setEdits] = useState<Drafts>({})
  const [problems, setProblems] = useState<{ conflicts: Problem[]; warnings: Problem[] } | null>(null)
  const [dayStarts, setDayStarts] = useState("09:00")
  const [dayEnds, setDayEnds] = useState("21:00")
  const [tableIds, setTableIds] = useState<string[] | null>(null)
  const [notice, setNotice] = useState("")
  const [beyond, setBeyond] = useState(0)

  const data = schedule.data
  const tables = useMemo(() => data?.tables ?? [], [data])
  const chosenTables = tableIds ?? tables.map((table) => table.id)

  const kept = useMemo(() => (data && tournament.data ? fromRows(data, timeZone) : {}), [data, tournament.data, timeZone])
  const drafts: Drafts = { ...kept, ...edits }
  const changed: Slot[] = Object.entries(drafts)
    .filter(([pk, draft]) => kept[pk] && (kept[pk].table_id !== draft.table_id || kept[pk].local !== draft.local))
    .map(([pk, draft]) => ({ match_id: pk, table_id: draft.table_id || null, scheduled_at: fromZonedInput(draft.local, timeZone) }))

  const recommend = useMutation({
    mutationFn: () => recommendSchedule(id, { day_starts: dayStarts, day_ends: dayEnds, table_ids: chosenTables }),
    onSuccess: (made) => {
      setEdits((now) => {
        const next = { ...now }
        for (const slot of made.slots) next[slot.match_id] = { table_id: slot.table_id ?? "", local: toZonedInput(slot.scheduled_at, timeZone) }
        return next
      })
      setProblems({ conflicts: made.conflicts, warnings: made.warnings })
      setBeyond(made.slots.filter((slot) => slot.beyond_last_day).length)
      setNotice("Recommended. Change anything you need, then keep the schedule.")
    },
  })
  const check = useMutation({
    mutationFn: () => checkSchedule(id, changed),
    onSuccess: (found) => {
      setProblems(found)
      setNotice(found.conflicts.length ? "" : "No conflicts.")
    },
  })
  const keep = useMutation({
    mutationFn: () => keepSchedule(id, changed),
    onSuccess: (fresh) => {
      queryClient.setQueryData(scheduleKeys.detail(id), fresh)
      setEdits({})
      setProblems({ conflicts: fresh.conflicts, warnings: fresh.warnings })
      setBeyond(0)
      setNotice("Schedule kept.")
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "schedule_conflicts") setProblems({ conflicts: conflictsOf(error.body), warnings: [] })
    },
  })

  if (refused) return <AccessLost />

  const shown = problems ?? (data ? { conflicts: data.conflicts, warnings: data.warnings } : { conflicts: [], warnings: [] })
  const problemsOf = (pk: string) => ({
    conflicts: shown.conflicts.filter((p) => p.match_id === pk),
    warnings: shown.warnings.filter((p) => p.match_id === pk),
  })
  const rows = [...(data?.rows ?? [])].sort((a, b) => {
    const [x, y] = [drafts[a.match_id]?.local || "~", drafts[b.match_id]?.local || "~"]
    return x.localeCompare(y)
  })
  const set = (pk: string, change: Partial<Draft>) => {
    setEdits((now) => ({ ...now, [pk]: { ...drafts[pk], ...now[pk], ...change } }))
    setNotice("")
  }
  const keepError = keep.error && !(keep.error instanceof ApiError && keep.error.code === "schedule_conflicts") ? errorMessage(keep.error) : ""

  return (
    <div className="flex max-w-[960px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{tournament.data?.name ?? "Tournament"}</BackLink>
      <header className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Schedule</h1>
        <p className="text-muted-foreground">
          When and on which table each match is planned, in the venue's time ({timeZone}). Times are estimates from each event's best-of; the tables board sends matches
          out in this order.
        </p>
      </header>

      {schedule.isPending && <p className="text-muted-foreground">Loading the schedule…</p>}
      {schedule.error && !refused && <FormAlert>{errorMessage(schedule.error)}</FormAlert>}

      {data && (
        <>
          <section aria-labelledby="recommend-heading" className="flex flex-col gap-4 rounded-xl border bg-card p-4">
            <h2 id="recommend-heading" className="text-xl font-bold">
              Recommend a schedule
            </h2>
            <p className="text-sm text-muted-foreground">
              Every match gets the earliest start and table where nobody plays twice at once or without their rest, and no match comes before the ones it waits for.
              Nothing is kept until you keep it.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Day starts" type="time" value={dayStarts} onChange={(e) => setDayStarts(e.target.value)} />
              <Field label="Day ends" type="time" value={dayEnds} onChange={(e) => setDayEnds(e.target.value)} />
            </div>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 text-sm font-semibold">Tables to use</legend>
              {tables.length === 0 && <p className="text-sm text-muted-foreground">The venue has no tables yet. Add them on the venue's page.</p>}
              <div className="flex flex-wrap gap-3">
                {tables.map((table) => (
                  <label key={table.id} className="flex min-h-11 items-center gap-2 rounded-lg border px-3">
                    <input
                      type="checkbox"
                      checked={chosenTables.includes(table.id)}
                      onChange={(e) => setTableIds(e.target.checked ? [...chosenTables, table.id] : chosenTables.filter((pk) => pk !== table.id))}
                    />
                    {table.label}
                  </label>
                ))}
              </div>
            </fieldset>
            {recommend.error && <FormAlert>{errorMessage(recommend.error)}</FormAlert>}
            <Button className="self-start" onClick={() => recommend.mutate()} disabled={recommend.isPending || chosenTables.length === 0 || rows.length === 0}>
              {recommend.isPending ? "Recommending…" : "Recommend times and tables"}
            </Button>
            {beyond > 0 && (
              <p className="flex items-center gap-2 text-sm text-warning">
                <TriangleAlert className="size-4" aria-hidden />
                {beyond} {beyond === 1 ? "match doesn't" : "matches don't"} fit in the tournament's days. Use more tables or longer days.
              </p>
            )}
          </section>

          {rows.length === 0 ? (
            <p className="text-muted-foreground">Nothing to plan: publish an event's draw first. Matches already decided or on a table aren't planned here.</p>
          ) : (
            <section aria-labelledby="plan-heading" className="flex flex-col gap-3">
              <h2 id="plan-heading" className="text-xl font-bold">
                Matches ({rows.length})
              </h2>
              <ol className="flex flex-col gap-3">
                {rows.map((row) => {
                  const draft = drafts[row.match_id] ?? { table_id: "", local: "" }
                  const own = problemsOf(row.match_id)
                  return (
                    <li key={row.match_id} className={`flex flex-col gap-3 rounded-xl border bg-card p-4 ${own.conflicts.length ? "border-destructive" : ""}`}>
                      <div className="flex flex-col gap-0.5">
                        <p className="text-sm text-muted-foreground">
                          {row.label} · {row.minutes} min
                        </p>
                        <p className="font-semibold break-words">{row.title}</p>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <label className="flex flex-col gap-1 text-sm font-semibold">
                          Table
                          <select
                            className="h-12 rounded-lg border bg-background px-3 text-base font-normal"
                            value={draft.table_id}
                            onChange={(e) => set(row.match_id, { table_id: e.target.value })}
                          >
                            <option value="">No table yet</option>
                            {tables.map((table) => (
                              <option key={table.id} value={table.id}>
                                {table.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="flex flex-col gap-1 text-sm font-semibold">
                          Starts
                          <input
                            type="datetime-local"
                            className="h-12 rounded-lg border bg-background px-3 text-base font-normal"
                            value={draft.local}
                            onChange={(e) => set(row.match_id, { local: e.target.value })}
                          />
                        </label>
                      </div>
                      {own.conflicts.map((p) => (
                        <p key={p.code + p.message} className="text-sm font-semibold text-destructive" role="alert">
                          {p.message}
                        </p>
                      ))}
                      {own.warnings.map((p) => (
                        <p key={p.code + p.message} className="text-sm text-warning">
                          {p.message}
                        </p>
                      ))}
                    </li>
                  )
                })}
              </ol>
            </section>
          )}

          {rows.length > 0 && (
            <div className="sticky bottom-0 flex flex-col gap-2 border-t bg-background py-3">
              {keepError && <FormAlert>{keepError}</FormAlert>}
              {check.error && <FormAlert>{errorMessage(check.error)}</FormAlert>}
              {shown.conflicts.length > 0 && (
                <p className="text-sm font-semibold text-destructive">
                  {shown.conflicts.length} {shown.conflicts.length === 1 ? "conflict" : "conflicts"} to settle before keeping.
                </p>
              )}
              {notice && <p className="text-sm text-muted-foreground" role="status">{notice}</p>}
              <div className="flex flex-wrap gap-3">
                <Button onClick={() => keep.mutate()} disabled={keep.isPending || changed.length === 0}>
                  {keep.isPending ? "Keeping…" : `Keep the schedule${changed.length ? ` (${changed.length} changed)` : ""}`}
                </Button>
                <Button variant="outline" onClick={() => check.mutate()} disabled={check.isPending || changed.length === 0}>
                  Check
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setEdits({})
                    setProblems(null)
                    setBeyond(0)
                    setNotice("")
                  }}
                  disabled={changed.length === 0}
                >
                  Undo changes
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
