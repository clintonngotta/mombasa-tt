import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type FormEvent } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, ClipboardList } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { TextAreaField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { formatInstant } from "@/lib/dates"
import { feedbackKeys, getMyForm, listAskedOfMe, saveMyAnswers, type Answers, type AnswerValue, type FeedbackQuestion, type MyFeedbackForm } from "@/lib/feedback"
import { cn } from "@/lib/utils"

const ZONE = "Africa/Nairobi"
const CHIP = "flex min-h-12 cursor-pointer items-center gap-2 rounded-lg border bg-card px-3 has-checked:border-brand-blue has-checked:bg-surface-selected has-focus-visible:ring-3 has-focus-visible:ring-ring/50"

/** Forms you were asked to answer and haven't yet, on Home. Hidden when there are none. */
export function FeedbackAsked() {
  // Someone else sends these, so ask the server each time.
  const asked = useQuery({ queryKey: feedbackKeys.asked, queryFn: listAskedOfMe, staleTime: 0 })
  const waiting = (asked.data ?? []).filter((form) => !form.answered)
  if (waiting.length === 0) return null
  return (
    <section aria-labelledby="feedback-asked-heading" className="flex flex-col gap-3">
      <h2 id="feedback-asked-heading" className="text-xl font-bold">
        Tell the organizers how it went
      </h2>
      <ul className="flex flex-col gap-2">
        {waiting.map((form) => (
          <li key={form.id}>
            <Link to={`/feedback/${form.id}`} className={cn(ROW, "flex-nowrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
              <ClipboardList aria-hidden className="size-5 shrink-0 text-brand-blue" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-semibold">{form.title}</span>
                <span className="text-sm text-muted-foreground">
                  {form.tournament?.name ?? form.organization.name}
                  {form.closes_at && ` · until ${formatInstant(form.closes_at, ZONE)}`}
                </span>
              </span>
              <ChevronRight aria-hidden className="size-5 shrink-0 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** A feedback form for someone asked to answer it (REQ-055): once each, changed until it closes. */
export function FeedbackAnswerPage() {
  const { formId = "" } = useParams()
  const form = useQuery({ queryKey: feedbackKeys.mine(formId), queryFn: () => getMyForm(formId), staleTime: 0, retry: false })
  const f = form.data
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/home">Home</BackLink>
      {form.isPending && <p className="text-muted-foreground">Loading…</p>}
      {form.isError && <FormAlert>{errorMessage(form.error, "This form isn't one you were asked to answer.")}</FormAlert>}
      {f && <AnswerForm key={f.id} form={f} />}
    </div>
  )
}

function AnswerForm({ form }: { form: MyFeedbackForm }) {
  const queryClient = useQueryClient()
  const draft = useDraft(`feedback-answers:${form.id}`)
  const [answers, setAnswers] = useDraftState<Answers>(draft, "answers", () => ({ ...(form.my_answers as Answers) }))
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () => saveMyAnswers(form.id, answers),
    onSuccess: (fresh) => {
      draft.clear()
      queryClient.setQueryData(feedbackKeys.mine(form.id), fresh)
      void queryClient.invalidateQueries({ queryKey: feedbackKeys.asked })
      setSaved(true)
    },
  })
  // The API answers with one message per question that is wrong.
  const perQuestion: Record<string, string | undefined> = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const set = (id: string, value: AnswerValue | undefined) => {
    setSaved(false)
    if (save.isError) save.reset() // the messages were about the answers as they were
    setAnswers((current) => {
      const next = { ...current }
      if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) delete next[id]
      else next[id] = value
      return next
    })
  }

  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-6"
    >
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">{form.title}</h1>
        <p className="text-muted-foreground">
          {form.tournament?.name ?? form.organization.name} · {form.organization.name}
        </p>
        {form.intro && <p className="whitespace-pre-wrap">{form.intro}</p>}
        <p className="text-sm text-muted-foreground">
          {form.anonymous ? "Anonymous: the organizers see your answers, never your name." : "The organizers see your answers with your name."}
          {form.closes_at && form.open && ` You can change them until ${formatInstant(form.closes_at, ZONE)}.`}
        </p>
      </div>
      {!form.open && <FormAlert>{form.answered ? "This form has closed. These are the answers you gave." : "This form isn't open for answers."}</FormAlert>}

      {form.sections.map((section) => (
        <section key={section.id} className="flex flex-col gap-4">
          {section.title && <h2 className="text-xl font-bold">{section.title}</h2>}
          {section.description && <p className="text-muted-foreground">{section.description}</p>}
          {section.questions.map((question) => (
            <Question key={question.id} question={question} value={answers[question.id]} disabled={!form.open} error={perQuestion[question.id]} onChange={(value) => set(question.id, value)} />
          ))}
        </section>
      ))}

      {save.isError && <FormAlert>{Object.keys(perQuestion).length ? "Some answers need another look." : errorMessage(save.error, "We couldn't save your answers.")}</FormAlert>}
      {form.open && <DraftBar draft={draft} />}
      {form.open && (
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : form.answered ? "Save my changes" : "Send my answers"}
          </Button>
          {saved && (
            <span role="status" className="font-semibold">
              Thank you. Your answers are saved.
            </span>
          )}
        </div>
      )}
    </form>
  )
}

function Question({ question, value, disabled, error, onChange }: { question: FeedbackQuestion; value: AnswerValue | undefined; disabled: boolean; error?: string; onChange: (value: AnswerValue | undefined) => void }) {
  const label = question.text
  const hint = question.help || undefined
  const optional = !question.required
  if (question.kind === "short_text") return <Field label={label} hint={hint} optional={optional} maxLength={300} disabled={disabled} error={error} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />
  if (question.kind === "long_text") return <TextAreaField label={label} hint={hint} optional={optional} rows={4} maxLength={3000} disabled={disabled} error={error} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />
  if (question.kind === "number")
    return <Field label={label} hint={hint} optional={optional} type="number" inputMode="decimal" className="max-w-xs" disabled={disabled} error={error} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />

  const options: { key: string; label: string; value: AnswerValue }[] =
    question.kind === "rating"
      ? [1, 2, 3, 4, 5].map((n) => ({ key: String(n), label: String(n), value: n }))
      : question.kind === "yes_no"
        ? [
            { key: "yes", label: "Yes", value: true },
            { key: "no", label: "No", value: false },
          ]
        : question.choices.map((choice) => ({ key: choice.id, label: choice.text, value: choice.id }))
  const many = question.kind === "multiple"
  const picked = many ? ((value as string[] | undefined) ?? []) : []
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 font-semibold">
        {label} {optional && <span className="font-normal text-muted-foreground">(optional)</span>}
      </legend>
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
      {question.kind === "rating" && <p className="text-sm text-muted-foreground">1 is poor, 5 is excellent.</p>}
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const checked = many ? picked.includes(option.value as string) : value === option.value
          return (
            <label key={option.key} className={CHIP}>
              <input
                type={many ? "checkbox" : "radio"}
                name={question.id}
                className="size-5 accent-brand-blue"
                checked={checked}
                disabled={disabled}
                onChange={() => onChange(many ? (checked ? picked.filter((id) => id !== option.value) : [...picked, option.value as string]) : option.value)}
              />
              {option.label}
            </label>
          )
        })}
      </div>
      {!many && optional && value !== undefined && !disabled && (
        <Button type="button" variant="ghost" size="sm" className="self-start" onClick={() => onChange(undefined)}>
          Clear my answer
        </Button>
      )}
      {error && <p className="text-sm font-semibold text-destructive">{error}</p>}
    </fieldset>
  )
}
