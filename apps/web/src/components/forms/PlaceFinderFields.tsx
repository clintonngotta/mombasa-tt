import { useState } from "react"
import { Crosshair, MapPinned } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field } from "@/components/forms/Field"
import { TextAreaField } from "@/components/forms/SelectField"
import { coordinate, mapLink, type PlaceFinder, type SavedPlace } from "@/lib/place"

/*
 * How to find a club or venue on the ground: written directions from a landmark and the main road or
 * stage, plus map coordinates. Coordinates are kept as typed text until saved.
 */

/** "-4.0435, 39.6682" as copied from a map app, split into its two numbers. */
function splitPair(text: string) {
  const match = text.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)$/)
  return match ? { latitude: match[1], longitude: match[2] } : null
}

export function PlaceFinderFields({
  value,
  onChange,
  errors = {},
  place = "club",
}: {
  value: PlaceFinder
  onChange: (value: PlaceFinder) => void
  errors?: Record<string, string | undefined>
  /** Shown in the hints: "club" or "venue". */
  place?: string
}) {
  const [locating, setLocating] = useState(false)
  const [locateError, setLocateError] = useState("")
  const lat = coordinate(value.latitude)
  const lng = coordinate(value.longitude)
  const pinned = lat !== null && lng !== null && Number.isFinite(lat) && Number.isFinite(lng)

  function typeCoordinate(name: "latitude" | "longitude", text: string) {
    const pair = splitPair(text)
    onChange(pair ? { ...value, ...pair } : { ...value, [name]: text })
  }

  function useCurrentLocation() {
    if (!("geolocation" in navigator)) {
      setLocateError("This device can't share its location. Copy the coordinates from a map app instead.")
      return
    }
    setLocating(true)
    setLocateError("")
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setLocating(false)
        onChange({ ...value, latitude: coords.latitude.toFixed(6), longitude: coords.longitude.toFixed(6) })
      },
      () => {
        setLocating(false)
        setLocateError("We couldn't get your location. Allow location access, or copy the coordinates from a map app.")
      },
      { enableHighAccuracy: true, timeout: 15000 },
    )
  }

  return (
    <>
      <TextAreaField
        label="Directions"
        optional
        rows={3}
        maxLength={500}
        value={value.directions}
        onChange={(e) => onChange({ ...value, directions: e.target.value })}
        error={errors.directions}
        placeholder="e.g. Behind Makadara Grounds. From the Buxton stage on Jomo Kenyatta Avenue, walk 200 m towards the Total petrol station and turn left at the blue gate."
        hint={
          <>
            Help players find the {place}. Include:
            <span className="mt-1 block">• The closest landmark, such as a school, church, mosque, petrol station or supermarket.</span>
            <span className="block">• Directions from the main road or the nearest matatu or boda boda stage.</span>
            <span className="block">• Which gate, building or floor to use.</span>
          </>
        }
      />
      <fieldset className="flex flex-col gap-3">
        <legend className="text-base font-semibold">
          Map coordinates <span className="font-normal text-muted-foreground">(optional)</span>
        </legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Latitude"
            inputMode="decimal"
            placeholder="-4.0435"
            value={value.latitude}
            onChange={(e) => typeCoordinate("latitude", e.target.value)}
            error={errors.latitude}
          />
          <Field
            label="Longitude"
            inputMode="decimal"
            placeholder="39.6682"
            value={value.longitude}
            onChange={(e) => typeCoordinate("longitude", e.target.value)}
            error={errors.longitude}
          />
        </div>
        <p className="text-sm text-muted-foreground">
          Standing at the {place}? Use your current location. Otherwise, in Google Maps press and hold the spot, copy the two numbers
          (like -4.0435, 39.6682) and paste them into Latitude.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" disabled={locating} onClick={useCurrentLocation}>
            <Crosshair aria-hidden className="size-4" /> {locating ? "Finding you…" : "Use my current location"}
          </Button>
          {pinned && (
            <a href={mapLink(lat, lng)} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-sm font-semibold text-brand-blue underline-offset-4 hover:underline">
              <MapPinned aria-hidden className="size-4" /> Check it on the map
            </a>
          )}
        </div>
        {locateError && <p role="alert" className="text-sm text-destructive">{locateError}</p>}
      </fieldset>
    </>
  )
}


/** A place's directions and a map link, for anyone looking for it. Nothing when neither is set. */
export function PlaceDirections({ place, className }: { place: SavedPlace; className?: string }) {
  const pinned = place.latitude != null && place.longitude != null
  if (!place.directions && !pinned) return null
  return (
    <div className={className}>
      {place.directions && <p className="text-sm whitespace-pre-line">{place.directions}</p>}
      {pinned && (
        <a
          href={mapLink(place.latitude!, place.longitude!)}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 inline-flex items-center gap-1 text-sm font-semibold text-brand-blue underline-offset-4 hover:underline"
        >
          <MapPinned aria-hidden className="size-4" /> Open in Maps
        </a>
      )}
    </div>
  )
}
