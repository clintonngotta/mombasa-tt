import { useState } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Clock, Globe, MapPin, UserCheck, Users } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import {
  activityKeys,
  ANSWER_LABEL,
  answerActivity,
  AUDIENCE_REACH,
  cancelActivity,
  checkInActivity,
  markActivityAttendance,
  getActivity,
  KIND_LABEL,
  listAttendees,
  publishActivity,
  shareActivityCost,
  type Activity,
  type Answer,
} from "@/lib/activities"
import { can, useActiveMembership } from "@/lib/clubs"
import { formatMoney } from "@/lib/coaching"
import { DEFAULT_TIME_ZONE, formatInstant } from "@/lib/dates"
import { toMinor } from "@/lib/finance"
import { cn } from "@/lib/utils"

/** One club activity (REQ-039): when and where, answering going, maybe or not going, and who is going
 * by display name. Staff publish and cancel it here. */
export function ActivityPage() {
  const { orgId = "", id = "" } = useParams()
  const { all } = useActiveMembership()
  const membership = all.find((m) => m.organization.id === orgId)
  const timeZone = membership?.organization.timezone ?? DEFAULT_TIME_ZONE
  const staff = can(membership, "activities.manage")
  const canShare = staff && can(membership, "finances.manage")
  const activity = useQuery({ queryKey: activityKeys.detail(orgId, id), queryFn: () => getActivity(orgId, id) })
  const a = activity.data

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      {staff ? <BackLink to="/club/activities">Activities</BackLink> : membership ? <BackLink to="/club/schedule">Club schedule</BackLink> : <BackLink to="/invited">Events for you</BackLink>}
      {activity.isError && <FormAlert>{errorMessage(activity.error, "This activity isn't available.")}</FormAlert>}
      {a && (
        <>
          <header className="flex flex-col gap-2">
            <p className="text-sm font-semibold text-brand-blue">
              {KIND_LABEL[a.kind ?? "other"]} · {a.organization.name}
              {a.status === "draft" && " · Draft: only organizers see it"}
            </p>
            <h1 className={cn("text-[32px] leading-9 font-bold", a.status === "cancelled" && "line-through")}>{a.title}</h1>
            {a.status === "cancelled" && (
              <p role="status" className="rounded-xl border border-destructive/40 p-3 font-semibold">
                Cancelled: {a.cancel_reason}
              </p>
            )}
            <p className="flex items-center gap-1.5">
              <Clock aria-hidden className="size-4 text-brand-blue" /> {formatInstant(a.starts_at, timeZone)} to {formatInstant(a.ends_at, timeZone)}
            </p>
            {a.place && (
              <p className="flex items-center gap-1.5">
                <MapPin aria-hidden className="size-4 text-brand-blue" /> {a.place}
              </p>
            )}
            {(a.public || a.audience === "open") && (
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <Globe aria-hidden className="size-4" /> {a.audience === "open" ? "Open to every player on Coast TT" : "Everyone on Coast TT can see this"}
              </p>
            )}
            {a.description && <p className="whitespace-pre-wrap">{a.description}</p>}
            {a.cost_note && !a.cost_share && <p className="text-sm">Cost: {a.cost_note}. Pay the organizers directly; Coast TT doesn't take payments.</p>}
            {a.cost_share && <CostShare share={a.cost_share} />}
            <p className="text-sm text-muted-foreground">
              {a.going} going{a.capacity ? ` of ${a.capacity} places` : ""}
              {a.waitlisted > 0 && ` · ${a.waitlisted} waiting`}
              {a.rsvp_deadline && ` · answers close ${formatInstant(a.rsvp_deadline, timeZone)}`}
            </p>
          </header>
          {(a.can_check_in || a.my_checked_in_at) && <CheckIn orgId={orgId} activity={a} />}
          {a.can_answer && <Answer orgId={orgId} activity={a} />}
          {(staff || (a.can_answer && a.audience !== "open")) && a.status !== "draft" && <Attendees orgId={orgId} activity={a} staff={staff} />}
          {staff && <StaffActions orgId={orgId} activity={a} />}
          {canShare && (a.audience === "members" || a.audience === "selected") && a.status === "published" && !a.cost_share && a.going > 0 && <ShareCost orgId={orgId} activity={a} />}
        </>
      )}
    </div>
  )
}

