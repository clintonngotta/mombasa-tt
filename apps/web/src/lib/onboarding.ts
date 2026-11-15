import { useCallback, useState } from "react"
import { api } from "@/lib/api"
import type { Page, Schemas } from "@/lib/schema"

export type Hand = Schemas["HandEnum"]
export type Grip = Schemas["GripEnum"]
export type Experience = Schemas["ExperienceEnum"]

export type ProfileDraft = {
  display_name: string
  nickname: string
  hand: Hand | ""
  grip: Grip | ""
  style: string
  experience: Experience | ""
  bio: string
}

export type Goal = Schemas["GoalsEnum"]

export type OnboardingDraft = {
  profile: ProfileDraft
  directoryOptIn: boolean
  goals: Goal[]
  joinRequests: Club[]
}

export type Club = Schemas["Organization"]

const STORAGE_KEY = "mombasa-tt:onboarding-draft"

const EMPTY_DRAFT: OnboardingDraft = {
  profile: { display_name: "", nickname: "", hand: "", grip: "", style: "", experience: "", bio: "" },
  directoryOptIn: false,
  goals: [],
  joinRequests: [],
}

function readDraft(): OnboardingDraft {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? { ...EMPTY_DRAFT, ...JSON.parse(raw) } : EMPTY_DRAFT
  } catch {
    return EMPTY_DRAFT
  }
}

/** Local copy so onboarding resumes where it stopped; the server copy stays authoritative. */
export function useOnboardingDraft() {
  const [draft, setDraft] = useState(readDraft)

  const update = useCallback((patch: Partial<OnboardingDraft>) => {
    setDraft((prev) => {
      const next = { ...prev, ...patch }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {
        // Storage can be unavailable (private mode); the in-memory draft still works.
      }
      return next
    })
  }, [])

  return [draft, update] as const
}

export function clearOnboardingDraft() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}

export const saveProfile = (profile: ProfileDraft) => api<void>("/me/profile/", { method: "PATCH", body: profile })

export const saveDiscovery = (directory_opt_in: boolean) =>
  api<void>("/me/profile/", { method: "PATCH", body: { directory_opt_in } })

// Goals only shape Home shortcuts; they never grant roles or touch ratings (REQ-006).
export const saveGoals = (goals: Goal[]) => api<void>("/me/goals/", { method: "PUT", body: { goals } })

export const searchClubs = (query: string) =>
  api<Page<Club>>(`/organizations/?search=${encodeURIComponent(query)}`)

export const requestToJoin = (organizationId: string) =>
  api<void>(`/organizations/${organizationId}/join-requests/`, { body: {} })

export const completeOnboarding = () => api<void>("/me/onboarding/complete/", { body: {} })
