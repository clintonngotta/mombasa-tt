import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { daysBetween, formatDay } from "@/lib/dates"
import { addSession, removeSession, scheduleKeys, type Schedule } from "@/lib/schedule"
import type { Tournament } from "@/lib/tournaments"

const hhmm = (time: string) => time.slice(0, 5)

function tournamentDays(tournament: Tournament): string[] {
  const count = daysBetween(tournament.starts_on, tournament.ends_on) + 1
  return Array.from({ length: Math.max(count, 1) }, (_, n) => {
    const day = new Date(`${tournament.starts_on}T00:00:00Z`)
    day.setUTCDate(day.getUTCDate() + n)
    return day.toISOString().slice(0, 10)
  })
}

/**
 * The day's sessions (TASK-081): hours, tables and, if chosen, the events each is for. With sessions
 * set, the recommendation places matches only inside them; without, every day runs on the hours chosen.
 */
export function SessionsPanel({ tournament, schedule }: { tournament: Tournament; schedule: Schedule }) {
  const queryClient = useQueryClient()
  const days = tournamentDays(tournament)
  const [day, setDay] = useState(days[0])
  const [starts, setStarts] = useState("09:00")
  const [ends, setEnds] = useState("13:00")
  const [name, setName] = useState("")
  const [tableIds, setTableIds] = useState<string[]>([])
  const [eventIds, setEventIds] = useState<string[]>([])
  const refresh = () => queryClient.invalidateQueries({ queryKey: scheduleKeys.detail(tournament.id) })

  const add = useMutation({
    mutationFn: () => addSession(tournament.id, { name, day, starts, ends, table_ids: tableIds, event_ids: eventIds }),
    onSuccess: () => {
      setName("")
      refresh()
    },
  })
  const remove = useMutation({ mutationFn: (sessionId: string) => removeSession(tournament.id, sessionId), onSuccess: refresh })
  const errors = add.error instanceof ApiError ? add.error.fieldErrors() : {}
  const tableLabel = new Map(schedule.tables.map((table) => [table.id, table.label]))
  const eventName = new Map(tournament.events.map((event) => [event.id, event.name]))
  const toggle = (list: string[], set: (next: string[]) => void, id: string, on: boolean) => set(on ? [...list, id] : list.filter((pk) => pk !== id))

  return (
    <section aria-labelledby="sessions-heading" className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 id="sessions-heading" className="text-xl font-bold">
        Sessions
      </h2>
      <p className="text-sm text-muted-foreground">
        Build each day as sessions: the hours, the tables in use and, if you like, the events each one is for. The recommendation fills sessions earliest first. Without
        sessions, every day runs on the hours and tables below.
      </p>
      {schedule.sessions.length > 0 && (
        <ul className="flex flex-col gap-2">
          {schedule.sessions.map((session) => (
            <li key={session.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2">
              <div className="flex flex-col">
                <span className="font-semibold">
                  {session.name ? `${session.name} · ` : ""}
                  {formatDay(session.day)}, {hhmm(session.starts)}–{hhmm(session.ends)}
                </span>
                <span className="text-sm text-muted-foreground">
                  {session.table_ids.map((pk) => tableLabel.get(pk) ?? "Table").join(", ")} ·{" "}
                  {session.event_ids?.length ? session.event_ids.map((pk) => eventName.get(pk) ?? "Event").join(", ") : "Every event"}
                </span>
              </div>
              <Button variant="ghost" onClick={() => remove.mutate(session.id)} disabled={remove.isPending} aria-label={`Remove the session on ${formatDay(session.day)} at ${hhmm(session.starts)}`}>
                <Trash2 className="size-4" aria-hidden />
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          add.mutate()
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm font-semibold">
            Day
            <select className="h-12 rounded-lg border bg-background px-3 text-base font-normal" value={day} onChange={(e) => setDay(e.target.value)}>
              {days.map((value) => (
                <option key={value} value={value}>
                  {formatDay(value)}
                </option>
              ))}
            </select>
          </label>
          <Field label="Name" optional value={name} maxLength={80} onChange={(e) => setName(e.target.value)} error={errors.name} />
          <Field label="Starts" type="time" value={starts} onChange={(e) => setStarts(e.target.value)} error={errors.starts} />
          <Field label="Ends" type="time" value={ends} onChange={(e) => setEnds(e.target.value)} error={errors.ends} />
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-sm font-semibold">Tables</legend>
          <div className="flex flex-wrap gap-3">
            {schedule.tables.map((table) => (
              <label key={table.id} className="flex min-h-11 items-center gap-2 rounded-lg border px-3">
                <input type="checkbox" checked={tableIds.includes(table.id)} onChange={(e) => toggle(tableIds, setTableIds, table.id, e.target.checked)} />
                {table.label}
              </label>
            ))}
          </div>
          {errors.table_ids && <p className="text-sm text-destructive">{errors.table_ids}</p>}
        </fieldset>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-sm font-semibold">Events (none chosen: every event)</legend>
          <div className="flex flex-wrap gap-3">
            {tournament.events.map((event) => (
              <label key={event.id} className="flex min-h-11 items-center gap-2 rounded-lg border px-3">
                <input type="checkbox" checked={eventIds.includes(event.id)} onChange={(e) => toggle(eventIds, setEventIds, event.id, e.target.checked)} />
                {event.name}
              </label>
            ))}
          </div>
        </fieldset>
        {add.error && !Object.keys(errors).length && <FormAlert>{errorMessage(add.error)}</FormAlert>}
        {remove.error && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
        <Button type="submit" variant="outline" className="self-start" disabled={add.isPending || tableIds.length === 0}>
          {add.isPending ? "Adding…" : "Add session"}
        </Button>
      </form>
    </section>
  )
}
