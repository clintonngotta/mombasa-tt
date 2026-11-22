import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import {
  addTournamentUmpire,
  listTournamentUmpires,
  listUmpireCandidates,
  removeTournamentUmpire,
  reservationKeys,
  setTableUmpire,
  umpireKeys,
  type Board,
  type BoardTable,
  type UmpireRosterEntry,
} from "@/lib/reservations"
import { scoringKeys } from "@/lib/scoring"

const NONE = ""

/**
 * The tournament's umpires and each table's umpire (user request, 2026-11-22). Staff pick members of the
 * host and players entered in the tournament, who can umpire between their own matches. A table's
 * umpire takes every match sent to that table, so it already has its umpire when the players arrive.
 */
export function UmpiresPanel({ tournamentId, tables }: { tournamentId: string; tables: BoardTable[] }) {
  const queryClient = useQueryClient()
  const roster = useQuery({ queryKey: umpireKeys.roster(tournamentId), queryFn: () => listTournamentUmpires(tournamentId) })
  const keepRoster = (fresh: UmpireRosterEntry[]) => {
    queryClient.setQueryData(umpireKeys.roster(tournamentId), fresh)
    void queryClient.invalidateQueries({ queryKey: ["reservations", "umpire-candidates", tournamentId] })
    void queryClient.invalidateQueries({ queryKey: reservationKeys.board(tournamentId) })
  }
  const remove = useMutation({ mutationFn: (userId: string) => removeTournamentUmpire(tournamentId, userId), onSuccess: keepRoster })
  const people = roster.data ?? []

  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="umpire-tables" className="flex flex-col gap-3">
        <h2 id="umpire-tables" className="text-2xl font-bold">
          Table umpires
        </h2>
        <p className="text-sm text-muted-foreground">
          Every match sent to a table takes its umpire at once. Change it whenever you need: the match waiting on the table changes too, unless scoring has started. Someone playing in a match, or
          playing elsewhere at that moment, is skipped and the table shows no umpire until you choose one.
        </p>
        {tables.length === 0 ? (
          <p className="text-muted-foreground">This tournament's venue has no tables in use.</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {tables.map((table) => (
              <TableUmpireRow key={table.id} tournamentId={tournamentId} table={table} people={people} />
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="umpire-list" className="flex flex-col gap-3">
        <h2 id="umpire-list" className="text-2xl font-bold">
          Umpires
        </h2>
        <p className="text-sm text-muted-foreground">Members of your club and players entered in this tournament. Being on the list lets them score this tournament's matches.</p>
        {roster.isPending && <p className="text-muted-foreground">Loading…</p>}
        {roster.isError && <FormAlert>{errorMessage(roster.error, "We couldn't load the umpires.")}</FormAlert>}
        {roster.isSuccess && people.length === 0 && <p className="text-muted-foreground">Nobody yet. Add the first below.</p>}
        {people.length > 0 && (
          <ul className="flex flex-col gap-2">
            {people.map((person) => (
              <li key={person.user_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-card p-3">
                <span className="flex flex-col">
                  <span className="font-semibold">{person.display_name}</span>
                  <span className="text-sm text-muted-foreground">
                    {[person.table ? `Umpires ${person.table}` : "No table", person.entered && "Also playing", person.playing_on && `Playing on ${person.playing_on} now`].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <Button variant="outline" disabled={remove.isPending} onClick={() => remove.mutate(person.user_id)} aria-label={`Take ${person.display_name} off the umpires`}>
                  Take off
                </Button>
              </li>
            ))}
          </ul>
        )}
        {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
        <AddUmpire tournamentId={tournamentId} onAdded={keepRoster} />
      </section>
    </div>
  )
}

function TableUmpireRow({ tournamentId, table, people }: { tournamentId: string; table: BoardTable; people: UmpireRosterEntry[] }) {
  const queryClient = useQueryClient()
  const save = useMutation({
    mutationFn: (userId: string) => setTableUmpire(tournamentId, table.id, userId || null),
    onSuccess: (fresh: Board) => {
      queryClient.setQueryData(reservationKeys.board(tournamentId), fresh)
      void queryClient.invalidateQueries({ queryKey: umpireKeys.roster(tournamentId) })
      void queryClient.invalidateQueries({ queryKey: scoringKeys.overview(tournamentId) })
    },
  })
  const current = table.table_umpire?.id ?? NONE
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <SelectField
        label={table.label}
        value={current}
        disabled={save.isPending}
        onChange={(value) => {
          if (value !== current) save.mutate(value)
        }}
        options={[
          { value: NONE, label: "No table umpire" },
          ...people.map((person) => ({
            value: person.user_id,
            label: person.table && person.table_id !== table.id ? `${person.display_name} (now ${person.table})` : person.display_name,
          })),
        ]}
        hint={people.length === 0 ? "Add umpires below first." : undefined}
      />
      {save.isPending && <p className="text-sm text-muted-foreground">Saving…</p>}
      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
    </li>
  )
}

function AddUmpire({ tournamentId, onAdded }: { tournamentId: string; onAdded: (fresh: UmpireRosterEntry[]) => void }) {
  const [term, setTerm] = useState("")
  const search = term.trim()
  const candidates = useQuery({ queryKey: umpireKeys.candidates(tournamentId, search), queryFn: () => listUmpireCandidates(tournamentId, search) })
  const add = useMutation({ mutationFn: (userId: string) => addTournamentUmpire(tournamentId, userId), onSuccess: onAdded })
  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h3 className="font-bold">Add an umpire</h3>
      <Field label="Find a member or player" type="search" value={term} onChange={(e) => setTerm(e.target.value)} hint="Members of your club and players entered in this tournament." />
      {candidates.isError && <FormAlert>{errorMessage(candidates.error, "We couldn't search just now.")}</FormAlert>}
      {candidates.isSuccess && candidates.data.length === 0 && <p className="text-sm text-muted-foreground">Nobody else matches.</p>}
      {candidates.data && candidates.data.length > 0 && (
        <ul className="flex flex-col gap-2">
          {candidates.data.map((person) => (
            <li key={person.id} className="flex items-center justify-between gap-2">
              <span>{person.display_name}</span>
              <Button variant="outline" disabled={add.isPending} onClick={() => add.mutate(person.id)} aria-label={`Add ${person.display_name} to the umpires`}>
                Add
              </Button>
            </li>
          ))}
        </ul>
      )}
      {add.isError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
    </div>
  )
}
