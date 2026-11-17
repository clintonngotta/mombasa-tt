import { useCallback, useState } from "react"
import { api } from "@/lib/api"
import type { Organization } from "@/lib/clubs"
import type { Experience, Goal, Grip, Hand } from "@/lib/profile"

export type ProfileDraft = {
  display_name: string
  nickname: string
  hand: Hand | ""
  grip: Grip | ""
  style: string
  experience: Experience | ""
  bio: string
}

export type OnboardingDraft = {
  profile: ProfileDraft
  directoryOptIn: boolean
  goals: Goal[]
  joinRequests: Organization[]
}

const STORAGE_KEY = "mombasa-tt:onboarding-draft"

const EMPTY_DRAFT: OnboardingDraft = {
  profile: { display_name: "", nickname: "", hand: "", grip: "", style: "", experience: "", bio: "" },
  directoryOptIn: false,
  goals: [],
  joinRequests: [],
}

/** True while nothing has been typed into the profile step on this device. */
export const isBlankProfile = (profile: ProfileDraft) => Object.values(profile).every((value) => value === "")

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

export const completeOnboarding = () => api<void>("/me/onboarding/complete/", { body: {} })
