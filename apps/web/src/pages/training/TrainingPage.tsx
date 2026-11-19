import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, CalendarClock, ChevronRight, Plus } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { ROW } from "@/lib/clubAdmin"
import { cn } from "@/lib/utils"
import { createPlan, getEquipment, listPlans, listUpcomingSessions, LOCAL_TIME_ZONE, saveEquipment, trainingKeys, type Equipment } from "@/lib/training"

/** Training (REQ-026, REQ-027): upcoming sessions, plans with progress, drills and equipment. All private. */
export function TrainingPage() {
  return (
    <div className="flex max-w-[720px] flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[32px] leading-9 font-bold">Training</h1>
        <Link to="/training/drills" className={buttonVariants({ variant: "outline" })}>
          <BookOpen aria-hidden className="size-5" /> Drills
        </Link>
      </div>
      <p className="-mt-4 text-muted-foreground">Only you see your plans, drills and equipment.</p>
      <Upcoming />
      <Plans />
      <EquipmentCard />
    </div>
  )
}

function Upcoming() {
  const sessions = useQuery({ queryKey: trainingKeys.upcoming, queryFn: listUpcomingSessions })
  return (
    <section aria-labelledby="upcoming-heading" className="flex flex-col gap-3">
      <h2 id="upcoming-heading" className="text-xl font-bold">
        Coming up
      </h2>
      {sessions.isError && <FormAlert>{errorMessage(sessions.error, "We couldn't load your sessions.")}</FormAlert>}
      {sessions.isSuccess && sessions.data.length === 0 && <p className="text-muted-foreground">No sessions booked. Add one to a plan.</p>}
      {sessions.data && sessions.data.length > 0 && (
        <ul className="flex flex-col gap-2">
          {sessions.data.map((session) => (
            <li key={session.id}>
              <Link to={`/training/plans/${session.plan}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
                <CalendarClock aria-hidden className="size-5 text-brand-blue" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-semibold">{session.title}</span>
                  <span className="text-sm text-muted-foreground">
                    {session.starts_at && `${formatInstant(session.starts_at, LOCAL_TIME_ZONE)} · `}
                    {session.plan_title}
                    {session.completed_at && " · done"}
                  </span>
                </span>
                <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Plans() {
  const navigate = useNavigate()
  const plans = useQuery({ queryKey: trainingKeys.plans, queryFn: listPlans })
  const [title, setTitle] = useState("")
  const create = useMutation({ mutationFn: () => createPlan({ title: title.trim() }), onSuccess: (plan) => navigate(`/training/plans/${plan.id}`) })
  const items = plans.data?.results ?? []
  const titleError = create.error instanceof ApiError ? create.error.fieldErrors().title : undefined

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    create.mutate()
  }

  return (
    <section aria-labelledby="plans-heading" className="flex flex-col gap-3">
      <h2 id="plans-heading" className="text-xl font-bold">
        Plans
      </h2>
      {plans.isError && <FormAlert>{errorMessage(plans.error, "We couldn't load your plans.")}</FormAlert>}
      {plans.isSuccess && items.length === 0 && <p className="text-muted-foreground">No plans yet. Start one below, for example a four-week footwork block.</p>}
      {items.length > 0 && (
        <ul className="flex flex-col gap-2">
          {items.map((plan) => {
            const { done, total } = plan.progress
            return (
              <li key={plan.id}>
                <Link to={`/training/plans/${plan.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
                  <span className="flex min-w-0 flex-1 flex-col gap-2">
                    <span className="truncate font-semibold">{plan.title}</span>
                    <span className="flex items-center gap-3 text-sm text-muted-foreground">
                      <span
                        role="progressbar"
                        aria-label={`${plan.title} progress`}
                        aria-valuemin={0}
                        aria-valuemax={total}
                        aria-valuenow={done}
                        className="h-2 w-32 overflow-hidden rounded-full bg-muted"
                      >
                        <span className="block h-full bg-brand-blue" style={{ width: total ? `${(done / total) * 100}%` : 0 }} />
                      </span>
                      {done} of {total} done
                    </span>
                  </span>
                  <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
                </Link>
              </li>
            )
          })}
        </ul>
      )}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-3 rounded-xl border bg-card p-4">
        <Field label="New plan" maxLength={80} value={title} onChange={(e) => setTitle(e.target.value)} error={titleError} hint="e.g. Backhand consistency, four weeks" />
        {create.isError && !titleError && <FormAlert>{errorMessage(create.error)}</FormAlert>}
        <Button type="submit" className="self-start" disabled={create.isPending || !title.trim()}>
          <Plus aria-hidden className="size-5" /> {create.isPending ? "Creating…" : "Create plan"}
        </Button>
      </form>
    </section>
  )
}

function EquipmentCard() {
  const equipment = useQuery({ queryKey: trainingKeys.equipment, queryFn: getEquipment })
  if (equipment.isError) return <FormAlert>{errorMessage(equipment.error, "We couldn't load your equipment.")}</FormAlert>
  if (!equipment.data) return null
  return <EquipmentForm key={equipment.data.updated_at ?? "new"} equipment={equipment.data} />
}

function EquipmentForm({ equipment }: { equipment: Equipment }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState({ blade: equipment.blade ?? "", forehand: equipment.forehand ?? "", backhand: equipment.backhand ?? "" })
  const save = useMutation({
    mutationFn: () => saveEquipment({ blade: draft.blade.trim(), forehand: draft.forehand.trim(), backhand: draft.backhand.trim() }),
    onSuccess: (saved) => queryClient.setQueryData(trainingKeys.equipment, saved),
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const set = (name: keyof typeof draft) => (e: React.ChangeEvent<HTMLInputElement>) => setDraft({ ...draft, [name]: e.target.value })

  return (
    <section aria-labelledby="equipment-heading" className="flex flex-col gap-3">
      <h2 id="equipment-heading" className="text-xl font-bold">
        Equipment
      </h2>
      <form
        noValidate
        className="flex flex-col gap-4 rounded-xl border bg-card p-4"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <p className="text-sm text-muted-foreground">Optional. Kept for your own reference; it never changes your rating.</p>
        <Field label="Blade" optional maxLength={100} value={draft.blade} onChange={set("blade")} error={errors.blade} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Forehand rubber" optional maxLength={100} value={draft.forehand} onChange={set("forehand")} error={errors.forehand} />
          <Field label="Backhand rubber" optional maxLength={100} value={draft.backhand} onChange={set("backhand")} error={errors.backhand} />
        </div>
        {save.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
        {save.isSuccess && (
          <p role="status" className="text-sm text-success">
            Saved.
          </p>
        )}
        <Button type="submit" variant="outline" className="self-start" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save equipment"}
        </Button>
      </form>
    </section>
  )
}
