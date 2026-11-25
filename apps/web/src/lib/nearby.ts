import { useState } from "react"
import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

/** Finding clubs and places to play near the player (REQ-004, REQ-044). The position is held in memory
 * only, sent in a request body, and never put in a URL or saved on the device. */

export type NearbyClub = Schemas["NearbyOrganization"]
export type NearbyFacility = Schemas["NearbyFacility"]
export type Position = { latitude: number; longitude: number; accuracy: number }

/** How far to look, in metres. The API accepts 100 m to 50 km. */
export const RADII = [300, 1000, 5000, 10000, 25000] as const
export type Radius = (typeof RADII)[number]
export const DEFAULT_RADIUS: Radius = 5000

/** "300 m", "1 km", "2.4 km". */
export function formatDistance(metres: number) {
  if (metres < 1000) return `${Math.max(Math.round(metres / 10) * 10, 10)} m`
  const km = metres / 1000
  return `${km < 10 && !Number.isInteger(km) ? km.toFixed(1) : Math.round(km)} km`
}

const round = (degrees: number) => Number(degrees.toFixed(6))
const point = (position: Position, radius: Radius, name: string) => ({
  latitude: round(position.latitude),
  longitude: round(position.longitude),
  radius_m: radius,
  ...(name.trim() ? { search: name.trim() } : {}),
})

export const findClubsNear = (position: Position, radius: Radius, name: string) =>
  api<Schemas["NearbyOrganizations"]>("/organizations/nearby/", { body: point(position, radius, name) })
export const findFacilitiesNear = (position: Position, radius: Radius, name: string, openNow: boolean) =>
  api<Schemas["NearbyFacilities"]>("/facilities/nearby/", { body: { ...point(position, radius, name), open_now: openNow } })

const WHY: Record<number, string> = {
  1: "Location is switched off for this site. Allow it in your browser's site settings, or search by city instead.",
  2: "Your device couldn't work out where it is. Try again outdoors or near a window, or search by city.",
  3: "Finding your location took too long. Try again, or search by city.",
}

/** The device's position, asked for once. Rejects with a sentence the page can show. */
export function locate(): Promise<Position> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("This browser can't share a location. Search by city instead."))
      return
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => resolve({ latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy }),
      (error) => reject(new Error(WHY[error.code] ?? WHY[2])),
      // A 300 m search needs the precise fix; a minute-old one is fine while the player stands still.
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 60_000 },
    )
  })
}

export type NearMe = {
  position: Position | null
  radius: Radius
  locating: boolean
  error: string
  /** A key for the search: changes whenever the place or distance does, without holding the coordinates. */
  stamp: number
  start: () => void
  stop: () => void
  setRadius: (radius: Radius) => void
}

/** "Near me" for a finder page: asks for the position on demand and remembers it only while the page is open. */
export function useNearMe(): NearMe {
  const [position, setPosition] = useState<Position | null>(null)
  const [radius, setRadius] = useState<Radius>(DEFAULT_RADIUS)
  const [locating, setLocating] = useState(false)
  const [error, setError] = useState("")
  const [stamp, setStamp] = useState(0)

  function start() {
    setLocating(true)
    setError("")
    locate()
      .then((found) => {
        setPosition(found)
        setStamp((n) => n + 1)
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLocating(false))
  }

  return {
    position,
    radius,
    locating,
    error,
    stamp,
    start,
    stop: () => {
      setPosition(null)
      setError("")
    },
    setRadius,
  }
}
