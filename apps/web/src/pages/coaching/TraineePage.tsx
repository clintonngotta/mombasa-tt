import { useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, ListChecks, Lock, MessageSquare, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { useActiveMembership } from "@/lib/clubs"
import {
  answerCoaching,
  BOOKING_STATUS_LABEL,
  coachingKeys,
  commentOnMatch,
  deleteComment,
  getTrainee,
  givePlan,
  type Trainee,
  type TraineeMatch,
} from "@/lib/coaching"
import { formatInstant } from "@/lib/dates"
import { listClubPlans, listPlans, LOCAL_TIME_ZONE, trainingKeys, type TrainingPlan } from "@/lib/training"
import { cn } from "@/lib/utils"

const DISCIPLINE: Record<string, string> = { singles: "Singles", doubles: "Doubles" }

/** A trainee, for their coach (REQ-047): progress on the plans you gave them, recent matches with your
 * notes, ratings and sessions between you. */
export function TraineePage() {
  const { id = "" } = useParams()
  const trainee = useQuery({ queryKey: coachingKeys.trainee(id), queryFn: () => getTrainee(id) })
  return (
    <div className="flex max-w-[860px] flex-col gap-6">
      <BackLink to="/training?tab=coaching">Coaching</BackLink>
      {trainee.isPending && <p className="text-muted-foreground">Loading…</p>}
      {trainee.isError && <FormAlert>{errorMessage(trainee.error, "You don't coach this player any more.")}</FormAlert>}
      {trainee.data && <TraineeView coachingId={id} data={trainee.data} />}
    </div>
  )
}

function TraineeView({ coachingId, data }: { coachingId: string; data: Trainee }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [confirmEnd, setConfirmEnd] = useState(false)
  const end = useMutation({
    mutationFn: () => answerCoaching(coachingId, "end"),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: coachingKeys.all })
      navigate("/training?tab=coaching")
    },
  })
  const name = data.coaching.trainee.display_name
  const won = data.record.won ?? 0
  const lost = data.record.lost ?? 0

  return (
    <>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">{name}</h1>
        <p className="text-muted-foreground">
          Coaching since {data.coaching.started_at ? new Date(data.coaching.started_at).toLocaleDateString("en-KE", { day: "numeric", month: "long", year: "numeric" }) : "recently"}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Recent matches" value={`${won}–${lost}`} hint="won–lost" />
        {data.ratings.map((r) => (
          <Stat key={r.discipline} label={`${DISCIPLINE[r.discipline] ?? r.discipline} rating`} value={String(Math.round(r.rating))} hint={`${r.won} of ${r.played} won`} />
        ))}
        <Stat label="Plans from you" value={String(data.plans.length)} hint={`${data.plans.reduce((n, p) => n + p.progress.done, 0)} items done`} />
      </dl>

      <section aria-labelledby="plans-heading" className="flex flex-col gap-3">
        <h2 id="plans-heading" className="text-xl font-bold">
          Plans
        </h2>
        {data.plans.length === 0 && <p className="text-muted-foreground">You haven't given {name} a plan yet.</p>}
        <ul className="flex flex-col gap-2">
          {data.plans.map((plan) => (
            <li key={plan.id}>
              <Link to={`/coaching/trainees/${coachingId}/plans/${plan.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
                <ListChecks aria-hidden className="size-5 text-brand-blue" />
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="truncate font-semibold">{plan.title}</span>
                  <PlanProgress plan={plan} />
                </span>
                <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
              </Link>
            </li>
          ))}
        </ul>
        <GivePlan coachingId={coachingId} name={name} />
      </section>

      {data.bookings.length > 0 && (
        <section aria-labelledby="sessions-heading" className="flex flex-col gap-3">
          <h2 id="sessions-heading" className="text-xl font-bold">
            Sessions
          </h2>
          <ul className="flex flex-col gap-2">
            {data.bookings.map((b) => (
              <li key={b.id} className={ROW}>
                <span className="font-semibold">{formatInstant(b.starts_at, LOCAL_TIME_ZONE)}</span>
                <span className="text-sm text-muted-foreground">
                  {BOOKING_STATUS_LABEL[b.status]}
                  {b.venue && ` · ${b.venue}`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="matches-heading" className="flex flex-col gap-3">
        <h2 id="matches-heading" className="text-xl font-bold">
          Matches
        </h2>
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Lock aria-hidden className="size-4" /> Your notes are private: only {name} reads them.
        </p>
        {data.matches.length === 0 && <p className="text-muted-foreground">No matches yet, in {name}'s match log or at tournaments.</p>}
        <ul className="flex flex-col gap-3">
          {data.matches.map((match) => (
            <MatchRow key={`${match.kind}-${match.id}`} coachingId={coachingId} match={match} />
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-3 border-t pt-6">
        {!confirmEnd ? (
          <Button variant="outline" className="self-start" onClick={() => setConfirmEnd(true)}>
            Stop coaching {name}
          </Button>
        ) : (
          <div className="flex flex-col gap-3 rounded-xl border border-destructive/40 bg-card p-4">
            <p>
              You'll no longer see {name}'s matches or the plans you gave them. They keep the plans and your notes.
            </p>
            {end.isError && <FormAlert>{errorMessage(end.error)}</FormAlert>}
            <div className="flex gap-2">
              <Button variant="destructive" disabled={end.isPending} onClick={() => end.mutate()}>
                Stop coaching
              </Button>
              <Button variant="outline" onClick={() => setConfirmEnd(false)}>
                Keep coaching
              </Button>
            </div>
          </div>
        )}
      </section>
    </>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="flex flex-col rounded-xl border bg-card p-3">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-2xl font-bold tabular-nums">{value}</dd>
      <dd className="text-xs text-muted-foreground">{hint}</dd>
    </div>
  )
}

function PlanProgress({ plan }: { plan: TrainingPlan }) {
  const { done, total } = plan.progress
  return (
    <span className="flex items-center gap-3 text-sm text-muted-foreground">
      <span role="progressbar" aria-label={`${plan.title} progress`} aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} className="h-2 w-32 overflow-hidden rounded-full bg-muted">
        <span className="block h-full bg-brand-blue" style={{ width: total ? `${(done / total) * 100}%` : 0 }} />
      </span>
      {done} of {total} done
    </span>
  )
}

const NEW = "new"

function GivePlan({ coachingId, name }: { coachingId: string; name: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { active } = useActiveMembership()
  const clubId = active && !active.managedOnly ? active.organization.id : ""
  const mine = useQuery({ queryKey: trainingKeys.plans, queryFn: listPlans })
  const club = useQuery({ queryKey: trainingKeys.clubPlans(clubId), queryFn: () => listClubPlans(clubId), enabled: !!clubId })
  const [source, setSource] = useState(NEW)
  const [title, setTitle] = useState("")
  const [open, setOpen] = useState(false)
  const give = useMutation({
    mutationFn: () => givePlan(coachingId, source === NEW ? { title: title.trim() } : { source_plan_id: source, ...(title.trim() ? { title: title.trim() } : {}) }),
    onSuccess: async (plan) => {
      await queryClient.invalidateQueries({ queryKey: coachingKeys.trainee(coachingId) })
      navigate(`/coaching/trainees/${coachingId}/plans/${plan.id}`)
    },
  })
  const options = [
    { value: NEW, label: "A new empty plan" },
    ...(mine.data?.results ?? []).filter((p) => !p.coach).map((p) => ({ value: p.id, label: `Copy my plan: ${p.title}` })),
    ...(club.data?.results ?? []).map((p) => ({ value: p.id, label: `Copy ${active?.organization.name} plan: ${p.title}` })),
  ]

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (source === NEW && !title.trim()) return
    give.mutate()
  }

  if (!open) {
    return (
      <Button variant="outline" className="self-start" onClick={() => setOpen(true)}>
        Give {name} a plan
      </Button>
    )
  }
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <SelectField label="Start from" options={options} value={source} onChange={setSource} hint="A copy goes into their training. Future sessions are checked against their calendar." />
      <Field label="Title" optional={source !== NEW} maxLength={80} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={source === NEW ? "e.g. Backhand block: 4 weeks" : "Keep the copied title"} />
      {give.isError && <FormAlert>{errorMessage(give.error)}</FormAlert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={give.isPending || (source === NEW && !title.trim())}>
          {give.isPending ? "Giving…" : "Give plan"}
        </Button>
        <Button type="button" variant="outline" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function MatchRow({ coachingId, match }: { coachingId: string; match: TraineeMatch }) {
  const queryClient = useQueryClient()
  const [body, setBody] = useState("")
  const refresh = () => queryClient.invalidateQueries({ queryKey: coachingKeys.trainee(coachingId) })
  const add = useMutation({
    mutationFn: () => commentOnMatch(coachingId, match.kind === "personal" ? { personal_match: match.id, body: body.trim() } : { match: match.id, body: body.trim() }),
    onSuccess: async () => {
      setBody("")
      await refresh()
    },
  })
  const remove = useMutation({ mutationFn: deleteComment, onSuccess: refresh })
  const resultClass = match.result === "win" ? "text-success" : match.result === "loss" ? "text-destructive" : "text-muted-foreground"

  return (
    <li className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="flex min-w-0 flex-col">
          <span className="font-semibold">{match.opponent ? `vs ${match.opponent}` : match.title}</span>
          <span className="text-sm text-muted-foreground">
            {match.played_on && new Date(match.played_on).toLocaleDateString("en-KE", { day: "numeric", month: "short" })} · {match.kind === "official" ? match.title : `${match.title} (match log)`}
          </span>
        </span>
        <span className={cn("font-semibold tabular-nums", resultClass)}>
          {match.result && `${match.result === "win" ? "Won" : match.result === "loss" ? "Lost" : "Drawn"} `}
          {match.score}
        </span>
      </div>
      {match.comments.length > 0 && (
        <ul className="flex flex-col gap-2 border-l-2 border-brand-blue/40 pl-3">
          {match.comments.map((c) => (
            <li key={c.id} className="flex items-start gap-2">
              <p className="flex-1 text-sm whitespace-pre-line">{c.body}</p>
              <Button variant="ghost" size="icon" aria-label="Delete note" disabled={remove.isPending} onClick={() => remove.mutate(c.id)}>
                <Trash2 aria-hidden className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (body.trim()) add.mutate()
        }}
        className="flex flex-col gap-2"
      >
        <TextAreaField label="Note for the player" rows={2} maxLength={2000} value={body} onChange={(e) => setBody(e.target.value)} placeholder="What went well, what to work on next" />
        {add.isError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
        <Button type="submit" variant="outline" className="self-start" disabled={add.isPending || !body.trim()}>
          <MessageSquare aria-hidden className="size-4" /> Add note
        </Button>
      </form>
    </li>
  )
}
