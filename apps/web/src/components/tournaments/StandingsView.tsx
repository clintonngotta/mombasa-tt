import { CircleCheck } from "lucide-react"
import type { Schemas } from "@/lib/schema"

type Standings = Schemas["Standings"]
type Group = Schemas["GroupStanding"]
type Row = Schemas["StandingRow"]

const LIST = new Intl.ListFormat("en", { type: "conjunction" })

const MEASURE: Record<Row["tie_break"][number]["measure"], string> = {
  match_points: "match points",
  rubbers: "individual matches won/lost",
  games: "games won/lost",
  points: "points won/lost",
  lot: "decided by lot",
}

/** "Level with B and C; between them: match points 3, games won/lost 5/3." One sentence per set of level entries. */
function explain(row: Row, names: Map<string, string>) {
  const sets: { others: string; found: string[] }[] = []
  let among = ""
  for (const step of row.tie_break) {
    const key = step.among.join()
    if (key !== among) {
      among = key
      const others = step.among.filter((id) => id !== row.entry.id).map((id) => names.get(id) ?? "another entry")
      sets.push({ others: LIST.format(others), found: [] })
    }
    sets[sets.length - 1].found.push(step.measure === "lot" ? MEASURE.lot : `${MEASURE[step.measure]} ${step.value}`)
  }
  return sets.map((set) => `Level with ${set.others}; between them: ${set.found.join(", ")}.`).join(" ")
}

function GroupTable({ group, single }: { group: Group; single: boolean }) {
  const names = new Map(group.rows.map((row) => [row.entry.id, row.entry.title]))
  const explained = group.rows.filter((row) => row.tie_break.length > 0)
  const name = single ? "Table" : group.name
  return (
    <section aria-label={`${name} standings`} className="flex flex-col gap-2">
      <h3 className="text-xl font-bold">{name}</h3>
      <div className="overflow-x-auto rounded-lg border bg-card">
        <table className="w-full text-left tabular-nums">
          <caption className="sr-only">
            {name}: rank, entry, played, won, lost, games won and lost, and match points
          </caption>
          <thead className="text-sm text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">#</th>
              <th scope="col" className="px-1 py-2 font-semibold">Entry</th>
              <th scope="col" className="px-2 py-2 text-right font-semibold"><abbr title="Played">P</abbr></th>
              <th scope="col" className="px-2 py-2 text-right font-semibold"><abbr title="Won">W</abbr></th>
              <th scope="col" className="px-2 py-2 text-right font-semibold"><abbr title="Lost">L</abbr></th>
              <th scope="col" className="px-2 py-2 text-right font-semibold">Games</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold"><abbr title="Match points">Pts</abbr></th>
            </tr>
          </thead>
          <tbody>
            {group.rows.map((row) => (
              <tr key={row.entry.id} className="border-t">
                <td className="px-3 py-2 font-semibold">{row.level ? "=" : row.rank}</td>
                <th scope="row" className="px-1 py-2 font-normal break-words">
                  {row.entry.title}{" "}
                  {row.qualified && (
                    <span className="ml-2 inline-flex items-center gap-1 text-sm font-semibold text-success">
                      <CircleCheck aria-hidden className="size-4" /> Qualified
                    </span>
                  )}
                </th>
                <td className="px-2 py-2 text-right">{row.played}</td>
                <td className="px-2 py-2 text-right">{row.won}</td>
                <td className="px-2 py-2 text-right">{row.lost}</td>
                <td className="px-2 py-2 text-right">
                  {row.games_won}–{row.games_lost}
                </td>
                <td className="px-3 py-2 text-right font-bold">{row.match_points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!group.complete && <p className="text-sm text-muted-foreground">Matches are still to be played. Entries marked = can't be separated yet.</p>}
      {explained.length > 0 && (
        <div className="flex flex-col gap-1 text-sm">
          <h4 className="font-semibold">How level entries were separated</h4>
          <ul className="flex flex-col gap-1">
            {explained.map((row) => (
              <li key={row.entry.id}>
                <span className="font-semibold">{row.entry.title}:</span> {explain(row, names)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

/** Group tables with the reason for every separated tie (REQ-010), and the knockout's decided places. */
export function StandingsView({ standings }: { standings: Standings }) {
  return (
    <div className="flex flex-col gap-6">
      {standings.placements.length > 0 && (
        <dl className="flex flex-col gap-1">
          {standings.placements.map((placement) => (
            <div key={placement.label} className="flex flex-wrap gap-x-2">
              <dt className="font-semibold">{placement.label}:</dt>
              <dd>{placement.entries.map((entry) => entry.title).join(", ")}</dd>
            </div>
          ))}
        </dl>
      )}
      {standings.groups.map((group) => (
        <GroupTable key={group.number} group={group} single={standings.groups.length === 1} />
      ))}
      {standings.groups.length > 0 && (
        <p className="text-sm text-muted-foreground">
          A win is 2 match points, a loss 1, a loss in a match not played or not finished 0. Entries level on match points are separated by the matches between
          them: match points, then (for teams) individual matches, games and points won and lost, then by lot (rules {standings.rules_version}).
        </p>
      )}
    </div>
  )
}
