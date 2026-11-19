import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ExternalLink, Pencil, Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { StepPanels, VirtualTable } from "@/components/training/VirtualTable"
import { errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import {
  addPlanItem,
  CATEGORY_LABEL,
  createPlan,
  getDrill,
  LEVEL_LABEL,
  LIBRARY_LABEL,
  listPlans,
  SKILL_LABEL,
  trainingKeys,
  type Drill,
} from "@/lib/training"

export function SkillChips({ skills, highlight = [] }: { skills: Drill["skills"]; highlight?: string[] }) {
  if (!skills?.length) return null
  return (
    <ul aria-label="What it teaches" className="flex flex-wrap gap-1.5">
      {skills.map((skill) => (
        <li
          key={skill}
          className={
            highlight.includes(skill)
              ? "rounded-full bg-brand-blue px-2.5 py-0.5 text-xs font-semibold text-white"
              : "rounded-full bg-surface-selected px-2.5 py-0.5 text-xs font-semibold text-brand-blue"
          }
        >
          {SKILL_LABEL[skill]}
        </li>
      ))}
    </ul>
  )
}

/** One drill (REQ-026): what it teaches, the pattern on the table step by step, how to play it. */
export function DrillDetailPage() {
  const { id = "" } = useParams()
  const drill = useQuery({ queryKey: trainingKeys.drill(id), queryFn: () => getDrill(id) })
  return (
    <div className="flex max-w-[860px] flex-col gap-6">
      <BackLink to="/training?tab=drills">Drills</BackLink>
      {drill.isPending && <p className="text-muted-foreground">Loading the drill…</p>}
      {drill.isError && <FormAlert>{errorMessage(drill.error, "We couldn't load this drill.")}</FormAlert>}
      {drill.data && <DrillView drill={drill.data} />}
    </div>
  )
}

function DrillView({ drill }: { drill: Drill }) {
  const { active } = useActiveMembership()
  const editable = drill.library === "personal" || (drill.library === "club" && can(active, "training.manage") && active?.organization.id === drill.organization)
  const facts = [
    drill.level && LEVEL_LABEL[drill.level],
    drill.category && CATEGORY_LABEL[drill.category],
    drill.duration_minutes && `${drill.duration_minutes} min`,
    drill.repetitions && `${drill.repetitions} reps`,
  ].filter(Boolean)
  const points = (drill.coaching_points ?? "").split("\n").map((p) => p.trim()).filter(Boolean)

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-2">
          <p className="text-sm font-semibold text-muted-foreground">
            {drill.library === "club" ? drill.organization_name : LIBRARY_LABEL[drill.library]} drill
            {facts.length > 0 && ` · ${facts.join(" · ")}`}
          </p>
          <h1 className="text-[32px] leading-9 font-bold">{drill.title}</h1>
          <SkillChips skills={drill.skills} />
        </div>
        {editable && (
          <Link to={`/training/drills/${drill.id}/edit`} className={buttonVariants({ variant: "outline" })}>
            <Pencil aria-hidden className="size-4" /> Edit
          </Link>
        )}
      </div>
      {drill.description && <p className="text-lg">{drill.description}</p>}

      <PlanActions drill={drill} />

      <div className="grid gap-6 md:grid-cols-[280px_1fr]">
        {drill.pattern.length > 0 && (
          <VirtualTable steps={drill.pattern} label={`${drill.title}: ${drill.pattern.map((s, i) => `${i + 1} ${s.stroke}`).join(", ")}`} />
        )}
        <div className="flex flex-col gap-4">
          <section aria-labelledby="how-heading" className="flex flex-col gap-2">
            <h2 id="how-heading" className="text-xl font-bold">
              How to play it
            </h2>
            <p className="whitespace-pre-line">{drill.instructions}</p>
            {drill.focus && <p className="text-sm text-muted-foreground">Focus: {drill.focus}</p>}
            {drill.equipment && <p className="text-sm text-muted-foreground">You need: {drill.equipment}</p>}
          </section>
          {points.length > 0 && (
            <section aria-labelledby="points-heading" className="flex flex-col gap-2">
              <h2 id="points-heading" className="text-xl font-bold">
                Coaching points
              </h2>
              <ul className="list-disc pl-5">
                {points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </section>
          )}
          {drill.video_url && (
            <a href={drill.video_url} target="_blank" rel="noopener noreferrer" className={buttonVariants({ variant: "outline", className: "self-start" })}>
              <ExternalLink aria-hidden className="size-4" /> {drill.video_url.includes("/results?") ? "Find videos on YouTube" : "Watch on YouTube"}
            </a>
          )}
        </div>
      </div>

      {drill.pattern.length > 1 && (
        <section aria-labelledby="steps-heading" className="flex flex-col gap-3">
          <h2 id="steps-heading" className="text-xl font-bold">
            Step by step
          </h2>
          <StepPanels steps={drill.pattern} />
        </section>
      )}
    </>
  )
}

const NEW = "new"

/** Start a plan built around this drill, or add it to a plan the player already has. */
function PlanActions({ drill }: { drill: Drill }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const plans = useQuery({ queryKey: trainingKeys.plans, queryFn: listPlans })
  const [target, setTarget] = useState(NEW)
  const go = useMutation({
    mutationFn: async () => {
      const plan =
        target === NEW ? await createPlan({ title: drill.title, goal_skills: drill.skills }) : { id: target }
      await addPlanItem(plan.id, { kind: "checklist", drill: drill.id })
      return plan.id
    },
    onSuccess: async (planId) => {
      await queryClient.invalidateQueries({ queryKey: trainingKeys.all })
      navigate(`/training/plans/${planId}`)
    },
  })
  const options = [{ value: NEW, label: "A new plan for this drill" }, ...(plans.data?.results ?? []).map((p) => ({ value: p.id, label: p.title }))]

  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-card p-4 sm:flex-row sm:items-end">
      <div className="flex-1">
        <SelectField label="Train this drill in" options={options} value={target} onChange={setTarget} />
      </div>
      <Button size="lg" disabled={go.isPending} onClick={() => go.mutate()}>
        <Plus aria-hidden className="size-5" /> {go.isPending ? "Adding…" : target === NEW ? "Create training plan" : "Add to plan"}
      </Button>
      {go.isError && <FormAlert>{errorMessage(go.error)}</FormAlert>}
    </div>
  )
}
