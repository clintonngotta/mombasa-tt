import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, NotebookPen } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { logOut } from "@/lib/auth"
import { useMe } from "@/lib/session"

export function ProfilePage() {
  const me = useMe()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const signOut = useMutation({
    mutationFn: logOut,
    onSuccess: () => {
      queryClient.clear()
      navigate("/login", { replace: true })
    },
  })

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">{me.data?.display_name ?? "Profile"}</h1>
        <p className="text-muted-foreground">{me.data?.email}</p>
      </div>

      <Link
        to="/matches"
        className="flex items-center gap-3 rounded-xl border bg-card p-4 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-surface-selected">
          <NotebookPen aria-hidden className="size-6 text-brand-blue" />
        </span>
        <span className="flex flex-1 flex-col">
          <span className="font-semibold">My match log</span>
          <span className="text-sm text-muted-foreground">Private record of your matches, sets and notes</span>
        </span>
        <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
      </Link>

      {signOut.isError && <FormAlert>{errorMessage(signOut.error)}</FormAlert>}
      <Button variant="outline" disabled={signOut.isPending} onClick={() => signOut.mutate()}>
        {signOut.isPending ? "Logging out…" : "Log out"}
      </Button>
    </div>
  )
}
