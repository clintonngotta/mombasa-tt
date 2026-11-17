import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { NotebookPen, UserPen, Users } from "lucide-react"
import { NavCard } from "@/components/layout/NavCard"
import { Avatar } from "@/components/profile/Avatar"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { logOut } from "@/lib/auth"
import { clearActiveOrganization } from "@/lib/clubs"
import { getProfile, profileKeys } from "@/lib/profile"
import { useMe } from "@/lib/session"

export function ProfilePage() {
  const me = useMe()
  const profile = useQuery({ queryKey: profileKeys.me, queryFn: getProfile })
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const signOut = useMutation({
    mutationFn: logOut,
    onSuccess: () => {
      queryClient.clear()
      clearActiveOrganization()
      navigate("/login", { replace: true })
    },
  })

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <div className="flex items-center gap-4">
        <Avatar link={profile.data?.avatar ?? null} className="size-16" />
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-[32px] leading-9 font-bold">{me.data?.display_name ?? "Profile"}</h1>
          <p className="truncate text-muted-foreground">{me.data?.email}</p>
        </div>
      </div>

      <nav aria-label="Profile" className="flex flex-col gap-3">
        <NavCard to="/profile/edit" icon={UserPen} title="Edit profile" description="Name, playing details, goals and what other players see" />
        <NavCard to="/players" icon={Users} title="Player directory" description="Find players who chose to be listed" />
        <NavCard to="/matches" icon={NotebookPen} title="My match log" description="Private record of your matches, sets and notes" />
      </nav>

      {signOut.isError && <FormAlert>{errorMessage(signOut.error)}</FormAlert>}
      <Button variant="outline" disabled={signOut.isPending} onClick={() => signOut.mutate()}>
        {signOut.isPending ? "Logging out…" : "Log out"}
      </Button>
    </div>
  )
}
