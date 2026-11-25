import { api, apiUrl } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Charge = Schemas["Charge"]
export type Payment = Schemas["Payment"]
export type Balance = Schemas["Balance"]

export const financeKeys = {
  all: ["finance"] as const,
  ledger: (orgId: string) => ["finance", "ledger", orgId] as const,
  mine: (orgId: string) => ["finance", "mine", orgId] as const,
}

const base = (orgId: string) => `/organizations/${orgId}/finance/`
export const listCharges = (orgId: string) => api<Charge[]>(`${base(orgId)}charges/`)
export const listPayments = (orgId: string) => api<Payment[]>(`${base(orgId)}payments/`)
export const listBalances = (orgId: string) => api<Balance[]>(`${base(orgId)}balances/`)
export const createCharge = (orgId: string, body: Schemas["ChargeRequest"]) => api<Charge>(`${base(orgId)}charges/`, { body })
export const waiveCharge = (orgId: string, id: string, reason: string) => api<Charge>(`${base(orgId)}charges/${id}/waive/`, { body: { reason } })
export const recordPayment = (orgId: string, body: Schemas["PaymentRequest"]) => api<Payment>(`${base(orgId)}payments/`, { body })
export const allocatePayment = (orgId: string, id: string, chargeId: string, amountMinor: number) =>
  api<Payment>(`${base(orgId)}payments/${id}/allocate/`, { body: { charge_id: chargeId, amount_minor: amountMinor } })
export const reversePayment = (orgId: string, id: string, reason: string) => api<Payment>(`${base(orgId)}payments/${id}/reverse/`, { body: { reason } })
export const getMyFinances = (orgId: string) => api<Schemas["MyFinances"]>(`/organizations/${orgId}/my-finances/`)

export const STATUS_LABEL: Record<string, string> = { paid: "Paid", partial: "Part paid", pending: "Owed", overdue: "Overdue", waived: "Waived" }
export const METHOD_LABEL: Record<Payment["method"], string> = { cash: "Cash", mpesa: "M-Pesa", bank: "Bank", other: "Other" }
export const KIND_LABEL: Record<Charge["kind"], string> = { event_fee: "Event fee", booking: "Booking", due: "Dues", visit: "Visit", welfare: "Welfare gift", other: "Other" }

/** Shillings typed by staff into minor units; null when it isn't a positive amount. */
export function toMinor(text: string): number | null {
  const value = Math.round(Number(text) * 100)
  return Number.isFinite(value) && value > 0 ? value : null
}

export type Campaign = Schemas["Campaign"]
export const campaignKeys = (orgId: string) => ["finance", "ledger", orgId, "campaigns"] as const
export const listCampaigns = (orgId: string) => api<Campaign[]>(`${base(orgId)}campaigns/`)
export const createCampaign = (orgId: string, body: Schemas["CampaignRequest"]) => api<Campaign>(`${base(orgId)}campaigns/`, { body })
export const updateCampaign = (orgId: string, id: string, body: Schemas["PatchedCampaignUpdateRequest"]) => api<Campaign>(`${base(orgId)}campaigns/${id}/`, { method: "PATCH", body })
export const closeCampaign = (orgId: string, id: string) => api<Campaign>(`${base(orgId)}campaigns/${id}/close/`, { body: {} })
export const setCampaignTerm = (orgId: string, id: string, body: Schemas["CampaignTermRequest"]) => api<Campaign>(`${base(orgId)}campaigns/${id}/terms/`, { body })

