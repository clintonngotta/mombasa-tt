/** How to find a club or venue: directions plus map coordinates, edited as text until saved. */

export type PlaceFinder = { directions: string; latitude: string; longitude: string }
export type SavedPlace = { directions?: string; latitude?: number | null; longitude?: number | null }

export const placeFinderFrom = (place?: SavedPlace): PlaceFinder => ({
  directions: place?.directions ?? "",
  latitude: place?.latitude?.toString() ?? "",
  longitude: place?.longitude?.toString() ?? "",
})

export const coordinate = (text: string) => (text.trim() === "" ? null : Number(text.trim()))

/** The body to send: trimmed directions and numeric coordinates, null when left empty. */
export const placeFinderBody = (value: PlaceFinder) => ({
  directions: value.directions.trim(),
  latitude: coordinate(value.latitude),
  longitude: coordinate(value.longitude),
})

/** What to fix before saving: a coordinate that isn't a number, out of range, or without its pair. */
export function placeFinderErrors(value: PlaceFinder): Partial<Record<"latitude" | "longitude", string>> {
  const errors: Partial<Record<"latitude" | "longitude", string>> = {}
  const check = (name: "latitude" | "longitude", limit: number, example: string) => {
    const n = coordinate(value[name])
    if (n !== null && (!Number.isFinite(n) || Math.abs(n) > limit)) errors[name] = `Enter a number between -${limit} and ${limit}, like ${example}.`
  }
  check("latitude", 90, "-4.0435")
  check("longitude", 180, "39.6682")
  const lat = value.latitude.trim()
  const lng = value.longitude.trim()
  if (lat && !lng && !errors.longitude) errors.longitude = "Enter the longitude too, or clear the latitude."
  if (lng && !lat && !errors.latitude) errors.latitude = "Enter the latitude too, or clear the longitude."
  return errors
}

export const mapLink = (latitude: number, longitude: number) => `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`
