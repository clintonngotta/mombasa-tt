import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { SIDE, sideOf, useActiveMembership } from "@/lib/clubs"

/** "← Somewhere" link at the top of a sub-page. The organization's pages all go back to "/club"; while a
 * team is the active organization (REQ-057) that is the Team tab, so the link leads there instead. */
export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  const { active } = useActiveMembership()
  const team = to === SIDE.club.path && sideOf(active?.organization.kind) === "team"
  return (
    <Link to={team ? SIDE.team.path : to} className="-ml-1 flex w-fit items-center gap-1 py-2 font-semibold text-brand-blue">
      <ArrowLeft aria-hidden className="size-5" /> {team && children === SIDE.club.title ? SIDE.team.title : children}
    </Link>
  )
}
