import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { DraftBar } from "@/components/forms/Draft"
import { FormAlert } from "@/components/forms/Field"
import { useAutoDraft, useDraft, useDraftState } from "@/components/forms/useDraft"
import { DrawView } from "@/components/tournaments/DrawView"
import { SeedList } from "@/components/tournaments/SeedList"
import { EventStatusChip } from "@/components/tournaments/StatusChip"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import { formatInstant } from "@/lib/dates"
import { discardDraw, drawKeys, getDraw, previewDraw, publishDraw, type EventDraw } from "@/lib/draws"
import { entryKeys, entryTitle, listAllEntries, type Entry } from "@/lib/entries"
import { canManageTournament, eventSummary, eventTabPath, firstTab, getTournament, isClosed, SEEDING_LABEL, tournamentKeys, type Tournament, type TournamentEvent } from "@/lib/tournaments"

/** The draw of one event (REQ-009): the published draw for everyone, and the organizers' draw desk. */
export function DrawPage() {
  const { id = "", eventId = "" } = useParams()
  const { results: memberships } = useMemberships()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const draw = useQuery({ queryKey: drawKeys.event(eventId), queryFn: () => getDraw(id, eventId), enabled: tournament.isSuccess })
  const t = tournament.data
  const event = t?.events.find((candidate) => candidate.id === eventId)
  const staff = !!t && canManageTournament(memberships, t)
  const missing = (tournament.error instanceof ApiError && tournament.error.status === 404) || (!!t && !event)
  const published = draw.data?.published

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      {tournament.isPending && <p className="text-muted-foreground">Loading event…</p>}
      {missing && <FormAlert>This event doesn't exist or hasn't been published.</FormAlert>}
      {tournament.isError && !missing && <FormAlert>{errorMessage(tournament.error, "We couldn't load this event.")}</FormAlert>}
      {t && event && (
        <>
          <header className="flex flex-col gap-2">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <h1 className="min-w-0 text-[32px] leading-9 font-bold break-words">{event.name}: draw desk</h1>
              <EventStatusChip status={event.status} />
            </div>
            <p className="text-muted-foreground">{eventSummary(event)}</p>
          </header>
          {draw.isPending && <p className="text-muted-foreground">Loading draw…</p>}
          {draw.isError && <FormAlert>{errorMessage(draw.error, "We couldn't load the draw.")}</FormAlert>}
          {draw.data && (
            <>
              {staff && <Desk tournament={t} event={event} draw={draw.data} />}
              <section aria-labelledby="draw-heading" className="flex flex-col gap-3">
                <h2 id="draw-heading" className="text-2xl font-bold">
                  {published ? `Published draw (version ${published.version})` : "Draw"}
                </h2>
                {published ? (
                  <>
                    <p className="text-sm text-muted-foreground">Published {published.published_at && formatInstant(published.published_at, t.timezone)}.</p>
                    {published.stale && <FormAlert>The entries have changed since this draw was published. Draw again and publish a new one.</FormAlert>}
                    <Link to={eventTabPath(id, eventId, firstTab(event.format))} className={buttonVariants({ variant: "outline", className: "self-start" })}>
                      See brackets, groups, schedule and standings
                    </Link>
                  </>
                ) : (
                  <p className="text-muted-foreground">The draw hasn't been published yet.</p>
                )}
              </section>
            </>
          )}
        </>
      )}
    </div>
  )
}

