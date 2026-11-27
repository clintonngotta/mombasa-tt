import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { DraftBar } from "@/components/forms/Draft"
import { Field, FormAlert } from "@/components/forms/Field"
import { SearchSelect } from "@/components/forms/SelectField"
import { Toggle } from "@/components/forms/Toggle"
import { useAutoDraft, useDraft, useDraftState } from "@/components/forms/useDraft"
import { DrawView } from "@/components/tournaments/DrawView"
import { SeedList } from "@/components/tournaments/SeedList"
import { EventStatusChip } from "@/components/tournaments/StatusChip"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import { formatInstant } from "@/lib/dates"
import { DEFAULT_RULES, discardDraw, drawKeys, getDraw, KEEP_APART, moveInDraw, previewDraw, publishDraw, reopenDraw, type Draw, type DrawRules, type EventDraw } from "@/lib/draws"
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
  // The rules of a groups stage: start from those the preview was drawn with.
  const grouped = event.format === "groups_knockout" && event.kind !== "jumbles"
  const [rules, setRules] = useState<DrawRules>(() =>
    draw.preview?.keep_apart ? { keep_apart: draw.preview.keep_apart, same_group_limit: draw.preview.same_group_limit } : DEFAULT_RULES
  )
  const make = useMutation({
    mutationFn: () => previewDraw(t.id, event.id, seeded ? chosen : [], grouped ? rules : undefined),
    onSuccess: (fresh) => {
      draft.clear() // the seeds are in the preview now
      settle(fresh)
    },
  })
  const publish = useMutation({ mutationFn: () => publishDraw(t.id, event.id), onSuccess: settle })
  const reopen = useMutation({ mutationFn: () => reopenDraw(t.id, event.id), onSuccess: settle })
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
          {grouped && <RulesPanel rules={rules} onChange={setRules} />}
          {make.isError && <FormAlert>{errorMessage(make.error)}</FormAlert>}
          {reopen.isError && <FormAlert>{errorMessage(reopen.error)}</FormAlert>}
          <div className="flex flex-wrap gap-2">
            <Button size="lg" variant={preview ? "outline" : "default"} disabled={make.isPending || entries.isPending} onClick={() => make.mutate()}>
              {make.isPending ? "Drawing…" : preview ? "Draw again" : "Make the draw"}
            </Button>
            {draw.published && event.kind !== "jumbles" && (
              <Button size="lg" variant="outline" disabled={reopen.isPending} onClick={() => reopen.mutate()}>
                {reopen.isPending ? "Copying…" : "Start from the published draw"}
              </Button>
            )}
          </div>
          {draw.published && event.kind !== "jumbles" && (
            <p className="text-sm text-muted-foreground">
              To add late entries or take withdrawn ones out without drawing again, start from the published draw: only the groups you change get new matches.
              {preview && " This replaces the preview below."}
            </p>
          )}

          {preview && (
            <div className="flex flex-col gap-4 rounded-lg border bg-card p-3">
              <div className="flex flex-col gap-1">
                <h3 className="text-lg font-bold">Preview (version {preview.version})</h3>
                <p className="text-sm text-muted-foreground">Nobody else sees this until you publish it.</p>
              </div>
              {preview.stale && (
                <FormAlert>
                  The accepted entries changed since this was drawn.{" "}
                  {(preview.not_in_draw ?? []).length || preview.places.some((place) => place.withdrawn) ? "Add or take out the entries listed below, or draw again, before publishing." : "Draw again before publishing."}
                </FormAlert>
              )}
              {(preview.over_limit ?? []).length > 0 && (
                <FormAlert>
                  Move entries before publishing:{" "}
                  {(preview.over_limit ?? []).map((over) => `${preview.groups.find((g) => g.number === over.group)?.name ?? `Group ${over.group}`} has ${over.count} from ${over.name} (at most ${over.limit})`).join("; ")}.
                </FormAlert>
              )}
              {preview.moved_at && <p className="text-sm text-muted-foreground">Entries were moved by hand {formatInstant(preview.moved_at, t.timezone)}.</p>}
              <DrawView draw={preview} />
              {event.kind !== "jumbles" && <LateEntries tournamentId={t.id} eventId={event.id} preview={preview} onChanged={settle} />}
              {event.kind !== "jumbles" && event.format !== "round_robin" && <MovePanel tournamentId={t.id} eventId={event.id} preview={preview} onMoved={settle} />}
              {publish.isError && <FormAlert>{errorMessage(publish.error)}</FormAlert>}
              {discard.isError && <FormAlert>{errorMessage(discard.error)}</FormAlert>}
              <div className="flex flex-wrap gap-2">
                <Button size="lg" disabled={publish.isPending || discard.isPending || preview.stale || (preview.over_limit ?? []).length > 0} onClick={() => publish.mutate()}>
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

/** What the draw keeps apart in the groups, and how many of one a group may hold. */
function RulesPanel({ rules, onChange }: { rules: DrawRules; onChange: (rules: DrawRules) => void }) {
  const on = (value: DrawRules["keep_apart"][number], checked: boolean) =>
    onChange({ ...rules, keep_apart: KEEP_APART.map((rule) => rule.value).filter((v) => (v === value ? checked : rules.keep_apart.includes(v))) })
  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-3">
      <h3 className="text-lg font-bold">Group rules</h3>
      <p className="text-sm text-muted-foreground">
        Choose who the draw spreads over the groups. A club, team or region with more entries than the groups can hold at this number gets its fair share in each group. The draw can't be published
        while a group breaks a rule you chose.
      </p>
      {KEEP_APART.map((rule) => (
        <Toggle key={rule.value} label={rule.label} description={rule.description} checked={rules.keep_apart.includes(rule.value)} onChange={(checked) => on(rule.value, checked)} />
      ))}
      <Field
        label="Most from one club, team or region in a group"
        type="number"
        min={1}
        max={16}
        inputMode="numeric"
        className="[&_input]:max-w-40"
        disabled={rules.keep_apart.length === 0}
        value={rules.same_group_limit}
        onChange={(e) => onChange({ ...rules, same_group_limit: Math.min(16, Math.max(1, Number(e.target.value) || 1)) })}
      />
    </div>
  )
}

/** Move an entry of the preview by hand: to another group, or into the place of another entry. */
function MovePanel({ tournamentId, eventId, preview, onMoved }: { tournamentId: string; eventId: string; preview: Draw; onMoved: (fresh: EventDraw) => void }) {
  const [entryId, setEntryId] = useState("")
  const [target, setTarget] = useState("")
  const knockout = preview.groups.length === 0
  const groupName = (number: number | null | undefined) => preview.groups.find((group) => group.number === number)?.name ?? ""
  const where = (place: Draw["places"][number]) => (knockout ? `line ${place.bracket_position}` : groupName(place.group))
  const label = (place: Draw["places"][number]) =>
    `${place.entry.title} (${where(place)}${place.affiliations?.length ? `, ${place.affiliations.join(", ")}` : ""})`
  const places = [...preview.places].sort((a, b) => (a.group ?? 0) - (b.group ?? 0) || (a.group_position ?? a.bracket_position ?? 0) - (b.group_position ?? b.bracket_position ?? 0))
  const chosen = places.find((place) => place.entry.id === entryId)
  const targets = chosen
    ? [
        ...(knockout ? [] : preview.groups.filter((group) => group.number !== chosen.group).map((group) => ({ value: `group:${group.number}`, label: `Move to ${group.name}` }))),
        ...places
          .filter((place) => place.entry.id !== chosen.entry.id && (knockout || place.group !== chosen.group))
          .map((place) => ({ value: `swap:${place.entry.id}`, label: `Swap with ${label(place)}` })),
      ]
    : []
  const move = useMutation({
    mutationFn: () => {
      const [kind, value] = target.split(":")
      return moveInDraw(tournamentId, eventId, kind === "group" ? { entry_id: entryId, group: Number(value) } : { entry_id: entryId, swap_with: value })
    },
    onSuccess: (fresh) => {
      setTarget("")
      onMoved(fresh)
    },
  })
  return (
    <div role="group" aria-labelledby="move-heading" className="flex flex-col gap-3 rounded-lg border p-3">
      <h4 id="move-heading" className="font-bold">
        Move or swap entries
      </h4>
      <p className="text-sm text-muted-foreground">
        {knockout
          ? "Swap two players, pairs or teams in the first round; a bye goes with its place."
          : "Move a player, pair or team to another group, or swap two of them between groups. Seeds stay first in their group."}
      </p>
      <SearchSelect aria-label="Entry to move" placeholder="Choose an entry" options={places.map((place) => ({ value: place.entry.id, label: label(place) }))} value={entryId} onChange={(value) => { setEntryId(value); setTarget("") }} />
      {chosen && <SearchSelect aria-label="Where to move it" placeholder="Choose where it goes" options={targets} value={target} onChange={setTarget} />}
      {move.isError && <FormAlert>{errorMessage(move.error)}</FormAlert>}
      <Button variant="outline" className="self-start" disabled={!chosen || !target || move.isPending} onClick={() => move.mutate()}>
        {move.isPending ? "Moving…" : "Move"}
      </Button>
    </div>
  )
}

/** Entries the preview doesn't hold yet (accepted since it was drawn), and ones no longer accepted. */
function LateEntries({ tournamentId, eventId, preview, onChanged }: { tournamentId: string; eventId: string; preview: Draw; onChanged: (fresh: EventDraw) => void }) {
  const [chosen, setChosen] = useState<Record<string, string>>({})
  const change = useMutation({
    mutationFn: (body: { entry_id: string; group?: number; remove?: boolean }) => moveInDraw(tournamentId, eventId, body),
    onSuccess: onChanged,
  })
  // A draw saved on the device by an older version of the app may lack these.
  const missing = preview.not_in_draw ?? []
  const withdrawn = preview.places.filter((place) => place.withdrawn)
  if (missing.length === 0 && withdrawn.length === 0) return null
  const groups = preview.groups.length ? preview.groups : null
  const groupName = (number: number | null | undefined) => preview.groups.find((group) => group.number === number)?.name ?? "the group"
  return (
    <div role="group" aria-labelledby="late-heading" className="flex flex-col gap-3 rounded-lg border border-brand-blue/30 p-3">
      <h4 id="late-heading" className="font-bold">
        Changes since the draw
      </h4>
      {change.isError && <FormAlert>{errorMessage(change.error)}</FormAlert>}
      {missing.map(({ entry, suggested_group }) => {
        const group = chosen[entry.id] ?? (suggested_group ? String(suggested_group) : "1")
        return (
          <div key={entry.id} className="flex flex-col gap-2 rounded-lg bg-card p-2">
            <p>
              <span className="font-semibold">{entry.title}</span> isn't in the draw yet.
              {!groups && " A knockout's bracket depends on how many entered: draw it again to include them."}
            </p>
            {groups && (
              <div className="flex flex-wrap items-center gap-2">
                <SearchSelect
                  aria-label={`Group for ${entry.title}`}
                  className="max-w-56"
                  options={groups.map((g) => ({ value: String(g.number), label: g.number === suggested_group ? `${g.name} (suggested)` : g.name }))}
                  value={group}
                  onChange={(value) => setChosen({ ...chosen, [entry.id]: value })}
                />
                <Button variant="outline" disabled={change.isPending} onClick={() => change.mutate({ entry_id: entry.id, group: Number(group) })}>
                  Add to {groupName(Number(group))}
                </Button>
              </div>
            )}
          </div>
        )
      })}
      {withdrawn.map((place) => (
        <div key={place.entry.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-card p-2">
          <p className="flex-1">
            <span className="font-semibold">{place.entry.title}</span> is no longer entered but is still in {groupName(place.group)}.
          </p>
          <Button variant="outline" disabled={change.isPending} onClick={() => change.mutate({ entry_id: place.entry.id, remove: true })}>
            Take out
          </Button>
        </div>
      ))}
    </div>
  )
}
