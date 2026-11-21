import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarCheck, CloudUpload, NotebookPen, Ticket, TrendingUp, UserPen, UserRoundCheck, Users } from "lucide-react"
import { NavCard } from "@/components/layout/NavCard"
import { Honours } from "@/components/ceremony/Honours"
import { InstallApp } from "@/components/layout/InstallApp"
import { Avatar } from "@/components/profile/Avatar"
import { Button, buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { useState } from "react"
import { Link } from "react-router-dom"
import { logOut } from "@/lib/auth"
import { purgeScoreJournal, unsentScoreActions } from "@/lib/deck"
import { forgetAccount, unsentChanges } from "@/lib/offline"
import { clearActiveOrganization } from "@/lib/clubs"
import { getProfile, profileKeys } from "@/lib/profile"
import { useMe } from "@/lib/session"

export function ProfilePage() {
  const me = useMe()
  const profile = useQuery({ queryKey: profileKeys.me, queryFn: getProfile })
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // Score actions and changes still on this device belong to this account: logging out must not lose them quietly.
  const [unsent, setUnsent] = useState({ scores: 0, changes: 0 })
  const userId = me.data?.id
  const signOut = useMutation({
    mutationFn: async ({ discard }: { discard: boolean }) => {
      if (userId && !discard) {
        const waiting = { scores: await unsentScoreActions(userId), changes: await unsentChanges(userId) }
        if (waiting.scores + waiting.changes > 0) return waiting
      }
      await logOut()
      if (userId) {
        await purgeScoreJournal(userId)
        await forgetAccount(userId)
      }
      return { scores: 0, changes: 0 }
    },
    onSuccess: (waiting) => {
      setUnsent(waiting)
      if (waiting.scores + waiting.changes > 0) return
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
        {userId && <NavCard to={`/ratings/${userId}`} icon={TrendingUp} title="My ratings" description="Singles and doubles ratings and the matches behind them" />}
        <NavCard to="/matches" icon={NotebookPen} title="My match log" description="Private record of your matches, sets and notes" />
        <NavCard to="/profile/bookings" icon={CalendarCheck} title="Table bookings" description="Your requests to book tables and the venues' answers" />
        <NavCard to="/profile/visits" icon={Ticket} title="Passes and visits" description="Your facility passes, to show at the door, and your visits" />
        <NavCard to="/profile/sync" icon={CloudUpload} title="Waiting to sync" description="Changes you made offline, and whether they have been sent" />
        <NavCard to="/profile/claims" icon={UserRoundCheck} title="Matches entered for you" description="Claim what a club entered under your name before you joined" />
      </nav>

      <Honours />

      <InstallApp />

      {signOut.isError && <FormAlert>{errorMessage(signOut.error)}</FormAlert>}
      {unsent.changes > 0 && unsent.scores === 0 && (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-warning/40 bg-warning/5 p-4">
          <p className="font-semibold">
            {unsent.changes} {unsent.changes === 1 ? "change you made offline hasn't" : "changes you made offline haven't"} reached Coast TT yet.
          </p>
          <p>Connect and wait until they are sent, then log out. Logging out now removes them from this device for good.</p>
          <div className="flex flex-wrap gap-2">
            <Link to="/profile/sync" className={buttonVariants()}>
              See changes
            </Link>
            <Button variant="destructive" disabled={signOut.isPending} onClick={() => signOut.mutate({ discard: true })}>
              Log out and discard them
            </Button>
          </div>
        </div>
      )}
      {unsent.scores > 0 && (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-warning/40 bg-warning/5 p-4">
          <p className="font-semibold">
            {unsent.scores} score {unsent.scores === 1 ? "action" : "actions"} on this device {unsent.scores === 1 ? "isn't" : "aren't"} on Coast TT: not sent yet, or not accepted and still to be shown to the organizers.
          </p>
          <p>
            Open the match from Play while you are connected and wait for "Saved", then log out.
            {unsent.changes > 0 && ` ${unsent.changes} other ${unsent.changes === 1 ? "change is" : "changes are"} waiting too.`} Logging out now removes them from this device for good.
          </p>
          <div className="flex flex-wrap gap-2">
            <Link to="/play" className={buttonVariants()}>
              Go to my matches
            </Link>
            <Button variant="destructive" disabled={signOut.isPending} onClick={() => signOut.mutate({ discard: true })}>
              Log out and discard them
            </Button>
          </div>
        </div>
      )}
      <Button variant="outline" disabled={signOut.isPending} onClick={() => signOut.mutate({ discard: false })}>
        {signOut.isPending ? "Logging out…" : "Log out"}
      </Button>
    </div>
  )
}