/** Seeds in order, a preview that can be drawn again, and publication. */
function Desk({ tournament: t, event, draw }: { tournament: Tournament; event: TournamentEvent; draw: EventDraw }) {
  const queryClient = useQueryClient()
  const open = t.status !== "draft" && !isClosed(t) && event.status === "scheduled"
  const seeded = event.seeding !== "none"
  // Start from the seeds of the draw already made, so drawing again keeps them.
  const [start] = useState<string[]>(() =>
    (draw.preview ?? draw.published)?.places
      .filter((place) => place.seed)
      .sort((a, b) => (a.seed ?? 0) - (b.seed ?? 0))
      .map((place) => place.entry.id) ?? draw.recommended_seeds
  )
  // Seeds put in order but not drawn yet stay on this device, saved as they change, until the draw is made.
  const draft = useDraft(open && seeded ? `draw:${event.id}` : null)
  const [seeds, setSeeds] = useDraftState<string[]>(draft, "seeds", start)
  useAutoDraft(draft, seeds, start)
  const entries = useQuery({ queryKey: entryKeys.accepted(event.id), queryFn: () => listAllEntries(t.id, event.id, "accepted"), enabled: open })
  const accepted = entries.data?.results ?? []
  const total = entries.data?.count ?? 0
  const byId = new Map(accepted.map((entry) => [entry.id, entry]))
  const chosen = seeds.filter((id) => byId.has(id)) // an entry withdrawn since is no longer a seed
  const settle = (fresh: EventDraw) => {
    queryClient.setQueryData(drawKeys.event(event.id), fresh)
    void queryClient.invalidateQueries({ queryKey: drawKeys.standings(event.id) })
  }
  const make = useMutation({
    mutationFn: () => previewDraw(t.id, event.id, seeded ? chosen : []),
    onSuccess: (fresh) => {
      draft.clear() // the seeds are in the preview now
      settle(fresh)
    },
  })
  const publish = useMutation({ mutationFn: () => publishDraw(t.id, event.id), onSuccess: settle })
  const [deleting, setDeleting] = useState(false) // asked once more before the preview goes
  const discard = useMutation({
    mutationFn: () => discardDraw(t.id, event.id),
    onSuccess: (fresh) => {
      settle(fresh)
      setDeleting(false)
    },
  })
  const preview = draw.preview

  return (
    <section aria-labelledby="draw-desk-heading" className="flex flex-col gap-4 rounded-xl border border-brand-blue/30 bg-surface-selected p-4">
      <div className="flex flex-col gap-1">
        <h2 id="draw-desk-heading" className="text-2xl font-bold">
          Draw desk
        </h2>
        <p className="text-sm text-muted-foreground">Only people who run competitions for {t.organization.name} see this.</p>
      </div>
      {!open ? (
        <p className="text-muted-foreground">{t.status === "draft" ? "Publish the tournament before making a draw." : "The event has started, so its draw is fixed."}</p>
      ) : (
        <>
          <p>
            {total} accepted {total === 1 ? "entry" : "entries"} will be drawn. {SEEDING_LABEL[event.seeding]}.
          </p>
          {seeded && total > accepted.length && <FormAlert>Only the first {accepted.length} accepted entries can be picked as seeds here.</FormAlert>}
          {entries.isError && <FormAlert>{errorMessage(entries.error, "We couldn't load the entries.")}</FormAlert>}
          {seeded && (
            <div className="flex flex-col gap-3 rounded-lg border bg-card p-3">
              <h3 className="text-lg font-bold">Seeds</h3>
              <p className="text-sm text-muted-foreground">
                Put the seeds in order, best first: drag a row by its handle or use the arrows. {event.seeding === "rating" && "The suggested order uses current rating points. "}
                Everyone else is drawn by lot.
              </p>
              {event.seeding === "rating" && <Button variant="outline" className="self-start" onClick={() => setSeeds(draw.recommended_seeds)}>
                Use rating order
              </Button>}
              {chosen.length > 0 && <SeedList seeds={chosen} title={(id) => entryTitle(byId.get(id) as Entry)} onChange={setSeeds} />}
              <ul className="flex flex-wrap gap-2" aria-label="Unseeded entries">
                {accepted
                  .filter((entry) => !chosen.includes(entry.id))
                  .map((entry) => (
                    <li key={entry.id}>
                      <Button variant="outline" aria-label={`Seed ${entryTitle(entry)} next`} onClick={() => setSeeds([...chosen, entry.id])}>
                        {entryTitle(entry)}
                      </Button>
                    </li>
                  ))}
              </ul>
              <DraftBar draft={draft} />
            </div>
          )}
          {make.isError && <FormAlert>{errorMessage(make.error)}</FormAlert>}
          <Button size="lg" variant={preview ? "outline" : "default"} className="self-start" disabled={make.isPending || entries.isPending} onClick={() => make.mutate()}>
            {make.isPending ? "Drawing…" : preview ? "Draw again" : "Make the draw"}
          </Button>

          {preview && (
            <div className="flex flex-col gap-4 rounded-lg border bg-card p-3">
              <div className="flex flex-col gap-1">
                <h3 className="text-lg font-bold">Preview (version {preview.version})</h3>
                <p className="text-sm text-muted-foreground">Nobody else sees this until you publish it.</p>
              </div>
              {preview.stale && <FormAlert>The accepted entries changed since this was drawn. Draw again before publishing.</FormAlert>}
              <DrawView draw={preview} />
              {publish.isError && <FormAlert>{errorMessage(publish.error)}</FormAlert>}
              {discard.isError && <FormAlert>{errorMessage(discard.error)}</FormAlert>}
              <div className="flex flex-wrap gap-2">
                <Button size="lg" disabled={publish.isPending || discard.isPending || preview.stale} onClick={() => publish.mutate()}>
                  {publish.isPending ? "Publishing…" : draw.published ? "Publish as the new draw" : "Publish draw"}
                </Button>
                {!deleting && (
                  <Button size="lg" variant="outline" disabled={publish.isPending} onClick={() => setDeleting(true)}>
                    Delete this draw
                  </Button>
                )}
              </div>
              {deleting && (
                <div role="group" aria-label="Delete this draw" className="flex flex-col gap-2 rounded-lg border border-destructive/40 p-3">
                  <p>
                    Delete this preview? Your seeds stay as they are, so you can draw again.
                    {draw.published && ` The published draw (version ${draw.published.version}) is not affected.`}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="destructive" disabled={discard.isPending} onClick={() => discard.mutate()}>
                      {discard.isPending ? "Deleting…" : "Yes, delete it"}
                    </Button>
                    <Button variant="outline" disabled={discard.isPending} onClick={() => setDeleting(false)}>
                      Keep it
                    </Button>
                  </div>
                </div>
              )}
              {draw.published && <p className="text-sm text-muted-foreground">Version {draw.published.version} stays on record as superseded.</p>}
            </div>
          )}
        </>
      )}
    </section>
  )
}
