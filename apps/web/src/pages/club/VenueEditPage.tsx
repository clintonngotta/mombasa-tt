import { useState, type FormEvent } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { addTable, createVenue, listVenues, updateTable, updateVenue, venueKeys, type Venue, type VenueTable } from "@/lib/venues"

/** Add a venue, or edit one and set up its tables (REQ-007). */
export function VenueEditPage() {
  const { id } = useParams()
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "facilities.manage")
  const venues = useQuery({ queryKey: venueKeys.list(orgId), queryFn: () => listVenues(orgId), enabled: allowed && !!id })
  const accessLost = useAdminAccessLost(venues.error)
  const venue = id && allowed && !accessLost ? venues.data?.find((v) => v.id === id) : undefined

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to="/club/venues">Venues and tables</BackLink>
      <h1 className="text-[32px] leading-9 font-bold break-words">{id ? (venue?.name ?? "Venue") : "New venue"}</h1>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {venues.isError && !accessLost && <FormAlert>{errorMessage(venues.error, "We couldn't load this venue.")}</FormAlert>}
      {id && allowed && venues.isSuccess && !venue && <FormAlert>This venue doesn't exist.</FormAlert>}
      {active && allowed && !accessLost && (!id || venue) && (
        <>
          <VenueForm key={venue?.id ?? "new"} orgId={orgId} venue={venue} />
          {venue && <Tables orgId={orgId} venue={venue} />}
        </>
      )}
    </div>
  )
}

/** Mutations here reply with the whole venue; put it in the cached list. */
function useVenueSaved(orgId: string) {
  const queryClient = useQueryClient()
  return (saved: Venue) => {
    queryClient.setQueryData<Venue[]>(venueKeys.list(orgId), (old) =>
      old ? (old.some((v) => v.id === saved.id) ? old.map((v) => (v.id === saved.id ? saved : v)) : [...old, saved]) : old
    )
    void queryClient.invalidateQueries({ queryKey: venueKeys.list(orgId) })
  }
}

function VenueForm({ orgId, venue }: { orgId: string; venue?: Venue }) {
  const navigate = useNavigate()
  const saved = useVenueSaved(orgId)
  const [name, setName] = useState(venue?.name ?? "")
  const [town, setTown] = useState(venue?.town ?? "")
  const [address, setAddress] = useState(venue?.address ?? "")
  const [justSaved, setJustSaved] = useState(false)

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), town: town.trim(), address: address.trim() }
      return venue ? updateVenue(orgId, venue.id, body) : createVenue(orgId, body)
    },
    onSuccess: (fresh) => {
      saved(fresh)
      if (venue) setJustSaved(true)
      else navigate(`/club/venues/${fresh.id}`, { replace: true })
    },
  })
  const setActive = useMutation({ mutationFn: (active: boolean) => updateVenue(orgId, venue!.id, { active }), onSuccess: saved })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setJustSaved(false)
    save.mutate()
  }

  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      {venue && !venue.active && (
        <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
          This venue is no longer in use. Tournaments already held here keep it; it isn't offered for new ones.
        </p>
      )}
      <Field label="Name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} hint="For example Makadara Hall" />
      <Field label="Town" required maxLength={80} value={town} onChange={(e) => setTown(e.target.value)} error={errors.town} />
      <Field
        label="Address"
        optional
        maxLength={200}
        value={address}
        onChange={(e) => setAddress(e.target.value)}
        error={errors.address}
        hint="Shown with tournaments held here so players can find it."
      />
      {save.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      {setActive.isError && <FormAlert>{errorMessage(setActive.error)}</FormAlert>}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="lg" disabled={save.isPending}>
          {save.isPending ? "Saving…" : venue ? "Save venue" : "Add venue"}
        </Button>
        {venue && (
          <Button type="button" variant="outline" disabled={setActive.isPending} onClick={() => setActive.mutate(!venue.active)}>
            {venue.active ? "Stop using this venue" : "Use this venue again"}
          </Button>
        )}
        {justSaved && (
          <span role="status" className="text-sm text-success">
            Saved.
          </span>
        )}
      </div>
    </form>
  )
}

function Tables({ orgId, venue }: { orgId: string; venue: Venue }) {
  const saved = useVenueSaved(orgId)
  const [label, setLabel] = useState("")
  const add = useMutation({
    mutationFn: (value: string) => addTable(orgId, venue.id, value),
    onSuccess: (fresh) => {
      setLabel("")
      saved(fresh)
    },
  })
  const toggle = useMutation({
    mutationFn: (table: VenueTable) => updateTable(orgId, venue.id, table.id, { active: !table.active }),
    onSuccess: saved,
  })

  function onAdd(e: FormEvent) {
    e.preventDefault()
    add.mutate(label.trim())
  }

  const labelError = add.error instanceof ApiError ? add.error.fieldErrors().label : undefined
  const next = `Table ${venue.tables.length + 1}`

  return (
    <section aria-labelledby="tables-heading" className="flex flex-col gap-3 border-t pt-6">
      <h2 id="tables-heading" className="text-2xl font-bold">
        Tables
      </h2>
      <p className="text-sm text-muted-foreground">
        Each physical table is listed once, in playing order. Matches are sent to these tables on the day.
      </p>
      {venue.tables.length === 0 && <p className="text-muted-foreground">No tables yet.</p>}
      {toggle.isError && <FormAlert>{errorMessage(toggle.error)}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {venue.tables.map((table) => (
          <li key={table.id} className={ROW}>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold break-words">{table.label}</span>
              {!table.active && <span className="text-sm text-muted-foreground">Not in use</span>}
            </span>
            <Button
              variant="outline"
              aria-label={`${table.active ? "Stop using" : "Use"} ${table.label}`}
              disabled={toggle.isPending && toggle.variables?.id === table.id}
              onClick={() => toggle.mutate(table)}
            >
              {table.active ? "Stop using" : "Use again"}
            </Button>
          </li>
        ))}
      </ul>
      <form onSubmit={onAdd} className="flex flex-col gap-3 rounded-xl border bg-card p-4" noValidate>
        <Field label="Add a table" required maxLength={40} placeholder={next} value={label} onChange={(e) => setLabel(e.target.value)} error={labelError} />
        {add.isError && !labelError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
        <Button type="submit" className="self-start" disabled={add.isPending}>
          {add.isPending ? "Adding…" : "Add table"}
        </Button>
      </form>
    </section>
  )
}
