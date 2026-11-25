import { useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, Plus, Shield, Trash2, UserMinus, UserPlus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { can, useActiveMembership } from "@/lib/clubs"
import { formatDay } from "@/lib/dates"
import {
  answerPlace,
  createSquad,
  deleteSquad,
  getRotation,
  getSquad,
  getSquadHistory,
  listMyPlaces,
  listSquads,
  pickPlayer,
  PLACE_STATUS,
  publishSquad,
  removePlace,
  squadKeys,
  type MySquadPlace,
  type Squad,
  type SquadCandidate,
} from "@/lib/squads"
import { cn } from "@/lib/utils"

const FOCUS = "outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
type SlotDraft = { label: string; places: string }

/** Squads for tournaments away from Coast TT (REQ-050), for whoever runs competitions: the list, a new
 * squad with its slots, and who has represented so far. */
export function SquadsPage() {
  const { active } = useActiveMembership()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "competitions.manage")
  const squads = useQuery({ queryKey: squadKeys.list(orgId), queryFn: () => listSquads(orgId), enabled: allowed, staleTime: 0 })
  const history = useQuery({ queryKey: squadKeys.history(orgId), queryFn: () => getSquadHistory(orgId), enabled: allowed })
  const [adding, setAdding] = useState(false)
  const [title, setTitle] = useState("")
  const [starts, setStarts] = useState("")
  const [ends, setEnds] = useState("")
  const [slots, setSlots] = useState<SlotDraft[]>([{ label: "", places: "4" }])
  const create = useMutation({
    mutationFn: () =>
      createSquad(orgId, {
        title: title.trim(),
        starts_on: starts,
        ends_on: ends || starts,
        slots: slots.filter((slot) => slot.label.trim()).map((slot) => ({ label: slot.label.trim(), places: Number(slot.places) || 1 })),
      }),
    onSuccess: async (squad) => {
      await queryClient.invalidateQueries({ queryKey: squadKeys.all })
      navigate(`/club/squads/${squad.id}`)
    },
  })
  const fields: Record<string, string | undefined> = create.error instanceof ApiError ? create.error.fieldErrors() : {}

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">{active?.organization.name ?? "Club"}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Squads</h1>
        <p className="text-muted-foreground">Who represents {active?.organization.name ?? "us"} at tournaments run elsewhere.</p>
      </div>
      {!allowed && <FormAlert>Squads are picked by whoever runs competitions.</FormAlert>}
      {squads.isError && <FormAlert>{errorMessage(squads.error, "We couldn't load the squads.")}</FormAlert>}
      {allowed && squads.isSuccess && (
        <>
          {squads.data.length === 0 && <p className="text-muted-foreground">No squads yet.</p>}
          <ul className="flex flex-col gap-2">
            {squads.data.map((squad) => {
              const going = squad.places.filter((place) => place.status === "accepted").length
              const total = squad.slots.reduce((sum, slot) => sum + slot.places, 0)
              return (
                <li key={squad.id}>
                  <Link to={`/club/squads/${squad.id}`} className={cn(ROW, FOCUS)}>
                    <Shield aria-hidden className="size-5 text-brand-blue" />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate font-semibold">{squad.title}</span>
                      <span className="text-sm text-muted-foreground">
                        {formatDay(squad.starts_on)} · {squad.status === "draft" ? "Draft" : `${going} of ${total} going`}
                      </span>
                    </span>
                    <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
                  </Link>
                </li>
              )
            })}
          </ul>
          {!adding ? (
            <Button className="self-start" onClick={() => setAdding(true)}>
              <Plus aria-hidden className="size-4" /> New squad
            </Button>
          ) : (
            <form
              onSubmit={(e: FormEvent) => {
                e.preventDefault()
                create.mutate()
              }}
              className="flex flex-col gap-4 rounded-xl border bg-card p-4"
            >
              <h2 className="text-xl font-bold">New squad</h2>
              {create.isError && <FormAlert>{fields.slots ?? errorMessage(create.error, "We couldn't save the squad.")}</FormAlert>}
              <Field label="Tournament" maxLength={120} placeholder="Nairobi Open" value={title} onChange={(e) => setTitle(e.target.value)} error={fields.title} />
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Starts" type="date" value={starts} onChange={(e) => setStarts(e.target.value)} error={fields.starts_on} />
                <Field label="Ends" optional type="date" value={ends} onChange={(e) => setEnds(e.target.value)} error={fields.ends_on} />
              </div>
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-1 font-semibold">Slots</legend>
                {slots.map((slot, i) => (
                  <div key={i} className="grid items-end gap-2 sm:grid-cols-[1fr_7rem_auto]">
                    <Field label={`Slot ${i + 1}`} maxLength={60} placeholder="Men's team" value={slot.label} onChange={(e) => setSlots(slots.map((s, j) => (j === i ? { ...s, label: e.target.value } : s)))} />
                    <Field label="Players" type="number" min={1} max={30} inputMode="numeric" value={slot.places} onChange={(e) => setSlots(slots.map((s, j) => (j === i ? { ...s, places: e.target.value } : s)))} />
                    <Button type="button" variant="outline" size="icon" aria-label={`Remove slot ${i + 1}`} disabled={slots.length === 1} onClick={() => setSlots(slots.filter((_, j) => j !== i))}>
                      <Trash2 aria-hidden className="size-5" />
                    </Button>
                  </div>
                ))}
                <Button type="button" variant="ghost" className="self-start" disabled={slots.length >= 12} onClick={() => setSlots([...slots, { label: "", places: "2" }])}>
                  <Plus aria-hidden className="size-4" /> Add a slot
                </Button>
              </fieldset>
              <p className="text-sm text-muted-foreground">It's a draft: nobody is told until you publish it.</p>
              <div className="flex gap-2">
                <Button type="submit" disabled={!title.trim() || !starts || !slots.some((slot) => slot.label.trim()) || create.isPending}>
                  {create.isPending ? "Saving…" : "Save draft"}
                </Button>
                <Button type="button" variant="outline" onClick={() => setAdding(false)}>
                  Cancel
                </Button>
              </div>
            </form>
          )}
          {(history.data?.length ?? 0) > 0 && (
            <section aria-labelledby="history-heading" className="flex flex-col gap-2">
              <h2 id="history-heading" className="text-xl font-bold">
                Who has represented
              </h2>
              <ul className="flex flex-col gap-1">
                {history.data!.map((row) => (
                  <li key={row.user_id} className="rounded-lg border bg-card px-3 py-2">
                    <span className="font-semibold">{row.display_name}</span>
                    {row.club && <span className="text-muted-foreground"> · {row.club}</span>}
                    <span className="block text-sm text-muted-foreground">
                      {row.times} {row.times === 1 ? "time" : "times"}
                      {row.last_represented_on && `, last ${formatDay(row.last_represented_on)}`} · {row.squads.join(", ")}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}

/** One squad for the selectors: who holds each slot, and the rotation to pick the next players from. */
export function SquadPage() {
  const { id = "" } = useParams()
  const { active } = useActiveMembership()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const orgId = active?.organization.id ?? ""
  // Players answer while the selector looks, so read fresh each time.
  const squad = useQuery({ queryKey: squadKeys.detail(orgId, id), queryFn: () => getSquad(orgId, id), enabled: !!orgId, staleTime: 0, retry: false })
  const rotation = useQuery({ queryKey: squadKeys.rotation(orgId, id), queryFn: () => getRotation(orgId, id), enabled: !!orgId, staleTime: 0, retry: false })
  const settle = (fresh: Squad) => {
    queryClient.setQueryData(squadKeys.detail(orgId, id), fresh)
    void queryClient.invalidateQueries({ queryKey: squadKeys.rotation(orgId, id) })
    void queryClient.invalidateQueries({ queryKey: squadKeys.list(orgId) })
  }
  const publish = useMutation({ mutationFn: () => publishSquad(orgId, id), onSuccess: settle })
  const remove = useMutation({ mutationFn: (placeId: string) => removePlace(orgId, id, placeId), onSuccess: settle })
  const discard = useMutation({
    mutationFn: () => deleteSquad(orgId, id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: squadKeys.all })
      navigate("/club/squads")
    },
  })
  const s = squad.data
  const failed = publish.error ?? remove.error ?? discard.error

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club/squads">Squads</BackLink>
      {squad.isError && <FormAlert>{errorMessage(squad.error, "Squads are picked by whoever runs competitions.")}</FormAlert>}
      {s && (
        <>
          <div className="flex flex-col gap-1">
            <h1 className="text-[32px] leading-9 font-bold">{s.title}</h1>
            <p className="text-muted-foreground">
              {formatDay(s.starts_on)}
              {s.ends_on !== s.starts_on && ` to ${formatDay(s.ends_on)}`} · {s.status === "draft" ? "Draft: nobody has been told" : "Published: players are told and answer"}
            </p>
          </div>
          {failed && <FormAlert>{errorMessage(failed)}</FormAlert>}
          {s.slots.map((slot) => {
            const held = s.places.filter((place) => place.slot === slot.id && (place.status === "picked" || place.status === "accepted"))
            const gone = s.places.filter((place) => place.slot === slot.id && (place.status === "declined" || place.status === "removed"))
            return (
              <section key={slot.id} aria-label={slot.label} className="flex flex-col gap-2 rounded-xl border bg-card p-4">
                <h2 className="text-xl font-bold">
                  {slot.label}{" "}
                  <span className="text-base font-normal text-muted-foreground">
                    {held.length} of {slot.places}
                  </span>
                </h2>
                {held.length === 0 && <p className="text-muted-foreground">Nobody picked yet.</p>}
                <ul className="flex flex-col gap-2">
                  {held.map((place) => (
                    <li key={place.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2">
                      <span className="min-w-0">
                        <span className="font-semibold">{place.display_name}</span>
                        {place.club && <span className="text-muted-foreground"> · {place.club}</span>}
                        <span className="block text-sm text-muted-foreground">
                          {s.status === "draft" ? "Picked" : PLACE_STATUS[place.status]}
                          {!place.recommended && ` · out of turn: ${place.override_reason}`}
                        </span>
                      </span>
                      <Button size="sm" variant="outline" disabled={remove.isPending} onClick={() => remove.mutate(place.id)}>
                        <UserMinus aria-hidden className="size-4" /> Take out
                      </Button>
                    </li>
                  ))}
                </ul>
                {gone.length > 0 && <p className="text-sm text-muted-foreground">{gone.map((place) => `${place.display_name} (${PLACE_STATUS[place.status].toLowerCase()})`).join(", ")}</p>}
                {held.length < slot.places && rotation.data && <Rotation orgId={orgId} squad={s} slotId={slot.id} free={slot.places - held.length} candidates={rotation.data} onPicked={settle} />}
              </section>
            )
          })}
          <div className="flex flex-wrap gap-2">
            {s.status === "draft" && (
              <>
                <Button disabled={publish.isPending || !s.places.some((place) => place.status === "picked")} onClick={() => publish.mutate()}>
                  {publish.isPending ? "Publishing…" : "Publish and tell the players"}
                </Button>
                <Button variant="outline" disabled={discard.isPending} onClick={() => discard.mutate()}>
                  Delete draft
                </Button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/** The next players in rotation for a slot. The first `free` are the app's recommendation; picking anyone
 * further down asks for a reason, which is kept with the place. */
function Rotation({ orgId, squad, slotId, free, candidates, onPicked }: { orgId: string; squad: Squad; slotId: string; free: number; candidates: SquadCandidate[]; onPicked: (squad: Squad) => void }) {
  const [more, setMore] = useState(false)
  const [asking, setAsking] = useState<SquadCandidate | null>(null)
  const [reason, setReason] = useState("")
  const pick = useMutation({
    mutationFn: ({ candidate, why }: { candidate: SquadCandidate; why: string }) => pickPlayer(orgId, squad.id, candidate.user_id, slotId, why),
    onSuccess: (fresh) => {
      setAsking(null)
      setReason("")
      onPicked(fresh)
    },
    onError: (error, { candidate }) => {
      // Someone else was picked meanwhile and the rotation moved: ask for the reason now.
      if (error instanceof ApiError && error.code === "reason_required") setAsking(candidate)
    },
  })
  const shown = more ? candidates.slice(0, 40) : candidates.slice(0, Math.max(free, 3))
  return (
    <div className="flex flex-col gap-2 border-t pt-3">
      <h3 className="font-semibold">Pick next, in rotation</h3>
      {pick.isError && !(pick.error instanceof ApiError && pick.error.code === "reason_required") && <FormAlert>{errorMessage(pick.error)}</FormAlert>}
      {candidates.length === 0 && <p className="text-muted-foreground">Nobody left to pick.</p>}
      <ul className="flex flex-col gap-2">
        {shown.map((candidate, index) => {
          const next = index < free
          return (
            <li key={candidate.user_id} className="flex flex-col gap-2 rounded-lg border px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="min-w-0">
                  <span className="font-semibold">{candidate.display_name}</span>
                  {candidate.club && <span className="text-muted-foreground"> · {candidate.club}</span>}
                  <span className="block text-sm text-muted-foreground">
                    {candidate.last_represented_on ? `Last went ${formatDay(candidate.last_represented_on)}` : "Hasn't represented yet"}
                    {candidate.in_previous_squad && " · was in the last squad"} · rating {candidate.rating}
                    {next && " · recommended"}
                  </span>
                </span>
                <Button size="sm" variant={next ? "default" : "outline"} disabled={pick.isPending} aria-label={`Pick ${candidate.display_name}`} onClick={() => (next ? pick.mutate({ candidate, why: "" }) : setAsking(candidate))}>
                  <UserPlus aria-hidden className="size-4" /> Pick
                </Button>
              </div>
              {asking?.user_id === candidate.user_id && (
                <div className="flex flex-wrap items-end gap-2">
                  <Field label={`Why ${candidate.display_name} out of turn?`} className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="Kept with the squad for the record." />
                  <Button size="sm" disabled={!reason.trim() || pick.isPending} onClick={() => pick.mutate({ candidate, why: reason.trim() })}>
                    Pick with this reason
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setAsking(null)}>
                    Cancel
                  </Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {!more && candidates.length > shown.length && (
        <Button variant="ghost" className="self-start" onClick={() => setMore(true)}>
          Show more players
        </Button>
      )}
    </div>
  )
}

function PlaceCard({ place }: { place: MySquadPlace }) {
  const queryClient = useQueryClient()
  const answer = useMutation({ mutationFn: (value: "accept" | "decline") => answerPlace(place.id, value), onSuccess: () => queryClient.invalidateQueries({ queryKey: squadKeys.mine }) })
  const [today] = useState(() => new Date().toISOString().slice(0, 10))
  const open = (place.status === "picked" || place.status === "accepted") && place.squad.starts_on > today
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">
        {place.squad.title} <span className="font-normal text-muted-foreground">· {place.organization.name}</span>
      </p>
      <p className="text-sm text-muted-foreground">
        {formatDay(place.squad.starts_on)}
        {place.slot_label && ` · ${place.slot_label}`} · {place.status === "picked" ? "Waiting for your answer" : place.status === "accepted" ? "You're going" : place.status === "declined" ? "You declined" : "You were taken out"}
      </p>
      {place.notes && <p className="whitespace-pre-wrap">{place.notes}</p>}
      {place.teammates.length > 0 && <p className="text-sm">Also going: {place.teammates.join(", ")}</p>}
      {answer.isError && <FormAlert>{errorMessage(answer.error)}</FormAlert>}
      {open && (
        <div className="flex flex-wrap gap-2">
          {place.status === "picked" && (
            <Button disabled={answer.isPending} onClick={() => answer.mutate("accept")}>
              I'll go
            </Button>
          )}
          <Button variant="outline" disabled={answer.isPending} onClick={() => answer.mutate("decline")}>
            {place.status === "accepted" ? "I can't go after all" : "I can't go"}
          </Button>
        </div>
      )}
    </li>
  )
}

// Selectors pick while the player isn't looking, so ask the server each time.
const useMyPlaces = () => useQuery({ queryKey: squadKeys.mine, queryFn: listMyPlaces, staleTime: 0 })

/** Places waiting for the player's answer, on Home. Hidden when there are none. */
export function SquadPlacesToAnswer() {
  const places = useMyPlaces()
  const waiting = (places.data ?? []).filter((place) => place.status === "picked")
  if (waiting.length === 0) return null
  return (
    <section aria-labelledby="picked-heading" className="flex flex-col gap-3">
      <h2 id="picked-heading" className="text-xl font-bold">
        You've been picked
      </h2>
      <ul className="flex flex-col gap-2">
        {waiting.map((place) => (
          <PlaceCard key={place.id} place={place} />
        ))}
      </ul>
    </section>
  )
}

/** The squads you were picked for: those to answer, those you're in, and where you have represented. */
export function MySquadsPage() {
  const places = useMyPlaces()
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/home">Home</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">My squads</h1>
        <p className="text-muted-foreground">Tournaments you were picked to represent your club or region at. Only you see this list.</p>
      </div>
      {places.isError && <FormAlert>{errorMessage(places.error, "We couldn't load your squads.")}</FormAlert>}
      {places.isSuccess && places.data.length === 0 && <p className="text-muted-foreground">You haven't been picked for a squad yet.</p>}
      <ul className="flex flex-col gap-2">
        {places.data?.map((place) => (
          <PlaceCard key={place.id} place={place} />
        ))}
      </ul>
    </div>
  )
}
