import { useState, type FormEvent } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarClock, ListChecks, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { Segmented } from "@/components/forms/Segmented"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant, fromZonedInput } from "@/lib/dates"
import { useActiveMembership } from "@/lib/clubs"
import { cn } from "@/lib/utils"
import {
  addPlanItem,
  deletePlan,
  deletePlanItem,
  getPlan,
  listClubDrills,
  listMyDrills,
  LOCAL_TIME_ZONE,
  trainingKeys,
  updatePlanItem,
  type CalendarConflict,
  type PlanItem,
  type TrainingPlan,
} from "@/lib/training"

type Kind = PlanItem["kind"]

/** One personal plan (REQ-027): tick items off, and book sessions that may not clash with the calendar. */
export function PlanPage() {
  const { id = "" } = useParams()
  const plan = useQuery({ queryKey: trainingKeys.plan(id), queryFn: () => getPlan(id) })
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/training">Training</BackLink>
      {plan.isPending && <p className="text-muted-foreground">Loading the plan…</p>}
      {plan.isError && <FormAlert>{errorMessage(plan.error, "We couldn't load this plan.")}</FormAlert>}
      {plan.data && <PlanView plan={plan.data} />}
    </div>
  )
}

function usePlanUpdate(planId: string) {
  const queryClient = useQueryClient()
  return async (plan: TrainingPlan) => {
    queryClient.setQueryData(trainingKeys.plan(planId), plan)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: trainingKeys.plans, exact: true }),
      queryClient.invalidateQueries({ queryKey: trainingKeys.upcoming }),
    ])
  }
}

function PlanView({ plan }: { plan: TrainingPlan }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const remove = useMutation({
    mutationFn: () => deletePlan(plan.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: trainingKeys.all })
      navigate("/training")
    },
  })
  const { done, total } = plan.progress

  return (
    <>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">{plan.title}</h1>
        <p className="text-muted-foreground">
          {done} of {total} done
        </p>
      </div>
      {plan.items.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">Nothing in this plan yet. Add a checklist item or a session below.</p>
      ) : (
        <ol aria-label="Plan items" className="flex flex-col gap-2">
          {plan.items.map((item) => (
            <ItemRow key={item.id} planId={plan.id} item={item} />
          ))}
        </ol>
      )}
      <AddItem planId={plan.id} />
      <section aria-label="Delete plan" className="flex flex-col gap-2 border-t pt-4">
        {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
        {confirmDelete ? (
          <div className="flex flex-wrap items-center gap-2">
            <p className="flex-1 text-sm">Delete {plan.title} and everything in it? Its sessions leave your calendar.</p>
            <Button variant="outline" onClick={() => setConfirmDelete(false)}>
              Keep
            </Button>
            <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {remove.isPending ? "Deleting…" : "Delete plan"}
            </Button>
          </div>
        ) : (
          <Button variant="ghost" className="self-start text-destructive" onClick={() => setConfirmDelete(true)}>
            Delete plan
          </Button>
        )}
      </section>
    </>
  )
}

function ItemRow({ planId, item }: { planId: string; item: PlanItem }) {
  const updated = usePlanUpdate(planId)
  const toggle = useMutation({ mutationFn: (completed: boolean) => updatePlanItem(planId, item.id, { completed }), onSuccess: updated })
  const remove = useMutation({ mutationFn: () => deletePlanItem(planId, item.id), onSuccess: updated })
  const done = !!item.completed_at
  const Icon = item.kind === "session" ? CalendarClock : ListChecks
  const checkboxId = `item-${item.id}`

  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <div className="flex items-start gap-3">
        <input
          id={checkboxId}
          type="checkbox"
          checked={done}
          disabled={toggle.isPending}
          onChange={(e) => toggle.mutate(e.target.checked)}
          className="mt-1 size-5 shrink-0 accent-[var(--color-brand-blue)]"
        />
        <label htmlFor={checkboxId} className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className={cn("font-semibold", done && "text-muted-foreground line-through")}>{item.title}</span>
          <span className="flex items-center gap-1 text-sm text-muted-foreground">
            <Icon aria-hidden className="size-4" />
            {item.kind === "session" && item.starts_at && item.ends_at
              ? `${formatInstant(item.starts_at, LOCAL_TIME_ZONE)} to ${formatInstant(item.ends_at, LOCAL_TIME_ZONE).split(", ").pop()}`
              : "Checklist"}
            {item.drill_title && item.drill_title !== item.title && ` · ${item.drill_title}`}
          </span>
          {item.notes && <span className="text-sm">{item.notes}</span>}
        </label>
        <Button variant="ghost" size="icon" aria-label={`Remove ${item.title}`} disabled={remove.isPending} onClick={() => remove.mutate()}>
          <Trash2 aria-hidden className="size-5" />
        </Button>
      </div>
      {(toggle.isError || remove.isError) && <FormAlert>{errorMessage(toggle.error ?? remove.error)}</FormAlert>}
    </li>
  )
}

