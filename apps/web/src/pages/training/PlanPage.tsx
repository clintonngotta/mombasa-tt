import { useMemo, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, CalendarClock, ListChecks, Plus, Sparkles, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { SearchSelect, SelectField, TextAreaField } from "@/components/forms/SelectField"
import { Segmented } from "@/components/forms/Segmented"
import { VirtualTable } from "@/components/training/VirtualTable"
import { SkillChips } from "@/pages/training/DrillDetailPage"
import { ApiError, errorMessage } from "@/lib/api"
import { formatDayRange, formatInstant, fromZonedInput } from "@/lib/dates"
import { can, useActiveMembership } from "@/lib/clubs"
import { traineePlanApi } from "@/lib/coaching"
import { cn } from "@/lib/utils"
import {
  clubPlanApi,
  listLibrary,
  LOCAL_TIME_ZONE,
  PERIOD_LABEL,
  personalPlanApi,
  PHASE_LABEL,
  PHASES,
  SKILL_LABEL,
  SKILLS,
  trainingKeys,
  type Activity,
  type CalendarConflict,
  type Drill,
  type Phase,
  type PlanApi,
  type PlanItem,
  type Skill,
  type TrainingPlan,
} from "@/lib/training"

type Kind = PlanItem["kind"]

/** A player's own plan (REQ-027). */
export function PlanPage() {
  const { id = "" } = useParams()
  const api = useMemo(() => personalPlanApi(id), [id])
  return <PlanScreen api={api} back="/training" backLabel="Training" editable personal />
}

/** A plan a coach gave one of their trainees (REQ-047): the coach builds it, the trainee ticks it off. */
export function TraineePlanPage() {
  const { coachingId = "", id = "" } = useParams()
  const api = useMemo(() => traineePlanApi(coachingId, id), [coachingId, id])
  return <PlanScreen api={api} back={`/coaching/trainees/${coachingId}`} backLabel="Trainee" editable personal />
}

/** A club's plan: members read it, training staff build it. */
export function ClubPlanPage() {
  const { id = "" } = useParams()
  const { active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const api = useMemo(() => clubPlanApi(orgId, id), [orgId, id])
  if (!orgId) return null
  return <PlanScreen api={api} back="/training?tab=club" backLabel={`${active!.organization.name} plans`} editable={can(active, "training.manage")} />
}

function PlanScreen({ api, back, backLabel, editable, personal }: { api: PlanApi; back: string; backLabel: string; editable: boolean; personal?: boolean }) {
  const plan = useQuery({ queryKey: api.key, queryFn: api.get })
  return (
    <div className="flex max-w-[860px] flex-col gap-6">
      <BackLink to={back}>{backLabel}</BackLink>
      {plan.isPending && <p className="text-muted-foreground">Loading the plan…</p>}
      {plan.isError && <FormAlert>{errorMessage(plan.error, "We couldn't load this plan.")}</FormAlert>}
      {plan.data && <PlanView plan={plan.data} api={api} back={back} editable={editable} personal={!!personal} />}
    </div>
  )
}

function usePlanUpdate(api: PlanApi) {
  const queryClient = useQueryClient()
  return async (plan: TrainingPlan) => {
    queryClient.setQueryData(api.key, plan)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: api.listKey, exact: true }),
      queryClient.invalidateQueries({ queryKey: trainingKeys.upcoming }),
      queryClient.invalidateQueries({ queryKey: ["training", "recommendations"] }),
    ])
  }
}