export const CADENCE_LABEL: Record<Campaign["cadence"], string> = { once: "One-time", weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly", yearly: "Yearly" }

/** The ready-made "Club operations" dues: every active member, weekly or monthly, for running costs. */
export const CLUB_OPERATIONS = {
  title: "Club operations",
  description: "Hall and table hire, balls, nets, repairs and utilities.",
  audience: "all" as const,
}

export const campaignDuesKey = (orgId: string, id: string, status: string) => ["finance", "ledger", orgId, "campaign-dues", id, status] as const
export const listCampaignDues = (orgId: string, id: string, status: string) =>
  api<Schemas["CampaignDues"]>(`${base(orgId)}campaigns/${id}/dues/${status ? `?status=${status}` : ""}`)
export const remindCampaign = (orgId: string, id: string) => api<Schemas["Reminded"]>(`${base(orgId)}campaigns/${id}/remind/`, { body: {} })

export type Expense = Schemas["Expense"]
export type PurposeTotal = Schemas["PurposeTotal"]
export const listExpenses = (orgId: string) => api<Expense[]>(`${base(orgId)}expenses/`)
export const recordExpense = (orgId: string, body: Schemas["ExpenseRequest"]) => api<Expense>(`${base(orgId)}expenses/`, { body })
export const reverseExpense = (orgId: string, id: string, reason: string) => api<Expense>(`${base(orgId)}expenses/${id}/reverse/`, { body: { reason } })
export function uploadReceipt(orgId: string, id: string, file: File) {
  const body = new FormData()
  body.append("file", file)
  return api<Expense>(`${base(orgId)}expenses/${id}/receipt/`, { method: "PUT", body })
}
export const getFinanceSummary = (orgId: string) => api<PurposeTotal[]>(`${base(orgId)}summary/`)
export const getPurposes = (orgId: string) => api<Schemas["Purposes"]>(`/organizations/${orgId}/finance-purposes/`)

export type WelfareProject = Schemas["WelfareProject"]
export type WelfareContribution = Schemas["WelfareContribution"]
export const welfareKeys = (orgId: string) => ["finance", "ledger", orgId, "welfare"] as const
const welfare = (orgId: string) => `/organizations/${orgId}/welfare-projects/`
export const listWelfare = (orgId: string) => api<WelfareProject[]>(welfare(orgId))
export const createWelfare = (orgId: string, body: Schemas["WelfareProjectRequest"]) => api<WelfareProject>(welfare(orgId), { body })
export const updateWelfare = (orgId: string, id: string, body: Schemas["PatchedWelfareUpdateRequest"]) => api<WelfareProject>(`${welfare(orgId)}${id}/`, { method: "PATCH", body })
export const hideWelfare = (orgId: string, id: string) => api<WelfareProject | null>(`${welfare(orgId)}${id}/hide/`, { body: {} })
export const closeWelfare = (orgId: string, id: string) => api<WelfareProject>(`${welfare(orgId)}${id}/close/`, { body: {} })
export const makeWelfareDue = (orgId: string, id: string, body: Schemas["WelfareDueRequest"]) => api<WelfareProject>(`${welfare(orgId)}${id}/due/`, { body })
export const listContributions = (orgId: string, id: string) => api<WelfareContribution[]>(`${welfare(orgId)}${id}/contributions/`)
export const recordContribution = (orgId: string, id: string, body: Schemas["WelfareContributionRequest"]) => api<WelfareContribution>(`${welfare(orgId)}${id}/contributions/`, { body })
export const reverseContribution = (orgId: string, id: string, contributionId: string, reason: string) =>
  api<WelfareContribution>(`${welfare(orgId)}${id}/contributions/${contributionId}/reverse/`, { body: { reason } })
export const recordWelfareExpense = (orgId: string, id: string, body: Schemas["ExpenseRequest"]) => api<Expense>(`${welfare(orgId)}${id}/expenses/`, { body })

// The financial year and the annual report (REQ-041): finance staff draft, publish and amend; members
// read published reports; a public report needs no login. Totals only, never a member or a payee.
export type AnnualReport = Schemas["AnnualReport"]
export type ReportCurrency = Schemas["ReportCurrency"]
export type ExpenseCategory = NonNullable<Expense["category"]>
export const EXPENSE_CATEGORY: Record<ExpenseCategory, string> = { hall_hire: "Hall hire", equipment: "Equipment", welfare: "Welfare", events: "Events", transport: "Transport", other: "Other" }
const reportsBase = (orgId: string) => `/organizations/${orgId}/annual-reports/`
export const reportKeys = { list: (orgId: string) => ["finance", orgId, "reports"] as const, settings: (orgId: string) => ["finance", orgId, "settings"] as const }
export const listReports = (orgId: string) => api<AnnualReport[]>(reportsBase(orgId))
export const draftReport = (orgId: string) => api<AnnualReport>(reportsBase(orgId), { body: {} })
export const updateReport = (orgId: string, id: string, body: { narrative?: string; public?: boolean }) => api<AnnualReport>(`${reportsBase(orgId)}${id}/`, { method: "PATCH", body })
export const deleteReport = (orgId: string, id: string) => api<void>(`${reportsBase(orgId)}${id}/`, { method: "DELETE" })
export const publishReport = (orgId: string, id: string) => api<AnnualReport>(`${reportsBase(orgId)}${id}/publish/`, { body: {} })
export const amendReport = (orgId: string, id: string) => api<AnnualReport>(`${reportsBase(orgId)}${id}/amend/`, { body: {} })
export const reportFileUrl = (orgId: string, id: string, kind: "csv" | "pdf") => apiUrl(`${reportsBase(orgId)}${id}/export.${kind}`)
export const getFinanceSettings = (orgId: string) => api<Schemas["FinanceSettings"]>(`${base(orgId)}settings/`)
export const saveFinanceSettings = (orgId: string, body: Schemas["FinanceSettingsRequest"]) => api<Schemas["FinanceSettings"]>(`${base(orgId)}settings/`, { method: "PUT", body })
/** "1,070.00" or "-50.00": minor units as money, a deficit with its minus. */
export const moneyText = (minor: number) => `${minor < 0 ? "-" : ""}${(Math.abs(minor) / 100).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// Money from outside the membership (REQ-051): the club's own list of sources, income recorded by choosing
// one, and what was received split into internal (members) and external (by source).
export type ExternalSource = Schemas["ExternalSource"]
export type ExternalIncome = Schemas["ExternalIncome"]
export type IncomeTotals = Schemas["IncomeTotals"]
export const externalKeys = {
  all: (orgId: string) => ["finance", orgId, "external"] as const,
  sources: (orgId: string) => ["finance", orgId, "external", "sources"] as const,
  income: (orgId: string, source: string, from: string, to: string) => ["finance", orgId, "external", "income", source, from, to] as const,
  totals: (orgId: string, from: string, to: string) => ["finance", orgId, "external", "totals", from, to] as const,
}
const range = (from: string, to: string, source = "") => {
  const params = new URLSearchParams()
  if (from) params.set("from", from)
  if (to) params.set("to", to)
  if (source) params.set("source", source)
  const query = params.toString()
  return query ? `?${query}` : ""
}
export const listExternalSources = (orgId: string) => api<ExternalSource[]>(`${base(orgId)}external-sources/`)
export const addExternalSource = (orgId: string, name: string) => api<ExternalSource>(`${base(orgId)}external-sources/`, { body: { name } })
export const setExternalSourceActive = (orgId: string, id: string, active: boolean) => api<ExternalSource>(`${base(orgId)}external-sources/${id}/`, { method: "PATCH", body: { active } })
export const deleteExternalSource = (orgId: string, id: string) => api<void>(`${base(orgId)}external-sources/${id}/`, { method: "DELETE" })
export const listExternalIncome = (orgId: string, source: string, from: string, to: string) => api<ExternalIncome[]>(`${base(orgId)}external-income/${range(from, to, source)}`)
export const recordExternalIncome = (orgId: string, body: Schemas["ExternalIncomeRequest"]) => api<ExternalIncome>(`${base(orgId)}external-income/`, { body })
export const reverseExternalIncome = (orgId: string, id: string, reason: string) => api<ExternalIncome>(`${base(orgId)}external-income/${id}/reverse/`, { body: { reason } })
export const getIncomeTotals = (orgId: string, from: string, to: string) => api<IncomeTotals[]>(`${base(orgId)}income-totals/${range(from, to)}`)
