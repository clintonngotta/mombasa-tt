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
  Swords,
  Trophy,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react"
import { BatIcon } from "@/components/brand/BatIcon"
import { can, isBodyKind, useActiveMembership, type Membership } from "@/lib/clubs"
import { coachingKeys, getMyCoachProfileOrNull } from "@/lib/coaching"
import { useMe } from "@/lib/session"

export type NavItem = { to: string; label: string; icon: LucideIcon }

/** Whose menu shows: a person's (their own play, training and record, plus any roles they hold), or a
 * facility's when the active organization is a facility the person works for. A facility isn't a person,
 * so its menu has no Play, Training or Rankings. */
export type NavMode = "person" | "facility"

/** The bottom bar holds this many entries; anything past it goes under More. */
export const TAB_LIMIT = 6

export const MORE_PATH = "/more"

const HOME: NavItem = { to: "/home", label: "Home", icon: House }
const PLAY: NavItem = { to: "/play", label: "Play", icon: Swords }
const TRAINING: NavItem = { to: "/training", label: "Training", icon: BatIcon }
const RANKINGS: NavItem = { to: "/rankings", label: "Rankings", icon: Trophy }
const CLUB: NavItem = { to: "/club", label: "Club", icon: Users }
const COACHING: NavItem = { to: "/coaching", label: "Coaching", icon: GraduationCap }
const REGIONAL: NavItem = { to: "/regional", label: "Regional", icon: Map }
// The organizer's tournaments (hosted list, dashboards, New tournament) for whoever runs competitions in
// the active organization.
const TOURNAMENTS: NavItem = { to: "/club/tournaments", label: "Tournaments", icon: Medal }
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
    ...(competitions ? [TOURNAMENTS] : []),
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
  const { memberships, all, active } = useActiveMembership()
  const facility = actsAsFacility(active)
  const coach = useQuery({
    queryKey: coachingKeys.profile,
    queryFn: getMyCoachProfileOrNull,
    enabled: signedIn && !facility,
    staleTime: 5 * 60 * 1000,
  })

  const mode: NavMode = facility ? "facility" : "person"
  const organizer = !!active && !active.managedOnly && can(active, "competitions.manage")
  const roles = [
    ...(organizer ? [TOURNAMENTS] : []),
    ...(coach.data ? [COACHING] : []),
    ...(isOfficial(all) ? [REGIONAL] : []),
  ]
  // Until the memberships arrive we can't tell a facility from a person, so show no menu rather than the wrong one.
  const loading = signedIn && memberships.isPending
  const items = loading ? [] : facility && active ? facilityItems(active) : [HOME, PLAY, TRAINING, RANKINGS, ...roles, CLUB, PROFILE]

  // Keep the person's own record and their roles on the bar; the rest waits under More.
  const order = facility || loading ? items : [HOME, PLAY, TRAINING, ...roles, PROFILE, RANKINGS, CLUB]
  const fits = items.length <= TAB_LIMIT
  const tabs = fits ? items : order.slice(0, TAB_LIMIT - 1)
  const more = fits ? [] : items.filter((item) => !tabs.includes(item))
  return { signedIn, mode, active, items, tabs, more }
}
