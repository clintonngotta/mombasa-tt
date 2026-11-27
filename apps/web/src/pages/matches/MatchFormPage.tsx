import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type ComponentProps, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Info, Plus, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { Field, FieldError, FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import {
  createMatchOrKeep,
  getMatch,
  getMatchLabels,
  matchKeys,
  updateMatch,
  type MatchFormat,
  type PersonalMatch,
  type PersonalMatchInput,
} from "@/lib/matchlog"
import { cn } from "@/lib/utils"

type SetRow = { mine: string; theirs: string }
type FormState = Omit<PersonalMatchInput, "games"> & { sets: SetRow[] }

const MAX_SETS = 7
const FORMATS: { value: MatchFormat; label: string }[] = [
  { value: "singles", label: "Singles" },
  { value: "doubles", label: "Doubles" },
]

const today = () => new Date().toLocaleDateString("en-CA") // YYYY-MM-DD in the device's timezone

function emptyForm(): FormState {
  return {
    played_on: today(),
    label: "",
    format: "singles",
    opponent_name: "",
    partner_name: "",
    venue: "",
    notes: "",
    sets: [0, 1, 2].map(() => ({ mine: "", theirs: "" })),
  }
}

function fromMatch(m: PersonalMatch): FormState {
  const { games, ...rest } = m
  return { ...rest, sets: games.map((g) => ({ mine: String(g.my_points), theirs: String(g.opponent_points) })) }
}

export function MatchFormPage() {
  const { id } = useParams()
  const existing = useQuery({ queryKey: matchKeys.detail(id ?? ""), queryFn: () => getMatch(id!), enabled: !!id })

  if (id && existing.isPending) return <p className="text-muted-foreground">Loading…</p>
  if (id && existing.isError) return <FormAlert>{errorMessage(existing.error, "We couldn't load that match.")}</FormAlert>
  return <MatchForm key={id ?? "new"} match={existing.data} />
}

function MatchForm({ match }: { match?: PersonalMatch }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const draft = useDraft(`match:${match?.id ?? "new"}`)
  const [form, setForm] = useDraftState<FormState>(draft, "form", () => (match ? fromMatch(match) : emptyForm()))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const labels = useQuery({ queryKey: matchKeys.labels, queryFn: getMatchLabels })

  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }))
  const setSet = (index: number, patch: Partial<SetRow>) =>
    set({ sets: form.sets.map((row, i) => (i === index ? { ...row, ...patch } : row)) })

  const save = useMutation({
    mutationFn: async (input: PersonalMatchInput) => (match ? { kept: false as const, data: await updateMatch(match.id, input) } : createMatchOrKeep(input)),
    onSuccess: (sent) => {
      draft.clear()
      // No connection: kept on this device, and the banner says it is waiting to be sent (REQ-035).
      if (sent.kept) return navigate("/matches", { replace: true })
      const saved = sent.data
      queryClient.invalidateQueries({ queryKey: matchKeys.all })
      queryClient.setQueryData(matchKeys.detail(saved.id), saved)
      navigate(`/matches/${saved.id}`, { replace: true })
    },
    onError: (error) => {
      if (error instanceof ApiError) setErrors(error.fieldErrors())
    },
  })

  // Rows left completely blank are ignored, so players can leave unused set rows empty.
  const filled = form.sets.filter((s) => s.mine !== "" || s.theirs !== "")
  const complete = filled.filter((s) => s.mine !== "" && s.theirs !== "" && s.mine !== s.theirs)
  const won = complete.filter((s) => Number(s.mine) > Number(s.theirs)).length
  const lost = complete.length - won

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const next: Record<string, string> = {}
    if (!form.label.trim()) next.label = "Add a label, such as Friendly or Tournament."
    if (!form.played_on) next.played_on = "Choose the date you played."
    if (filled.length === 0) next.games = "Add the score of at least one set."
    else if (filled.some((s) => s.mine === "" || s.theirs === "")) next.games = "Fill in both scores for each set."
    else if (filled.some((s) => s.mine === s.theirs)) next.games = "A set needs a winner; the scores can't be level."
    setErrors(next)
    if (Object.keys(next).length) return

    const { sets: _sets, ...rest } = form
    save.mutate({
      ...rest,
      label: form.label.trim(),
      partner_name: form.format === "doubles" ? form.partner_name.trim() : "",
      games: filled.map((s) => ({ my_points: Number(s.mine), opponent_points: Number(s.theirs) })),
    })
  }

  const myLabel = form.format === "doubles" ? "You & partner" : "You"

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <Link
        to={match ? `/matches/${match.id}` : "/matches"}
        className="-ml-1 flex w-fit items-center gap-1 py-2 font-semibold text-brand-blue"
      >
        <ArrowLeft aria-hidden className="size-5" /> {match ? "Back to match" : "My match log"}
      </Link>
      <h1 className="text-[32px] leading-9 font-bold">{match ? "Edit match" : "Record a match"}</h1>

      {!match && (
        <p className="flex gap-2 rounded-xl bg-surface-selected p-3 text-sm">
          <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-brand-blue" />
          <span>
            For matches you play elsewhere: friendlies, practice, or tournaments outside Coast TT. Official
            Coast TT matches are already recorded; you'll add your private notes to those on the match itself.
          </span>
        </p>
      )}

      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-6">
        {save.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}

        <div className="flex flex-col gap-2">
          <Field
            label="Label"
            value={form.label}
            maxLength={40}
            onChange={(e) => set({ label: e.target.value })}
            error={errors.label}
            hint="Any name you like. Use the same label to group matches."
          />
          {labels.data && (
            <div role="group" aria-label="Label suggestions" className="flex flex-wrap gap-2">
              {labels.data.labels.slice(0, 8).map((l) => (
                <button
                  key={l}
                  type="button"
                  onClick={() => set({ label: l })}
                  className={cn(
                    "h-10 rounded-full border px-3 text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    form.label.trim().toLowerCase() === l.toLowerCase()
                      ? "border-brand-blue bg-surface-selected text-brand-blue"
                      : "bg-card"
                  )}
                >
                  {l}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="grid gap-6 sm:grid-cols-2">
          <Field
            label="Date played"
            type="date"
            max={today()}
            value={form.played_on}
            onChange={(e) => set({ played_on: e.target.value })}
            error={errors.played_on}
          />
          <Field
            label="Venue"
            optional
            value={form.venue}
            maxLength={120}
            onChange={(e) => set({ venue: e.target.value })}
          />
        </div>

        <ChoiceGroup legend="Format" options={FORMATS} value={form.format} onChange={(format) => set({ format })} />

        <div className="grid gap-6 sm:grid-cols-2">
          {form.format === "doubles" && (
            <Field
              label="Your partner"
              optional
              value={form.partner_name}
              maxLength={80}
              onChange={(e) => set({ partner_name: e.target.value })}
            />
          )}
          <Field
            label={form.format === "doubles" ? "Opponents" : "Opponent"}
            optional
            value={form.opponent_name}
            maxLength={120}
            onChange={(e) => set({ opponent_name: e.target.value })}
            hint="Only you see this name. It isn't linked to anyone's profile."
            error={errors.opponent_name}
          />
        </div>

        <fieldset className="flex flex-col gap-3">
          <legend className="mb-1 font-semibold">Sets</legend>
          <div className="grid grid-cols-[3.5rem_1fr_1fr_3rem] items-center gap-2 text-sm font-semibold text-muted-foreground">
            <span />
            <span className="truncate">{myLabel}</span>
            <span className="truncate text-right">{form.opponent_name.trim() || "Opponent"}</span>
            <span />
          </div>
          {form.sets.map((row, i) => (
            <div key={i} className="grid grid-cols-[3.5rem_1fr_1fr_3rem] items-center gap-2">
              <Label className="text-sm text-muted-foreground" htmlFor={`set-${i}-mine`}>
                Set {i + 1}
              </Label>
              <ScoreInput
                id={`set-${i}-mine`}
                aria-label={`Set ${i + 1}, your points`}
                value={row.mine}
                onChange={(mine) => setSet(i, { mine })}
              />
              <ScoreInput
                aria-label={`Set ${i + 1}, opponent's points`}
                value={row.theirs}
                onChange={(theirs) => setSet(i, { theirs })}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={form.sets.length === 1}
                onClick={() => set({ sets: form.sets.filter((_, j) => j !== i) })}
                aria-label={`Remove set ${i + 1}`}
              >
                <X aria-hidden className="size-5" />
              </Button>
            </div>
          ))}
          {errors.games && <FieldError>{errors.games}</FieldError>}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button
              type="button"
              variant="outline"
              disabled={form.sets.length >= MAX_SETS}
              onClick={() => set({ sets: [...form.sets, { mine: "", theirs: "" }] })}
            >
              <Plus aria-hidden className="size-5" /> Add set
            </Button>
            {complete.length > 0 && (
              <p aria-live="polite" className="font-semibold tabular">
                {won > lost ? "You won" : won < lost ? "You lost" : "Level"} {won}–{lost}
              </p>
            )}
          </div>
        </fieldset>

        <div className="flex flex-col gap-2">
          <Label htmlFor="notes" className="text-base font-semibold">
            Notes <span className="font-normal text-muted-foreground">(optional)</span>
          </Label>
          <textarea
            id="notes"
            rows={5}
            maxLength={5000}
            value={form.notes}
            onChange={(e) => set({ notes: e.target.value })}
            placeholder="What worked, what didn't, what to practise next"
            className="w-full rounded-lg border border-input bg-card px-3 py-2 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </div>

        <DraftBar draft={draft} />

        <Button type="submit" size="lg" disabled={save.isPending}>
          {save.isPending ? "Saving…" : match ? "Save changes" : "Save match"}
        </Button>
      </form>
    </div>
  )
}

function ScoreInput({
  value,
  onChange,
  ...props
}: { value: string; onChange: (value: string) => void } & Omit<ComponentProps<typeof Input>, "value" | "onChange">) {
  return (
    <Input
      {...props}
      inputMode="numeric"
      pattern="[0-9]*"
      maxLength={2}
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))}
      className="text-center font-display text-2xl font-bold tabular"
    />
  )
}