const SHARE_STATUS = { paid: "paid", partial: "part paid", pending: "not paid yet", overdue: "overdue" } as const

function CostShare({ share }: { share: NonNullable<Activity["cost_share"]> }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border bg-card p-3 text-sm">
      <p>
        <span className="font-semibold">Shared cost:</span> {formatMoney(share.amount_minor, share.currency)} each for those going, by {share.due_on}. Pay the club treasurer; Coast TT doesn't take payments.
      </p>
      {share.my_share && (
        <p className={cn(share.my_share.status === "overdue" && "font-semibold text-destructive")}>
          Your share is {SHARE_STATUS[share.my_share.status]}
          {share.my_share.outstanding_minor > 0 && share.my_share.status !== "pending" && ` (${formatMoney(share.my_share.outstanding_minor, share.currency)} left)`}.
        </p>
      )}
      {share.received_minor != null && share.remaining_minor != null && (
        <p className="text-muted-foreground">
          Received {formatMoney(share.received_minor, share.currency)} · spent {formatMoney(share.spent_minor, share.currency)} ·{" "}
          <span className={cn(share.remaining_minor < 0 && "font-semibold text-destructive")}>
            {share.remaining_minor < 0 ? `deficit ${formatMoney(-share.remaining_minor, share.currency)}` : `${formatMoney(share.remaining_minor, share.currency)} left`}
          </span>
        </p>
      )}
    </div>
  )
}

/** Bill those going their share (REQ-039 Phase 2): an amount each, or a total split evenly. Record the
 * activity's spending as expenses on its campaign under Finance. */