function PlanView({ plan, api, back, editable, personal }: { plan: TrainingPlan; api: PlanApi; back: string; editable: boolean; personal: boolean }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const remove = useMutation({
    mutationFn: api.remove,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: trainingKeys.all })
      navigate(back)
    },
  })
  const library = useQuery({ queryKey: trainingKeys.library, queryFn: listLibrary, enabled: editable })
  // A club plan can't use anyone's personal drills.
  const drills = (library.data ?? []).filter((d) => personal || d.library !== "personal")
  const { done, total } = plan.progress

  return (
    <>
      <div className="flex flex-col gap-2">
        <h1 className="text-[32px] leading-9 font-bold">{plan.title}</h1>
        <p className="text-muted-foreground">
          {plan.starts_on && `${plan.period && plan.period !== "custom" ? `${PERIOD_LABEL[plan.period]} · ` : ""}${formatDayRange(plan.starts_on, plan.ends_on ?? plan.starts_on)} · `}
          {done} of {total} done
        </p>
        {plan.goal && <p>{plan.goal}</p>}
        {plan.coach_name && <p className="text-sm font-semibold text-brand-blue">From coach {plan.coach_name}</p>}
      </div>
      <Goal plan={plan} api={api} editable={editable} />
      {editable && (plan.goal_skills?.length ?? 0) > 0 && <Recommendations plan={plan} api={api} />}
      {plan.items.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">Nothing in this plan yet.{editable && " Add a drill, a checklist item or a session."}</p>
      ) : (
        <ol aria-label="Plan items" className="flex flex-col gap-2">
          {plan.items.map((item) => (
            <ItemRow key={item.id} api={api} item={item} editable={editable} />
          ))}
        </ol>
      )}
      {editable && <AddItem api={api} plan={plan} drills={drills} personal={personal} />}
      {editable && (
        <section aria-label="Delete plan" className="flex flex-col gap-2 border-t pt-4">
          {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
          {confirmDelete ? (
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex-1 text-sm">Delete {plan.title} and everything in it?{personal && " Its sessions leave your calendar."}</p>
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
      )}
    </>
  )
}

/** What the plan is for. Drills teaching it are recommended. */
function Goal({ plan, api, editable }: { plan: TrainingPlan; api: PlanApi; editable: boolean }) {
  const updated = usePlanUpdate(api)
  const [editing, setEditing] = useState(false)
  const [skills, setSkills] = useState<Skill[]>(plan.goal_skills ?? [])
  const save = useMutation({
    mutationFn: () => api.update({ goal_skills: skills }),
    onSuccess: async (saved) => {
      setEditing(false)
      await updated(saved)
    },
  })
  if (editing) {
    return (
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-4">
        <ChoiceGroup legend="Goal" optional multiple columns={3} options={SKILLS.map((s) => ({ value: s, label: SKILL_LABEL[s] }))} value={skills} onChange={setSkills} />
        {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
        <div className="flex gap-2">
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            Save goal
          </Button>
          <Button variant="outline" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="font-semibold">Goal:</span>
      {plan.goal_skills?.length ? <SkillChips skills={plan.goal_skills} /> : <span className="text-muted-foreground">Not set</span>}
      {editable && (
        <Button variant="ghost" onClick={() => setEditing(true)}>
          {plan.goal_skills?.length ? "Change" : "Set a goal"}
        </Button>
      )}
    </div>
  )
}

function Recommendations({ plan, api }: { plan: TrainingPlan; api: PlanApi }) {
  const updated = usePlanUpdate(api)
  const found = useQuery({ queryKey: [...trainingKeys.recommendations(plan.id), plan.goal_skills, plan.items.length], queryFn: api.recommendations })
  const add = useMutation({ mutationFn: (drill: Drill) => api.addItem({ kind: "checklist", drill: drill.id }), onSuccess: updated })
  return (
    <section aria-labelledby="recommended-heading" className="flex flex-col gap-3">
      <h2 id="recommended-heading" className="flex items-center gap-2 text-xl font-bold">
        <Sparkles aria-hidden className="size-5 text-brand-blue" /> Recommended for this goal
      </h2>
      {found.isError && <FormAlert>{errorMessage(found.error, "We couldn't load recommendations.")}</FormAlert>}
      {found.isSuccess && found.data.length === 0 && <p className="text-muted-foreground">No more drills for this goal. Every match is already in the plan.</p>}
      {add.isError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <ul className="grid gap-3 sm:grid-cols-2">
        {(found.data ?? []).map(({ drill, matched }) => (
          <li key={drill.id} className="flex gap-3 rounded-xl border bg-card p-3">
            <div className="w-16 shrink-0">{drill.pattern.length > 0 && <VirtualTable steps={drill.pattern} label="" />}</div>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Link to={`/training/drills/${drill.id}`} className="font-semibold underline-offset-2 hover:underline">
                {drill.title}
              </Link>
              <SkillChips skills={drill.skills} highlight={matched} />
              <Button size="sm" variant="outline" className="self-start" disabled={add.isPending} onClick={() => add.mutate(drill)}>
                <Plus aria-hidden className="size-4" /> Add to plan
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

const endTime = (iso: string) => formatInstant(iso, LOCAL_TIME_ZONE).split(", ").pop()

function ItemRow({ api, item, editable }: { api: PlanApi; item: PlanItem; editable: boolean }) {
  const updated = usePlanUpdate(api)
  const toggle = useMutation({ mutationFn: (completed: boolean) => api.updateItem(item.id, { completed }), onSuccess: updated })
  const remove = useMutation({ mutationFn: () => api.deleteItem(item.id), onSuccess: updated })
  const done = !!item.completed_at
  const Icon = item.kind === "session" ? CalendarClock : ListChecks
  const checkboxId = `item-${item.id}`
  const activities = item.activities ?? []

  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <div className="flex items-start gap-3">
        <input
          id={checkboxId}
          type="checkbox"
          checked={done}
          disabled={!editable || toggle.isPending}
          onChange={(e) => toggle.mutate(e.target.checked)}
          className="mt-1 size-5 shrink-0 accent-[var(--color-brand-blue)]"
        />
        <label htmlFor={checkboxId} className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className={cn("font-semibold", done && "text-muted-foreground line-through")}>{item.title}</span>
          <span className="flex items-center gap-1 text-sm text-muted-foreground">
            <Icon aria-hidden className="size-4" />
            {item.kind === "session" && item.starts_at && item.ends_at ? `${formatInstant(item.starts_at, LOCAL_TIME_ZONE)} to ${endTime(item.ends_at)}` : "Checklist"}
          </span>
          {item.notes && <span className="text-sm">{item.notes}</span>}
        </label>
        {item.drill && (
          <Link to={`/training/drills/${item.drill}`} className="text-sm font-semibold text-brand-blue underline-offset-2 hover:underline">
            View drill
          </Link>
        )}
        {editable && (
          <Button variant="ghost" size="icon" aria-label={`Remove ${item.title}`} disabled={remove.isPending} onClick={() => remove.mutate()}>
            <Trash2 aria-hidden className="size-5" />
          </Button>
        )}
      </div>
      {activities.length > 0 && (
        <ol aria-label={`${item.title} running order`} className="ml-8 flex flex-col gap-1 border-l-2 border-brand-blue/30 pl-3 text-sm">
          {activities.map((activity, i) => (
            <li key={i} className="flex flex-wrap gap-x-2">
              <span className="w-28 shrink-0 font-semibold text-muted-foreground">{PHASE_LABEL[activity.phase]}</span>
              {activity.drill ? (
                <Link to={`/training/drills/${activity.drill}`} className="underline-offset-2 hover:underline">
                  {activity.title}
                </Link>
              ) : (
                <span>{activity.title}</span>
              )}
              {activity.minutes && <span className="text-muted-foreground">{activity.minutes} min</span>}
            </li>
          ))}
        </ol>
      )}
      {(toggle.isError || remove.isError) && <FormAlert>{errorMessage(toggle.error ?? remove.error)}</FormAlert>}
    </li>
  )
}

const NO_DRILL = "none"
// Which library categories suit each part of a session.
const PHASE_CATEGORIES: Record<Phase, string[]> = {
  warm_up: ["warm_up"],
  on_table: ["serve", "receive", "footwork", "topspin", "block", "short_game", "multiball"],
  off_table: ["off_table"],
  match_play: ["match_play"],
  cool_down: ["cool_down"],
}

type Draft = { phase: Phase; title: string; minutes: string; drill: string }

const toDraft = (phase: Phase, drill?: Drill): Draft => ({ phase, title: drill ? drill.title : "", minutes: drill?.duration_minutes ? String(drill.duration_minutes) : "", drill: drill?.id ?? NO_DRILL })

function AddItem({ api, plan, drills, personal }: { api: PlanApi; plan: TrainingPlan; drills: Drill[]; personal: boolean }) {
  const updated = usePlanUpdate(api)
  const [kind, setKind] = useState<Kind>("checklist")
  const [title, setTitle] = useState("")
  const [drill, setDrill] = useState(NO_DRILL)
  const [notes, setNotes] = useState("")
  const [starts, setStarts] = useState("")
  const [ends, setEnds] = useState("")
  const [run, setRun] = useState<Draft[]>([])
  const recommended = useQuery({ queryKey: [...trainingKeys.recommendations(plan.id), plan.goal_skills, plan.items.length], queryFn: api.recommendations, enabled: kind === "session" })

  const add = useMutation({
    mutationFn: () =>
      api.addItem({
        kind,
        title: title.trim(),
        notes: notes.trim(),
        drill: drill === NO_DRILL ? null : drill,
        ...(kind === "session"
          ? {
              starts_at: fromZonedInput(starts, LOCAL_TIME_ZONE),
              ends_at: fromZonedInput(ends, LOCAL_TIME_ZONE),
              activities: run.map(
                (a): Activity => ({ phase: a.phase, title: a.title.trim(), minutes: a.minutes ? Number(a.minutes) : null, drill: a.drill === NO_DRILL ? null : a.drill }),
              ),
            }
          : {}),
      }),
    onSuccess: async (saved) => {
      setTitle("")
      setNotes("")
      setDrill(NO_DRILL)
      setRun([])
      await updated(saved)
    },
  })
  const error = add.error instanceof ApiError ? add.error : null
  const errors = error?.fieldErrors() ?? {}
  const conflicts = error?.code === "calendar_conflict" ? ((error.body as { conflicts?: CalendarConflict[] }).conflicts ?? []) : []
  const drillOptions = [{ value: NO_DRILL, label: "No drill" }, ...drills.map((d) => ({ value: d.id, label: d.title }))]

  const byCategory = (phase: Phase) => drills.filter((d) => d.category && PHASE_CATEGORIES[phase].includes(d.category))
  /** Warm-up, the plan's recommended drills on the table, work off the table, then the cool-down. */
  function fillStandard() {
    const onTable = (recommended.data ?? []).map((r) => r.drill).filter((d) => PHASE_CATEGORIES.on_table.includes(d.category ?? "")).slice(0, 2)
    const fallback = onTable.length ? onTable : byCategory("on_table").slice(0, 2)
    setRun([
      toDraft("warm_up", byCategory("warm_up")[0]),
      ...fallback.map((d) => toDraft("on_table", d)),
      toDraft("off_table", byCategory("off_table")[0]),
      toDraft("cool_down", byCategory("cool_down")[0]),
    ])
  }
  const planned = run.reduce((sum, a) => sum + (Number(a.minutes) || 0), 0)
  const startsAt = fromZonedInput(starts, LOCAL_TIME_ZONE)
  const endsAt = fromZonedInput(ends, LOCAL_TIME_ZONE)
  const length = startsAt && endsAt ? Math.round((Date.parse(endsAt) - Date.parse(startsAt)) / 60000) : null
  const setRow = (i: number, patch: Partial<Draft>) => setRun(run.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const moveRow = (i: number, to: number) => {
    const next = [...run]
    const [row] = next.splice(i, 1)
    next.splice(to, 0, row)
    setRun(next)
  }

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
          : personal
            ? "A training session with its running order, from warm-up to cool-down. It goes in your calendar and can't overlap your other sessions or a match you're scheduled to play."
            : "A club session with its running order, from warm-up to cool-down, on the club's timetable."}
      </p>
      {kind === "checklist" && <SelectField label="Drill" optional options={drillOptions} value={drill} onChange={setDrill} error={errors.drill} />}
      <Field
        label="Title"
        optional={kind === "checklist" && drill !== NO_DRILL}
        maxLength={120}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        error={errors.title}
        hint={kind === "checklist" && drill !== NO_DRILL ? "Leave blank to use the drill's title" : kind === "session" ? "e.g. Tuesday club night" : undefined}
      />
      {kind === "session" && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Starts" type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} error={errors.starts_at} />
            <Field label="Ends" type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} error={errors.ends_at} />
          </div>
          <fieldset className="flex flex-col gap-3">
            <legend className="mb-1 flex w-full flex-wrap items-center justify-between gap-2 font-semibold">
              Running order
              <Button type="button" variant="outline" size="sm" onClick={fillStandard}>
                <Sparkles aria-hidden className="size-4" /> Fill a standard session
              </Button>
            </legend>
            {run.length === 0 && <p className="text-sm text-muted-foreground">Warm-up, drills on the table, work off it, match play and the cool-down. Fill a standard session to start from the plan's goal.</p>}
            {run.map((row, i) => {
              const options = [{ value: NO_DRILL, label: "No drill" }, ...byCategory(row.phase).map((d) => ({ value: d.id, label: d.title })), ...drills.filter((d) => !byCategory(row.phase).includes(d)).map((d) => ({ value: d.id, label: `${d.title} (other)` }))]
              return (
                <div key={i} className="grid gap-2 rounded-lg border p-2 sm:grid-cols-[140px_1fr_1fr_80px_auto]">
                  <SearchSelect aria-label={`Part ${i + 1}`} options={PHASES.map((p) => ({ value: p, label: PHASE_LABEL[p] }))} value={row.phase} onChange={(phase) => setRow(i, { phase: phase as Phase })} />
                  <SearchSelect
                    aria-label={`Drill for part ${i + 1}`}
                    options={options}
                    value={row.drill}
                    onChange={(value) => {
                      const chosen = drills.find((d) => d.id === value)
                      setRow(i, { drill: value, title: chosen ? chosen.title : row.title, minutes: chosen?.duration_minutes ? String(chosen.duration_minutes) : row.minutes })
                    }}
                  />
                  <Input aria-label={`Title of part ${i + 1}`} placeholder="Title" maxLength={80} value={row.title} onChange={(e) => setRow(i, { title: e.target.value })} className="h-12" />
                  <Input aria-label={`Minutes for part ${i + 1}`} placeholder="Min" type="number" min={1} max={240} value={row.minutes} onChange={(e) => setRow(i, { minutes: e.target.value })} className="h-12" />
                  <div className="flex">
                    <Button type="button" variant="ghost" size="icon" aria-label={`Move part ${i + 1} up`} disabled={i === 0} onClick={() => moveRow(i, i - 1)}>
                      <ArrowUp aria-hidden className="size-4" />
                    </Button>
                    <Button type="button" variant="ghost" size="icon" aria-label={`Move part ${i + 1} down`} disabled={i === run.length - 1} onClick={() => moveRow(i, i + 1)}>
                      <ArrowDown aria-hidden className="size-4" />
                    </Button>
                    <Button type="button" variant="ghost" size="icon" aria-label={`Remove part ${i + 1}`} onClick={() => setRun(run.filter((_, j) => j !== i))}>
                      <Trash2 aria-hidden className="size-4" />
                    </Button>
                  </div>
                </div>
              )
            })}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" variant="ghost" size="sm" disabled={run.length >= 20} onClick={() => setRun([...run, toDraft(run.length ? "on_table" : "warm_up")])}>
                <Plus aria-hidden className="size-4" /> Add a part
              </Button>
              {run.length > 0 && (
                <span className={cn("text-sm", length !== null && planned > length ? "font-semibold text-destructive" : "text-muted-foreground")}>
                  {planned} min planned{length !== null && ` of ${length}`}
                </span>
              )}
            </div>
            {errors.activities && <p className="text-sm font-semibold text-destructive">{errors.activities}</p>}
          </fieldset>
        </>
      )}
      <TextAreaField label="Notes" optional rows={2} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} error={errors.notes} />
      {conflicts.length > 0 && (
        <div role="alert" className="flex flex-col gap-2 rounded-lg border border-destructive bg-destructive/5 p-3 text-sm">
          <p className="font-semibold">That time clashes with:</p>
          <ul className="list-disc pl-5">
            {conflicts.map((c) => (
              <li key={`${c.kind}-${c.starts_at}`}>
                {c.kind === "match" ? "Match: " : ""}
                {c.title}, {formatInstant(c.starts_at, LOCAL_TIME_ZONE)} to {endTime(c.ends_at)}
              </li>
            ))}
          </ul>
          <p>Choose another time.</p>
        </div>
      )}
      {add.isError && conflicts.length === 0 && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <Button type="submit" className="self-start" disabled={add.isPending}>
        {add.isPending ? "Adding…" : kind === "session" ? "Add session" : "Add item"}
      </Button>
    </form>
  )
}
