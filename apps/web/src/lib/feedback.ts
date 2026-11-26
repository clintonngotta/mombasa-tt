import { api, apiUrl } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// Feedback forms (REQ-055): competition staff build a form, send it to a tournament's attendees and read
// the totals; whoever was asked answers once and can change their answers until it closes.
export type FeedbackForm = Schemas["FeedbackForm"]
export type FeedbackFormInput = Schemas["FeedbackFormRequest"]
export type FeedbackSection = Schemas["FeedbackSection"]
export type FeedbackQuestion = Schemas["FeedbackQuestion"]
export type QuestionKind = Schemas["QuestionKindEnum"]
export type FeedbackTotals = Schemas["FeedbackTotals"]
export type MyFeedbackForm = Schemas["MyFeedbackForm"]
export type AnswerValue = number | boolean | string | string[]
export type Answers = Record<string, AnswerValue>

export const KIND_LABEL: Record<QuestionKind, string> = {
  rating: "Rating, 1 to 5",
  single: "One choice",
  multiple: "Several choices",
  short_text: "Short text",
  long_text: "Long text",
  yes_no: "Yes or no",
  number: "Number",
}
export const MAX_QUESTIONS = 60
export const MAX_CHOICES = 12

const base = (orgId: string) => `/organizations/${orgId}/feedback-forms/`
export const feedbackKeys = {
  all: ["feedback"] as const,
  forTournament: (orgId: string, tournamentId: string) => ["feedback", orgId, "tournament", tournamentId] as const,
  templates: (orgId: string) => ["feedback", orgId, "templates"] as const,
  form: (orgId: string, id: string) => ["feedback", orgId, "form", id] as const,
  totals: (orgId: string, id: string) => ["feedback", orgId, "totals", id] as const,
  asked: ["feedback", "me"] as const,
  mine: (id: string) => ["feedback", "me", id] as const,
}

export const listTournamentForms = (orgId: string, tournamentId: string) => api<FeedbackForm[]>(`${base(orgId)}?tournament=${tournamentId}`)
export const listTemplates = (orgId: string) => api<FeedbackForm[]>(`${base(orgId)}?templates=1`)
export const getForm = (orgId: string, id: string) => api<FeedbackForm>(`${base(orgId)}${id}/`)
export const createForm = (orgId: string, body: Partial<FeedbackFormInput>) => api<FeedbackForm>(base(orgId), { body })
export const updateForm = (orgId: string, id: string, body: Partial<FeedbackFormInput>) => api<FeedbackForm>(`${base(orgId)}${id}/`, { method: "PATCH", body })
export const deleteForm = (orgId: string, id: string) => api<void>(`${base(orgId)}${id}/`, { method: "DELETE" })
export const sendForm = (orgId: string, id: string, closesAt: string) => api<FeedbackForm>(`${base(orgId)}${id}/send/`, { body: { closes_at: closesAt } })
export const moveClosing = (orgId: string, id: string, closesAt: string) => api<FeedbackForm>(`${base(orgId)}${id}/closing/`, { body: { closes_at: closesAt } })
export const getTotals = (orgId: string, id: string) => api<FeedbackTotals>(`${base(orgId)}${id}/totals/`)
export const exportUrl = (orgId: string, id: string) => apiUrl(`${base(orgId)}${id}/export.csv`)

export const listAskedOfMe = () => api<MyFeedbackForm[]>("/me/feedback-forms/")
export const getMyForm = (id: string) => api<MyFeedbackForm>(`/feedback-forms/${id}/`)
export const saveMyAnswers = (id: string, answers: Answers) => api<MyFeedbackForm>(`/feedback-forms/${id}/`, { method: "PUT", body: { answers } })

/** "Open until Fri 28 Nov", "Closed", "Draft". */
export function formState(form: Pick<FeedbackForm, "status" | "open" | "opens_at">, now = Date.now()) {
  if (form.status === "draft") return "Draft"
  if (form.open) return "Open"
  return form.opens_at && new Date(form.opens_at).getTime() > now ? "Not open yet" : "Closed"
}
