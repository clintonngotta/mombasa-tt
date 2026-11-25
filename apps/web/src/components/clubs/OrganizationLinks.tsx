import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import {
  Banknote,
  Bell,
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  ChevronRight,
  ClipboardList,
  HeartHandshake,
  KeyRound,
  Landmark,
  UserRoundCheck,
  Map,
  MapPin,
  Megaphone,
  PartyPopper,
  Store,
  Trophy,
  UserRoundPlus,
  Users,
  type LucideIcon,
} from "lucide-react"
import { ROW } from "@/lib/clubAdmin"
import { can, isBodyKind, type Membership } from "@/lib/clubs"
import { cn } from "@/lib/utils"

type OrgLink = { to: string; label: string; icon: LucideIcon }
type Group = { title: string; links: OrgLink[] }

const runsTables = (membership: Membership) =>
  membership.organization.kind === "facility" || membership.organization.kind === "club_facility"

/** Everything an organization offers the signed-in person, grouped by what it's for and limited to what
 * their roles allow (REQ-005). A club lists its members' own pages first; a facility, which isn't a
 * person's club, starts with the front desk. */
function organizationGroups(membership: Membership, variant: "club" | "facility"): Group[] {
  const member = !membership.managedOnly
  const manageMembers = can(membership, "members.manage")
  const manageRoles = can(membership, "roles.manage")
  const competitions = can(membership, "competitions.manage")
  const facilities = can(membership, "facilities.manage")
  const training = can(membership, "training.manage")
  const finances = can(membership, "finances.view", "finances.manage")
  const announce = can(membership, "announcements.manage")
  const activities = can(membership, "activities.manage")
  const governance = can(membership, "governance.manage")
  const pick = (...links: (OrgLink | false)[]) => links.filter(Boolean) as OrgLink[]
  const word = variant === "facility" ? "facility" : "club"

  const desk: Group = {
    title: variant === "facility" ? "Front desk" : "Tables and venues",
    links: pick(
      facilities && { to: "/club/bookings", label: "Table bookings", icon: CalendarCheck },
      facilities && { to: "/club/venues", label: variant === "facility" ? "Branches, tables, hours and passes" : "Venues and tables", icon: MapPin },
      runsTables(membership) && finances && { to: "/club/takings", label: "Door takings", icon: Banknote },
    ),
  }
  const programme: Group = {
    title: "Programme",
    links: pick(
      (manageRoles || training) && { to: "/club/profile", label: `${variant === "facility" ? "Facility" : "Club"} profile and training hours`, icon: Store },
      training && { to: "/club/sessions", label: "Training sessions: invitations and attendance", icon: CalendarClock },
      competitions && { to: "/club/tournaments", label: "Tournaments and their dashboards", icon: Trophy },
      activities && { to: "/club/activities", label: "Activities: nights out, fun days and visits", icon: PartyPopper },
      announce && { to: "/club/announce", label: `Announce to ${variant === "facility" ? "players" : "members"}`, icon: Bell },
      announce && { to: "/club/external-events", label: "Events elsewhere: list a tournament run outside Coast TT", icon: Megaphone },
    ),
  }
  const people: Group = {
    title: variant === "facility" ? "Staff and players" : "People",
    links: pick(
      (manageMembers || manageRoles) && { to: "/club/members", label: variant === "facility" ? "Staff and their roles" : "Members and their roles", icon: Users },
      (manageMembers || competitions) && { to: "/club/guests", label: "Guests and their claims", icon: UserRoundPlus },
      manageRoles && { to: "/club/roles", label: "Roles and permissions", icon: KeyRound },
      manageMembers && { to: "/club/fields", label: "Member fields", icon: ClipboardList },
    ),
  }
  const money: Group = {
    title: "Money",
    links: pick(finances && { to: "/club/finance", label: "Finances: charges, payments and balances", icon: Banknote }),
  }
  const governanceGroup: Group = {
    title: "Governance",
    links: pick(
      { to: "/club/committee", label: governance ? "Committee and its positions" : "Committee", icon: Landmark },
      member &&
        variant === "club" &&
        membership.organization.kind !== "coaching" && {
          to: "/club/representatives",
          label: isBodyKind(membership.organization.kind) ? "Representatives sent by clubs and regions" : "Representatives to the regional body",
          icon: UserRoundCheck,
        },
      member && { to: "/club/meetings", label: "Meetings", icon: CalendarClock },
      isBodyKind(membership.organization.kind) && { to: "/region", label: "Region: agenda, clubs, articles, meetings, sponsorships and approvals", icon: Map },
    ),
  }
  const mine: Group = {
    title: `Your ${word}`,
    links: pick(
      member && { to: "/club/schedule", label: "Schedule: activities, tournaments and training", icon: CalendarDays },
      member && { to: "/club/training-rules", label: "Training rules: weekly slots, place and check-in", icon: MapPin },
      member && { to: "/club/my-payments", label: "My payments", icon: Banknote },
      member && { to: "/club/welfare", label: "Welfare projects", icon: HeartHandshake },
    ),
  }

  const groups = variant === "facility" ? [desk, programme, money, people, governanceGroup] : [mine, programme, desk, money, people, governanceGroup]
  return groups.filter((group) => group.links.length > 0)
}

export function OrganizationLinks({ membership, variant }: { membership: Membership; variant: "club" | "facility" }) {
  return (
    <div className="flex flex-col gap-6">
      {organizationGroups(membership, variant).map((group) => (
        <nav key={group.title} aria-label={group.title} className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">{group.title}</h2>
          {group.links.map(({ to, label, icon: Icon }) => (
            <OrgLinkRow key={to} to={to} icon={<Icon aria-hidden className="size-5 text-brand-blue" />}>
              {label}
            </OrgLinkRow>
          ))}
        </nav>
      ))}
    </div>
  )
}

export function OrgLinkRow({ to, icon, children }: { to: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Link to={to} className={cn(ROW, "min-h-12 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
      {icon}
      <span className="flex-1">{children}</span>
      <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
    </Link>
  )
}
