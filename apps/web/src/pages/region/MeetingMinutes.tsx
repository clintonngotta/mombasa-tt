import { useRef, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ChevronRight, Download, FileText, ListChecks, Plus, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { ApiError, apiOriginUrl, errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { formatDay, formatInstant, fromZonedInput, toZonedInput } from "@/lib/dates"
import { getAttachmentLink, type AttachmentLink } from "@/lib/profile"
import {
  addMeetingDocument,
  amendMinutes,
  approveMinutes,
  listMyActionItems,
  MAX_MEETING_DOCUMENTS,
  recordMinutes,
  regionKeys,
  removeMeetingDocument,
  setActionItemStatus,
  updateMeeting,
  type ActionItem,
  type Meeting,
} from "@/lib/regions"
import { cn } from "@/lib/utils"

const MAX_PDF_BYTES = 10 * 1024 * 1024
type Change = (meeting: Meeting) => void

/** "Item 2: Accounts", or the meeting as a whole when the item is gone. */
function itemLabel(meeting: Meeting, item: string) {
  const index = meeting.agenda.findIndex((row) => row.id === item)
  return index < 0 ? "" : `${index + 1}. ${meeting.agenda[index].title}`
}

const itemOptions = (meeting: Meeting, none: string) => [{ value: "", label: none }, ...meeting.agenda.filter((row) => row.id).map((row) => ({ value: row.id, label: itemLabel(meeting, row.id) }))]

/** Open a document with a fresh link: the one that came with the meeting may have expired. */
async function download(file: AttachmentLink) {
  const fresh = await getAttachmentLink(file.id).catch(() => file)
  window.location.assign(apiOriginUrl(fresh.url))
}

/** The meeting's papers (PDFs), for its invitees. Governance staff add and remove them. */
export function MeetingDocuments({ orgId, meeting, staff, onChange }: { orgId: string; meeting: Meeting; staff: boolean; onChange: Change }) {
  const [title, setTitle] = useState("")
  const [item, setItem] = useState("")
  const [pdf, setPdf] = useState<File | null>(null)
  const [tooBig, setTooBig] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const add = useMutation({
    mutationFn: () => addMeetingDocument(orgId, meeting.id, title.trim(), item, pdf!),
    onSuccess: (fresh) => {
      onChange(fresh)
      setTitle("")
      setPdf(null)
      if (input.current) input.current.value = ""
    },
  })
  const remove = useMutation({ mutationFn: (documentId: string) => removeMeetingDocument(orgId, meeting.id, documentId), onSuccess: onChange })
  const canAdd = staff && meeting.status !== "cancelled" && meeting.documents.length < MAX_MEETING_DOCUMENTS
  if (meeting.documents.length === 0 && !canAdd) return null
  const failed = add.error ?? remove.error
  const fields: Record<string, string | undefined> = failed instanceof ApiError ? failed.fieldErrors() : {}

  function onAdd(e: FormEvent) {
    e.preventDefault()
    if (!pdf || !title.trim()) return
    setTooBig(pdf.size > MAX_PDF_BYTES)
    if (pdf.size <= MAX_PDF_BYTES) add.mutate()
  }

  return (
    <section aria-labelledby="papers-heading" className="flex flex-col gap-3">
      <h2 id="papers-heading" className="text-xl font-bold">
        Documents
      </h2>
      {meeting.documents.length === 0 && <p className="text-muted-foreground">No documents yet.</p>}
      <ul className="flex flex-col gap-2">
        {meeting.documents.map((document) => (
          <li key={document.id} className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void download(document.file)}
              className="flex min-h-12 min-w-0 flex-1 items-center gap-3 rounded-xl border bg-card px-4 py-2 text-left outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <FileText aria-hidden className="size-5 shrink-0 text-brand-blue" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold break-words">{document.title}</span>
                {itemLabel(meeting, document.item) && <span className="text-sm text-muted-foreground">{itemLabel(meeting, document.item)}</span>}
              </span>
              <Download aria-hidden className="size-5 text-muted-foreground" />
              <span className="sr-only">Download PDF</span>
            </button>
            {staff && (
              <Button variant="outline" size="icon" aria-label={`Remove ${document.title}`} disabled={remove.isPending} onClick={() => remove.mutate(document.id)}>
                <Trash2 aria-hidden className="size-5" />
              </Button>
            )}
          </li>
        ))}
      </ul>
      {failed && <FormAlert>{fields.file ?? fields.title ?? fields.item ?? errorMessage(failed, "We couldn't save the document.")}</FormAlert>}
      {tooBig && <FormAlert>Choose a PDF under 10 MB.</FormAlert>}
      {canAdd && (
        <form onSubmit={onAdd} className="flex flex-col gap-3 rounded-xl border p-4">
          <h3 className="font-semibold">Add a document</h3>
          <Field label="Title" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} />
          {meeting.agenda.length > 0 && <SelectField label="For" options={itemOptions(meeting, "The whole meeting")} value={item} onChange={setItem} />}
          <label className="flex flex-col gap-1 font-semibold">
            PDF
            <input ref={input} type="file" accept="application/pdf" className="font-normal" onChange={(e) => setPdf(e.target.files?.[0] ?? null)} />
          </label>
          <Button type="submit" className="self-start" disabled={!pdf || !title.trim() || add.isPending}>
            {add.isPending ? "Adding…" : "Add document"}
          </Button>
        </form>
      )}
    </section>
  )
}

