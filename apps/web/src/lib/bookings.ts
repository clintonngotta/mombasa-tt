import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type TableBooking = Schemas["TableBooking"]

export const bookingKeys = {
  all: ["bookings"] as const,
  mine: ["bookings", "mine"] as const,
  club: (orgId: string, status: string) => ["bookings", "club", orgId, status] as const,
}

export const listMyBookings = () => api<Schemas["PaginatedTableBookingList"]>("/me/table-bookings/?page_size=50")
export const requestBooking = (body: Schemas["TableBookingRequest"]) => api<TableBooking>("/me/table-bookings/", { body })
export const cancelMyBooking = (id: string, reason = "") => api<TableBooking>(`/me/table-bookings/${id}/cancel/`, { body: { reason } })

const club = (orgId: string) => `/organizations/${orgId}/bookings/`
export const listClubBookings = (orgId: string, status: string) => api<Schemas["PaginatedTableBookingList"]>(`${club(orgId)}?page_size=50${status ? `&status=${status}` : ""}`)
export const approveBooking = (orgId: string, id: string, feeMinor: number | null) => api<TableBooking>(`${club(orgId)}${id}/approve/`, { body: { fee_minor: feeMinor } })
export const rejectBooking = (orgId: string, id: string, reason: string) => api<TableBooking>(`${club(orgId)}${id}/reject/`, { body: { reason } })
export const cancelClubBooking = (orgId: string, id: string, reason: string) => api<TableBooking>(`${club(orgId)}${id}/cancel/`, { body: { reason } })

export const STATUS_LABEL: Record<TableBooking["status"], string> = { requested: "Requested", approved: "Approved", rejected: "Not approved", cancelled: "Cancelled" }
