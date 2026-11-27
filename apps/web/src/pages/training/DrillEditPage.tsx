import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type FormEvent } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { PatternEditor } from "@/components/training/PatternEditor"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import {
  CATEGORY_LABEL,
  createClubDrill,
  createMyDrill,
  deleteClubDrill,
  deleteMyDrill,
  getDrill,
  LEVEL_LABEL,
  SKILL_LABEL,
  SKILLS,
  trainingKeys,
  updateClubDrill,
  updateMyDrill,
  type Category,
  type Drill,
  type DrillInput,
  type PatternStep,
  type Skill,
} from "@/lib/training"

const NONE = "none"

/** Create or edit a drill: a player's own, or (for training staff) their club's. */
export function DrillEditPage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const { active } = useActiveMembership()
  const drill = useQuery({ queryKey: trainingKeys.drill(id ?? ""), queryFn: () => getDrill(id!), enabled: !!id })
  const club = id ? drill.data?.library === "club" : params.get("library") === "club"
  const orgId = club ? (drill.data?.organization ?? active?.organization.id ?? "") : ""
  const allowed = !club || (can(active, "training.manage") && active?.organization.id === orgId)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={id ? `/training/drills/${id}` : "/training?tab=drills"}>{id ? "Drill" : "Drills"}</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">{id ? `Edit ${drill.data?.title ?? "drill"}` : club ? `New ${active?.organization.name ?? "club"} drill` : "New drill"}</h1>
      {drill.isError && <FormAlert>{errorMessage(drill.error, "We couldn't load this drill.")}</FormAlert>}
      {id && drill.data?.library === "standard" && <FormAlert>Standard drills can't be changed. Add your own drill instead.</FormAlert>}
      {!allowed && <FormAlert>Only the club's training staff can change its drills.</FormAlert>}
      {allowed && (!id || (drill.data && drill.data.library !== "standard")) && <DrillForm key={drill.data?.id ?? "new"} drill={drill.data} orgId={club ? orgId : ""} />}
    </div>
  )
}

function DrillForm({ drill, orgId }: { drill?: Drill; orgId: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const kept = useDraft(`drill:${drill?.id ?? "new"}`)
  const [draft, setDraft] = useDraftState(kept, "draft", {
    title: drill?.title ?? "",
    instructions: drill?.instructions ?? "",
    description: drill?.description ?? "",
    coaching: drill?.coaching_points ?? "",
    focus: drill?.focus ?? "",
    duration: drill?.duration_minutes?.toString() ?? "",
    repetitions: drill?.repetitions?.toString() ?? "",
    equipment: drill?.equipment ?? "",
    video: drill?.video_url ?? "",
    category: (drill?.category || NONE) as Category | typeof NONE,
    level: drill?.level || NONE,
  })
  const [skills, setSkills] = useDraftState<Skill[]>(kept, "skills", drill?.skills ?? [])
  const [pattern, setPattern] = useDraftState<PatternStep[]>(kept, "pattern", drill?.pattern ?? [])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const set = (name: keyof typeof draft) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft({ ...draft, [name]: e.target.value })

  const save = useMutation({
    mutationFn: () => {
      const body: DrillInput = {
        title: draft.title.trim(),
        instructions: draft.instructions.trim(),
        description: draft.description.trim(),
        coaching_points: draft.coaching.trim(),
        focus: draft.focus.trim(),
        equipment: draft.equipment.trim(),
        video_url: draft.video.trim(),
        duration_minutes: draft.duration ? Number(draft.duration) : null,
        repetitions: draft.repetitions ? Number(draft.repetitions) : null,
        category: draft.category === NONE ? "" : draft.category,
        level: draft.level === NONE ? "" : (draft.level as DrillInput["level"]),
        skills,
        pattern: pattern.map((step) => ({ ...step, note: step.note?.trim() ?? "" })),
      }
      if (drill) return orgId ? updateClubDrill(orgId, drill.id, body) : updateMyDrill(drill.id, body)
      return orgId ? createClubDrill(orgId, body) : createMyDrill(body)
    },
    onSuccess: async (saved) => {
      kept.clear()
      await queryClient.invalidateQueries({ queryKey: trainingKeys.all })
      navigate(`/training/drills/${saved.id}`)
    },
  })
  const remove = useMutation({
    mutationFn: () => (orgId ? deleteClubDrill(orgId, drill!.id) : deleteMyDrill(drill!.id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: trainingKeys.all })
      navigate("/training?tab=drills")
    },
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
      <Field label="Title" required maxLength={80} value={draft.title} onChange={set("title")} error={errors.title} />
      <TextAreaField label="Instructions" required rows={4} maxLength={2000} value={draft.instructions} onChange={set("instructions")} error={errors.instructions} hint="What to do, step by step." />
      <PatternEditor steps={pattern} onChange={setPattern} error={errors.pattern} />
      <ChoiceGroup
        legend="What it teaches"
        optional
        multiple
        columns={3}
        options={SKILLS.map((skill) => ({ value: skill, label: SKILL_LABEL[skill] }))}
        value={skills}
        onChange={setSkills}
        error={errors.skills}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField
          label="Category"
          optional
          options={[{ value: NONE, label: "None" }, ...(Object.keys(CATEGORY_LABEL) as Category[]).map((c) => ({ value: c, label: CATEGORY_LABEL[c] }))]}
          value={draft.category}
          onChange={(value) => setDraft({ ...draft, category: value as Category })}
          error={errors.category}
        />
        <SelectField
          label="Level"
          optional
          options={[{ value: NONE, label: "Any level" }, ...Object.entries(LEVEL_LABEL).map(([value, label]) => ({ value, label }))]}
          value={draft.level}
          onChange={(value) => setDraft({ ...draft, level: value })}
          error={errors.level}
        />
        <Field label="Focus" optional maxLength={80} value={draft.focus} onChange={set("focus")} error={errors.focus} hint="e.g. Footwork and pivot" />
        <Field label="Equipment" optional maxLength={200} value={draft.equipment} onChange={set("equipment")} error={errors.equipment} hint="e.g. Ball basket" />
        <Field label="Minutes" optional type="number" inputMode="numeric" min={1} max={600} value={draft.duration} onChange={set("duration")} error={errors.duration_minutes} />
        <Field label="Repetitions" optional type="number" inputMode="numeric" min={1} value={draft.repetitions} onChange={set("repetitions")} error={errors.repetitions} />
      </div>
      <TextAreaField label="Coaching points" optional rows={3} maxLength={2000} value={draft.coaching} onChange={set("coaching")} error={errors.coaching_points} hint="One per line." />
      <TextAreaField label="About this drill" optional rows={3} maxLength={2000} value={draft.description} onChange={set("description")} error={errors.description} hint="Where it comes from and what it builds." />
      <Field label="YouTube video" optional type="url" maxLength={300} value={draft.video} onChange={set("video")} error={errors.video_url} hint="A video of the drill being played." />
      {save.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
      <DraftBar draft={kept} />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="lg" disabled={save.isPending}>
          {save.isPending ? "Saving…" : drill ? "Save drill" : "Create drill"}
        </Button>
        {drill &&
          (confirmDelete ? (
            <Button type="button" variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {remove.isPending ? "Deleting…" : "Confirm delete"}
            </Button>
          ) : (
            <Button type="button" variant="ghost" className="text-destructive" onClick={() => setConfirmDelete(true)}>
              Delete drill
            </Button>
          ))}
      </div>
    </form>
  )
}
