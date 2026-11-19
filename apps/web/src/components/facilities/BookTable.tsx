import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { ConflictList } from "@/components/training/ConflictList"
import { errorMessage } from "@/lib/api"
import { bookingKeys, requestBooking } from "@/lib/bookings"
import { clashesOf } from "@/lib/clubSessions"
import { fromZonedInput } from "@/lib/dates"

/** Ask to book tables at a branch (REQ-021). A request holds nothing until the venue's staff approve it. */
export function BookTable({ venueId, timeZone, tables }: { venueId: string; timeZone: string; tables: { id: string; label: string }[] }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [day, setDay] = useState("")
  const [from, setFrom] = useState("")
  const [to, setTo] = useState("")
  const [chosen, setChosen] = useState<string[]>([])
  const [note, setNote] = useState("")
  const ask = useMutation({
    mutationFn: () =>
      requestBooking({
        venue_id: venueId,
        table_ids: chosen,
        starts_at: fromZonedInput(`${day}T${from}`, timeZone) ?? "",
        ends_at: fromZonedInput(`${day}T${to}`, timeZone) ?? "",
        note: note.trim(),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: bookingKeys.all })
      setOpen(false)
    },
  })
  if (!tables.length) return null
  if (!open)
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" onClick={() => setOpen(true)}>
          Book a table
        </Button>
        {ask.isSuccess && (
          <p role="status" className="text-sm">
            Requested. <Link to="/profile/bookings" className="font-semibold text-brand-blue underline">See your bookings</Link>
          </p>
        )}
      </div>
    )
  const submit = (e: FormEvent) => {
    e.preventDefault()
    ask.mutate()
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-bold">Book a table</h2>
      <p className="text-sm text-muted-foreground">The venue's staff approve or decline your request. Any fee is paid at the venue.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Day" type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        <Field label="From" type="time" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Field label="To" type="time" value={to} onChange={(e) => setTo(e.target.value)} />
      </div>
      <ChoiceGroup legend="Tables" multiple columns={3} options={tables.map((t) => ({ value: t.id, label: t.label }))} value={chosen} onChange={setChosen} />
      <Field label="Note" optional maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
      <ConflictList conflicts={clashesOf(ask.error)} timeZone={timeZone} lead="Taken then:" next="Choose another time or table." />
      {ask.isError && !clashesOf(ask.error).length && <FormAlert>{errorMessage(ask.error)}</FormAlert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={!day || !from || !to || !chosen.length || ask.isPending}>
          {ask.isPending ? "Sending…" : "Request"}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
