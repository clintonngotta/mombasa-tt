import { useDeferredValue, useState, type FormEvent } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarClock, ChevronRight, Plus } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { SelectField } from "@/components/forms/SelectField"
import { VirtualTable } from "@/components/training/VirtualTable"
import { SkillChips } from "@/pages/training/DrillDetailPage"
import { CoachingTab } from "@/pages/coaching/CoachingTab"
import { ClubInvitations } from "@/components/training/ClubInvitations"
import { ApiError, errorMessage } from "@/lib/api"
import { formatDayRange, formatInstant } from "@/lib/dates"
import { ROW } from "@/lib/clubAdmin"
import { can, useActiveMembership, type Membership } from "@/lib/clubs"
import { cn } from "@/lib/utils"
import {
  CATEGORY_LABEL,
  createClubPlan,
  createPlan,
  getEquipment,
  LEVEL_LABEL,
  LIBRARY_LABEL,
  listClubPlans,
  listLibrary,
  listPlans,
  listUpcomingSessions,
  LOCAL_TIME_ZONE,
  PERIOD_LABEL,
  saveEquipment,
  SKILL_LABEL,
  SKILLS,
  trainingKeys,
  type Category,
  type Equipment,
  type Period,
  type Skill,
  type TrainingPlan,
} from "@/lib/training"

type Tab = "mine" | "drills" | "club" | "coaching"
const TABS: { value: Tab; label: string }[] = [
  { value: "mine", label: "My training" },
  { value: "drills", label: "Drills" },
  { value: "club", label: "Club plans" },
  { value: "coaching", label: "Coaching" },
]

/** Training (REQ-026, REQ-027, REQ-047): your plans and sessions, the drill library, your club's plans and
 * coaching, as a coach or with one. */
