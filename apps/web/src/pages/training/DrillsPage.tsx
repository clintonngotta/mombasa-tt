import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { TextAreaField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import {
  createClubDrill,
  createMyDrill,
  deleteClubDrill,
  deleteMyDrill,
  listClubDrills,
  listMyDrills,
  trainingKeys,
  updateClubDrill,
  updateMyDrill,
  type Drill,
  type DrillInput,
} from "@/lib/training"

type Library = {
  key: readonly unknown[]
  create: (body: DrillInput) => Promise<Drill>
  update: (id: string, body: DrillInput) => Promise<Drill>
  remove: (id: string) => Promise<void>
}

/** Drill libraries (REQ-026): the player's own, private, and their club's, edited by its training staff. */
export function DrillsPage() {
  const { active } = useActiveMembership()
  const orgId = active && !active.managedOnly ? active.organization.id : ""
  const mine = useQuery({ queryKey: trainingKeys.myDrills, queryFn: listMyDrills })
  const club = useQuery({ queryKey: trainingKeys.clubDrills(orgId), queryFn: () => listClubDrills(orgId), enabled: !!orgId })
  const personal: Library = {
    key: trainingKeys.myDrills,
    create: createMyDrill,
    update: updateMyDrill,
    remove: deleteMyDrill,
  }
  const clubLibrary: Library = {
    key: trainingKeys.clubDrills(orgId),
    create: (body) => createClubDrill(orgId, body),
    update: (id, body) => updateClubDrill(orgId, id, body),
    remove: (id) => deleteClubDrill(orgId, id),
  }

  return (
    <div className="flex max-w-[720px] flex-col gap-8">
      <BackLink to="/training">Training</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Drills</h1>
      <DrillSection
        heading="My drills"
        note="Only you see these."
        drills={mine.data?.results}
        error={mine.error}
        library={personal}
        editable
      />
      {orgId && (
        <DrillSection
          heading={`${active!.organization.name} drills`}
          note={can(active, "training.manage") ? "Every member of the club sees these." : "Shared by the club's coaches. Add any of them to your plans."}
          drills={club.data}
          error={club.error}
          library={clubLibrary}
          editable={can(active, "training.manage")}
        />
      )}
    </div>
  )
}

function DrillSection({
  heading,
  note,
  drills,
  error,
  library,
  editable,
}: {
  heading: string
  note: string
  drills?: Drill[]
  error: unknown
  library: Library
  editable: boolean
}) {
  const [adding, setAdding] = useState(false)
  return (
    <section aria-label={heading} className="flex flex-col gap-3">
      <h2 className="text-xl font-bold">{heading}</h2>
      <p className="-mt-2 text-sm text-muted-foreground">{note}</p>
      {error ? <FormAlert>{errorMessage(error, "We couldn't load these drills.")}</FormAlert> : null}
      {drills && drills.length === 0 && <p className="text-muted-foreground">No drills yet.</p>}
      {drills && drills.length > 0 && (
        <ul className="flex flex-col gap-2">
          {drills.map((drill) => (
            <DrillRow key={drill.id} drill={drill} library={library} editable={editable} />
          ))}
        </ul>
      )}
      {editable &&
        (adding ? (
          <div className="rounded-xl border bg-card p-4">
            <DrillForm library={library} onDone={() => setAdding(false)} />
          </div>
        ) : (
          <Button variant="outline" className="self-start" onClick={() => setAdding(true)}>
            <Plus aria-hidden className="size-5" /> Add a drill
          </Button>
        ))}
    </section>
  )
}

function details(drill: Drill) {
  return [
    drill.focus,
    drill.duration_minutes ? `${drill.duration_minutes} min` : null,
    drill.repetitions ? `${drill.repetitions} reps` : null,
    drill.equipment,
  ]
    .filter(Boolean)
    .join(" · ")
}

function DrillRow({ drill, library, editable }: { drill: Drill; library: Library; editable: boolean }) {
  const [editing, setEditing] = useState(false)
  const summary = details(drill)
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      {editing ? (
        <DrillForm drill={drill} library={library} onDone={() => setEditing(false)} />
      ) : (
        <div className="flex flex-wrap items-start gap-3">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <h3 className="font-semibold">{drill.title}</h3>
            {summary && <p className="text-sm text-muted-foreground">{summary}</p>}
            <p className="text-sm whitespace-pre-line">{drill.instructions}</p>
          </div>
          {editable && (
            <Button variant="outline" aria-label={`Edit ${drill.title}`} onClick={() => setEditing(true)}>
              Edit
            </Button>
          )}
        </div>
      )}
    </li>
  )
}

function DrillForm({ drill, library, onDone }: { drill?: Drill; library: Library; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState({
    title: drill?.title ?? "",
    instructions: drill?.instructions ?? "",
    focus: drill?.focus ?? "",
    duration: drill?.duration_minutes?.toString() ?? "",
    repetitions: drill?.repetitions?.toString() ?? "",
    equipment: drill?.equipment ?? "",
  })
  const [confirmDelete, setConfirmDelete] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: library.key })
  const save = useMutation({
    mutationFn: () => {
      const body: DrillInput = {
        title: draft.title.trim(),
        instructions: draft.instructions.trim(),
        focus: draft.focus.trim(),
        equipment: draft.equipment.trim(),
        duration_minutes: draft.duration ? Number(draft.duration) : null,
        repetitions: draft.repetitions ? Number(draft.repetitions) : null,
      }
      return drill ? library.update(drill.id, body) : library.create(body)
    },
    onSuccess: async () => {
      await refresh()
      onDone()
    },
  })
  const remove = useMutation({
    mutationFn: () => library.remove(drill!.id),
    onSuccess: async () => {
      await refresh()
      onDone()
    },
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const set = (name: keyof typeof draft) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft({ ...draft, [name]: e.target.value })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex w-full flex-col gap-4">
      <Field label="Title" required maxLength={80} value={draft.title} onChange={set("title")} error={errors.title} />
      <TextAreaField label="Instructions" required rows={4} maxLength={2000} value={draft.instructions} onChange={set("instructions")} error={errors.instructions} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Focus" optional maxLength={80} value={draft.focus} onChange={set("focus")} error={errors.focus} hint="e.g. Footwork" />
        <Field label="Equipment" optional maxLength={200} value={draft.equipment} onChange={set("equipment")} error={errors.equipment} hint="e.g. Ball basket" />
        <Field label="Minutes" optional type="number" inputMode="numeric" min={1} max={600} value={draft.duration} onChange={set("duration")} error={errors.duration_minutes} />
        <Field label="Repetitions" optional type="number" inputMode="numeric" min={1} value={draft.repetitions} onChange={set("repetitions")} error={errors.repetitions} />
      </div>
      {save.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : drill ? "Save drill" : "Add drill"}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        {drill &&
          (confirmDelete ? (
            <Button type="button" variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {remove.isPending ? "Deleting…" : "Confirm delete"}
            </Button>
          ) : (
            <Button type="button" variant="ghost" className="text-destructive" onClick={() => setConfirmDelete(true)}>
              Delete
            </Button>
          ))}
      </div>
    </form>
  )
}
