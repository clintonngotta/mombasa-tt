import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Alert = Schemas["Notification"]
export type Preference = Schemas["Preference"]

export const alertKeys = {
  all: ["notifications"] as const,
  list: (unread: boolean) => ["notifications", "list", unread] as const,
  unread: ["notifications", "unread"] as const,
  preferences: ["notifications", "preferences"] as const,
}

const BASE = "/me/notifications/"
export const listAlerts = (unread: boolean) => api<Schemas["PaginatedNotificationList"]>(`${BASE}?page_size=50${unread ? "&unread=true" : ""}`)
export const unreadCount = () => api<Schemas["Unread"]>(`${BASE}unread-count/`)
export const markRead = (id: string) => api<Alert>(`${BASE}${id}/read/`, { body: {} })
export const markAllRead = () => api<Schemas["Unread"]>(`${BASE}read-all/`, { body: {} })
export const getPreferences = () => api<Schemas["Preferences"]>("/me/notification-preferences/")
export const savePreferences = (preferences: { category: Preference["category"]; enabled: boolean }[]) =>
  api<Schemas["Preferences"]>("/me/notification-preferences/", { method: "PUT", body: { preferences } })
export const sendAnnouncement = (orgId: string, body: Schemas["AnnouncementRequest"]) => api<Schemas["Sent"]>(`/organizations/${orgId}/announcements/`, { body })
