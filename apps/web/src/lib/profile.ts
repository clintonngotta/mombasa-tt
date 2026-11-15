import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Profile = Schemas["Profile"]
export type ProfileUpdate = Schemas["PatchedProfileRequest"]
export type PublishedDetail = Schemas["PublishedDetailsEnum"]
export type Hand = Schemas["HandEnum"]
export type Grip = Schemas["GripEnum"]
export type Experience = Schemas["ExperienceEnum"]
export type Goal = Schemas["GoalsEnum"]
export type DirectoryPlayer = Schemas["DirectoryPlayer"]
export type Player = Schemas["Player"]

type Option<T extends string> = { value: T; label: string; description?: string }

export const HANDS: Option<Hand>[] = [
  { value: "right", label: "Right-handed" },
  { value: "left", label: "Left-handed" },
]

export const GRIPS: Option<Grip>[] = [
  { value: "shakehand", label: "Shakehand" },
  { value: "penhold", label: "Penhold" },
  { value: "other", label: "Other" },
]

export const EXPERIENCE: Option<Experience>[] = [
  { value: "new", label: "New to the game", description: "Learning the basics" },
  { value: "casual", label: "Casual", description: "Play for fun now and then" },
  { value: "club", label: "Club player", description: "Play regularly at a club" },
  { value: "competitive", label: "Competitive", description: "Enter leagues or tournaments" },
]

export const GOALS: Option<Goal>[] = [
  { value: "compete", label: "Play in tournaments", description: "Find events and get match calls" },
  { value: "rating", label: "Track my rating", description: "Follow singles and doubles Elo" },
  { value: "train", label: "Train regularly", description: "Plan sessions and drills" },
  { value: "find_club", label: "Find a club", description: "Join a club near me" },
  { value: "umpire", label: "Umpire matches", description: "Score matches I'm assigned" },
  { value: "organize", label: "Run a club or event", description: "Manage members and competitions" },
]

export const DETAIL_LABEL: Record<PublishedDetail, string> = {
  hand: "Playing hand",
  grip: "Grip",
  style: "Playing style",
  experience: "Experience",
  bio: "Bio",
}

const labelOf = <T extends string>(options: Option<T>[], value: T) => options.find((o) => o.value === value)?.label ?? value

/** Human text for a published detail value, e.g. "left" → "Left-handed". */
export function detailText(player: Player, detail: PublishedDetail): string | null {
  switch (detail) {
    case "hand":
      return player.hand ? labelOf(HANDS, player.hand) : null
    case "grip":
      return player.grip ? labelOf(GRIPS, player.grip) : null
    case "experience":
      return player.experience ? labelOf(EXPERIENCE, player.experience) : null
    case "style":
      return player.style ?? null
    case "bio":
      return player.bio ?? null
  }
}

export const profileKeys = {
  me: ["profile", "me"] as const,
  search: (term: string) => ["players", "search", term] as const,
  player: (id: string) => ["players", id] as const,
}

export const MIN_SEARCH_LENGTH = 2

export const getProfile = () => api<Profile>("/me/profile/")
export const updateProfile = (body: ProfileUpdate) => api<Profile>("/me/profile/", { method: "PATCH", body })
// Goals only shape Home shortcuts; they never grant roles or touch ratings (REQ-006).
export const saveGoals = (goals: Goal[]) => api<{ goals: Goal[] }>("/me/goals/", { method: "PUT", body: { goals } })
export const searchPlayers = (term: string) =>
  api<Schemas["PaginatedDirectoryPlayerList"]>(`/players/?search=${encodeURIComponent(term)}`)
export const getPlayer = (id: string) => api<Player>(`/players/${id}/`)
