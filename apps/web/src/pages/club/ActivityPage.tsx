import { useState } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Clock, Globe, MapPin, Users } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import {
  activityKeys,
  ANSWER_LABEL,
  answerActivity,
  cancelActivity,
  getActivity,
  KIND_LABEL,
  listAttendees,
  publishActivity,
  type Activity,
  type Answer,
} from "@/lib/activities"
import { can, useActiveMembership } from "@/lib/clubs"
import { DEFAULT_TIME_ZONE, formatInstant } from "@/lib/dates"
import { cn } from "@/lib/utils"

/** One club activity (REQ-039): when and where, answering going, maybe or not going, and who is going
 * by display name. Staff publish and cancel it here. */
export function ActivityPage() {
  const { orgId = "", id = "" } = useParams()
  const { all } = useActiveMembership()
  const membership = all.find((m) => m.organization.id === orgId)
  const timeZone = membership?.organization.timezone ?? DEFAULT_TIME_ZONE
  const staff = can(membership, "activities.manage")
  const activity = useQuery({ queryKey: activityKeys.detail(orgId, id), queryFn: () => getActivity(orgId, id) })
  const a = activity.data

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={staff ? "/club/activities" : "/club/schedule"}>{staff ? "Activities" : "Club schedule"}</BackLink>
      {activity.isError && <FormAlert>{errorMessage(activity.error, "This activity isn't available.")}</FormAlert>}
      {a && (
        <>
          <header className="flex flex-col gap-2">
            <p className="text-sm font-semibold text-brand-blue">
              {KIND_LABEL[a.kind ?? "other"]}
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
            {a.public && (
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <Globe aria-hidden className="size-4" /> Open to everyone on Coast TT
              </p>
            )}
            {a.description && <p className="whitespace-pre-wrap">{a.description}</p>}
            {a.cost_note && <p className="text-sm">Cost: {a.cost_note}. Pay the organizers directly; Coast TT doesn't take payments.</p>}
            <p className="text-sm text-muted-foreground">
              {a.going} going{a.capacity ? ` of ${a.capacity} places` : ""}
              {a.waitlisted > 0 && ` · ${a.waitlisted} waiting`}
              {a.rsvp_deadline && ` · answers close ${formatInstant(a.rsvp_deadline, timeZone)}`}
            </p>
          </header>
          {a.can_answer && <Answer orgId={orgId} activity={a} />}
          {(a.can_answer || staff) && a.status !== "draft" && <Attendees orgId={orgId} id={a.id} />}
          {staff && <StaffActions orgId={orgId} activity={a} />}
        </>
      )}
    </div>
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

function Attendees({ orgId, id }: { orgId: string; id: string }) {
  const attendees = useQuery({ queryKey: activityKeys.attendees(orgId, id), queryFn: () => listAttendees(orgId, id) })
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
      {attendees.isSuccess && list.length === 0 && <p className="text-muted-foreground">No answers yet.</p>}
      {[
        ["Going", going],
        ["Maybe", maybe],
        ["Waiting for a place", waiting],
      ].map(([label, people]) =>
        (people as typeof list).length ? (
          <div key={label as string}>
            <p className="text-sm font-semibold">{label as string}</p>
            <p>{(people as typeof list).map((p) => p.display_name).join(", ")}</p>
          </div>
        ) : null
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
            Publish to {activity.audience === "selected" ? "the members invited" : "all members"}
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
          <Field label="Why it's cancelled" className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="Members see this. The activity stays listed as cancelled." />
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
