import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, ChevronRight, ClipboardList, Download, Plus, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { formatInstant, fromZonedInput, toZonedInput } from "@/lib/dates"
import {
  createForm,
  deleteForm,
  exportUrl,
  feedbackKeys,
  formState,
  getForm,
  getTotals,
  KIND_LABEL,
  listTemplates,
  listTournamentForms,
  MAX_CHOICES,
  MAX_QUESTIONS,
  moveClosing,
  sendForm,
  updateForm,
  type FeedbackForm,
  type FeedbackTotals,
  type QuestionKind,
} from "@/lib/feedback"
import { getTournament, tournamentKeys } from "@/lib/tournaments"
import { cn } from "@/lib/utils"

const ZONE = "Africa/Nairobi"
const FOCUS = "outline-none focus-visible:ring-3 focus-visible:ring-ring/50"

/** A tournament's feedback forms, for the host's competition staff: make one (from scratch or a template),
 * send it to the attendees and open its results. Templates are kept here too. */
export function TournamentFeedbackPage() {
  const { id = "" } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const t = tournament.data
  const orgId = t?.organization.id ?? ""
  const forms = useQuery({ queryKey: feedbackKeys.forTournament(orgId, id), queryFn: () => listTournamentForms(orgId, id), enabled: !!orgId, staleTime: 0, retry: false })
  const templates = useQuery({ queryKey: feedbackKeys.templates(orgId), queryFn: () => listTemplates(orgId), enabled: !!orgId, retry: false })
  const [title, setTitle] = useState("")
  const [from, setFrom] = useState("")
  const make = useMutation({
    mutationFn: (template: boolean) =>
      createForm(orgId, { title: title.trim(), ...(template ? { is_template: true } : { tournament_id: id }), ...(from ? { copy_from: from } : {}) }),
    onSuccess: async (form) => {
      await queryClient.invalidateQueries({ queryKey: feedbackKeys.all })
      navigate(`/feedback/${orgId}/${form.id}/edit`)
    },
  })
  const remove = useMutation({ mutationFn: (formId: string) => deleteForm(orgId, formId), onSuccess: () => queryClient.invalidateQueries({ queryKey: feedbackKeys.all }) })

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Feedback forms</h1>
        <p className="text-muted-foreground">Ask the people who were there how it went. They answer in the app; you see the totals.</p>
      </div>
      {forms.isError && <FormAlert>{errorMessage(forms.error, "Feedback forms are for the organizers.")}</FormAlert>}
      {forms.isSuccess && (
        <>
          <section aria-labelledby="forms-heading" className="flex flex-col gap-3">
            <h2 id="forms-heading" className="text-xl font-bold">
              This tournament's forms
            </h2>
            {forms.data.length === 0 && <p className="text-muted-foreground">None yet.</p>}
            <ul className="flex flex-col gap-2">
              {forms.data.map((form) => (
                <li key={form.id}>
                  <Link to={`/feedback/${orgId}/${form.id}/${form.status === "draft" ? "edit" : "results"}`} className={cn(ROW, FOCUS)}>
                    <ClipboardList aria-hidden className="size-5 text-brand-blue" />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate font-semibold">{form.title}</span>
                      <span className="text-sm text-muted-foreground">
                        {formState(form)}
                        {form.status === "sent" && ` · ${form.responses} of ${form.recipients} answered`}
                        {form.anonymous && " · anonymous"}
                      </span>
                    </span>
                    <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <form
            onSubmit={(e: FormEvent) => {
              e.preventDefault()
              make.mutate(false)
            }}
            className="flex flex-col gap-3 rounded-xl border bg-card p-4"
          >
            <h2 className="text-xl font-bold">New form</h2>
            {make.isError && <FormAlert>{errorMessage(make.error, "We couldn't make the form.")}</FormAlert>}
            <Field label="Title" maxLength={120} placeholder="How was the Coast Open?" value={title} onChange={(e) => setTitle(e.target.value)} />
            {(templates.data?.length ?? 0) > 0 && (
              <SelectField label="Start from" options={[{ value: "", label: "A blank form" }, ...templates.data!.map((template) => ({ value: template.id, label: `Template: ${template.title}` }))]} value={from} onChange={setFrom} />
            )}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={!title.trim() || make.isPending}>
                <Plus aria-hidden className="size-4" /> Make the form
              </Button>
              <Button type="button" variant="outline" disabled={!title.trim() || make.isPending} onClick={() => make.mutate(true)}>
                Make a template instead
              </Button>
            </div>
          </form>

          {(templates.data?.length ?? 0) > 0 && (
            <section aria-labelledby="templates-heading" className="flex flex-col gap-3">
              <h2 id="templates-heading" className="text-xl font-bold">
                Templates
              </h2>
              <p className="text-sm text-muted-foreground">Kept for reuse at every tournament. A template is never sent; forms are made from it.</p>
              {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
              <ul className="flex flex-col gap-2">
                {templates.data!.map((template) => (
                  <li key={template.id} className="flex items-center gap-2">
                    <Link to={`/feedback/${orgId}/${template.id}/edit`} className={cn(ROW, FOCUS, "min-w-0 flex-1")}>
                      <span className="truncate font-semibold">{template.title}</span>
                    </Link>
                    <Button variant="outline" size="icon" aria-label={`Remove template ${template.title}`} disabled={remove.isPending} onClick={() => remove.mutate(template.id)}>
                      <Trash2 aria-hidden className="size-5" />
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}

type ChoiceDraft = { id?: string; text: string }
type QuestionDraft = { id?: string; kind: QuestionKind; text: string; help: string; required: boolean; choices: ChoiceDraft[] }
type SectionDraft = { id?: string; title: string; description: string; questions: QuestionDraft[] }

const blankQuestion = (): QuestionDraft => ({ kind: "rating", text: "", help: "", required: false, choices: [] })
const hasChoices = (kind: QuestionKind) => kind === "single" || kind === "multiple"

function move<T>(list: T[], index: number, by: number): T[] {
  const to = index + by
  if (to < 0 || to >= list.length) return list
  const copy = [...list]
  ;[copy[index], copy[to]] = [copy[to], copy[index]]
  return copy
}

/** The form builder: sections and questions in order, who is asked, and sending. A sent form can't change. */
export function FeedbackBuilderPage() {
  const { orgId = "", formId = "" } = useParams()
  const form = useQuery({ queryKey: feedbackKeys.form(orgId, formId), queryFn: () => getForm(orgId, formId), staleTime: 0, retry: false })
  const f = form.data
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={f?.tournament ? `/tournaments/${f.tournament.id}/feedback` : "/club/tournaments"}>{f?.tournament ? "Feedback forms" : "Tournaments"}</BackLink>
      {form.isPending && <p className="text-muted-foreground">Loading…</p>}
      {form.isError && <FormAlert>{errorMessage(form.error, "Feedback forms are for the organizers.")}</FormAlert>}
      {f && f.status !== "draft" && (
        <FormAlert>
          This form was sent and can't change. <Link to={`/feedback/${orgId}/${f.id}/results`}>See its results.</Link>
        </FormAlert>
      )}
      {f && f.status === "draft" && <Builder key={f.id} orgId={orgId} form={f} />}
    </div>
  )
}

function Builder({ orgId, form }: { orgId: string; form: FeedbackForm }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const draft = useDraft(`feedback-form:${form.id}`)
  const [title, setTitle] = useDraftState(draft, "title", form.title)
  const [intro, setIntro] = useDraftState(draft, "intro", form.intro)
  const [anonymous, setAnonymous] = useDraftState(draft, "anonymous", form.anonymous)
  const [toEntrants, setToEntrants] = useDraftState(draft, "toEntrants", form.to_entrants)
  const [toUmpires, setToUmpires] = useDraftState(draft, "toUmpires", form.to_umpires)
  const [toStaff, setToStaff] = useDraftState(draft, "toStaff", form.to_staff)
  const [sections, setSections] = useDraftState<SectionDraft[]>(draft, "sections", () => (form.sections.length ? form.sections.map((s) => ({ ...s, questions: s.questions.map((q) => ({ ...q })) })) : [{ title: "", description: "", questions: [blankQuestion()] }]))
  const [closes, setCloses] = useState("")
  const [saved, setSaved] = useState(false)
  const count = sections.reduce((sum, section) => sum + section.questions.length, 0)

  const body = () => ({
    title: title.trim(),
    intro: intro.trim(),
    anonymous,
    to_entrants: toEntrants,
    to_umpires: toUmpires,
    to_staff: toStaff,
    sections: sections
      .map((section) => ({
        ...section,
        title: section.title.trim(),
        description: section.description.trim(),
        questions: section.questions
          .filter((q) => q.text.trim())
          .map((q) => ({ ...q, text: q.text.trim(), help: q.help.trim(), choices: hasChoices(q.kind) ? q.choices.filter((c) => c.text.trim()).map((c) => ({ ...c, text: c.text.trim() })) : [] })),
      }))
      .filter((section) => section.questions.length > 0) as FeedbackForm["sections"],
  })
  const settle = (fresh: FeedbackForm) => {
    queryClient.setQueryData(feedbackKeys.form(orgId, form.id), fresh)
    void queryClient.invalidateQueries({ queryKey: feedbackKeys.all, refetchType: "none" })
  }
  const save = useMutation({
    mutationFn: () => updateForm(orgId, form.id, body()),
    onSuccess: (fresh) => {
      draft.clear()
      settle(fresh)
      setSaved(true)
    },
  })
  const send = useMutation({
    mutationFn: async () => {
      await updateForm(orgId, form.id, body())
      return sendForm(orgId, form.id, fromZonedInput(closes, ZONE) ?? "")
    },
    onSuccess: (fresh) => {
      settle(fresh)
      navigate(`/feedback/${orgId}/${form.id}/results`)
    },
  })
  const asTemplate = useMutation({
    mutationFn: async () => {
      await updateForm(orgId, form.id, body())
      return createForm(orgId, { title: title.trim(), is_template: true, copy_from: form.id })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: feedbackKeys.templates(orgId) }),
  })
  const failed = save.error ?? send.error ?? asTemplate.error
  const fields: Record<string, string | undefined> = failed instanceof ApiError ? failed.fieldErrors() : {}
  const setSection = (index: number, change: Partial<SectionDraft>) => {
    setSaved(false)
    setSections(sections.map((s, i) => (i === index ? { ...s, ...change } : s)))
  }
  const setQuestion = (si: number, qi: number, change: Partial<QuestionDraft>) => setSection(si, { questions: sections[si].questions.map((q, i) => (i === qi ? { ...q, ...change } : q)) })

  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-6"
    >
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">{form.is_template ? "Template" : "Build the form"}</h1>
        <p className="text-muted-foreground">{form.is_template ? "Kept for reuse. Forms made from it start with these questions." : `For ${form.tournament?.name}. It's a draft until you send it.`}</p>
      </div>
      <Field label="Title" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} error={fields.title} />
      <TextAreaField label="Introduction" optional rows={2} maxLength={1000} value={intro} onChange={(e) => setIntro(e.target.value)} hint="Shown above the questions." />

      {sections.map((section, si) => (
        <fieldset key={section.id ?? `new-${si}`} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
          <legend className="px-1 font-semibold">Section {si + 1}</legend>
          <div className="flex items-end gap-2">
            <Field label="Section title" optional className="flex-1" maxLength={120} value={section.title} onChange={(e) => setSection(si, { title: e.target.value })} />
            <Button type="button" variant="outline" size="icon" aria-label={`Move section ${si + 1} up`} disabled={si === 0} onClick={() => setSections(move(sections, si, -1))}>
              <ArrowUp aria-hidden className="size-5" />
            </Button>
            <Button type="button" variant="outline" size="icon" aria-label={`Move section ${si + 1} down`} disabled={si === sections.length - 1} onClick={() => setSections(move(sections, si, 1))}>
              <ArrowDown aria-hidden className="size-5" />
            </Button>
            <Button type="button" variant="outline" size="icon" aria-label={`Remove section ${si + 1}`} disabled={sections.length === 1} onClick={() => setSections(sections.filter((_, i) => i !== si))}>
              <Trash2 aria-hidden className="size-5" />
            </Button>
          </div>
          {section.questions.map((question, qi) => {
            const name = `question ${qi + 1} of section ${si + 1}`
            return (
              <div key={question.id ?? `new-${qi}`} className="flex flex-col gap-3 rounded-lg border p-3">
                <Field label={`Question ${qi + 1}`} maxLength={300} value={question.text} onChange={(e) => setQuestion(si, qi, { text: e.target.value })} />
                <div className="grid gap-3 sm:grid-cols-2">
                  <SelectField
                    label="Answer"
                    options={(Object.keys(KIND_LABEL) as QuestionKind[]).map((kind) => ({ value: kind, label: KIND_LABEL[kind] }))}
                    value={question.kind}
                    onChange={(kind) => setQuestion(si, qi, { kind: kind as QuestionKind, choices: hasChoices(kind as QuestionKind) && question.choices.length < 2 ? [{ text: "" }, { text: "" }] : question.choices })}
                  />
                  <Field label="Help text" optional maxLength={300} value={question.help} onChange={(e) => setQuestion(si, qi, { help: e.target.value })} />
                </div>
                {hasChoices(question.kind) && (
                  <div className="flex flex-col gap-2">
                    {question.choices.map((choice, ci) => (
                      <div key={choice.id ?? `new-${ci}`} className="flex items-end gap-2">
                        <Field label={`Choice ${ci + 1}`} className="flex-1" maxLength={120} value={choice.text} onChange={(e) => setQuestion(si, qi, { choices: question.choices.map((c, i) => (i === ci ? { ...c, text: e.target.value } : c)) })} />
                        <Button type="button" variant="outline" size="icon" aria-label={`Remove choice ${ci + 1} of ${name}`} disabled={question.choices.length <= 2} onClick={() => setQuestion(si, qi, { choices: question.choices.filter((_, i) => i !== ci) })}>
                          <Trash2 aria-hidden className="size-5" />
                        </Button>
                      </div>
                    ))}
                    <Button type="button" variant="ghost" className="self-start" disabled={question.choices.length >= MAX_CHOICES} onClick={() => setQuestion(si, qi, { choices: [...question.choices, { text: "" }] })}>
                      <Plus aria-hidden className="size-4" /> Add a choice
                    </Button>
                  </div>
                )}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label className="flex min-h-12 items-center gap-2">
                    <input type="checkbox" className="size-5 accent-brand-blue" checked={question.required} onChange={(e) => setQuestion(si, qi, { required: e.target.checked })} />
                    Must be answered
                  </label>
                  <div className="flex gap-1">
                    <Button type="button" variant="outline" size="icon" aria-label={`Move ${name} up`} disabled={qi === 0} onClick={() => setSection(si, { questions: move(section.questions, qi, -1) })}>
                      <ArrowUp aria-hidden className="size-5" />
                    </Button>
                    <Button type="button" variant="outline" size="icon" aria-label={`Move ${name} down`} disabled={qi === section.questions.length - 1} onClick={() => setSection(si, { questions: move(section.questions, qi, 1) })}>
                      <ArrowDown aria-hidden className="size-5" />
                    </Button>
                    <Button type="button" variant="outline" size="icon" aria-label={`Remove ${name}`} onClick={() => setSection(si, { questions: section.questions.filter((_, i) => i !== qi) })}>
                      <Trash2 aria-hidden className="size-5" />
                    </Button>
                  </div>
                </div>
              </div>
            )
          })}
          <Button type="button" variant="ghost" className="self-start" disabled={count >= MAX_QUESTIONS} onClick={() => setSection(si, { questions: [...section.questions, blankQuestion()] })}>
            <Plus aria-hidden className="size-4" /> Add a question
          </Button>
        </fieldset>
      ))}
      <Button type="button" variant="outline" className="self-start" disabled={sections.length >= 10} onClick={() => setSections([...sections, { title: "", description: "", questions: [blankQuestion()] }])}>
        <Plus aria-hidden className="size-4" /> Add a section
      </Button>

      {!form.is_template && (
        <fieldset className="flex flex-col gap-2 rounded-xl border bg-card p-4">
          <legend className="px-1 font-semibold">Who is asked</legend>
          {(
            [
              ["Players with an accepted entry", toEntrants, setToEntrants],
              ["The tournament's umpires", toUmpires, setToUmpires],
              ["Your competition staff", toStaff, setToStaff],
            ] as const
          ).map(([label, value, set]) => (
            <label key={label} className="flex min-h-12 items-center gap-3">
              <input type="checkbox" className="size-5 accent-brand-blue" checked={value} onChange={(e) => set(e.target.checked)} />
              {label}
            </label>
          ))}
          <label className="flex min-h-12 items-center gap-3 border-t pt-2">
            <input type="checkbox" className="size-5 accent-brand-blue" checked={anonymous} onChange={(e) => setAnonymous(e.target.checked)} />
            <span>
              <span className="font-semibold">Anonymous</span>
              <span className="text-muted-foreground">: you see the answers, never who gave them.</span>
            </span>
          </label>
        </fieldset>
      )}

      {/* Beside the buttons that caused it, not at the top of a long form. */}
      {(save.error ?? asTemplate.error) && <FormAlert>{fields.sections ?? errorMessage(save.error ?? asTemplate.error, "We couldn't save the form.")}</FormAlert>}
      <DraftBar draft={draft} label="Finish later" />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!title.trim() || save.isPending}>
          {save.isPending ? "Saving…" : "Save draft"}
        </Button>
        {!form.is_template && (
          <Button type="button" variant="outline" disabled={!title.trim() || asTemplate.isPending} onClick={() => asTemplate.mutate()}>
            {asTemplate.isSuccess ? "Saved as a template" : "Save as a template too"}
          </Button>
        )}
        {saved && (
          <span role="status" className="text-sm font-semibold text-muted-foreground">
            Saved
          </span>
        )}
      </div>

      {!form.is_template && (
        <section aria-labelledby="send-heading" className="flex flex-col gap-3 border-t pt-6">
          <h2 id="send-heading" className="text-xl font-bold">
            Send it
          </h2>
          <p className="text-muted-foreground">Sending fixes the questions and who is asked. They are told in the app and can answer until it closes.</p>
          <Field label="Closes" type="datetime-local" className="max-w-xs" value={closes} onChange={(e) => setCloses(e.target.value)} hint={`In ${ZONE}. At most 180 days from now.`} error={send.isError ? fields.closes_at : undefined} />
          {send.isError && !fields.closes_at && <FormAlert>{fields.sections ?? errorMessage(send.error, "We couldn't send the form.")}</FormAlert>}
          <Button type="button" className="self-start" disabled={!closes || !title.trim() || send.isPending} onClick={() => send.mutate()}>
            {send.isPending ? "Sending…" : "Send the form"}
          </Button>
        </section>
      )}
    </form>
  )
}

/** A sent form's totals: how many answered and, per question, the average, the counts or the text. */
export function FeedbackResultsPage() {
  const { orgId = "", formId = "" } = useParams()
  const queryClient = useQueryClient()
  // People answer while staff watch, so read fresh each time.
  const form = useQuery({ queryKey: feedbackKeys.form(orgId, formId), queryFn: () => getForm(orgId, formId), staleTime: 0, retry: false })
  const totals = useQuery({ queryKey: feedbackKeys.totals(orgId, formId), queryFn: () => getTotals(orgId, formId), staleTime: 0, retry: false })
  const [closes, setCloses] = useState("")
  const closing = useMutation({
    mutationFn: (at: string) => moveClosing(orgId, formId, at),
    onSuccess: (fresh) => {
      queryClient.setQueryData(feedbackKeys.form(orgId, formId), fresh)
      setCloses("")
    },
  })
  const f = form.data
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={f?.tournament ? `/tournaments/${f.tournament.id}/feedback` : "/club/tournaments"}>Feedback forms</BackLink>
      {form.isError && <FormAlert>{errorMessage(form.error, "Feedback forms are for the organizers.")}</FormAlert>}
      {f && (
        <>
          <div className="flex flex-col gap-1">
            <h1 className="text-[32px] leading-9 font-bold">{f.title}</h1>
            <p className="text-muted-foreground">
              {f.tournament?.name} · {formState(f)}
              {f.closes_at && ` · ${f.open ? "closes" : "closed"} ${formatInstant(f.closes_at, ZONE)}`}
              {f.anonymous && " · anonymous"}
            </p>
          </div>
          {f.status === "sent" && (
            <div className="flex flex-col gap-3 rounded-xl border bg-card p-4">
              {closing.isError && <FormAlert>{errorMessage(closing.error)}</FormAlert>}
              <div className="flex flex-wrap items-end gap-2">
                <Field label={f.open ? "Keep it open until" : "Open it again until"} type="datetime-local" className="max-w-xs" value={closes || toZonedInput(f.open ? f.closes_at : null, ZONE)} onChange={(e) => setCloses(e.target.value)} />
                <Button variant="outline" disabled={!closes || closing.isPending} onClick={() => closing.mutate(fromZonedInput(closes, ZONE) ?? "")}>
                  Change closing time
                </Button>
                {f.open && (
                  <Button variant="outline" disabled={closing.isPending} onClick={() => closing.mutate(new Date().toISOString())}>
                    Close it now
                  </Button>
                )}
              </div>
              <a href={exportUrl(orgId, formId)} className={cn("flex items-center gap-2 self-start font-semibold text-brand-blue underline-offset-4 hover:underline", FOCUS)}>
                <Download aria-hidden className="size-4" /> Download the answers (CSV)
              </a>
              <p className="text-sm text-muted-foreground">{f.anonymous ? "The file has the answers only: no names and no times." : "The file names who answered and when."}</p>
            </div>
          )}
          {totals.data && <Totals totals={totals.data} />}
        </>
      )}
    </div>
  )
}

function Bar({ label, count, of }: { label: string; count: number; of: number }) {
  const share = of ? Math.round((count / of) * 100) : 0
  return (
    <li className="flex flex-col gap-1">
      <span className="flex justify-between gap-2 text-sm">
        <span className="min-w-0 break-words">{label}</span>
        <span className="shrink-0 font-semibold tabular-nums">
          {count} ({share}%)
        </span>
      </span>
      <span aria-hidden className="h-2 rounded-full bg-surface-selected">
        <span className="block h-2 rounded-full bg-brand-blue" style={{ width: `${share}%` }} />
      </span>
    </li>
  )
}

function Totals({ totals }: { totals: FeedbackTotals }) {
  return (
    <section aria-labelledby="totals-heading" className="flex flex-col gap-4">
      <h2 id="totals-heading" className="text-xl font-bold">
        {totals.responses} of {totals.recipients} answered
      </h2>
      {totals.questions.map((question) => (
        <article key={question.id} className="flex flex-col gap-2 rounded-xl border bg-card p-4">
          <h3 className="font-semibold">{question.text}</h3>
          <p className="text-sm text-muted-foreground">
            {question.section && `${question.section} · `}
            {question.answered} {question.answered === 1 ? "answer" : "answers"}
            {question.average != null && ` · average ${question.average}`}
          </p>
          {question.counts.length > 0 && (
            <ul className="flex flex-col gap-2">
              {question.counts.map((row) => (
                <Bar key={row.label} label={question.kind === "rating" ? `${row.label} of 5` : row.label} count={row.count} of={question.answered} />
              ))}
            </ul>
          )}
          {question.texts.length > 0 && (
            <ul className="flex flex-col gap-1">
              {question.texts.map((text, i) => (
                <li key={i} className="rounded-lg border px-3 py-2 whitespace-pre-wrap">
                  {text}
                </li>
              ))}
            </ul>
          )}
        </article>
      ))}
    </section>
  )
}