type AgendaDraft = { id?: string; title: string; presenter: string; tournament: string | null }

/** Governance staff change a meeting until it starts. Once it is published, invitees are told. */
export function EditMeeting({ orgId, meeting, timeZone, onChange, onDone }: { orgId: string; meeting: Meeting; timeZone: string; onChange: Change; onDone: () => void }) {
  const [title, setTitle] = useState(meeting.title)
  const [starts, setStarts] = useState(toZonedInput(meeting.starts_at, timeZone))
  const [ends, setEnds] = useState(toZonedInput(meeting.ends_at, timeZone))
  const [location, setLocation] = useState(meeting.location)
  const [link, setLink] = useState(meeting.online_link)
  const [agenda, setAgenda] = useState<AgendaDraft[]>(() => meeting.agenda.map((row) => ({ id: row.id || undefined, title: row.title, presenter: row.presenter, tournament: row.tournament })))
  const save = useMutation({
    mutationFn: () =>
      updateMeeting(orgId, meeting.id, {
        title: title.trim(),
        starts_at: fromZonedInput(starts, timeZone) ?? meeting.starts_at,
        ends_at: fromZonedInput(ends, timeZone) ?? meeting.ends_at,
        location: location.trim(),
        online_link: link.trim(),
        agenda: agenda.filter((row) => row.title.trim()).map((row) => ({ ...row, title: row.title.trim(), presenter: row.presenter.trim() })) as Meeting["agenda"],
      }),
    onSuccess: (fresh) => {
      onChange(fresh)
      onDone()
    },
  })
  const fields: Record<string, string | undefined> = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const setRow = (index: number, change: Partial<AgendaDraft>) => setAgenda(agenda.map((row, i) => (i === index ? { ...row, ...change } : row)))

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-4 rounded-xl border bg-card p-4"
    >
      <h3 className="text-lg font-bold">Change the meeting</h3>
      {meeting.status === "published" && <p className="text-sm text-muted-foreground">Invitees are told about the change.</p>}
      {save.isError && <FormAlert>{fields.agenda ?? errorMessage(save.error, "We couldn't save the meeting.")}</FormAlert>}
      <Field label="Title" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} error={fields.title} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Starts" type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} error={fields.starts_at} />
        <Field label="Ends" type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} error={fields.ends_at} />
      </div>
      <Field label="Where" optional maxLength={200} value={location} onChange={(e) => setLocation(e.target.value)} />
      <Field label="Online link" optional type="url" value={link} onChange={(e) => setLink(e.target.value)} error={fields.online_link} />
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-semibold">Agenda</legend>
        {agenda.map((row, i) => (
          <div key={row.id ?? `new-${i}`} className="grid items-end gap-2 sm:grid-cols-[1fr_12rem_auto]">
            <Field label={`Item ${i + 1}`} maxLength={200} value={row.title} onChange={(e) => setRow(i, { title: e.target.value })} />
            <Field label="Presenter" optional maxLength={120} value={row.presenter} onChange={(e) => setRow(i, { presenter: e.target.value })} />
            <Button type="button" variant="outline" size="icon" aria-label={`Remove item ${i + 1}`} onClick={() => setAgenda(agenda.filter((_, j) => j !== i))}>
              <Trash2 aria-hidden className="size-5" />
            </Button>
          </div>
        ))}
        <Button type="button" variant="ghost" className="self-start" disabled={agenda.length >= 30} onClick={() => setAgenda([...agenda, { title: "", presenter: "", tournament: null }])}>
          <Plus aria-hidden className="size-4" /> Add an item
        </Button>
      </fieldset>
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || !title.trim() || !starts || !ends}>
          {save.isPending ? "Saving…" : "Save changes"}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function ActionRow({ meeting, action, canChange, pending, onToggle }: { meeting: Meeting; action: ActionItem; canChange: boolean; pending: boolean; onToggle: () => void }) {
  const done = action.status === "done"
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card px-3 py-2">
      <span className="min-w-0 flex-1">
        <span className={cn("font-semibold break-words", done && "text-muted-foreground line-through")}>{action.description}</span>
        <span className="block text-sm text-muted-foreground">
          {action.owner_name ?? "Nobody yet"}
          {action.due_on && ` · by ${formatDay(action.due_on)}`}
          {itemLabel(meeting, action.item) && ` · ${itemLabel(meeting, action.item)}`}
          {done && " · done"}
        </span>
      </span>
      {canChange && (
        <Button size="sm" variant={done ? "outline" : "default"} disabled={pending} onClick={onToggle}>
          {done ? "Reopen" : "Mark done"}
        </Button>
      )}
    </li>
  )
}

