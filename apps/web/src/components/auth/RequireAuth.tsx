import { Navigate, Outlet, useLocation } from "react-router-dom"
import { LoaderCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { useMe } from "@/lib/session"

export function RequireAuth() {
  const location = useLocation()
  const me = useMe()

  if (me.isPending) {
    return (
      <p role="status" className="flex items-center gap-2 text-muted-foreground">
        <LoaderCircle aria-hidden className="size-5 animate-spin" /> Loading…
      </p>
    )
  }

  if (me.error instanceof ApiError && me.error.status === 401) {
    const next = location.pathname + location.search
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />
  }

  if (me.isError) {
    return (
      <div className="flex max-w-[640px] flex-col gap-3">
        <FormAlert>{errorMessage(me.error)}</FormAlert>
        <Button variant="outline" onClick={() => me.refetch()}>
          Try again
        </Button>
      </div>
    )
  }

  return <Outlet />
}
