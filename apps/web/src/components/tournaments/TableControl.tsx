import { useId, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { drawKeys, type MatchDetail } from "@/lib/draws"
import { dispatchMatch, listTables, OVERRIDE_FOR, OVERRIDE_LABEL, recallMatch, reservationKeys, type Override } from "@/lib/reservations"
import { scoringKeys } from "@/lib/scoring"

type Ids = { tournamentId: string; eventId: string; matchId: string }

/**
 * Where a match is played (REQ-014). Everybody sees the table it is on. Competition staff send it to a
 * free table, which holds the table and the players until the result is official, and can call it
 * back. A refusal names what stands in the way; only the check-in and rest checks can be set aside,
 * with a reason.
 */
export function TableControl({ match, ids, timeZone }: { match: MatchDetail; ids: Ids; timeZone: string }) {
  const queryClient = useQueryClient()
  const selectId = useId()
  const [chosen, setChosen] = useState("")
  const [overrides, setOverrides] = useState<Override[]>([])
  const [reason, setReason] = useState("")
  const [recalling, setRecalling] = useState(false)
  const [recallReason, setRecallReason] = useState("")
  const tables = useQuery({ queryKey: reservationKeys.tables(ids.tournamentId), queryFn: () => listTables(ids.tournamentId), enabled: match.can_dispatch && !match.on_table, staleTime: 0 })
  const settle = (fresh: MatchDetail) => {
    queryClient.setQueryData(drawKeys.match(ids.matchId), fresh)
    void queryClient.invalidateQueries({ queryKey: reservationKeys.tables(ids.tournamentId) })
    void queryClient.invalidateQueries({ queryKey: reservationKeys.board(ids.tournamentId) })
    void queryClient.invalidateQueries({ queryKey: drawKeys.event(ids.eventId) })
    void queryClient.invalidateQueries({ queryKey: scoringKeys.overview(ids.tournamentId) })
    setRecalling(false)
    setRecallReason("")
    setOverrides([])
    setReason("")
  }
  // A refusal means what the screen showed was out of date (the table was just taken, say): look again.
  const lookAgain = () => void queryClient.invalidateQueries({ queryKey: reservationKeys.tables(ids.tournamentId) })
  const send = useMutation({
    // The reason belongs to the checks set aside: none of them, no reason.
    mutationFn: () => dispatchMatch(ids.tournamentId, ids.eventId, ids.matchId, tableId, overrides, overrides.length > 0 ? reason.trim() : ""),
    onSuccess: settle,
    onError: lookAgain,
  })
  const recall = useMutation({ mutationFn: () => recallMatch(ids.tournamentId, ids.eventId, ids.matchId, recallReason.trim()), onSuccess: settle })
  // A refusal over check-in or rest can be set aside; one over a busy table or player cannot.
  const refusedOver = send.error instanceof ApiError ? OVERRIDE_FOR[send.error.code ?? ""] : undefined
  const offered = [...new Set([...overrides, ...(refusedOver ? [refusedOver] : [])])]
  const free = tables.data?.filter((table) => table.free) ?? []
  const busy = tables.data?.filter((table) => !table.free) ?? []
  // A table chosen a moment ago may have been taken since: then nothing is chosen.
  const tableId = free.some((table) => table.id === chosen) ? chosen : ""

  function onSend(e: FormEvent) {
    e.preventDefault()
    send.mutate()
  }

  function onRecall(e: FormEvent) {
    e.preventDefault()
    recall.mutate()
  }

  if (match.on_table) {
    const held = match.on_table
    return (
      <div className="flex flex-col gap-2">
        <p>
          <span className="font-semibold">On {held.table}</span> since {formatInstant(held.since, timeZone)}. The table{held.people.length > 0 && ` and ${held.people.join(", ")}`} {held.people.length > 0 ? "are" : "is"} held until
          the result is official.
        </p>
        {held.waiting_for.length > 0 && (
          <FormAlert>
            {held.waiting_for.join(", ")} {held.waiting_for.length === 1 ? "is" : "are"} needed for the next rubber but {held.waiting_for.length === 1 ? "is" : "are"} playing or umpiring elsewhere. They are held for this tie as
            soon as they are free.
          </FormAlert>
        )}
        {match.can_dispatch &&
          (recalling ? (
            <form onSubmit={onRecall} className="flex flex-col gap-3 rounded-lg border bg-card p-3" noValidate>
              <Field label="Why is the match called back?" required maxLength={300} value={recallReason} onChange={(e) => setRecallReason(e.target.value)} hint="The table and the players become free. A score already started is kept." />
              {recall.isError && <FormAlert>{errorMessage(recall.error)}</FormAlert>}
              <div className="flex flex-wrap gap-2">
                <Button type="submit" variant="destructive" disabled={!recallReason.trim() || recall.isPending}>
                  {recall.isPending ? "Calling back…" : "Call the match back"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setRecalling(false)
                    setRecallReason("")
                  }}
                >
                  Keep it on the table
                </Button>
              </div>
            </form>
          ) : (
            <Button variant="outline" className="self-start" onClick={() => setRecalling(true)}>
              Call back from {held.table}
            </Button>
          ))}
      </div>
    )
  }

  if (!match.can_dispatch) return <p className="text-muted-foreground">Not on a table yet.</p>

  return (
    <form onSubmit={onSend} className="flex flex-col gap-3" noValidate>
      <div className="flex flex-col gap-2">
        <label htmlFor={selectId} className="font-semibold">
          Send to a table
        </label>
        {tables.isError && <FormAlert>{errorMessage(tables.error, "We couldn't load the tables.")}</FormAlert>}
        <select id={selectId} value={tableId} onChange={(e) => setChosen(e.target.value)} disabled={tables.isPending} className="h-12 rounded-lg border bg-card px-3 text-base outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <option value="">{tables.isPending ? "Loading…" : free.length ? "Choose a free table" : "No table is free"}</option>
          {free.map((table) => (
            <option key={table.id} value={table.id}>
              {table.label}
            </option>
          ))}
        </select>
        {busy.length > 0 && (
          <p className="text-sm text-muted-foreground">
            In use: {busy.map((table) => `${table.label} (${table.held_by})`).join("; ")}.
          </p>
        )}
        {tables.data?.length === 0 && <p className="text-sm text-muted-foreground">This tournament's venue has no tables in use. Add them under Club, Venues.</p>}
      </div>
      {send.isError && <FormAlert>{errorMessage(send.error)}</FormAlert>}
      {offered.length > 0 && (
        <fieldset className="flex flex-col gap-2 rounded-lg border bg-card p-3">
          <legend className="px-1 text-sm font-semibold">Setting a check aside</legend>
          {offered.map((name) => (
            <label key={name} className="flex min-h-12 items-center gap-3">
              <input type="checkbox" className="size-5" checked={overrides.includes(name)} onChange={(e) => setOverrides(e.target.checked ? [...overrides, name] : overrides.filter((kept) => kept !== name))} />
              <span>{OVERRIDE_LABEL[name]}</span>
            </label>
          ))}
          {overrides.length > 0 && <Field label="Reason" required maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="Kept with the match. A table or a player in use elsewhere can never be set aside." />}
        </fieldset>
      )}
      <Button type="submit" className="self-start" disabled={!tableId || send.isPending || (overrides.length > 0 && !reason.trim())}>
        {send.isPending ? "Sending…" : "Send to the table"}
      </Button>
    </form>
  )
}
