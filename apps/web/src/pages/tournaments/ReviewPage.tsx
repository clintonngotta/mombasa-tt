import { useState, type FormEvent } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Plus, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { TextAreaField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { formatDay, formatInstant } from "@/lib/dates"
import { getReview, MAX_REVIEW_ACTIONS, reviewKey, saveReview, type TournamentReview } from "@/lib/review"
import { getTournament, tournamentKeys } from "@/lib/tournaments"
import { cn } from "@/lib/utils"

type ActionDraft = { text: string; owner: string; due: string; done: boolean }

/** The review of a finished tournament (REQ-055): what went well, what went wrong and what to do next time.
 * The host's competition staff write it; they and the region's officials read it. It is never public. */
export function ReviewPage() {
  const { id = "" } = useParams()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  // Colleagues edit the same review, so read it fresh each time.
  const review = useQuery({ queryKey: reviewKey(id), queryFn: () => getReview(id), staleTime: 0, retry: false })
  const [editing, setEditing] = useState(false)
  const t = tournament.data
  const r = review.data
  const written = !!r?.updated_at

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Review</h1>
        <p className="text-muted-foreground">For the organizers and the region's officials. Players and the public don't see it.</p>
      </div>
      {review.isPending && <p className="text-muted-foreground">Loading…</p>}
      {review.isError && <FormAlert>{errorMessage(review.error, "The review is for the host's staff and officials.")}</FormAlert>}
      {r && !editing && (
        <>
          {!written && <p className="text-muted-foreground">{r.can_edit ? "No review yet. Write it while the day is fresh." : "No review has been written yet."}</p>}
          {written && <ReviewText review={r} timeZone={t?.timezone ?? "Africa/Nairobi"} />}
          {r.can_edit && (
            <Button className="self-start" variant={written ? "outline" : "default"} onClick={() => setEditing(true)}>
              {written ? "Change the review" : "Write the review"}
            </Button>
          )}
          {!r.can_edit && !written && t && t.status !== "completed" && <p className="text-sm text-muted-foreground">It can be written from the tournament's last day.</p>}
        </>
      )}
      {r && editing && <ReviewForm tournamentId={id} review={r} onDone={() => setEditing(false)} />}
    </div>
  )
}

function ReviewText({ review, timeZone }: { review: TournamentReview; timeZone: string }) {
  return (
    <>
      {review.went_well && (
        <section aria-labelledby="well-heading" className="flex flex-col gap-2">
          <h2 id="well-heading" className="text-xl font-bold">
            What went well
          </h2>
          <p className="rounded-xl border bg-card p-4 whitespace-pre-wrap">{review.went_well}</p>
        </section>
      )}
      {review.went_wrong && (
        <section aria-labelledby="wrong-heading" className="flex flex-col gap-2">
          <h2 id="wrong-heading" className="text-xl font-bold">
            What went wrong
          </h2>
          <p className="rounded-xl border bg-card p-4 whitespace-pre-wrap">{review.went_wrong}</p>
        </section>
      )}
      {(review.actions?.length ?? 0) > 0 && (
        <section aria-labelledby="actions-heading" className="flex flex-col gap-2">
          <h2 id="actions-heading" className="text-xl font-bold">
            Actions for next time
          </h2>
          <ul className="flex flex-col gap-2">
            {review.actions!.map((action, i) => (
              <li key={i} className="flex items-start gap-2 rounded-lg border bg-card px-3 py-2">
                {action.done && <Check aria-hidden className="mt-1 size-4 shrink-0 text-brand-blue" />}
                <span>
                  <span className={cn("font-semibold break-words", action.done && "text-muted-foreground line-through")}>{action.text}</span>
                  <span className="block text-sm text-muted-foreground">
                    {action.owner || "No owner yet"}
                    {action.due_on && ` · by ${formatDay(action.due_on)}`}
                    {action.done && " · done"}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {review.updated_at && (
        <p className="text-sm text-muted-foreground">
          Last changed {formatInstant(review.updated_at, timeZone)}
          {review.updated_by_name && ` by ${review.updated_by_name}`}
        </p>
      )}
    </>
  )
}

function ReviewForm({ tournamentId, review, onDone }: { tournamentId: string; review: TournamentReview; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [well, setWell] = useState(review.went_well ?? "")
  const [wrong, setWrong] = useState(review.went_wrong ?? "")
  const [actions, setActions] = useState<ActionDraft[]>(() => (review.actions ?? []).map((a) => ({ text: a.text, owner: a.owner ?? "", due: a.due_on ?? "", done: !!a.done })))
  const save = useMutation({
    mutationFn: () =>
      saveReview(tournamentId, {
        went_well: well.trim(),
        went_wrong: wrong.trim(),
        actions: actions.filter((a) => a.text.trim()).map((a) => ({ text: a.text.trim(), owner: a.owner.trim(), due_on: a.due || null, done: a.done })),
      }),
    onSuccess: (fresh) => {
      queryClient.setQueryData(reviewKey(tournamentId), fresh)
      onDone()
    },
  })
  const fields: Record<string, string | undefined> = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const setAction = (index: number, change: Partial<ActionDraft>) => setActions(actions.map((a, i) => (i === index ? { ...a, ...change } : a)))
  const empty = !well.trim() && !wrong.trim() && !actions.some((a) => a.text.trim())

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      {save.isError && <FormAlert>{fields.went_well ?? fields.went_wrong ?? fields.actions ?? errorMessage(save.error, "We couldn't save the review.")}</FormAlert>}
      <TextAreaField label="What went well" optional rows={5} maxLength={5000} value={well} onChange={(e) => setWell(e.target.value)} />
      <TextAreaField label="What went wrong" optional rows={5} maxLength={5000} value={wrong} onChange={(e) => setWrong(e.target.value)} />
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-semibold">Actions for next time</legend>
        {actions.map((action, i) => (
          <div key={i} className="flex flex-col gap-2 rounded-lg border p-3">
            <Field label={`Action ${i + 1}`} maxLength={300} value={action.text} onChange={(e) => setAction(i, { text: e.target.value })} />
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label="Owner" optional maxLength={120} placeholder="A name or a role" value={action.owner} onChange={(e) => setAction(i, { owner: e.target.value })} />
              <Field label="Due" optional type="date" value={action.due} onChange={(e) => setAction(i, { due: e.target.value })} />
            </div>
            <div className="flex items-center justify-between gap-2">
              <label className="flex min-h-12 items-center gap-2">
                <input type="checkbox" className="size-5 accent-brand-blue" checked={action.done} onChange={(e) => setAction(i, { done: e.target.checked })} />
                Done
              </label>
              <Button type="button" variant="outline" size="icon" aria-label={`Remove action ${i + 1}`} onClick={() => setActions(actions.filter((_, j) => j !== i))}>
                <Trash2 aria-hidden className="size-5" />
              </Button>
            </div>
          </div>
        ))}
        <Button type="button" variant="ghost" className="self-start" disabled={actions.length >= MAX_REVIEW_ACTIONS} onClick={() => setActions([...actions, { text: "", owner: "", due: "", done: false }])}>
          <Plus aria-hidden className="size-4" /> Add an action
        </Button>
      </fieldset>
      <div className="flex gap-2">
        <Button type="submit" disabled={empty || save.isPending}>
          {save.isPending ? "Saving…" : "Save review"}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
