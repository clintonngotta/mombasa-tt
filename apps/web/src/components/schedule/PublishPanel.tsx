import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import {
  conflictsOf,
  DELAY_REASON_LABEL,
  delayTable,
  getVersion,
  listVersions,
  publishSchedule,
  scheduleKeys,
  type DelayReason,
  type Problem,
  type Schedule,
  type ScheduleVersion,
  type ScheduleVersionSummary,
} from "@/lib/schedule"
import { tournamentKeys, updateTournament, type Tournament } from "@/lib/tournaments"

// A player's request moves matches from the order of play page, not as a table delay.
const REASONS = (Object.keys(DELAY_REASON_LABEL) as DelayReason[]).filter((reason): reason is Exclude<DelayReason, "player_request"> => reason !== "player_request")

type Place = ScheduleVersion["changes"][number]["before"]

function where(place: Place, timeZone: string) {
  const when = place.scheduled_at ? formatInstant(place.scheduled_at, timeZone) : "no time"
  return `${when}, ${place.table?.label ?? "no table"}`
}

function versionTitle(version: ScheduleVersionSummary) {
  if (version.kind === "delay") {
    const reason = version.reason ? DELAY_REASON_LABEL[version.reason as DelayReason] : "Delay"
    return `${reason}: ${version.delayed_table?.label ?? "a table"} ${version.delay_minutes} min later`
  }
  if (version.kind === "moved") {
    return `Moved later${version.reason === "player_request" ? " at a player's request" : ""}`
  }
  return "Published"
}

