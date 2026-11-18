import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { countryName, type Location } from "@/lib/geography"
import { api } from "@/lib/api"

type Option = { value: string; label: string }
type Region = { name: string; cities: string[] }
type Catalogue = { catalogue_only: boolean; regions: Region[] }

async function getOptions<T>(file: string): Promise<T> {
  const response = await fetch(`${import.meta.env.BASE_URL}geography/${file}.json`)
  if (!response.ok) throw new Error("Location data is unavailable.")
  return response.json()
}

async function countryOptions() {
  const [fallback, managed] = await Promise.allSettled([
    getOptions<Option[]>("countries"),
    api<Option[]>("/geography/countries/"),
  ])
  if (fallback.status === "rejected" && managed.status === "rejected") throw managed.reason
  return [...new Map([
    ...(fallback.status === "fulfilled" ? fallback.value : []),
    ...(managed.status === "fulfilled" ? managed.value : []),
  ].map((option) => [option.value, option])).values()].sort((a, b) => a.label.localeCompare(b.label))
}

async function countryRegions(code: string) {
  const managed = await api<Catalogue>(`/geography/countries/${encodeURIComponent(code)}/`).catch(() => null)
  if (managed?.catalogue_only) return managed.regions
  const known = await getOptions<Region[]>(code).catch(() => [] as Region[])
  const merged = new Map(known.map((region) => [region.name.toLowerCase(), region]))
  for (const region of managed?.regions ?? []) {
    const key = region.name.toLowerCase()
    const cities = [...new Set([...(merged.get(key)?.cities ?? []), ...region.cities])].sort()
    merged.set(key, { name: region.name, cities })
  }
  return [...merged.values()].sort((a, b) => a.name.localeCompare(b.name))
}

export function LocationFields({ value, onChange, errors = {}, cityLimit = 100 }: {
  value: Location
  onChange: (location: Location) => void
  errors?: Record<string, string>
  cityLimit?: number
}) {
  const [otherRegion, setOtherRegion] = useState(false)
  const [otherCity, setOtherCity] = useState(false)
  const countries = useQuery({
    queryKey: ["location-options", "countries"],
    queryFn: countryOptions,
  })
  const country = useQuery({
    queryKey: ["location-options", value.country],
    queryFn: () => countryRegions(value.country),
    enabled: !!value.country,
  })
  const regions = country.data ?? []
  const cities = regions.find((region) => region.name === value.region)?.cities ?? []

  function chooseRegion(region: string) {
    setOtherCity(false)
    onChange({ ...value, region, city: region === value.region ? value.city : "" })
  }

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-2 font-semibold">Location</legend>
      <SelectField
        label="Country"
        value={value.country}
        onChange={(code) => {
          setOtherRegion(false)
          setOtherCity(false)
          if (code !== value.country) onChange({ country: code, region: "", city: "" })
        }}
        options={countries.data ?? (value.country ? [{ value: value.country, label: countryName(value.country) }] : [])}
        placeholder={countries.isPending ? "Loading countries…" : "Choose a country"}
        disabled={countries.isPending}
        error={errors.country}
      />
      {countries.isError && <FormAlert>Countries could not be loaded. Refresh the page to try again.</FormAlert>}
      <div className="grid items-start gap-3 sm:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-1">
          {value.country && (otherRegion || country.isError || (country.isSuccess && regions.length === 0)) ? (
            <Field label="Region" autoComplete="address-level1" maxLength={100} value={value.region} onChange={(event) => chooseRegion(event.target.value)} error={errors.region} />
          ) : (
            <SelectField
              label="Region"
              value={value.region}
              onChange={chooseRegion}
              options={namedOptions(regions.map((region) => region.name), value.region)}
              placeholder={value.country && country.isPending ? "Loading regions…" : "Choose a region"}
              disabled={!value.country || country.isPending}
              error={errors.region}
            />
          )}
          {regions.length > 0 && (
            <Button type="button" variant="link" size="sm" className="self-start px-0" onClick={() => setOtherRegion(!otherRegion)}>
              {otherRegion ? "Choose a listed region" : "Enter another region"}
            </Button>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          {value.region && (otherCity || country.isError || (country.isSuccess && cities.length === 0)) ? (
            <Field label="City" autoComplete="address-level2" maxLength={cityLimit} value={value.city} onChange={(event) => onChange({ ...value, city: event.target.value })} error={errors.city ?? errors.town} />
          ) : (
            <SelectField
              label="City"
              value={value.city}
              onChange={(city) => onChange({ ...value, city })}
              options={namedOptions(cities.filter((city) => city.length <= cityLimit), value.city)}
              placeholder="Choose a city"
              disabled={!value.region || country.isPending}
              error={errors.city ?? errors.town}
            />
          )}
          {cities.length > 0 && (
            <Button type="button" variant="link" size="sm" className="self-start px-0" onClick={() => setOtherCity(!otherCity)}>
              {otherCity ? "Choose a listed city" : "Enter another city"}
            </Button>
          )}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Location data from the <a className="underline" href="https://github.com/dr5hn/countries-states-cities-database" target="_blank" rel="noreferrer">Countries States Cities Database</a> under <a className="underline" href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noreferrer">ODbL 1.0</a>.
      </p>
    </fieldset>
  )
}

function namedOptions(names: string[], current: string): Option[] {
  const values = new Set(names)
  if (current) values.add(current)
  return [...values].map((name) => ({ value: name, label: name }))
}
