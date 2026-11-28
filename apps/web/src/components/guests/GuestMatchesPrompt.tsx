import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, UserRoundCheck } from "lucide-react"
import { guestKeys, listMyGuestInvitations } from "@/lib/guests"

/**
 * On Home, for a player a club entered as a guest before they joined (REQ-003): matches are waiting to
 * be claimed. Shown only while something is open; claiming happens on Profile, Matches entered for you.
 */
export function GuestMatchesPrompt() {
  const invitations = useQuery({ queryKey: guestKeys.myInvitations, queryFn: listMyGuestInvitations })
  const open = invitations.data?.results ?? []
  if (open.length === 0) return null
  const clubs = [...new Set(open.map((invitation) => invitation.organization_name))]
  return (
    <Link
      to="/profile/claims"
      className="flex items-center gap-3 rounded-xl border border-brand-blue/30 bg-surface-selected p-4 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <UserRoundCheck aria-hidden className="size-6 shrink-0 text-brand-blue" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="font-semibold">Did you play before you joined?</span>
        <span className="text-sm text-muted-foreground">
          {clubs.join(", ")} entered a player who may be you. Check and claim the matches, so your history stays in one account.
        </span>
      </span>
      <ChevronRight aria-hidden className="size-5 shrink-0 text-muted-foreground" />
    </Link>
  )
}
