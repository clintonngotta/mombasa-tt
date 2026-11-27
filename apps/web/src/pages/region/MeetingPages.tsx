import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarClock, ChevronRight, Gavel, Plus, Trash2, Users } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { SelectField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { can, isBodyKind, listMembers, useActiveMembership, useMemberships } from "@/lib/clubs"
import { formatMoney } from "@/lib/coaching"
import { toMinor } from "@/lib/finance"
import { formatInstant, fromZonedInput } from "@/lib/dates"
import {
  answerMeeting,
  ATTENDANCE_LABEL,
  AUDIENCE_LABEL,
  cancelMeeting,
  createMeeting,
  deleteMeeting,
  getMeeting,
  issuePenalties,
  listMeetings,
  markAttendanceOrKeep,
  checkInOrKeep,
  meetingAction,
  MEETING_KIND_LABEL,
  PENALIZED,
  PENALTY_STATUS_LABEL,
  regionKeys,
  RULE_LABEL,
  updatePenalty,
  type AttendanceMark,
  type Meeting,
  type MeetingAudience,
  type MeetingInvitee,
  type MeetingKind,
  type MeetingPenalty,
  type Penalized,
} from "@/lib/regions"
import { cn } from "@/lib/utils"
import { EditMeeting, MeetingDocuments, Minutes, MyActionItemsLink } from "@/pages/region/MeetingMinutes"

/** The active organization's meetings (REQ-046): governance staff call them; invitees see theirs. */
export function MeetingsPage() {
  const { active } = useActiveMembership()
  if (!active) return null
  return (
    <div className="flex max-w-[860px] flex-col gap-6">
      <BackLink to={isBodyKind(active.organization.kind) ? "/region" : "/club"}>{active.organization.name}</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Meetings</h1>
      <MyActionItemsLink />
      <MeetingsPanel orgId={active.organization.id} timeZone={active.organization.timezone ?? "Africa/Nairobi"} staff={can(active, "governance.manage")} body={isBodyKind(active.organization.kind)} />
    </div>
  )
}

export function MeetingsPanel({ orgId, timeZone, staff, body }: { orgId: string; timeZone: string; staff: boolean; body: boolean }) {
  const meetings = useQuery({ queryKey: regionKeys.meetings(orgId), queryFn: () => listMeetings(orgId) })
  const [adding, setAdding] = useState(false)
  return (
    <section aria-label="Meetings" className="flex flex-col gap-3">
      {meetings.isError && <FormAlert>{errorMessage(meetings.error, "We couldn't load meetings.")}</FormAlert>}
      {meetings.isSuccess && meetings.data.length === 0 && <p className="text-muted-foreground">No meetings yet.</p>}
      <ul className="flex flex-col gap-2">
        {meetings.data?.map((meeting) => (
          <li key={meeting.id}>
            <Link to={`/meetings/${orgId}/${meeting.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
              <CalendarClock aria-hidden className="size-5 text-brand-blue" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-semibold">{meeting.title}</span>
                <span className="text-sm text-muted-foreground">
                  {formatInstant(meeting.starts_at, timeZone)} · {MEETING_KIND_LABEL[meeting.kind ?? "general"]} · {meeting.status === "draft" ? "Draft" : meeting.status === "cancelled" ? "Cancelled" : "Published"}
                </span>
              </span>
              <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
      {staff && !adding && (
        <Button variant="outline" className="self-start" onClick={() => setAdding(true)}>
          <Plus aria-hidden className="size-4" /> Call a meeting
        </Button>
      )}
      {staff && adding && <NewMeeting orgId={orgId} timeZone={timeZone} body={body} onDone={() => setAdding(false)} />}
    </section>
  )
}

function NewMeeting({ orgId, timeZone, body, onDone }: { orgId: string; timeZone: string; body: boolean; onDone: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const draft = useDraft(`meeting-new:${orgId}`)
  const [title, setTitle] = useDraftState(draft, "title", "")
  const [kind, setKind] = useDraftState<MeetingKind>(draft, "kind", body ? "representatives" : "committee")
  const [audience, setAudience] = useDraftState<MeetingAudience>(draft, "audience", body ? "club_admins" : "committee")
  const [starts, setStarts] = useDraftState(draft, "starts", "")
  const [ends, setEnds] = useDraftState(draft, "ends", "")
  const [location, setLocation] = useDraftState(draft, "location", "")
  const [link, setLink] = useDraftState(draft, "link", "")
  const [agenda, setAgenda] = useDraftState<string[]>(draft, "agenda", [""])
  const [rules, setRules] = useDraftState<Record<Penalized, { penalty: string; amount: string }>>(draft, "rules", {
    absent: { penalty: "", amount: "" },
    late: { penalty: "", amount: "" },
    apologies: { penalty: "", amount: "" },
  })
  const [secretary, setSecretary] = useDraftState(draft, "secretary", "")
  const members = useQuery({ queryKey: ["clubs", orgId, "members", ""], queryFn: () => listMembers(orgId, "") })
  const create = useMutation({
    mutationFn: () =>
      createMeeting(orgId, {
        title: title.trim(),
        kind,
        audience,
        starts_at: fromZonedInput(starts, timeZone) ?? "",
        ends_at: fromZonedInput(ends, timeZone) ?? "",
        location: location.trim(),
        online_link: link.trim(),
        agenda: agenda.map((a) => a.trim()).filter(Boolean).map((item) => ({ title: item, presenter: "" })),
        rules: PENALIZED.filter((key) => rules[key].penalty.trim()).map((key) => ({
          applies_to: key,
          penalty: rules[key].penalty.trim(),
          amount_minor: toMinor(rules[key].amount),
        })),
        ...(secretary ? { secretary_id: secretary } : {}),
      }),
    onSuccess: async (meeting) => {
      draft.clear()
      await queryClient.invalidateQueries({ queryKey: regionKeys.meetings(orgId) })
      onDone()
      navigate(`/meetings/${orgId}/${meeting.id}`)
    },
  })
  const fields: Record<string, string | undefined> = create.error instanceof ApiError ? create.error.fieldErrors() : {}
  const audiences = (Object.keys(AUDIENCE_LABEL) as MeetingAudience[]).filter((a) => a !== "named" && (body || (a !== "club_admins" && a !== "representatives")))

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    create.mutate()
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-bold">Call a meeting</h2>
      {create.isError && <FormAlert>{errorMessage(create.error, "We couldn't save the meeting.")}</FormAlert>}
      <Field label="Title" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} error={fields.title} />
      <SelectField label="Kind" options={(Object.keys(MEETING_KIND_LABEL) as MeetingKind[]).map((k) => ({ value: k, label: MEETING_KIND_LABEL[k] }))} value={kind} onChange={(v) => setKind(v as MeetingKind)} />
      <ChoiceGroup legend="Who is invited" options={audiences.map((a) => ({ value: a, label: AUDIENCE_LABEL[a] }))} value={audience} onChange={setAudience} error={fields.audience} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Starts" type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} error={fields.starts_at} />
        <Field label="Ends" type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} error={fields.ends_at} />
      </div>
      <Field label="Where" optional maxLength={200} value={location} onChange={(e) => setLocation(e.target.value)} />
      <Field label="Online link" optional type="url" value={link} onChange={(e) => setLink(e.target.value)} error={fields.online_link} />
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 font-semibold">Agenda</legend>
        {agenda.map((item, i) => (
          <div key={i} className="flex items-end gap-2">
            <Field label={`Item ${i + 1}`} className="flex-1" maxLength={200} value={item} onChange={(e) => setAgenda(agenda.map((a, j) => (j === i ? e.target.value : a)))} />
            <Button type="button" variant="outline" size="icon" aria-label={`Remove item ${i + 1}`} onClick={() => setAgenda(agenda.filter((_, j) => j !== i))}>
              <Trash2 aria-hidden className="size-5" />
            </Button>
          </div>
        ))}
        <Button type="button" variant="ghost" className="self-start" disabled={agenda.length >= 30} onClick={() => setAgenda([...agenda, ""])}>
          <Plus aria-hidden className="size-4" /> Add an item
        </Button>
      </fieldset>
      <SelectField
        label="Secretary"
        hint="Takes attendance during the meeting and issues the penalties afterwards."
        options={[{ value: "", label: "Me" }, ...(members.data?.results ?? []).map((m) => ({ value: m.user, label: m.display_name }))]}
        value={secretary}
        onChange={setSecretary}
        error={fields.secretary_id}
      />
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-semibold">
          Rules for missing it <span className="font-normal text-muted-foreground">(optional)</span>
        </legend>
        <p className="text-sm text-muted-foreground">Invitees see these when you publish. Leave a penalty empty for no rule. Fines are recorded, not collected here.</p>
        {PENALIZED.map((key) => (
          <div key={key} className="grid gap-2 sm:grid-cols-[1fr_9rem]">
            <Field label={RULE_LABEL[key]} optional maxLength={200} placeholder="e.g. Fine, or a written warning" value={rules[key].penalty} onChange={(e) => setRules({ ...rules, [key]: { ...rules[key], penalty: e.target.value } })} />
            <Field label="Fine (KES)" optional inputMode="decimal" value={rules[key].amount} disabled={!rules[key].penalty.trim()} onChange={(e) => setRules({ ...rules, [key]: { ...rules[key], amount: e.target.value } })} />
          </div>
        ))}
        {fields.rules && <p className="text-sm text-destructive">{fields.rules}</p>}
      </fieldset>
      <p className="text-sm text-muted-foreground">It's saved as a draft. Invitees are fixed and see it when you publish.</p>
      <DraftBar draft={draft} label="Finish later" />
      <div className="flex gap-2">
        <Button type="submit" disabled={create.isPending || !title.trim() || !starts || !ends}>
          {create.isPending ? "Saving…" : "Save draft"}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

/** One meeting: the agenda, and for staff the invitees, publish, cancel and minutes; for an invitee
 * their answer and check-in. */
export function MeetingPage() {
  const { orgId = "", id = "" } = useParams()
  const meeting = useQuery({ queryKey: regionKeys.meeting(orgId, id), queryFn: () => getMeeting(orgId, id) })
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Back</BackLink>
      {meeting.isPending && <p className="text-muted-foreground">Loading…</p>}
      {meeting.isError && <FormAlert>{errorMessage(meeting.error, "This meeting isn't open to you.")}</FormAlert>}
      {meeting.data && <MeetingView orgId={orgId} meeting={meeting.data} />}
    </div>
  )
}

function MeetingView({ orgId, meeting }: { orgId: string; meeting: Meeting }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { results: memberships } = useMemberships()
  const host = memberships.find((m) => m.organization.id === orgId)
  const staff = !!host && can(host, "governance.manage")
  const timeZone = host?.organization.timezone ?? "Africa/Nairobi"
  const [reason, setReason] = useState("")
  const [editing, setEditing] = useState(false)
  const update = (data: Meeting) => {
    queryClient.setQueryData(regionKeys.meeting(orgId, meeting.id), data)
    return queryClient.invalidateQueries({ queryKey: regionKeys.all })
  }
  const act = useMutation({ mutationFn: (action: "publish") => meetingAction(orgId, meeting.id, action), onSuccess: update })
  // Kept on the device with no connection: shown as checked in at once, sent later (REQ-035).
  const checkIn = useMutation({
    mutationFn: () => checkInOrKeep(orgId, meeting),
    onSuccess: (sent) => {
      if (!sent.kept) return update(sent.data)
      const now = new Date().toISOString()
      queryClient.setQueryData<Meeting>(regionKeys.meeting(orgId, meeting.id), (m) => (m?.me ? { ...m, me: { ...m.me, checked_in_at: now, attendance: m.me.attendance || "present" } } : m))
    },
  })
  const [apology, setApology] = useState<string | null>(null)
  const answer = useMutation({
    mutationFn: (value: "attending" | "apologies") => answerMeeting(orgId, meeting.id, value, value === "apologies" ? (apology ?? "").trim() : ""),
    onSuccess: (fresh) => {
      setApology(null)
      return update(fresh)
    },
  })
  const cancel = useMutation({ mutationFn: () => cancelMeeting(orgId, meeting.id, reason.trim()), onSuccess: update })
  const remove = useMutation({
    mutationFn: () => deleteMeeting(orgId, meeting.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: regionKeys.all })
      navigate(-1)
    },
  })
  const [now] = useState(() => Date.now())
  const started = new Date(meeting.starts_at).getTime() <= now
  const running = started && now < new Date(meeting.ends_at).getTime()
  const error = act.error ?? checkIn.error ?? answer.error ?? cancel.error ?? remove.error

  return (
    <>
      <div className="flex flex-col gap-2">
        <h1 className="text-[32px] leading-9 font-bold">{meeting.title}</h1>
        <p className="text-muted-foreground">
          {meeting.organization.name} · {MEETING_KIND_LABEL[meeting.kind ?? "general"]} · {formatInstant(meeting.starts_at, timeZone)}–{formatInstant(meeting.ends_at, timeZone).slice(-5)}
        </p>
        {meeting.location && <p>{meeting.location}</p>}
        {meeting.online_link && (
          <a href={meeting.online_link} target="_blank" rel="noopener noreferrer" className="font-semibold text-brand-blue underline-offset-4 hover:underline">
            Join online
          </a>
        )}
        {meeting.status === "cancelled" && <FormAlert>Cancelled: {meeting.cancel_reason}</FormAlert>}
        {meeting.status === "draft" && <p className="font-semibold text-warning">Draft: only governance staff see it.</p>}
      </div>
      {error && <FormAlert>{errorMessage(error)}</FormAlert>}

      <section aria-labelledby="agenda-heading" className="flex flex-col gap-2">
        <h2 id="agenda-heading" className="text-xl font-bold">
          Agenda
        </h2>
        {(meeting.agenda?.length ?? 0) === 0 ? (
          <p className="text-muted-foreground">No items yet.</p>
        ) : (
          <ol className="list-decimal pl-6">
            {meeting.agenda!.map((item, i) => (
              <li key={i} className="py-1">
                {item.title}
                {item.presenter && <span className="text-muted-foreground"> · {item.presenter}</span>}
                {item.tournament && item.tournament_name && (
                  <>
                    {" · "}
                    <Link to={`/tournaments/${item.tournament}`} className="font-semibold text-brand-blue underline-offset-4 hover:underline">
                      {item.tournament_name}
                    </Link>
                  </>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      <MeetingDocuments orgId={orgId} meeting={meeting} staff={staff} onChange={update} />

      {(meeting.rules?.length ?? 0) > 0 && (
        <section aria-labelledby="rules-heading" className="flex flex-col gap-2">
          <h2 id="rules-heading" className="flex items-center gap-2 text-xl font-bold">
            <Gavel aria-hidden className="size-5 text-brand-blue" /> Rules
          </h2>
          <ul className="flex flex-col gap-1">
            {meeting.rules!.map((rule) => (
              <li key={rule.applies_to}>
                <span className="font-semibold">{RULE_LABEL[rule.applies_to]}:</span> {rule.penalty}
                {rule.amount_minor ? ` (${formatMoney(rule.amount_minor, "KES")})` : ""}
              </li>
            ))}
          </ul>
          {meeting.secretary && <p className="text-sm text-muted-foreground">Secretary: {meeting.secretary.display_name}</p>}
        </section>
      )}

      {meeting.me && meeting.status === "published" && (
        <section aria-labelledby="you-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
          <h2 id="you-heading" className="text-xl font-bold">
            You're invited
          </h2>
          <p className="text-muted-foreground">
            {meeting.me.attendance ? `Recorded as ${ATTENDANCE_LABEL[meeting.me.attendance as AttendanceMark].toLowerCase()}.` : meeting.me.checked_in_at ? "You're checked in." : meeting.me.answer === "attending" ? "You said you'll attend." : meeting.me.answer === "apologies" ? "You sent apologies." : started ? "This meeting has started." : "Let the organizers know if you're coming."}
          </p>
          {checkIn.data?.kept && <WaitingToSync />}
          {meeting.me.penalty && <PenaltyLine penalty={meeting.me.penalty} />}
          <div className="flex flex-wrap gap-2">
            {running && !meeting.me.checked_in_at && (
              <Button disabled={checkIn.isPending} onClick={() => checkIn.mutate()}>
                Check in
              </Button>
            )}
            {!started && (
              <>
                <Button variant={meeting.me.answer === "attending" ? "default" : "outline"} disabled={answer.isPending} onClick={() => answer.mutate("attending")}>
                  I'll attend
                </Button>
                <Button variant={meeting.me.answer === "apologies" ? "default" : "outline"} disabled={answer.isPending} onClick={() => setApology(meeting.me?.apology_reason ?? "")}>
                  Send apologies
                </Button>
              </>
            )}
          </div>
        </section>
      )}

      {apology !== null && meeting.me && !started && (
        <div className="flex flex-col gap-2 rounded-xl border bg-card p-4">
          <Field label="Why you can't come" optional maxLength={300} value={apology} onChange={(e) => setApology(e.target.value)} hint="Whoever takes attendance sees this. You're recorded as apologies, not absent." />
          <div className="flex flex-wrap gap-2">
            <Button disabled={answer.isPending} onClick={() => answer.mutate("apologies")}>
              {answer.isPending ? "Sending…" : "Send apology"}
            </Button>
            <Button variant="ghost" onClick={() => setApology(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {meeting.can_take_attendance && meeting.invitees.length > 0 && <Attendance orgId={orgId} meeting={meeting} started={started} over={started && !running} onChange={update} />}

      <Minutes orgId={orgId} meeting={meeting} staff={staff} timeZone={timeZone} started={started} over={started && !running} onChange={update} />

      {staff && (
        <section aria-labelledby="staff-heading" className="flex flex-col gap-4 border-t pt-6">
          <h2 id="staff-heading" className="text-xl font-bold">
            Organize
          </h2>
          <p className="text-muted-foreground">Invite: {AUDIENCE_LABEL[meeting.audience ?? "committee"]}</p>
          {meeting.status === "draft" && (
            <div className="flex flex-wrap gap-2">
              <Button disabled={act.isPending} onClick={() => act.mutate("publish")}>
                Publish and invite
              </Button>
              <Button variant="outline" disabled={remove.isPending} onClick={() => remove.mutate()}>
                Delete draft
              </Button>
            </div>
          )}
          {meeting.status === "draft" && meeting.invitees.length > 0 && <p className="text-muted-foreground">{meeting.invitees.length} invited</p>}
          {meeting.status === "published" && !started && (
            <div className="flex flex-col gap-2">
              <Field label="Reason to cancel" value={reason} onChange={(e) => setReason(e.target.value)} />
              <Button variant="outline" className="self-start" disabled={!reason.trim() || cancel.isPending} onClick={() => cancel.mutate()}>
                Cancel the meeting
              </Button>
            </div>
          )}
          {meeting.status !== "cancelled" && !started && !editing && (
            <Button variant="outline" className="self-start" onClick={() => setEditing(true)}>
              Change the meeting
            </Button>
          )}
          {editing && !started && <EditMeeting orgId={orgId} meeting={meeting} timeZone={timeZone} onChange={update} onDone={() => setEditing(false)} />}
        </section>
      )}
    </>
  )
}

const MARKS: AttendanceMark[] = ["present", "late", "apologies", "absent"]

function PenaltyLine({ penalty }: { penalty: MeetingPenalty }) {
  return (
    <p className={cn("text-sm", penalty.status === "issued" ? "font-semibold text-destructive" : "text-muted-foreground")}>
      Penalty: {penalty.penalty}
      {penalty.amount_minor ? ` · ${formatMoney(penalty.amount_minor, penalty.currency)}` : ""} · {PENALTY_STATUS_LABEL[penalty.status]}
      {penalty.note && ` · ${penalty.note}`}
    </p>
  )
}

/** The attendance record: the secretary or governance staff mark invitees while the meeting runs or after
 * it, then issue the penalties its rules set. Once issued, only the host's admin changes a penalty. */
function Attendance({ orgId, meeting, started, over, onChange }: { orgId: string; meeting: Meeting; started: boolean; over: boolean; onChange: (m: Meeting) => void }) {
  const queryClient = useQueryClient()
  // Marks made with no connection are kept on the device and shown at once (REQ-035).
  const [kept, setKept] = useState<Set<string>>(() => new Set())
  const mark = useMutation({
    mutationFn: ({ invitee, value }: { invitee: MeetingInvitee; value: AttendanceMark }) => markAttendanceOrKeep(orgId, meeting, invitee, value),
    onSuccess: (sent, { invitee, value }) => {
      if (!sent.kept) {
        setKept((ids) => (ids.has(invitee.id) ? new Set([...ids].filter((id) => id !== invitee.id)) : ids))
        return onChange(sent.data)
      }
      setKept((ids) => new Set(ids).add(invitee.id))
      queryClient.setQueryData<Meeting>(regionKeys.meeting(orgId, meeting.id), (m) =>
        m ? { ...m, invitees: m.invitees.map((i) => (i.id === invitee.id ? { ...i, attendance: value } : i)) } : m
      )
    },
  })
  const issue = useMutation({ mutationFn: () => issuePenalties(orgId, meeting.id), onSuccess: onChange })
  const marked = meeting.invitees.filter((i) => i.attendance).length
  const error = mark.error ?? issue.error
  return (
    <section aria-labelledby="attendance-heading" className="flex flex-col gap-3 border-t pt-6">
      <h2 id="attendance-heading" className="flex items-center gap-2 text-xl font-bold">
        <Users aria-hidden className="size-5" /> Attendance ({marked} of {meeting.invitees.length} marked)
      </h2>
      {!started && <p className="text-muted-foreground">You can mark attendance once the meeting starts.</p>}
      {error && <FormAlert>{errorMessage(error)}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {meeting.invitees.map((invitee) => (
          <InviteeRow key={invitee.id} orgId={orgId} meeting={meeting} invitee={invitee} editable={started && meeting.status === "published"} pending={mark.isPending} waiting={kept.has(invitee.id)} onMark={(value) => mark.mutate({ invitee, value })} />
        ))}
      </ul>
      {over && (meeting.rules?.length ?? 0) > 0 && meeting.invitees.some((i) => !i.penalty) && (
        <div className="flex flex-col gap-2 rounded-xl border bg-card p-4">
          <p>Issue the penalties the rules set. Anyone still unmarked is recorded as absent, or apologies if they sent them. After this only the admin can change a penalty.</p>
          <Button className="self-start" disabled={issue.isPending} onClick={() => issue.mutate()}>
            <Gavel aria-hidden className="size-4" /> {issue.isPending ? "Issuing…" : "Issue penalties"}
          </Button>
        </div>
      )}
    </section>
  )
}

function InviteeRow({ orgId, meeting, invitee, editable, pending, waiting, onMark }: { orgId: string; meeting: Meeting; invitee: MeetingInvitee; editable: boolean; pending: boolean; waiting: boolean; onMark: (value: AttendanceMark) => void }) {
  const answer = invitee.answer === "attending" ? "Said they'll attend" : invitee.answer === "apologies" ? `Sent apologies${invitee.apology_reason ? `: ${invitee.apology_reason}` : ""}` : "No answer"
  return (
    <li className="flex flex-col gap-2 rounded-lg border bg-card px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          <span className="font-semibold">{invitee.display_name}</span>
          {invitee.club && <span className="text-muted-foreground"> · {invitee.club}</span>}
          <span className="block text-sm text-muted-foreground">
            {answer}
            {invitee.checked_in_at && " · checked in"}
            {waiting && " · waiting to sync"}
          </span>
        </span>
        {editable && !invitee.penalty ? (
          <div role="group" aria-label={`Attendance of ${invitee.display_name}`} className="flex flex-wrap gap-1">
            {MARKS.map((value) => (
              <Button key={value} size="sm" variant={invitee.attendance === value ? "default" : "outline"} aria-pressed={invitee.attendance === value} disabled={pending} onClick={() => onMark(value)}>
                {ATTENDANCE_LABEL[value]}
              </Button>
            ))}
          </div>
        ) : (
          <span className="text-sm font-semibold">{invitee.attendance ? ATTENDANCE_LABEL[invitee.attendance as AttendanceMark] : "Not marked"}</span>
        )}
      </div>
      {invitee.penalty && <PenaltyEditor orgId={orgId} meeting={meeting} penalty={invitee.penalty} />}
    </li>
  )
}

function PenaltyEditor({ orgId, meeting, penalty }: { orgId: string; meeting: Meeting; penalty: MeetingPenalty }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(penalty.penalty)
  const [amount, setAmount] = useState(penalty.amount_minor ? String(penalty.amount_minor / 100) : "")
  const [status, setStatus] = useState<MeetingPenalty["status"]>(penalty.status)
  const [note, setNote] = useState(penalty.note)
  const save = useMutation({
    mutationFn: () => updatePenalty(orgId, meeting.id, penalty.id, { penalty: text.trim(), amount_minor: toMinor(amount), status, note: note.trim() }),
    onSuccess: async () => {
      setEditing(false)
      await queryClient.invalidateQueries({ queryKey: regionKeys.meeting(orgId, meeting.id) })
    },
  })
  return (
    <div className="flex flex-col gap-2">
      <PenaltyLine penalty={penalty} />
      {penalty.history.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Changed {penalty.history.length} time{penalty.history.length === 1 ? "" : "s"}, last by {penalty.history[penalty.history.length - 1].by_name}
        </p>
      )}
      {meeting.can_edit_penalties && !editing && (
        <Button size="sm" variant="ghost" className="self-start" onClick={() => setEditing(true)}>
          Change penalty
        </Button>
      )}
      {editing && (
        <div className="flex flex-col gap-2 rounded-lg border p-3">
          {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
          <Field label="Penalty" maxLength={200} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Fine (KES)" optional inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <SelectField label="Status" options={(Object.keys(PENALTY_STATUS_LABEL) as MeetingPenalty["status"][]).map((v) => ({ value: v, label: PENALTY_STATUS_LABEL[v] }))} value={status} onChange={(v) => setStatus(v as MeetingPenalty["status"])} />
          </div>
          <Field label="Note" optional maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} hint="Why it changed, for the record." />
          <div className="flex gap-2">
            <Button size="sm" disabled={!text.trim() || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function WaitingToSync() {
  return <p className="text-sm font-semibold text-muted-foreground">Saved on this device: it will be sent when you're back online.</p>
}