type ActionDraft = { id?: string; item: string; description: string; owner: string; due: string }
type DecisionDraft = { item: string; text: string }

/** The minutes: a draft for whoever writes them (governance staff or the secretary), approved by governance
 * staff once the meeting is over, then read by the invitees and corrected only by amendments. */
export function Minutes({ orgId, meeting, staff, timeZone, started, over, onChange }: { orgId: string; meeting: Meeting; staff: boolean; timeZone: string; started: boolean; over: boolean; onChange: Change }) {
  const writer = meeting.can_take_attendance
  const approved = meeting.minutes_status === "approved"
  const draft = meeting.minutes_status === "draft"
  const [editing, setEditing] = useState(false)
  const [createNext, setCreateNext] = useState(true)
  const [amendment, setAmendment] = useState("")
  const approve = useMutation({ mutationFn: () => approveMinutes(orgId, meeting.id, createNext && !!meeting.next_meeting_at), onSuccess: onChange })
  const amend = useMutation({
    mutationFn: () => amendMinutes(orgId, meeting.id, amendment.trim()),
    onSuccess: (fresh) => {
      onChange(fresh)
      setAmendment("")
    },
  })
  const toggle = useMutation({
    mutationFn: (action: ActionItem) => setActionItemStatus(orgId, meeting.id, action.id, action.status === "done" ? "open" : "done"),
    onSuccess: (fresh) => fresh && onChange(fresh),
  })
  const canWrite = writer && started && meeting.status === "published" && !approved
  if (!approved && !draft && !canWrite) return null
  const error = approve.error ?? amend.error ?? toggle.error

  return (
    <section aria-labelledby="minutes-heading" className="flex flex-col gap-4 border-t pt-6">
      <h2 id="minutes-heading" className="text-xl font-bold">
        Minutes
      </h2>
      {draft && <p className="font-semibold text-warning">Draft: invitees see the minutes once governance staff approve them.</p>}
      {error && <FormAlert>{errorMessage(error)}</FormAlert>}

      {(approved || draft) && !editing && (
        <>
          {meeting.minutes && <p className="rounded-xl border bg-card p-4 whitespace-pre-wrap">{meeting.minutes}</p>}
          {meeting.decisions.length > 0 && (
            <div className="flex flex-col gap-2">
              <h3 className="font-semibold">Decisions</h3>
              <ul className="flex flex-col gap-2">
                {meeting.decisions.map((decision, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <Check aria-hidden className="mt-1 size-4 shrink-0 text-brand-blue" />
                    <span>
                      {decision.text}
                      {itemLabel(meeting, decision.item ?? "") && <span className="block text-sm text-muted-foreground">{itemLabel(meeting, decision.item ?? "")}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {meeting.action_items.length > 0 && (
            <div className="flex flex-col gap-2">
              <h3 className="font-semibold">Action items</h3>
              <ul className="flex flex-col gap-2">
                {meeting.action_items.map((action) => (
                  <ActionRow key={action.id} meeting={meeting} action={action} canChange={writer || (approved && action.mine)} pending={toggle.isPending} onToggle={() => toggle.mutate(action)} />
                ))}
              </ul>
            </div>
          )}
          {meeting.next_meeting_at && <p>Next meeting: {formatInstant(meeting.next_meeting_at, timeZone)}</p>}
          {meeting.next_meeting && (
            <Link to={`/meetings/${orgId}/${meeting.next_meeting}`} className="self-start font-semibold text-brand-blue underline-offset-4 hover:underline">
              Open the next meeting's draft
            </Link>
          )}
          {meeting.amendments.length > 0 && (
            <div className="flex flex-col gap-2">
              <h3 className="font-semibold">Amendments</h3>
              <ul className="flex flex-col gap-2">
                {meeting.amendments.map((entry) => (
                  <li key={entry.id} className="rounded-lg border bg-card px-3 py-2">
                    <p className="whitespace-pre-wrap">{entry.text}</p>
                    <p className="text-sm text-muted-foreground">
                      {entry.by_name ?? "Staff"} · {formatInstant(entry.created_at, timeZone)}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {canWrite && !editing && (
        <Button variant={draft ? "outline" : "default"} className="self-start" onClick={() => setEditing(true)}>
          {draft ? "Change the draft" : "Write the minutes"}
        </Button>
      )}
      {canWrite && editing && <MinutesEditor orgId={orgId} meeting={meeting} timeZone={timeZone} onChange={onChange} onDone={() => setEditing(false)} />}

      {staff && draft && !editing && (
        <div className="flex flex-col gap-3 rounded-xl border bg-card p-4">
          {over ? (
            <>
              <p>Approving shows the minutes to the invitees. After that they can't be changed, only amended.</p>
              {meeting.next_meeting_at && (
                <label className="flex items-center gap-2">
                  <input type="checkbox" className="size-5" checked={createNext} onChange={(e) => setCreateNext(e.target.checked)} />
                  Create the next meeting as a draft
                </label>
              )}
              <Button className="self-start" disabled={approve.isPending} onClick={() => approve.mutate()}>
                {approve.isPending ? "Approving…" : "Approve the minutes"}
              </Button>
            </>
          ) : (
            <p className="text-muted-foreground">You can approve the minutes once the meeting is over.</p>
          )}
        </div>
      )}

      {staff && approved && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            amend.mutate()
          }}
          className="flex flex-col gap-2"
        >
          <TextAreaField label="Add an amendment" rows={3} maxLength={5000} value={amendment} onChange={(e) => setAmendment(e.target.value)} hint="A correction shown under the minutes. The approved minutes stay as they are." />
          <Button type="submit" variant="outline" className="self-start" disabled={!amendment.trim() || amend.isPending}>
            {amend.isPending ? "Saving…" : "Add amendment"}
          </Button>
        </form>
      )}
    </section>
  )
}

function MinutesEditor({ orgId, meeting, timeZone, onChange, onDone }: { orgId: string; meeting: Meeting; timeZone: string; onChange: Change; onDone: () => void }) {
  const [text, setText] = useState(meeting.minutes)
  const [decisions, setDecisions] = useState<DecisionDraft[]>(() => meeting.decisions.map((d) => ({ item: d.item ?? "", text: d.text })))
  const [actions, setActions] = useState<ActionDraft[]>(() =>
    meeting.action_items.map((a) => ({ id: a.id, item: a.item, description: a.description, owner: a.owner_id ?? "", due: a.due_on ?? "" }))
  )
  const [next, setNext] = useState(toZonedInput(meeting.next_meeting_at, timeZone))
  const save = useMutation({
    mutationFn: () =>
      recordMinutes(orgId, meeting.id, {
        minutes: text.trim(),
        decisions: decisions.filter((d) => d.text.trim()).map((d) => ({ item: d.item, text: d.text.trim() })),
        action_items: actions
          .filter((a) => a.description.trim())
          .map((a) => ({ ...(a.id ? { id: a.id } : {}), item: a.item, description: a.description.trim(), owner_id: a.owner || null, due_on: a.due || null })),
        next_meeting_at: fromZonedInput(next, timeZone),
      }),
    onSuccess: (fresh) => {
      onChange(fresh)
      onDone()
    },
  })
  const fields: Record<string, string | undefined> = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const items = itemOptions(meeting, "No agenda item")
  const owners = [{ value: "", label: "Nobody yet" }, ...meeting.owner_choices.map((person) => ({ value: person.id, label: person.display_name }))]
  const setDecision = (index: number, change: Partial<DecisionDraft>) => setDecisions(decisions.map((d, i) => (i === index ? { ...d, ...change } : d)))
  const setAction = (index: number, change: Partial<ActionDraft>) => setActions(actions.map((a, i) => (i === index ? { ...a, ...change } : a)))
  const empty = !text.trim() && !decisions.some((d) => d.text.trim()) && !actions.some((a) => a.description.trim())

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-4 rounded-xl border bg-card p-4"
    >
      {save.isError && <FormAlert>{fields.minutes ?? fields.action_items ?? fields.next_meeting_at ?? errorMessage(save.error, "We couldn't save the minutes.")}</FormAlert>}
      <TextAreaField label="What was discussed" optional rows={6} maxLength={20000} value={text} onChange={(e) => setText(e.target.value)} />

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-semibold">Decisions</legend>
        {decisions.map((decision, i) => (
          <div key={i} className="flex flex-col gap-2 rounded-lg border p-3">
            <Field label={`Decision ${i + 1}`} maxLength={1000} value={decision.text} onChange={(e) => setDecision(i, { text: e.target.value })} />
            <div className="flex items-end gap-2">
              <div className="min-w-0 flex-1">
                <SelectField label="Agenda item" options={items} value={decision.item} onChange={(value) => setDecision(i, { item: value })} />
              </div>
              <Button type="button" variant="outline" size="icon" aria-label={`Remove decision ${i + 1}`} onClick={() => setDecisions(decisions.filter((_, j) => j !== i))}>
                <Trash2 aria-hidden className="size-5" />
              </Button>
            </div>
          </div>
        ))}
        <Button type="button" variant="ghost" className="self-start" disabled={decisions.length >= 60} onClick={() => setDecisions([...decisions, { item: "", text: "" }])}>
          <Plus aria-hidden className="size-4" /> Add a decision
        </Button>
      </fieldset>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-semibold">Action items</legend>
        {actions.map((action, i) => (
          <div key={action.id ?? `new-${i}`} className="flex flex-col gap-2 rounded-lg border p-3">
            <Field label={`Action ${i + 1}`} maxLength={300} placeholder="What needs doing" value={action.description} onChange={(e) => setAction(i, { description: e.target.value })} />
            <div className="grid gap-2 sm:grid-cols-2">
              <SelectField label="Who" options={owners} value={action.owner} onChange={(value) => setAction(i, { owner: value })} />
              <Field label="Due" optional type="date" value={action.due} onChange={(e) => setAction(i, { due: e.target.value })} />
            </div>
            <div className="flex items-end gap-2">
              <div className="min-w-0 flex-1">
                <SelectField label="Agenda item" options={items} value={action.item} onChange={(value) => setAction(i, { item: value })} />
              </div>
              <Button type="button" variant="outline" size="icon" aria-label={`Remove action ${i + 1}`} onClick={() => setActions(actions.filter((_, j) => j !== i))}>
                <Trash2 aria-hidden className="size-5" />
              </Button>
            </div>
          </div>
        ))}
        <Button type="button" variant="ghost" className="self-start" disabled={actions.length >= 60} onClick={() => setActions([...actions, { item: "", description: "", owner: "", due: "" }])}>
          <Plus aria-hidden className="size-4" /> Add an action item
        </Button>
      </fieldset>

      <Field label="Next meeting" optional type="datetime-local" value={next} onChange={(e) => setNext(e.target.value)} hint="When you approve the minutes you can create it as a draft." />
      <div className="flex gap-2">
        <Button type="submit" disabled={empty || save.isPending}>
          {save.isPending ? "Saving…" : "Save draft"}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

/** A link to your open action items, shown only when there are some. */
export function MyActionItemsLink() {
  const mine = useQuery({ queryKey: regionKeys.myActionItems, queryFn: listMyActionItems, staleTime: 0 })
  if (!mine.data?.length) return null
  return (
    <Link to="/action-items" className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
      <ListChecks aria-hidden className="size-5 text-brand-blue" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="font-semibold">My action items</span>
        <span className="text-sm text-muted-foreground">{mine.data.length} open from meetings</span>
      </span>
      <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
    </Link>
  )
}

/** What meetings asked you to do, in every club and body (REQ-046): soonest due first. */
export function ActionItemsPage() {
  const queryClient = useQueryClient()
  // Someone else approves the minutes that create these, so always ask the server.
  const mine = useQuery({ queryKey: regionKeys.myActionItems, queryFn: listMyActionItems, staleTime: 0 })
  const done = useMutation({
    mutationFn: (action: { id: string; meeting: string; organization: { id: string } }) => setActionItemStatus(action.organization.id, action.meeting, action.id, "done"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: regionKeys.all }),
  })
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/">Home</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">My action items</h1>
      {mine.isPending && <p className="text-muted-foreground">Loading…</p>}
      {mine.isError && <FormAlert>{errorMessage(mine.error, "We couldn't load your action items.")}</FormAlert>}
      {done.isError && <FormAlert>{errorMessage(done.error)}</FormAlert>}
      {mine.isSuccess && mine.data.length === 0 && <p className="text-muted-foreground">Nothing is waiting on you. Action items from approved minutes appear here.</p>}
      <ul className="flex flex-col gap-2">
        {mine.data?.map((action) => (
          <li key={action.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3">
            <span className="min-w-0 flex-1">
              <span className="font-semibold break-words">{action.description}</span>
              <span className="block text-sm text-muted-foreground">
                {action.due_on ? `By ${formatDay(action.due_on)} · ` : ""}
                <Link to={`/meetings/${action.organization.id}/${action.meeting}`} className="text-brand-blue underline-offset-4 hover:underline">
                  {action.meeting_title}
                </Link>{" "}
                · {action.organization.name}
              </span>
            </span>
            <Button size="sm" disabled={done.isPending} onClick={() => done.mutate(action)}>
              Mark done
            </Button>
          </li>
        ))}
      </ul>
    </div>
  )
}