const NO_DRILL = "none"

function AddItem({ planId }: { planId: string }) {
  const updated = usePlanUpdate(planId)
  const { active } = useActiveMembership()
  const orgId = active && !active.managedOnly ? active.organization.id : ""
  const mine = useQuery({ queryKey: trainingKeys.myDrills, queryFn: listMyDrills })
  const club = useQuery({ queryKey: trainingKeys.clubDrills(orgId), queryFn: () => listClubDrills(orgId), enabled: !!orgId })
  const [kind, setKind] = useState<Kind>("checklist")
  const [title, setTitle] = useState("")
  const [drill, setDrill] = useState(NO_DRILL)
  const [notes, setNotes] = useState("")
  const [starts, setStarts] = useState("")
  const [ends, setEnds] = useState("")

  const add = useMutation({
    mutationFn: () =>
      addPlanItem(planId, {
        kind,
        title: title.trim(),
        notes: notes.trim(),
        drill: drill === NO_DRILL ? null : drill,
        ...(kind === "session" ? { starts_at: fromZonedInput(starts, LOCAL_TIME_ZONE), ends_at: fromZonedInput(ends, LOCAL_TIME_ZONE) } : {}),
      }),
    onSuccess: async (plan) => {
      setTitle("")
      setNotes("")
      setDrill(NO_DRILL)
      await updated(plan)
    },
  })
  const error = add.error instanceof ApiError ? add.error : null
  const errors = error?.fieldErrors() ?? {}
  const conflicts = error?.code === "calendar_conflict" ? ((error.body as { conflicts?: CalendarConflict[] }).conflicts ?? []) : []
  const drillOptions = [
    { value: NO_DRILL, label: "No drill" },
    ...(mine.data?.results ?? []).map((d) => ({ value: d.id, label: `${d.title} (mine)` })),
    ...(club.data ?? []).map((d) => ({ value: d.id, label: `${d.title} (${active?.organization.name})` })),
  ]

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    add.mutate()
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 className="text-lg font-bold">Add to the plan</h2>
      <Segmented
        label="Kind"
        options={[
          { value: "checklist", label: "Checklist item" },
          { value: "session", label: "Session" },
        ]}
        value={kind}
        onChange={setKind}
      />
      <p className="text-sm text-muted-foreground">
        {kind === "checklist"
          ? "Something to tick off. It doesn't book any time."
          : "Booked in your calendar. It can't overlap your other sessions or a match you're scheduled to play."}
      </p>
      <SelectField label="Drill" optional options={drillOptions} value={drill} onChange={setDrill} error={errors.drill} />
      <Field
        label="Title"
        optional={drill !== NO_DRILL}
        maxLength={120}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        error={errors.title}
        hint={drill !== NO_DRILL ? "Leave blank to use the drill's title" : undefined}
      />
      {kind === "session" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Starts" type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} error={errors.starts_at} />
          <Field label="Ends" type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} error={errors.ends_at} />
        </div>
      )}
      <TextAreaField label="Notes" optional rows={2} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} error={errors.notes} />
      {conflicts.length > 0 && (
        <div role="alert" className="flex flex-col gap-2 rounded-lg border border-destructive bg-destructive/5 p-3 text-sm">
          <p className="font-semibold">That time clashes with:</p>
          <ul className="list-disc pl-5">
            {conflicts.map((c) => (
              <li key={`${c.kind}-${c.starts_at}`}>
                {c.kind === "match" ? "Match: " : ""}
                {c.title}, {formatInstant(c.starts_at, LOCAL_TIME_ZONE)} to {formatInstant(c.ends_at, LOCAL_TIME_ZONE).split(", ").pop()}
              </li>
            ))}
          </ul>
          <p>Choose another time.</p>
        </div>
      )}
      {add.isError && conflicts.length === 0 && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <Button type="submit" className="self-start" disabled={add.isPending}>
        {add.isPending ? "Adding…" : kind === "session" ? "Book session" : "Add item"}
      </Button>
    </form>
  )
}
