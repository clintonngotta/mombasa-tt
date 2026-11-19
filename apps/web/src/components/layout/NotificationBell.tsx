import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Bell } from "lucide-react"
import { alertKeys, unreadCount } from "@/lib/notifications"
import { useMe } from "@/lib/session"
import { cn } from "@/lib/utils"

/** The inbox's unread count, checked every minute while the app is open. */
export function NotificationBell({ className }: { className?: string }) {
  const me = useMe()
  const unread = useQuery({ queryKey: alertKeys.unread, queryFn: unreadCount, enabled: !!me.data, refetchInterval: 60_000 })
  if (!me.data) return null
  const count = unread.data?.unread ?? 0
  return (
    <Link
      to="/notifications"
      aria-label={count ? `Notifications, ${count} unread` : "Notifications"}
      className={cn("relative flex size-12 items-center justify-center rounded-lg outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50", className)}
    >
      <Bell aria-hidden className="size-6" />
      {count > 0 && (
        <span className="absolute top-1.5 right-1.5 flex min-w-5 items-center justify-center rounded-full bg-destructive px-1 text-xs font-bold text-white">
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  )
}
