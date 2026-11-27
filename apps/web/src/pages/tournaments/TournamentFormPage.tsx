import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useId, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership, useMemberships } from "@/lib/clubs"
import { coachingKeys, getMyCoachProfile } from "@/lib/coaching"
import { DEFAULT_TIME_ZONE, timeZones } from "@/lib/dates"
import { SCOPE_OPTIONS, canManageTournament, createTournament, getTournament, isClosed, tournamentKeys, updateTournament, type Tournament, type TournamentScope } from "@/lib/tournaments"
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
  const coachDesk = id ? t?.organizer.kind === "coach" || t?.organizer.kind === "firm" : active?.organization.kind === "coaching"

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to={id ? `/tournaments/${id}` : "/club/tournaments"}>{id ? (t?.name ?? "Tournament") : "Tournaments"}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">{id ? "Edit tournament" : "New tournament"}</h1>
        {organization && <p className="text-muted-foreground">{t ? `Organized by ${t.organizer.name}` : coachDesk ? "Organized from your coaching desk" : `Organized by ${organization.name}`}</p>}
      </div>
      {existing.isError && <FormAlert>{errorMessage(existing.error, "We couldn't load this tournament.")}</FormAlert>}
      {memberships.isSuccess && (!id || t) && !allowed && <AccessLost />}
      {closed && <FormAlert>This tournament is over and can't be changed.</FormAlert>}
      {organization && allowed && !closed && (!id || t) && (
        <TournamentForm key={t?.id ?? "new"} orgId={organization.id} coachDesk={coachDesk} tournament={t} defaultZone={defaultZone} />
      )}
    </div>
  )
}

function TournamentForm({ orgId, coachDesk, tournament: t, defaultZone }: { orgId: string; coachDesk: boolean; tournament?: Tournament; defaultZone: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const zonesId = useId()
  const venues = useQuery({ queryKey: venueKeys.list(orgId), queryFn: () => listVenues(orgId) })
  const draft = useDraft(`tournament:${t?.id ?? "new"}`)
  const [name, setName] = useDraftState(draft, "name", t?.name ?? "")
  const [description, setDescription] = useDraftState(draft, "description", t?.description ?? "")
  const [startsOn, setStartsOn] = useDraftState(draft, "startsOn", t?.starts_on ?? "")
  const [endsOn, setEndsOn] = useDraftState(draft, "endsOn", t?.ends_on ?? "")
  const [venueId, setVenueId] = useDraftState(draft, "venueId", t?.venue?.id ?? "")
  const [zone, setZone] = useDraftState(draft, "zone", t?.timezone ?? defaultZone)
  const [scope, setScope] = useDraftState<TournamentScope>(draft, "scope", t?.scope ?? "local")
  // A coach's tournament is organized in their own name or their firm's.
  const coach = useQuery({ queryKey: coachingKeys.profile, queryFn: getMyCoachProfile, enabled: coachDesk })
  const [params] = useSearchParams()
  const [presentedAs, setPresentedAs] = useDraftState<"coach" | "firm">(draft, "presentedAs", (t ? t.presented_as : params.get("as")) === "firm" ? "firm" : "coach")
  const firm = coach.data?.firm_name ?? ""
  const [paid, setPaid] = useDraftState(draft, "paid", (t?.registration_fee.amount_minor ?? 0) > 0)
  const [fee, setFee] = useDraftState(draft, "fee", t?.registration_fee.amount_minor ? String(t.registration_fee.amount_minor / 100) : "")
  const [currency, setCurrency] = useDraftState(draft, "currency", t?.registration_fee.currency ?? "KES")
  const [feeError, setFeeError] = useState("")
  const started = t?.status === "in_progress"
  const scopeFrozen = !!t && t.status !== "draft"

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
        registration_fee: { amount_minor: paid ? Math.round(Number(fee) * 100) : 0, currency },
        ...(started ? {} : { timezone: zone.trim() }),
        ...(scopeFrozen ? {} : { scope }),
        ...(coachDesk ? { presented_as: presentedAs } : {}),
      }
      return t ? updateTournament(t.id, body) : createTournament(orgId, body)
    },
    onSuccess: async (saved) => {
      draft.clear()
      queryClient.setQueryData(tournamentKeys.detail(saved.id), saved)
      await queryClient.invalidateQueries({ queryKey: tournamentKeys.all, refetchType: "active" })
      navigate(`/tournaments/${saved.id}`)
    },
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const amount = Math.round(Number(fee) * 100)
    if (paid && (!Number.isFinite(amount) || amount < 1)) {
      setFeeError("Enter a registration fee greater than zero.")
      return
    }
    setFeeError("")
    save.mutate()
  }

  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      <Field label="Name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
      {coachDesk && (
        <SelectField
          label="Organize as"
          value={presentedAs}
          onChange={(value) => setPresentedAs(value as "coach" | "firm")}
          options={[
            { value: "coach", label: coach.data ? `Myself, as a coach (${coach.data.user.display_name})` : "Myself, as a coach" },
            ...(firm ? [{ value: "firm", label: `My firm (${firm})` }] : []),
          ]}
          error={errors.presented_as}
          hint={firm ? "Players see this name as the organizer." : "Add your company or firm to your coach profile to organize in its name."}
        />
      )}
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
        onChange={setVenueId}
        options={[
          ...(!t || t.status === "draft" || !t.venue ? [{ value: "", label: "Not decided yet" }] : []),
          ...choices.map((venue) => ({ value: venue.id, label: `${venue.name}, ${venue.town}` })),
        ]}
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
      />
      {venues.isError && <FormAlert>{errorMessage(venues.error, "We couldn't load your venues.")}</FormAlert>}
      <SelectField
        label="Tournament scope"
        value={scope}
        onChange={(value) => setScope(value as TournamentScope)}
        options={SCOPE_OPTIONS}
        disabled={scopeFrozen}
        error={errors.scope}
        hint={scopeFrozen ? "Fixed after publication." : "The level this tournament is played at."}
      />
      <SelectField
        label="Registration cost"
        value={paid ? "paid" : "free"}
        onChange={(value) => { setPaid(value === "paid"); setFeeError("") }}
        options={[{ value: "free", label: "Free" }, { value: "paid", label: "Paid" }]}
      />
      {paid && <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Registration fee" type="number" inputMode="decimal" min="0.01" step="0.01" value={fee}
          onChange={(event) => setFee(event.target.value)} error={feeError || errors["registration_fee.amount_minor"]} />
        <Field label="Currency code" hint="For example KES." value={currency} maxLength={3} onChange={(event) => setCurrency(event.target.value.toUpperCase())}
          error={errors["registration_fee.currency"]} />
      </div>}
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
      <DraftBar draft={draft} label="Finish later" />
      {!t && <p className="text-sm text-muted-foreground">Only your competition staff see a draft. Next you add events, then publish it for players.</p>}
    </form>
  )
}
