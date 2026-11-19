import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { formatDayRange } from "@/lib/dates"
import { approveEvent, eventKeys, rejectEvent, removeLiveLink, reviewQueue, type ExternalEvent } from "@/lib/events"

/** The curator's queue (REQ-042): external events waiting for review, and live links people reported. */
export function ReviewEventsPage() {
  const queue = useQuery({ queryKey: eventKeys.review, queryFn: reviewQueue, retry: false })
  const forbidden = queue.error instanceof ApiError && queue.error.status === 403
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/events">Events</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Review events</h1>
      {forbidden && <FormAlert>Only the platform's curators review events.</FormAlert>}
      {queue.isError && !forbidden && <FormAlert>{errorMessage(queue.error)}</FormAlert>}
      {queue.isSuccess && queue.data.length === 0 && <p className="text-muted-foreground">Nothing waiting.</p>}
      <ul className="flex flex-col gap-3">
        {(queue.data ?? []).map((event) => (
          <li key={event.id}>
            <Item event={event} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function Item({ event }: { event: ExternalEvent }) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState("")
  const run = useMutation({
    mutationFn: (step: () => Promise<ExternalEvent>) => step(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: eventKeys.all }),
  })
  return (
    <article className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">{event.name}</p>
      <p className="text-sm text-muted-foreground">
        {formatDayRange(event.starts_on, event.ends_on)} · {event.town} · {event.organizer} · from {event.submitted_by_club}
      </p>
      {event.info_url && <p className="text-sm break-all">Info: {event.info_url}</p>}
      {event.live_url && (
        <p className="text-sm break-all">
          Live: {event.live_url}
          {event.report_count > 0 && <span className="font-semibold"> · reported {event.report_count}×</span>}
        </p>
      )}
      {run.isError && <FormAlert>{errorMessage(run.error)}</FormAlert>}
      {event.review === "pending" && (
        <div className="flex flex-wrap items-end gap-2">
          <Button disabled={run.isPending} onClick={() => run.mutate(() => approveEvent(event.id))}>
            Approve
          </Button>
          <Field label="Why not" className="min-w-48 flex-1" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="outline" disabled={run.isPending || !note.trim()} onClick={() => run.mutate(() => rejectEvent(event.id, note.trim()))}>
            Reject
          </Button>
        </div>
      )}
      {event.live_url && event.report_count > 0 && (
        <Button variant="outline" className="self-start text-destructive" disabled={run.isPending} onClick={() => run.mutate(() => removeLiveLink(event.id))}>
          Remove the live link
        </Button>
      )}
    </article>
  )
}