export function TrainingPage() {
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find((t) => t.value === params.get("tab"))?.value ?? "mine") as Tab
  const { active } = useActiveMembership()
  const member = active && !active.managedOnly ? active : undefined

  return (
    <div className="flex max-w-[860px] flex-col gap-6">
      <h1 className="text-[32px] leading-9 font-bold">Training</h1>
      <div role="tablist" aria-label="Training" className="flex gap-1 overflow-x-auto border-b">
        {TABS.filter((t) => t.value !== "club" || member).map((t) => (
          <button
            key={t.value}
            role="tab"
            type="button"
            aria-selected={tab === t.value}
            onClick={() => setParams(t.value === "mine" ? {} : { tab: t.value })}
            className={cn(
              "-mb-px min-h-12 shrink-0 border-b-2 px-4 font-semibold whitespace-nowrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              tab === t.value ? "border-brand-blue text-brand-blue" : "border-transparent text-muted-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="flex flex-col gap-8">
        {tab === "mine" && (
          <>
            <p className="-mb-4 text-muted-foreground">Only you see your plans, drills and equipment.</p>
            <ClubInvitations />
            <Upcoming />
            <Plans />
            <EquipmentCard />
          </>
        )}
        {tab === "drills" && <DrillLibrary membership={member} />}
        {tab === "club" && member && <ClubPlans membership={member} />}
        {tab === "coaching" && <CoachingTab />}
      </div>
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

function Progress({ plan }: { plan: TrainingPlan }) {
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

function PlanList({ plans, to }: { plans: TrainingPlan[]; to: (plan: TrainingPlan) => string }) {
  return (
    <ul className="flex flex-col gap-2">
      {plans.map((plan) => (
        <li key={plan.id}>
          <Link to={to(plan)} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
            <span className="flex min-w-0 flex-1 flex-col gap-2">
              <span className="truncate font-semibold">{plan.title}</span>
              {plan.coach_name && <span className="text-sm font-semibold text-brand-blue">From coach {plan.coach_name}</span>}
              {plan.starts_on && (
                <span className="text-sm text-muted-foreground">
                  {plan.period !== "custom" && `${PERIOD_LABEL[plan.period ?? "custom"]} · `}
                  {formatDayRange(plan.starts_on, plan.ends_on ?? plan.starts_on)}
                </span>
              )}
              <SkillChips skills={plan.goal_skills} />
              <Progress plan={plan} />
            </span>
            <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  )
}

/** Title, goal skills and, for clubs, the period: the start of every plan. */
function NewPlanForm({ club, onCreate, pending, error }: { club?: boolean; onCreate: (body: Parameters<typeof createPlan>[0]) => void; pending: boolean; error: unknown }) {
  const [title, setTitle] = useState("")
  const [skills, setSkills] = useState<Skill[]>([])
  const [period, setPeriod] = useState<Period>(club ? "week" : "custom")
  const [startsOn, setStartsOn] = useState("")
  const errors = error instanceof ApiError ? error.fieldErrors() : {}

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    onCreate({ title: title.trim(), goal_skills: skills, period, ...(startsOn ? { starts_on: startsOn } : {}) })
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h3 className="text-lg font-bold">{club ? "New club plan" : "New plan"}</h3>
      <Field label="Title" maxLength={80} value={title} onChange={(e) => setTitle(e.target.value)} error={errors.title} hint={club ? "e.g. Juniors, week 1" : "e.g. Attack after my serve"} />
      <ChoiceGroup
        legend="Goal"
        optional
        multiple
        columns={3}
        options={SKILLS.map((skill) => ({ value: skill, label: SKILL_LABEL[skill] }))}
        value={skills}
        onChange={setSkills}
        error={errors.goal_skills}
      />
      <p className="-mt-2 text-sm text-muted-foreground">We'll recommend drills that teach what you choose.</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField
          label="Covers"
          options={(Object.keys(PERIOD_LABEL) as Period[]).map((p) => ({ value: p, label: PERIOD_LABEL[p] }))}
          value={period}
          onChange={(value) => setPeriod(value as Period)}
          error={errors.period}
        />
        <Field
          label={period === "custom" ? "Starts" : `First day of the ${period}`}
          optional={period === "custom"}
          type="date"
          value={startsOn}
          onChange={(e) => setStartsOn(e.target.value)}
          error={errors.starts_on}
        />
      </div>
      {error != null && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(error)}</FormAlert>}
      <Button type="submit" className="self-start" disabled={pending || !title.trim()}>
        <Plus aria-hidden className="size-5" /> {pending ? "Creating…" : "Create plan"}
      </Button>
    </form>
  )
}

function Plans() {
  const navigate = useNavigate()
  const plans = useQuery({ queryKey: trainingKeys.plans, queryFn: listPlans })
  const create = useMutation({ mutationFn: createPlan, onSuccess: (plan) => navigate(`/training/plans/${plan.id}`) })
  const items = plans.data?.results ?? []
  return (
    <section aria-labelledby="plans-heading" className="flex flex-col gap-3">
      <h2 id="plans-heading" className="text-xl font-bold">
        My plans
      </h2>
      {plans.isError && <FormAlert>{errorMessage(plans.error, "We couldn't load your plans.")}</FormAlert>}
      {plans.isSuccess && items.length === 0 && <p className="text-muted-foreground">No plans yet. Start one below, or from a drill.</p>}
      {items.length > 0 && <PlanList plans={items} to={(plan) => `/training/plans/${plan.id}`} />}
      <NewPlanForm onCreate={(body) => create.mutate(body)} pending={create.isPending} error={create.error} />
    </section>
  )
}

const ALL = "all"

function DrillLibrary({ membership }: { membership?: Membership }) {
  const library = useQuery({ queryKey: trainingKeys.library, queryFn: listLibrary })
  const [term, setTerm] = useState("")
  const [skill, setSkill] = useState<string>(ALL)
  const [category, setCategory] = useState<string>(ALL)
  const search = useDeferredValue(term.trim().toLowerCase())
  const drills = (library.data ?? []).filter(
    (d) =>
      (skill === ALL || d.skills?.includes(skill as Skill)) &&
      (category === ALL || d.category === category) &&
      (!search || d.title.toLowerCase().includes(search) || (d.focus ?? "").toLowerCase().includes(search)),
  )
  const coach = can(membership, "training.manage")

  return (
    <section aria-label="Drill library" className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        <Link to="/training/drills/new" className={buttonVariants({ variant: "outline" })}>
          <Plus aria-hidden className="size-5" /> My own drill
        </Link>
        {coach && (
          <Link to="/training/drills/new?library=club" className={buttonVariants({ variant: "outline" })}>
            <Plus aria-hidden className="size-5" /> {membership!.organization.name} drill
          </Link>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Search" type="search" value={term} onChange={(e) => setTerm(e.target.value)} />
        <SelectField
          label="Teaches"
          options={[{ value: ALL, label: "Anything" }, ...SKILLS.map((s) => ({ value: s, label: SKILL_LABEL[s] }))]}
          value={skill}
          onChange={setSkill}
        />
        <SelectField
          label="Kind"
          options={[{ value: ALL, label: "All kinds" }, ...(Object.keys(CATEGORY_LABEL) as Category[]).map((c) => ({ value: c, label: CATEGORY_LABEL[c] }))]}
          value={category}
          onChange={setCategory}
        />
      </div>
      {library.isPending && <p className="text-muted-foreground">Loading drills…</p>}
      {library.isError && <FormAlert>{errorMessage(library.error, "We couldn't load the drills.")}</FormAlert>}
      {library.isSuccess && drills.length === 0 && <p className="text-muted-foreground">No drills match.</p>}
      <ul className="grid gap-3 sm:grid-cols-2">
        {drills.map((drill) => (
          <li key={drill.id}>
            <Link
              to={`/training/drills/${drill.id}`}
              className="flex h-full gap-3 rounded-xl border bg-card p-3 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <div className="w-20 shrink-0">{drill.pattern.length > 0 && <VirtualTable steps={drill.pattern} label="" className="pointer-events-none" />}</div>
              <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="font-semibold">{drill.title}</span>
                <span className="text-xs text-muted-foreground">
                  {drill.library === "club" ? drill.organization_name : LIBRARY_LABEL[drill.library]}
                  {drill.level && ` · ${LEVEL_LABEL[drill.level]}`}
                  {drill.duration_minutes && ` · ${drill.duration_minutes} min`}
                </span>
                <SkillChips skills={drill.skills} highlight={skill === ALL ? [] : [skill]} />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ClubPlans({ membership }: { membership: Membership }) {
  const navigate = useNavigate()
  const orgId = membership.organization.id
  const plans = useQuery({ queryKey: trainingKeys.clubPlans(orgId), queryFn: () => listClubPlans(orgId) })
  const create = useMutation({ mutationFn: (body: Parameters<typeof createPlan>[0]) => createClubPlan(orgId, body), onSuccess: (plan) => navigate(`/training/club-plans/${plan.id}`) })
  const coach = can(membership, "training.manage")
  const items = plans.data?.results ?? []

  return (
    <section aria-label={`${membership.organization.name} training plans`} className="flex flex-col gap-3">
      <p className="text-muted-foreground">
        {membership.organization.name}'s training programme: plans for a day, a week or longer{coach ? ", set by its coaches" : ""}.
      </p>
      {plans.isError && <FormAlert>{errorMessage(plans.error, "We couldn't load the club's plans.")}</FormAlert>}
      {plans.isSuccess && items.length === 0 && <p className="text-muted-foreground">The club hasn't published a training plan yet.</p>}
      {items.length > 0 && <PlanList plans={items} to={(plan) => `/training/club-plans/${plan.id}`} />}
      {coach && <NewPlanForm club onCreate={(body) => create.mutate(body)} pending={create.isPending} error={create.error} />}
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
