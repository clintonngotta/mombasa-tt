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
export const KIND_LABEL: Record<Charge["kind"], string> = { event_fee: "Event fee", booking: "Booking", due: "Dues", visit: "Visit", other: "Other" }

/** Shillings typed by staff into minor units; null when it isn't a positive amount. */
export function toMinor(text: string): number | null {
  const value = Math.round(Number(text) * 100)
  return Number.isFinite(value) && value > 0 ? value : null
}
