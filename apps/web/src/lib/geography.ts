export type Location = { country: string; region: string; city: string }

export const EMPTY_LOCATION: Location = { country: "", region: "", city: "" }

const countryNames = new Intl.DisplayNames("en", { type: "region" })

export function countryName(code: string): string {
  return /^[A-Z]{2}$/.test(code) ? countryNames.of(code) ?? code : code
}

export function locationErrors(location: Location): Record<string, string> {
  return Object.fromEntries(
    (["country", "region", "city"] as const)
      .filter((field) => !location[field].trim())
      .map((field) => [field, `Choose a ${field}.`]),
  )
}
