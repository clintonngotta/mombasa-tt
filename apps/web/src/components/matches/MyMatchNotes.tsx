import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Lock, NotebookPen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { TextAreaField } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import { createMatchNote, deleteMatchNote, matchNoteKeys, noteFor, updateMatchNote, type MatchLink, type MatchNote } from "@/lib/matchNotes"

/**
 * The player's own notes on a match they played (REQ-025): what they noticed and what to work on.
 * Private to them: the opponent, club staff and coaches never see these. The match's score stays as the
 * umpire recorded it.
 */
export function MyMatchNotes({ link }: { link: MatchLink }) {
  const note = useQuery({ queryKey: matchNoteKeys.of(link), queryFn: () => noteFor(link) })
  const [editing, setEditing] = useState(false)
  if (note.isPending) return null

  return (
    <section aria-labelledby="my-notes-heading" className="flex flex-col gap-2">
      <h2 id="my-notes-heading" className="flex items-center gap-2 text-xl">
        <NotebookPen aria-hidden className="size-5 text-brand-blue" /> My notes
      </h2>
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Lock aria-hidden className="size-4" /> Only you see these. The score stays as the umpire recorded it.
      </p>
      {note.isError && <FormAlert>{errorMessage(note.error, "We couldn't load your notes.")}</FormAlert>}
      {editing || !note.data ? (
        <NoteForm link={link} note={note.data ?? null} onDone={() => setEditing(false)} startOpen={editing} />
      ) : (
        <div className="flex flex-col gap-3 rounded-xl border bg-card p-4">
          {note.data.observations && (
            <div>
              <p className="text-sm font-semibold">What I noticed</p>
              <p className="whitespace-pre-wrap">{note.data.observations}</p>
            </div>
          )}
          {note.data.goals && (
            <div>
              <p className="text-sm font-semibold">What to work on</p>
              <p className="whitespace-pre-wrap">{note.data.goals}</p>
            </div>
          )}
          <p className="text-sm text-muted-foreground">Updated {new Date(note.data.updated_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</p>
          <Button variant="outline" className="self-start" onClick={() => setEditing(true)}>
            Edit notes
          </Button>
        </div>
      )}
    </section>
  )
}

function NoteForm({ link, note, onDone, startOpen }: { link: MatchLink; note: MatchNote | null; onDone: () => void; startOpen: boolean }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(startOpen)
  const [observations, setObservations] = useState(note?.observations ?? "")
  const [goals, setGoals] = useState(note?.goals ?? "")
  const refresh = () => queryClient.invalidateQueries({ queryKey: matchNoteKeys.all })
  const save = useMutation({
    mutationFn: () => (note ? updateMatchNote(note.id, { observations, goals }) : createMatchNote(link, { observations, goals })),
    onSuccess: () => {
      void refresh()
      onDone()
    },
  })
  const remove = useMutation({
    mutationFn: () => deleteMatchNote(note!.id),
    onSuccess: () => {
      void refresh()
      onDone()
    },
  })
  if (!open) {
    return (
      <Button variant="outline" className="self-start" onClick={() => setOpen(true)}>
        Add notes on this match
      </Button>
    )
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-3 rounded-xl border bg-card p-4" noValidate>
      <TextAreaField label="What I noticed" optional maxLength={4000} rows={4} value={observations} onChange={(e) => setObservations(e.target.value)} />
      <TextAreaField label="What to work on" optional maxLength={2000} rows={3} value={goals} onChange={(e) => setGoals(e.target.value)} />
      {(save.isError || remove.isError) && <FormAlert>{errorMessage(save.error ?? remove.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending || (!observations.trim() && !goals.trim())}>
          {save.isPending ? "Saving…" : "Save notes"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            if (!note) setOpen(false)
            onDone()
          }}
        >
          Cancel
        </Button>
        {note && (
          <Button type="button" variant="ghost" className="text-destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
            Delete notes
          </Button>
        )}
      </div>
    </form>
  )
}
