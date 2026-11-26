import { useQuery } from "@tanstack/react-query"
import {
  Banknote,
  Building2,
  CalendarCheck,
  CalendarClock,
  GraduationCap,
  House,
  Map,
  MapPin,
  Medal,
  ShieldCheck,
  Swords,
  Trophy,
  UserRound,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react"
import { BatIcon } from "@/components/brand/BatIcon"
import { can, isBodyKind, sideOf, useActiveMembership, type Membership } from "@/lib/clubs"
import { coachingKeys, getMyCoachProfileOrNull } from "@/lib/coaching"
import { useMe } from "@/lib/session"

/** `also` lists other paths that light this entry up, when its pages don't all sit under `to`. `exact`
 * lights the entry on its own path only, when the pages beneath it belong to another entry for now. */
export type NavItem = { to: string; label: string; icon: LucideIcon; also?: string[]; exact?: boolean }

/** Whose menu shows: a person's (their own play, training and record, plus any roles they hold), or a
 * facility's when the active organization is a facility the person works for. A facility isn't a person,
 * so its menu has no Play, Training or Rankings. */
export type NavMode = "person" | "facility"

/** The bottom bar holds this many entries; anything past it goes under More. Five is what fits a small
 * phone with every label, "Tournaments" included, readable in full. */
export const TAB_LIMIT = 5

export const MORE_PATH = "/more"

const HOME: NavItem = { to: "/home", label: "Home", icon: House }
const PLAY: NavItem = { to: "/play", label: "Play", icon: Swords }
const TRAINING: NavItem = { to: "/training", label: "Training", icon: BatIcon }
const RANKINGS: NavItem = { to: "/rankings", label: "Rankings", icon: Trophy }
const CLUB: NavItem = { to: "/club", label: "Club", icon: Users }
// A team (REQ-057): players who play together without a training place of their own.
const TEAM: NavItem = { to: "/team", label: "Team", icon: UsersRound }
const COACHING: NavItem = { to: "/coaching", label: "Coaching", icon: GraduationCap }
const REGIONAL: NavItem = { to: "/regional", label: "Regional", icon: Map }
// The platform's back office, for platform super admins (REQ-056).
const ADMIN: NavItem = { to: "/admin", label: "Admin", icon: ShieldCheck }
// Everyone's tournaments: find one, enter, follow the scores. The organizer's own list and dashboards
// live under /club/tournaments and are reached from this tab, so they light it up too.
const TOURNAMENTS: NavItem = { to: "/tournaments", label: "Tournaments", icon: Medal, also: ["/club/tournaments"] }
// A facility isn't a player: its Tournaments entry is the organizer's list of the ones it hosts.
const HOSTED: NavItem = { to: "/club/tournaments", label: "Tournaments", icon: Medal }
const PROFILE: NavItem = { to: "/profile", label: "Profile", icon: UserRound }

/** The facility is the active organization and the person works there, not a regional official looking in. */
export const actsAsFacility = (membership: Membership | undefined) =>
  !!membership && membership.organization.kind === "facility" && !membership.managedOnly

/** Someone who oversees organizations as a regional, country or platform official, or belongs to a regional body. */
export const isOfficial = (all: Membership[]) =>
  all.some((m) => !!m.authority || (isBodyKind(m.organization.kind) && !m.managedOnly))

function facilityItems(membership: Membership): NavItem[] {
  const facilities = can(membership, "facilities.manage")
  const finances = can(membership, "finances.view", "finances.manage")
  const people = can(membership, "members.manage", "roles.manage")
  const training = can(membership, "training.manage")
  const competitions = can(membership, "competitions.manage")
  return [
    { to: "/facility", label: "Facility", icon: Building2 },
    ...(competitions ? [HOSTED] : []),
    ...(facilities ? [{ to: "/club/venues", label: "Branches", icon: MapPin }] : []),
    ...(facilities ? [{ to: "/club/bookings", label: "Bookings", icon: CalendarCheck }] : []),
    ...(finances ? [{ to: "/club/takings", label: "Takings", icon: Banknote }] : []),
    ...(training ? [{ to: "/club/sessions", label: "Sessions", icon: CalendarClock }] : []),
    ...(people ? [{ to: "/club/members", label: "Staff", icon: Users }] : []),
    { ...PROFILE, label: "Account" },
  ]
}

/** The menu for the signed-in person and the organization they're acting for. The sidebar shows every
 * item; the bottom bar shows the first few and puts the rest under More. */
export function useNavigation() {
  const me = useMe()
  const signedIn = me.isSuccess
  // Known to be signed out, not merely still asking: the sidebar is for people with an account.
  const guest = me.isError
  const { memberships, all, active } = useActiveMembership()
  const facility = actsAsFacility(active)
  const coach = useQuery({
    queryKey: coachingKeys.profile,
    queryFn: getMyCoachProfileOrNull,
    enabled: signedIn && !facility,
    staleTime: 5 * 60 * 1000,
  })

  const mode: NavMode = facility ? "facility" : "person"
  const roles = [...(coach.data ? [COACHING] : []), ...(isOfficial(all) ? [REGIONAL] : []), ...(me.data?.is_platform_admin ? [ADMIN] : [])]
  // Until the memberships arrive we can't tell a facility from a person, so show no menu rather than the wrong one.
  const loading = signedIn && memberships.isPending
  // The organization's own pages all sit under /club. While a team is the active organization they are the
  // team's, so Team lights up on them and Club only on its own page.
  const teamActive = sideOf(active?.organization.kind) === "team"
  const club = teamActive ? { ...CLUB, exact: true } : CLUB
  const team = teamActive ? { ...TEAM, also: ["/club"] } : TEAM
  const items = loading ? [] : facility && active ? facilityItems(active) : [HOME, TOURNAMENTS, PLAY, TRAINING, RANKINGS, ...roles, club, team, PROFILE]

  // What people come for stays on the bar: tournaments, play and their club or team. The rest waits under
  // More. The bar has one place for the two: the team's while a team is the active organization, or for a
  // player who is in a team and in no club; otherwise the club's.
  const own = all.filter((m) => !m.managedOnly)
  const teamFirst = teamActive || (own.length > 0 && own.every((m) => sideOf(m.organization.kind) === "team"))
  const theirs = teamFirst ? [team, club] : [club, team]
  const order = facility || loading ? items : [HOME, TOURNAMENTS, PLAY, ...theirs, ...roles, TRAINING, PROFILE, RANKINGS]
  const fits = items.length <= TAB_LIMIT
  const tabs = fits ? items : order.slice(0, TAB_LIMIT - 1)
  const more = fits ? [] : items.filter((item) => !tabs.includes(item))
  return { signedIn, guest, mode, active, items, tabs, more }
}
