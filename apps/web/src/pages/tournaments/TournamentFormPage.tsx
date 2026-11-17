import { useId, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership, useMemberships } from "@/lib/clubs"
import { DEFAULT_TIME_ZONE, timeZones } from "@/lib/dates"
import { canManageTournament, createTournament, getTournament, isClosed, tournamentKeys, updateTournament, type Tournament } from "@/lib/tournaments"
import { listVenues, venueKeys } from "@/lib/venues"

/** Create a draft tournament for the active organization, or edit one (REQ-007). */
export function TournamentFormPage() {
  const { id } = useParams()
  const { memberships, active } = useActiveMembership()
  const { results: all } = useMemberships()
  const existing = useQuery({ queryKey: tournamentKeys.detail(id ?? ""), queryFn: () => getTournament(id!), enabled: !!id })
  const t = existing.data
  const organization = id ? t?.organization : active?.organization
  const allowed = id ? !!t && canManageTournament(all, t) : can(active, "competitions.manage")
  const closed = !!t && isClosed(t)
  const defaultZone = active?.organization.timezone ?? DEFAULT_TIME_ZONE

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to={id ? `/tournaments/${id}` : "/club/tournaments"}>{id ? (t?.name ?? "Tournament") : "Tournaments"}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">{id ? "Edit tournament" : "New tournament"}</h1>
        {organization && <p className="text-muted-foreground">Hosted by {organization.name}</p>}
      </div>
      {existing.isError && <FormAlert>{errorMessage(existing.error, "We couldn't load this tournament.")}</FormAlert>}
      {memberships.isSuccess && (!id || t) && !allowed && <AccessLost />}
      {closed && <FormAlert>This tournament is over and can't be changed.</FormAlert>}
      {organization && allowed && !closed && (!id || t) && (
        <TournamentForm key={t?.id ?? "new"} orgId={organization.id} tournament={t} defaultZone={defaultZone} />
      )}
    </div>
  )
}

function TournamentForm({ orgId, tournament: t, defaultZone }: { orgId: string; tournament?: Tournament; defaultZone: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const zonesId = useId()
  const venues = useQuery({ queryKey: venueKeys.list(orgId), queryFn: () => listVenues(orgId) })
  const [name, setName] = useState(t?.name ?? "")
  const [description, setDescription] = useState(t?.description ?? "")
  const [startsOn, setStartsOn] = useState(t?.starts_on ?? "")
  const [endsOn, setEndsOn] = useState(t?.ends_on ?? "")
  const [venueId, setVenueId] = useState(t?.venue?.id ?? "")
  const [zone, setZone] = useState(t?.timezone ?? defaultZone)
  const started = t?.status === "in_progress"

  // Venues in use, plus the one this tournament already has even if it was switched off since.
  const choices = (venues.data ?? []).filter((venue) => venue.active || venue.id === t?.venue?.id)

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(),
        description: description.trim(),
        // An empty date is left out, so the server answers "required" instead of "wrong format".
        starts_on: (startsOn || undefined) as string,
        ends_on: (endsOn || startsOn || undefined) as string,
        venue_id: venueId || null,
        ...(started ? {} : { timezone: zone.trim() }),
      }
      return t ? updateTournament(t.id, body) : createTournament(orgId, body)
    },
    onSuccess: async (saved) => {
      queryClient.setQueryData(tournamentKeys.detail(saved.id), saved)
      await queryClient.invalidateQueries({ queryKey: tournamentKeys.all, refetchType: "active" })
      navigate(`/tournaments/${saved.id}`)
    },
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      <Field label="Name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="First day" type="date" required value={startsOn} onChange={(e) => setStartsOn(e.target.value)} error={errors.starts_on} />
        <Field
          label="Last day"
          type="date"
          min={startsOn || undefined}
          value={endsOn}
          onChange={(e) => setEndsOn(e.target.value)}
          error={startsOn ? errors.ends_on : undefined}
          hint="Leave empty for a one-day tournament."
        />
      </div>
      <SelectField
        label="Venue"
        value={venueId}
        onChange={(e) => setVenueId(e.target.value)}
        error={errors.venue_id}
        hint={
          venues.isSuccess && choices.length === 0 ? (
            <>
              No venues yet. <Link to="/club/venues" className="font-semibold text-brand-blue underline">Add a venue</Link> first; a tournament needs one to be published.
            </>
          ) : (
            "Needed before publishing."
          )
        }
      >
        {/* Once published a tournament keeps a venue; it can move, not lose it. */}
        {(!t || t.status === "draft" || !t.venue) && <option value="">Not decided yet</option>}
        {choices.map((venue) => (
          <option key={venue.id} value={venue.id}>
            {venue.name}, {venue.town}
          </option>
        ))}
      </SelectField>
      {venues.isError && <FormAlert>{errorMessage(venues.error, "We couldn't load your venues.")}</FormAlert>}
      <Field
        label="Timezone"
        list={zonesId}
        required
        disabled={started}
        value={zone}
        onChange={(e) => setZone(e.target.value)}
        error={errors.timezone}
        hint={started ? "Fixed once the tournament has started." : "Dates and times are entered and shown in this timezone."}
      />
      <datalist id={zonesId}>
        {timeZones().map((tz) => (
          <option key={tz} value={tz} />
        ))}
      </datalist>
      <TextAreaField
        label="Description"
        optional
        maxLength={2000}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        error={errors.description}
        hint="Shown to everyone once published."
      />
      {save.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <Button type="submit" size="lg" disabled={save.isPending}>
        {save.isPending ? "Saving…" : t ? "Save tournament" : "Create draft"}
      </Button>
      {!t && <p className="text-sm text-muted-foreground">A draft is seen only by people who run competitions for your club, until you publish it.</p>}
    </form>
  )
}