/** One version's changes, loaded when opened. */
function VersionChanges({ tournamentId, number, timeZone }: { tournamentId: string; number: number; timeZone: string }) {
  const version = useQuery({ queryKey: scheduleKeys.version(tournamentId, number), queryFn: () => getVersion(tournamentId, number) })
  if (version.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (version.error) return <FormAlert>{errorMessage(version.error)}</FormAlert>
  if (!version.data.changes.length) return <p className="text-sm text-muted-foreground">No match moved.</p>
  return (
    <ul className="flex flex-col gap-2">
      {version.data.changes.map((change) => (
        <li key={change.match_id} className="text-sm">
          <span className="font-semibold">{change.label}</span> ({change.title}): {where(change.before, timeZone)} → {where(change.after, timeZone)}
          {change.notify && <span className="text-muted-foreground"> · players and umpire told</span>}
        </li>
      ))}
    </ul>
  )
}

/**
 * Publishing the kept plan as numbered versions, table delays, and the history of both (TASK-081).
 * Only the people of a match that moves table, or moves by more than the notice threshold, are told.
 */
export function PublishPanel({ tournament, schedule, onConflicts }: { tournament: Tournament; schedule: Schedule; onConflicts: (conflicts: Problem[]) => void }) {
  const queryClient = useQueryClient()
  const id = tournament.id
  const timeZone = tournament.timezone
  const unpublished = schedule.rows.filter((row) => row.unpublished).length
  const [note, setNote] = useState("")
  const [notice, setNotice] = useState("")
  const [threshold, setThreshold] = useState<string | null>(null)
  const [delayTableId, setDelayTableId] = useState("")
  const [minutes, setMinutes] = useState("15")
  const [reason, setReason] = useState<(typeof REASONS)[number]>("late_start")
  const [delayNote, setDelayNote] = useState("")
  const [open, setOpen] = useState<number | null>(null)
  const versions = useQuery({ queryKey: scheduleKeys.versions(id), queryFn: () => listVersions(id) })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: scheduleKeys.detail(id) })
  }
  const told = (version: ScheduleVersion) => {
    const moved = version.changes.length
    const notified = version.changes.filter((change) => change.notify).length
    return `Version ${version.number}: ${moved} ${moved === 1 ? "match" : "matches"} changed${notified ? `, the people of ${notified} will be told` : ""}.`
  }

  const publish = useMutation({
    mutationFn: () => publishSchedule(id, note),
    onSuccess: (version) => {
      setNote("")
      setNotice(told(version))
      refresh()
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "schedule_conflicts") onConflicts(conflictsOf(error.body))
    },
  })
  const delay = useMutation({
    mutationFn: () => delayTable(id, { table_id: delayTableId, minutes: Number(minutes), reason, note: delayNote }),
    onSuccess: (done) => {
      setDelayNote("")
      setNotice(told(done.version) + (done.conflicts.length ? " Some matches still need moving: see the list." : ""))
      onConflicts(done.conflicts)
      refresh()
    },
  })
  const saveThreshold = useMutation({
    mutationFn: () => updateTournament(id, { schedule_notice_minutes: Number(threshold) }),
    onSuccess: (fresh) => {
      queryClient.setQueryData(tournamentKeys.detail(id), fresh)
      setThreshold(null)
      refresh()
    },
  })
  const publishError = publish.error && !(publish.error instanceof ApiError && publish.error.code === "schedule_conflicts") ? errorMessage(publish.error) : ""

  return (
    <section aria-labelledby="publish-heading" className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 id="publish-heading" className="text-xl font-bold">
        Publish
      </h2>
      <p className="text-sm text-muted-foreground">
        Players, umpires and the tables board see the published schedule, not the plan you are editing.{" "}
        {schedule.published_version ? `Version ${schedule.published_version} is published. ` : "Nothing is published yet. "}
        {unpublished > 0 ? `${unpublished} ${unpublished === 1 ? "match differs" : "matches differ"} from it.` : "The plan matches it."} When a published match moves to
        another table, or by more than {schedule.notice_minutes} minutes, its players and umpire get an email; nobody else does.
      </p>
      <Field label="Note for the players" optional value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
      {publishError && <FormAlert>{publishError}</FormAlert>}
      <Button className="self-start" onClick={() => publish.mutate()} disabled={publish.isPending || unpublished === 0}>
        {publish.isPending ? "Publishing…" : "Publish the schedule"}
      </Button>
      {notice && (
        <p className="text-sm text-muted-foreground" role="status">
          {notice}
        </p>
      )}

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          saveThreshold.mutate()
        }}
      >
        <Field
          label="Tell people when a match moves by more than (minutes)"
          type="number"
          min={0}
          max={240}
          value={threshold ?? String(schedule.notice_minutes)}
          onChange={(e) => setThreshold(e.target.value)}
        />
        <Button type="submit" variant="outline" disabled={threshold === null || saveThreshold.isPending}>
          Save
        </Button>
      </form>
      {saveThreshold.error && <FormAlert>{errorMessage(saveThreshold.error)}</FormAlert>}

      <h3 className="text-lg font-bold">Delay a table</h3>
      <p className="text-sm text-muted-foreground">
        A late start or a table out of service moves that table's remaining published matches on, and any match that then clashes for a player or a round. It is
        published at once.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          delay.mutate()
        }}
      >
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-sm font-semibold">
            Table
            <select className="h-12 rounded-lg border bg-background px-3 text-base font-normal" value={delayTableId} onChange={(e) => setDelayTableId(e.target.value)}>
              <option value="">Choose a table</option>
              {schedule.tables.map((table) => (
                <option key={table.id} value={table.id}>
                  {table.label}
                </option>
              ))}
            </select>
          </label>
          <Field label="Minutes later" type="number" min={1} max={480} value={minutes} onChange={(e) => setMinutes(e.target.value)} />
          <label className="flex flex-col gap-1 text-sm font-semibold">
            Why
            <select className="h-12 rounded-lg border bg-background px-3 text-base font-normal" value={reason} onChange={(e) => setReason(e.target.value as (typeof REASONS)[number])}>
              {REASONS.map((value) => (
                <option key={value} value={value}>
                  {DELAY_REASON_LABEL[value]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <Field label="Note for the players" optional value={delayNote} maxLength={300} onChange={(e) => setDelayNote(e.target.value)} />
        {delay.error && <FormAlert>{errorMessage(delay.error)}</FormAlert>}
        <Button type="submit" variant="outline" className="self-start" disabled={delay.isPending || !delayTableId || !(Number(minutes) > 0)}>
          {delay.isPending ? "Delaying…" : "Delay the table"}
        </Button>
      </form>

      <h3 className="text-lg font-bold">History</h3>
      {versions.error && <FormAlert>{errorMessage(versions.error)}</FormAlert>}
      {versions.data?.length === 0 && <p className="text-sm text-muted-foreground">No version yet.</p>}
      <ol className="flex flex-col gap-2">
        {versions.data?.map((version) => (
          <li key={version.number} className="flex flex-col gap-2 rounded-lg border px-3 py-2">
            <button
              type="button"
              className="flex min-h-11 flex-wrap items-center justify-between gap-2 text-left"
              aria-expanded={open === version.number}
              onClick={() => setOpen(open === version.number ? null : version.number)}
            >
              <span className="font-semibold">
                Version {version.number} · {versionTitle(version)}
              </span>
              <span className="text-sm text-muted-foreground">
                {formatInstant(version.published_at, timeZone)}
                {version.published_by_name ? ` by ${version.published_by_name}` : ""} · {version.change_count} changed
                {version.notify_count ? `, ${version.notify_count} with notices` : ""}
              </span>
            </button>
            {version.note && <p className="text-sm">{version.note}</p>}
            {open === version.number && <VersionChanges tournamentId={id} number={version.number} timeZone={timeZone} />}
          </li>
        ))}
      </ol>
    </section>
  )
}