function ShareCost({ orgId, activity }: { orgId: string; activity: Activity }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [split, setSplit] = useState(false)
  const [amount, setAmount] = useState("")
  const [dueOn, setDueOn] = useState(() => new Date().toISOString().slice(0, 10))
  const share = useMutation({
    mutationFn: () => shareActivityCost(orgId, activity.id, { due_on: dueOn, currency: "KES", ...(split ? { total_minor: toMinor(amount) ?? 0 } : { amount_minor: toMinor(amount) ?? 0 }) }),
    onSuccess: (fresh) => {
      queryClient.setQueryData(activityKeys.detail(orgId, activity.id), fresh)
      setOpen(false)
    },
  })
  if (!open) {
    return (
      <Button variant="outline" className="self-start" onClick={() => setOpen(true)}>
        Share the cost
      </Button>
    )
  }
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-bold">Share the cost</h2>
      <p className="text-sm">The {activity.going} going will each owe their share, and show as overdue if it isn't paid by the date. Those waiting for a place don't owe. Add anyone who joins later from the campaign under Finance.</p>
      <label className="flex min-h-12 items-center gap-3">
        <input type="checkbox" className="size-5 accent-brand-blue" checked={split} onChange={(e) => setSplit(e.target.checked)} />
        Split a total evenly (rounded up to whole shillings)
      </label>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={split ? "Total (KES)" : "Each (KES)"} type="number" min={0} className="w-40" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <Field label="Due by" type="date" className="w-44" value={dueOn} onChange={(e) => setDueOn(e.target.value)} />
      </div>
      {share.isError && <FormAlert>{errorMessage(share.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button disabled={toMinor(amount) == null || !dueOn || share.isPending} onClick={() => share.mutate()}>
          Share the cost
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </section>
  )
}

function Answer({ orgId, activity }: { orgId: string; activity: Activity }) {
  const queryClient = useQueryClient()
  const send = useMutation({
    mutationFn: (answer: Answer) => answerActivity(orgId, activity.id, answer),
    onSuccess: (fresh) => {
      queryClient.setQueryData(activityKeys.detail(orgId, activity.id), fresh)
      void queryClient.invalidateQueries({ queryKey: activityKeys.all })
    },
  })
  const mine = activity.my_answer as Answer | null
  return (
    <section aria-labelledby="answer-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 id="answer-heading" className="text-xl font-bold">
        Are you coming?
      </h2>
      <div role="group" aria-label="Your answer" className="flex flex-wrap gap-2">
        {(Object.keys(ANSWER_LABEL) as Answer[]).map((answer) => (
          <Button key={answer} variant={mine === answer ? "default" : "outline"} aria-pressed={mine === answer} disabled={send.isPending} onClick={() => send.mutate(answer)}>
            {ANSWER_LABEL[answer]}
          </Button>
        ))}
      </div>
      {activity.my_waitlisted && (
        <p role="status" className="font-semibold">
          It's full, so you're on the waiting list. If a place opens, answer Going again to take it.
        </p>
      )}
      {send.isError && <FormAlert>{errorMessage(send.error)}</FormAlert>}
    </section>
  )
}

/** While the activity runs, whoever it is for says they are there. */
function CheckIn({ orgId, activity }: { orgId: string; activity: Activity }) {
  const queryClient = useQueryClient()
  const checkIn = useMutation({
    mutationFn: () => checkInActivity(orgId, activity.id),
    onSuccess: (fresh) => {
      queryClient.setQueryData(activityKeys.detail(orgId, activity.id), fresh)
      void queryClient.invalidateQueries({ queryKey: activityKeys.all })
    },
  })
  return (
    <section aria-labelledby="check-in-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 id="check-in-heading" className="flex items-center gap-2 text-xl font-bold">
        <UserCheck aria-hidden className="size-5 text-brand-blue" /> {activity.my_checked_in_at ? "You're checked in" : "It's on now"}
      </h2>
      {!activity.my_checked_in_at && (
        <Button className="self-start" disabled={checkIn.isPending} onClick={() => checkIn.mutate()}>
          {checkIn.isPending ? "Checking in…" : "Check in"}
        </Button>
      )}
      {checkIn.isError && <FormAlert>{errorMessage(checkIn.error)}</FormAlert>}
    </section>
  )
}

function Attendees({ orgId, activity, staff }: { orgId: string; activity: Activity; staff: boolean }) {
  const queryClient = useQueryClient()
  const id = activity.id
  // Other people answer and check in, so staff taking attendance always see the latest list.
  const attendees = useQuery({ queryKey: activityKeys.attendees(orgId, id), queryFn: () => listAttendees(orgId, id), staleTime: staff ? 0 : undefined })
  const mark = useMutation({
    mutationFn: ({ rsvp, attended }: { rsvp: string; attended: boolean }) => markActivityAttendance(orgId, id, rsvp, attended),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: activityKeys.attendees(orgId, id) }),
  })
  const [now] = useState(() => Date.now())
  const taking = staff && activity.status === "published" && new Date(activity.starts_at).getTime() <= now
  const list = attendees.data ?? []
  const going = list.filter((a) => a.answer === "going" && !a.waitlisted)
  const maybe = list.filter((a) => a.answer === "maybe")
  const waiting = list.filter((a) => a.waitlisted)
  return (
    <section aria-labelledby="who-heading" className="flex flex-col gap-2">
      <h2 id="who-heading" className="flex items-center gap-2 text-xl font-bold">
        <Users aria-hidden className="size-5 text-brand-blue" /> Who's coming
      </h2>
      {attendees.isError && <FormAlert>{errorMessage(attendees.error)}</FormAlert>}
      {mark.isError && <FormAlert>{errorMessage(mark.error)}</FormAlert>}
      {attendees.isSuccess && list.length === 0 && <p className="text-muted-foreground">No answers yet.</p>}
      {taking && going.length + maybe.length > 0 ? (
        <>
          <p className="text-sm text-muted-foreground">
            {list.filter((a) => a.attended).length} of {going.length + maybe.length} here. People who check in are marked for you.
          </p>
          <ul aria-label="Attendance" className="flex flex-col gap-2">
            {[...going, ...maybe].map((person) => (
              <li key={person.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card px-3 py-2">
                <span>
                  <span className="font-semibold">{person.display_name}</span>
                  <span className="block text-sm text-muted-foreground">
                    {person.answer === "maybe" ? "Said maybe" : "Said going"}
                    {person.checked_in_at && " · checked in"}
                  </span>
                </span>
                <div role="group" aria-label={`Attendance of ${person.display_name}`} className="flex gap-1">
                  <Button size="sm" variant={person.attended === true ? "default" : "outline"} aria-pressed={person.attended === true} disabled={mark.isPending} onClick={() => mark.mutate({ rsvp: person.id, attended: true })}>
                    Here
                  </Button>
                  <Button size="sm" variant={person.attended === false ? "default" : "outline"} aria-pressed={person.attended === false} disabled={mark.isPending} onClick={() => mark.mutate({ rsvp: person.id, attended: false })}>
                    Not here
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : (
        [
          ["Going", going],
          ["Maybe", maybe],
        ].map(([label, people]) =>
          (people as typeof list).length ? (
            <div key={label as string}>
              <p className="text-sm font-semibold">{label as string}</p>
              <p>{(people as typeof list).map((p) => p.display_name).join(", ")}</p>
            </div>
          ) : null
        )
      )}
      {waiting.length > 0 && (
        <div>
          <p className="text-sm font-semibold">Waiting for a place</p>
          <p>{waiting.map((p) => p.display_name).join(", ")}</p>
        </div>
      )}
    </section>
  )
}

function StaffActions({ orgId, activity }: { orgId: string; activity: Activity }) {
  const queryClient = useQueryClient()
  const [cancelling, setCancelling] = useState(false)
  const [reason, setReason] = useState("")
  const done = (fresh: Activity) => {
    queryClient.setQueryData(activityKeys.detail(orgId, activity.id), fresh)
    void queryClient.invalidateQueries({ queryKey: activityKeys.all })
    setCancelling(false)
  }
  const publish = useMutation({ mutationFn: () => publishActivity(orgId, activity.id), onSuccess: done })
  const cancel = useMutation({ mutationFn: () => cancelActivity(orgId, activity.id, reason.trim()), onSuccess: done })
  if (activity.status === "cancelled") return null
  return (
    <section className="flex flex-col gap-3 border-t pt-6">
      <h2 className="text-xl font-bold">Organizer</h2>
      {(publish.isError || cancel.isError) && <FormAlert>{errorMessage(publish.error ?? cancel.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        {activity.status === "draft" && (
          <Button disabled={publish.isPending} onClick={() => publish.mutate()}>
            Publish to {AUDIENCE_REACH[activity.audience ?? "members"]}
          </Button>
        )}
        {!cancelling && (
          <Button variant="outline" className="text-destructive" onClick={() => setCancelling(true)}>
            Cancel activity
          </Button>
        )}
      </div>
      {cancelling && (
        <div className="flex flex-wrap items-end gap-2 rounded-xl border border-destructive/40 p-4">
          <Field label="Why it's cancelled" className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="Everyone it's for sees this. The activity stays listed as cancelled." />
          <Button variant="destructive" disabled={!reason.trim() || cancel.isPending} onClick={() => cancel.mutate()}>
            Cancel it
          </Button>
          <Button variant="ghost" onClick={() => setCancelling(false)}>
            Keep it
          </Button>
        </div>
      )}
    </section>
  )
}
