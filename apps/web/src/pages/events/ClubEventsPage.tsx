import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { TextAreaField } from "@/components/forms/SelectField"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { useAdminAccessLost } from "@/lib/clubAdmin"
import { formatDayRange } from "@/lib/dates"
import { CATEGORY_LABEL, eventKeys, listClubEvents, markLive, submitEvent, updateEvent, type ExternalEvent } from "@/lib/events"

const REVIEW: Record<string, string> = { pending: "Awaiting review", approved: "Listed", rejected: "Not listed" }

/** Events run elsewhere that the club lists on Coast TT (REQ-042). A curator reviews each before it's public. */
export function ClubEventsPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "announcements.manage")
  const [adding, setAdding] = useState(false)
  const events = useQuery({ queryKey: eventKeys.club(orgId), queryFn: () => listClubEvents(orgId), enabled: allowed })
  const accessLost = useAdminAccessLost(events.error)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Events elsewhere</h1>
        <p className="text-muted-foreground">List a tournament run outside Coast TT. Your members see it at once; everyone else once a curator approves it.</p>
      </div>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          {adding ? (
            <SubmitForm orgId={orgId} onClose={() => setAdding(false)} />
          ) : (
            <Button className="self-start" onClick={() => setAdding(true)}>
              <Plus aria-hidden className="size-5" /> List an event
            </Button>
          )}
          {events.isError && <FormAlert>{errorMessage(events.error)}</FormAlert>}
          <ul className="flex flex-col gap-2">
            {(events.data ?? []).map((event) => (
              <li key={event.id}>
                <Submission orgId={orgId} event={event} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function Submission({ orgId, event }: { orgId: string; event: ExternalEvent }) {
  const queryClient = useQueryClient()
  const run = useMutation({
    mutationFn: (step: () => Promise<ExternalEvent>) => step(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: eventKeys.all }),
  })
  return (
    <article className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">
        {event.name} <span className="font-normal text-muted-foreground">· {REVIEW[event.review]}{event.status !== "scheduled" ? ` · ${event.status}` : ""}</span>
      </p>
      <p className="text-sm text-muted-foreground">
        {formatDayRange(event.starts_on, event.ends_on)} · {event.town} · {event.organizer}
      </p>
      {event.review === "rejected" && event.review_note && <p className="text-sm">Curator: {event.review_note}</p>}
      {run.isError && <FormAlert>{errorMessage(run.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        {event.live_url && (
          <Button variant="outline" disabled={run.isPending} onClick={() => run.mutate(() => markLive(orgId, event.id, !event.marked_live))}>
            {event.marked_live ? "Not live any more" : "It's live now"}
          </Button>
        )}
        {event.status === "scheduled" && (
          <>
            <Button variant="ghost" disabled={run.isPending} onClick={() => run.mutate(() => updateEvent(orgId, event.id, { status: "postponed" }))}>
              Postponed
            </Button>
            <Button variant="ghost" className="text-destructive" disabled={run.isPending} onClick={() => run.mutate(() => updateEvent(orgId, event.id, { status: "cancelled" }))}>
              Cancelled
            </Button>
          </>
        )}
      </div>
    </article>
  )
}

function SubmitForm({ orgId, onClose }: { orgId: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  const draft = useDraft(`external-event:${orgId}`)
  const [form, setForm] = useDraftState(draft, "form", { name: "", organizer: "", starts_on: "", ends_on: "", venue: "", town: "", entry_info: "", info_url: "", live_url: "" })
  const [categories, setCategories] = useDraftState<string[]>(draft, "categories", [])
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })
  const save = useMutation({
    mutationFn: () => submitEvent(orgId, { ...form, ends_on: form.ends_on || form.starts_on, categories: categories as never }),
    onSuccess: () => {
      draft.clear()
      void queryClient.invalidateQueries({ queryKey: eventKeys.all })
      onClose()
    },
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-bold">List an event</h2>
      <Field label="Name" maxLength={120} value={form.name} onChange={set("name")} error={errors.name} />
      <Field label="Run by" maxLength={120} value={form.organizer} onChange={set("organizer")} error={errors.organizer} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="First day" type="date" value={form.starts_on} onChange={set("starts_on")} error={errors.starts_on} />
        <Field label="Last day" optional type="date" value={form.ends_on} onChange={set("ends_on")} error={errors.ends_on} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Venue" optional maxLength={120} value={form.venue} onChange={set("venue")} />
        <Field label="Town" maxLength={80} value={form.town} onChange={set("town")} error={errors.town} />
      </div>
      <ChoiceGroup legend="Categories" multiple columns={3} options={Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label }))} value={categories} onChange={setCategories} />
      <TextAreaField label="How to enter" optional maxLength={1000} rows={3} value={form.entry_info} onChange={set("entry_info")} />
      <Field label="Official information link" optional type="url" maxLength={500} value={form.info_url} onChange={set("info_url")} placeholder="https://" error={errors.info_url} />
      <Field label="Live stream link" optional type="url" maxLength={500} value={form.live_url} onChange={set("live_url")} placeholder="https://" hint="Shown while the event is on." error={errors.live_url} />
      {save.isError && !Object.keys(errors).length && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <DraftBar draft={draft} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || !form.name.trim() || !form.starts_on || !form.town.trim()}>
          {save.isPending ? "Sending…" : "Send for review"}
        </Button>
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
