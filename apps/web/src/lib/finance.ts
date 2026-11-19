import { api } from "@/lib/api"
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
export const listContributions = (orgId: string, id: string) => api<WelfareContribution[]>(`${welfare(orgId)}${id}/contributions/`)
export const recordContribution = (orgId: string, id: string, body: Schemas["WelfareContributionRequest"]) => api<WelfareContribution>(`${welfare(orgId)}${id}/contributions/`, { body })
export const reverseContribution = (orgId: string, id: string, contributionId: string, reason: string) =>
  api<WelfareContribution>(`${welfare(orgId)}${id}/contributions/${contributionId}/reverse/`, { body: { reason } })
export const recordWelfareExpense = (orgId: string, id: string, body: Schemas["ExpenseRequest"]) => api<Expense>(`${welfare(orgId)}${id}/expenses/`, { body })
