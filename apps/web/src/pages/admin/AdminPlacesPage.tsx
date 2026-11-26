import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { Toggle } from "@/components/forms/Toggle"
import { api, errorMessage } from "@/lib/api"
import {
  addCity,
  addRegion,
  getCountry,
  platformKeys,
  removeCity,
  removeRegion,
  renameCity,
  renameRegion,
  setCatalogueOnly,
  type PlatformRegion,
} from "@/lib/platform"

type Option = { value: string; label: string }

/** One place's name with Rename and Remove. Removing asks first; a place still in use is refused by the
 * API, and its message says to rename instead. */
function Place({ kind, name, onRename, onRemove, onDone }: { kind: string; name: string; onRename: (name: string) => Promise<unknown>; onRemove: () => Promise<unknown>; onDone: () => Promise<unknown> }) {
  const [mode, setMode] = useState<"view" | "rename" | "remove">("view")
  const [draft, setDraft] = useState(name)
  const act = useMutation({
    mutationFn: () => (mode === "rename" ? onRename(draft.trim()) : onRemove()),
    onSuccess: async () => {
      setMode("view")
      await onDone()
    },
  })
  const back = () => { setMode("view"); setDraft(name); act.reset() }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (draft.trim() === name) back()
    else act.mutate()
  }

  if (mode === "view") {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 break-words">{name}</span>
        <Button variant="ghost" aria-label={`Rename ${name}`} onClick={() => setMode("rename")}>
          Rename
        </Button>
        <Button variant="ghost" aria-label={`Remove ${name}`} onClick={() => setMode("remove")}>
          Remove
        </Button>
      </div>
    )
  }
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2 rounded-lg border bg-background p-3">
      {mode === "rename" ? (
        <Input aria-label={`New name for ${name}`} autoFocus required minLength={2} maxLength={100} value={draft} onChange={(e) => setDraft(e.target.value)} />
      ) : (
        <p>
          Remove the {kind} {name} from the list?
        </p>
      )}
      {mode === "rename" && <p className="text-sm text-muted-foreground">Clubs and players there move to the new name.</p>}
      {act.isError && <FormAlert>{errorMessage(act.error, `We couldn't change the ${kind}.`)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        {mode === "rename" ? (
          <Button type="submit" disabled={act.isPending || draft.trim().length < 2}>
            {act.isPending ? "Saving…" : "Save name"}
          </Button>
        ) : (
          <Button type="button" variant="destructive" disabled={act.isPending} onClick={() => act.mutate()}>
            {act.isPending ? "Removing…" : "Remove"}
          </Button>
        )}
        <Button type="button" variant="outline" disabled={act.isPending} onClick={back}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function AddPlace({ label, placeholder, onAdd, onDone }: { label: string; placeholder: string; onAdd: (name: string) => Promise<unknown>; onDone: () => Promise<unknown> }) {
  const [name, setName] = useState("")
  const add = useMutation({
    mutationFn: () => onAdd(name.trim()),
    onSuccess: async () => {
      setName("")
      await onDone()
    },
  })
  function onSubmit(event: FormEvent) {
    event.preventDefault()
    add.mutate()
  }
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <Input aria-label={label} placeholder={placeholder} maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" variant="outline" className="h-12" disabled={add.isPending || name.trim().length < 2}>
          {add.isPending ? "Adding…" : "Add"}
        </Button>
      </div>
      {add.isError && <FormAlert>{errorMessage(add.error, "We couldn't add it.")}</FormAlert>}
    </form>
  )
}

function Region({ region, onDone }: { region: PlatformRegion; onDone: () => Promise<unknown> }) {
  return (
    <li className="rounded-xl border bg-card">
      <details className="group">
        <summary className="flex min-h-12 cursor-pointer items-center justify-between gap-3 rounded-xl px-4 py-2 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <span className="min-w-0 break-words">{region.name}</span>
          <span className="shrink-0 text-sm font-normal text-muted-foreground">
            {region.cities.length} {region.cities.length === 1 ? "town" : "towns"}
          </span>
        </summary>
        <div className="flex flex-col gap-3 border-t p-4">
          <Place kind="region" name={region.name} onRename={(name) => renameRegion(region.id, name)} onRemove={() => removeRegion(region.id)} onDone={onDone} />
          <h3 className="text-sm font-semibold text-muted-foreground">Towns</h3>
          {region.cities.length === 0 && <p className="text-sm text-muted-foreground">No towns listed yet.</p>}
          <ul className="flex flex-col divide-y">
            {region.cities.map((city) => (
              <li key={city.id} className="py-1">
                <Place kind="town" name={city.name} onRename={(name) => renameCity(city.id, name)} onRemove={() => removeCity(city.id)} onDone={onDone} />
              </li>
            ))}
          </ul>
          <AddPlace label={`New town in ${region.name}`} placeholder="Add a town" onAdd={(name) => addCity(region.id, name)} onDone={onDone} />
        </div>
      </details>
    </li>
  )
}

/** The place catalogue: each country's regions and towns, the choices offered at sign-up, club setup and
 * in rankings by place. Renaming a place moves its clubs and players with it. */
export function AdminPlacesPage() {
  const queryClient = useQueryClient()
  const [code, setCode] = useState("KE")
  const countries = useQuery({ queryKey: ["catalogue", "countries"], queryFn: () => api<Option[]>("/geography/countries/") })
  const country = useQuery({ queryKey: platformKeys.country(code), queryFn: () => getCountry(code), enabled: !!code })
  // The pickers elsewhere in the app read the same catalogue, so they are refreshed too.
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: platformKeys.country(code) }), queryClient.invalidateQueries({ queryKey: ["catalogue"] })])
  const listedOnly = useMutation({ mutationFn: (on: boolean) => setCatalogueOnly(code, on), onSuccess: refresh })

  return (
    <div className="flex max-w-[720px] flex-col gap-5">
      <SelectField
        label="Country"
        value={code}
        onChange={setCode}
        options={countries.data ?? []}
        placeholder={countries.isPending ? "Loading countries…" : "Choose a country"}
        disabled={countries.isPending}
      />
      {country.isPending && <p className="text-muted-foreground">Loading…</p>}
      {country.isError && <FormAlert>{errorMessage(country.error, "We couldn't load this country's places.")}</FormAlert>}
      {country.isSuccess && (
        <>
          <Toggle
            checked={country.data.catalogue_only}
            onChange={(on) => listedOnly.mutate(on)}
            label="Listed places only"
            description={`On: people in ${country.data.name} choose a region from this list. Off: they may also type one that isn't listed.`}
          />
          {listedOnly.isError && <FormAlert>{errorMessage(listedOnly.error, "We couldn't save that.")}</FormAlert>}
          <section aria-labelledby="regions-heading" className="flex flex-col gap-3">
            <h2 id="regions-heading" className="text-xl font-bold">
              Regions ({country.data.regions.length})
            </h2>
            {country.data.regions.length === 0 && <p className="text-muted-foreground">No regions listed for {country.data.name} yet.</p>}
            <ul className="flex flex-col gap-2">
              {country.data.regions.map((region) => (
                <Region key={region.id} region={region} onDone={refresh} />
              ))}
            </ul>
            <AddPlace label={`New region in ${country.data.name}`} placeholder="Add a region" onAdd={(name) => addRegion(code, name)} onDone={refresh} />
          </section>
        </>
      )}
    </div>
  )
}
