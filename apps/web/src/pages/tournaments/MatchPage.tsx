import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CoachNotes } from "@/components/coaching/CoachNotes"
import { WatchLinks } from "@/components/streams/WatchLinks"
import { MatchRecap } from "@/components/tournaments/MatchRecap"
import { MyMatchNotes } from "@/components/matches/MyMatchNotes"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { MatchStateChip, YouBadge } from "@/components/tournaments/MatchCard"
import { TieView } from "@/components/tournaments/TieView"
import { ResultControl } from "@/components/tournaments/ResultControl"
import { TableControl } from "@/components/tournaments/TableControl"
import { UmpireControl } from "@/components/tournaments/UmpireControl"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { drawKeys, gameWinner, getMatch, sideScores, OUTCOME_LABEL, OUTCOME_MARK, sideWon, spokenScore, type DrawSide, type MatchDetail } from "@/lib/draws"
import { canManageTournament, eventTabPath, firstTab, getTournament, tieSummary, tournamentKeys, type TournamentEvent } from "@/lib/tournaments"
import { useMemberships } from "@/lib/clubs"
import { cn } from "@/lib/utils"
import { pollUnless, useLiveTournament } from "@/lib/live"
import { LiveScoreboard, type CardShown } from "@/components/tournaments/LiveScore"
import { EntryNames } from "@/components/tournaments/PlayerNames"

/**
 * One match of a published draw (REQ-010): the two sides left and right, the games, and where and when
 * it is played. It is a page for reading: scoring belongs to the assigned umpire's deck, never here.
 */
export function MatchPage() {
  const { id = "", eventId = "", matchId = "" } = useParams()
  const socketOpen = useLiveTournament(id)
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const match = useQuery({
    queryKey: drawKeys.match(matchId),
    queryFn: () => getMatch(id, eventId, matchId),
    enabled: tournament.isSuccess,
    // While the match is being played and the socket is down, the page asks again every few seconds.
    refetchInterval: (query) => (query.state.data?.status !== "completed" && tournament.data?.status === "in_progress" ? pollUnless(socketOpen) : false),
  })
  const t = tournament.data
  const event = t?.events.find((candidate) => candidate.id === eventId)
  const failed = tournament.error ?? match.error
  const missing = (failed instanceof ApiError && failed.status === 404) || (!!t && !event)
  const m = match.data
  const { results: memberships } = useMemberships()
  const staff = !!t && canManageTournament(memberships, t)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={event ? eventTabPath(id, eventId, m?.stage === "knockout" ? "brackets" : m ? "groups" : firstTab(event.format)) : `/tournaments/${id}`}>
        {event?.name ?? "Tournament"}
      </BackLink>
      {(tournament.isPending || (match.isPending && !failed)) && <p className="text-muted-foreground">Loading match…</p>}
      {missing && <FormAlert>This match doesn't exist. The draw may have been published again since you opened it.</FormAlert>}
      {failed && !missing && <FormAlert>{errorMessage(failed, "We couldn't load this match.")}</FormAlert>}
      {t && event && m && m.b && <Details match={m} second={m.b} event={event} tournamentId={id} timeZone={t.timezone} />}
      {t && m && <MatchRecap tournamentId={id} eventId={eventId} matchId={matchId} />}
      {t && m && <WatchLinks tournament={t} staff={staff} matchId={matchId} live={t.status === "in_progress" && m.status === "scheduled" && !!m.b} />}
      {m && (m.a.entry?.mine || m.b?.entry?.mine) && <MyMatchNotes link={{ match_id: matchId }} />}
      {m && (m.a.entry?.mine || m.b?.entry?.mine) && <CoachNotes kind="official" matchId={matchId} />}
      {t && event && m && !m.b && (
        <p className="rounded-xl border bg-card p-4">
          {m.a.entry ? `${m.a.entry.title} has a bye in the ${m.round_name.toLowerCase()}` : `This place in the ${m.round_name.toLowerCase()} is a bye`}: nothing is played and the entry
          goes straight through.
        </p>
      )}
    </div>
  )
}

function Name({ side, won, align, matchId }: { side: DrawSide; won: boolean; align: "left" | "right"; matchId: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", align === "right" && "items-end text-right")}>
      {side.entry ? (
        <>
          <span className={cn("text-xl leading-6 break-words", won && "font-bold")}>
            <EntryNames entry={side.entry} exceptMatch={matchId} />
          </span>
          <span className="flex flex-wrap gap-1 text-sm text-muted-foreground">
            {side.seed && <span>Seed {side.seed}</span>}
            {side.entry.mine && <YouBadge />}
            {won && <span className="font-semibold text-success">Winner</span>}
          </span>
        </>
      ) : (
        <span className="text-muted-foreground italic">{side.awaiting}</span>
      )}
    </div>
  )
}

function Details({ match: m, second: b, event, tournamentId, timeZone }: { match: MatchDetail; second: DrawSide; event: TournamentEvent; tournamentId: string; timeZone: string }) {
  const won = (side: DrawSide) => sideWon(m, side)
  const games = sideScores(m)
  const decided = m.status === "completed"
  // A tie under way already has rubbers won to show.
  const counted = decided ? m.outcome !== "walkover" : !!m.tie_score
  const round = [m.group_name, m.round_name, m.status !== "bye" && !m.tie ? `Best of ${m.best_of}` : ""].filter(Boolean).join(" · ")
  const names = { a: m.a.entry?.title ?? "First side", b: b.entry?.title ?? "Second side" }
  const facts: [string, string][] = [
    ["Event", event.name],
    ["Round", round],
    ["Played as", m.tie ? `${tieSummary(m.tie.template, m.tie.wins_needed)}; each rubber best of ${event.best_of} games` : `Best of ${event.best_of} games`],
    ["Table", m.table || "Not given yet"],
    ["Expected start", m.scheduled_at ? `${formatInstant(m.scheduled_at, timeZone)} (venue time, an estimate)` : "Not scheduled yet"],
  ]
  if (decided && m.outcome) facts.push(["Result", OUTCOME_LABEL[m.outcome]])
  if (!decided && m.winner_plays_in) facts.push(["The winner plays in", `the ${m.winner_plays_in.toLowerCase()}`])

  return (
    <>
      <header className="flex flex-col gap-3 rounded-xl border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-2xl font-bold">{round}</h1>
          <MatchStateChip match={m} />
        </div>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
          <Name matchId={m.id} side={m.a} won={won(m.a)} align="left" />
          <p className="font-display text-[80px] leading-none font-bold tabular-nums max-sm:text-[56px]">
            <span aria-hidden>
              {counted ? `${games.a}–${games.b}` : decided ? "W/O" : <span className="text-2xl font-semibold text-muted-foreground">v</span>}
              {decided && OUTCOME_MARK[m.outcome] && <span className="block text-center text-base font-semibold text-muted-foreground">{OUTCOME_MARK[m.outcome]?.short.trim()}</span>}
            </span>
            <span className="sr-only">{spokenScore(m)}</span>
          </p>
          <Name matchId={m.id} side={b} won={won(b)} align="right" />
        </div>
      </header>

      {!decided && <Live match={m} names={names} />}

      {!decided && (m.on_table || m.can_dispatch) && (
        <section aria-labelledby="table-heading" className="flex flex-col gap-2 rounded-xl border bg-card p-4">
          <h2 id="table-heading" className="text-xl font-bold">
            Table
          </h2>
          <TableControl match={m} ids={{ tournamentId, eventId: event.id, matchId: m.id }} timeZone={timeZone} />
        </section>
      )}

      {m.scoring && (m.scoring.status !== "unassigned" || !decided) && (
        <section aria-labelledby="scoring-heading" className="flex flex-col gap-2 rounded-xl border bg-card p-4">
          <h2 id="scoring-heading" className="text-xl font-bold">
            Scoring
          </h2>
          <UmpireControl scoring={m.scoring} ids={{ tournamentId, eventId: event.id, matchId: m.id }} what="this match" />
        </section>
      )}

      {m.tie && <TieView match={m} second={b} ids={{ tournamentId, eventId: event.id, matchId: m.id }} />}

      {(m.result || m.can_record_result || m.held_for_correction) && (
        <section aria-labelledby="result-heading" className="flex flex-col gap-2 rounded-xl border bg-card p-4">
          <h2 id="result-heading" className="text-xl font-bold">
            Official result
          </h2>
          <ResultControl match={m} ids={{ tournamentId, eventId: event.id, matchId: m.id }} timeZone={timeZone} />
        </section>
      )}

      {m.games.length > 0 && (
        <section aria-labelledby="games-heading" className="flex flex-col gap-2">
          <h2 id="games-heading" className="text-2xl font-bold">
            Games
          </h2>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-center tabular-nums">
              <caption className="sr-only">Points in each game, {names.a} on the left and {names.b} on the right</caption>
              <thead className="text-sm text-muted-foreground">
                <tr>
                  <th scope="col" className="w-1/3 px-3 py-2 text-left font-semibold break-words">{names.a}</th>
                  <th scope="col" className="px-3 py-2 font-semibold">Game</th>
                  <th scope="col" className="w-1/3 px-3 py-2 text-right font-semibold break-words">{names.b}</th>
                </tr>
              </thead>
              <tbody>
                {m.games.map((game, index) => {
                  const winner = gameWinner(game)
                  return (
                    <tr key={index} className="border-t">
                      <td className={cn("px-3 py-2 text-left text-lg", winner === "a" && "font-bold")}>{game[0]}</td>
                      <th scope="row" className="px-3 py-2 text-sm font-normal text-muted-foreground">
                        {index + 1}
                        {!winner && " (not finished)"}
                      </th>
                      <td className={cn("px-3 py-2 text-right text-lg", winner === "b" && "font-bold")}>{game[1]}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {OUTCOME_MARK[m.outcome] && m.games.length > 0 && <p className="text-sm text-muted-foreground">The match was not finished. The points shown are the ones that were played.</p>}
          {m.outcome === "disqualified" && m.games.length === 0 && <p className="text-sm text-muted-foreground">The referee disqualified the loser before play.</p>}
        </section>
      )}

      <section aria-labelledby="about-heading" className="flex flex-col gap-2">
        <h2 id="about-heading" className="text-2xl font-bold">
          About this match
        </h2>
        <dl className="flex flex-col rounded-xl border bg-card">
          {facts.map(([label, value]) => (
            <div key={label} className="flex flex-wrap justify-between gap-x-4 gap-y-1 border-t px-3 py-2.5 first:border-t-0">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-semibold">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-sm text-muted-foreground">Scores are entered by the umpire assigned to the match and become official once the umpire confirms the finished match. The organizers can record a walkover or a retirement, and correct a result with a reason.</p>
      </section>
    </>
  )
}

type Incident = NonNullable<MatchDetail["scoring"]>["incidents"][number]

/** The cards among a sheet's incidents, as the live score lists them. */
const cardsOf = (incidents: Incident[]): CardShown[] =>
  incidents
    .filter((incident) => incident.kind === "card" || incident.kind === "adviser_card")
    .map((incident) => ({
      side: incident.side as CardShown["side"],
      player_name: incident.player_name,
      card: incident.card as CardShown["card"],
      penalty_points: incident.penalty_points,
      adviser: incident.kind === "adviser_card",
      reason: incident.reason,
    }))

/** The live score of the match, or of the rubber of a tie being played now. Reading only: no control. */
function Live({ match: m, names }: { match: MatchDetail; names: { a: string; b: string } }) {
  if (m.scoring?.live) return <LiveScoreboard score={m.scoring.live} cards={cardsOf(m.scoring.incidents)} names={names} />
  const rubber = m.tie?.rubbers.find((candidate) => candidate.status === "scheduled" && candidate.scoring?.live)
  if (!rubber?.scoring?.live) return null
  const team = (players: { display_name: string }[], fallback: string) => players.map((player) => player.display_name).join(" / ") || fallback
  return (
    <LiveScoreboard
      heading={`Live: rubber ${rubber.position}`}
      score={rubber.scoring.live}
      cards={cardsOf(rubber.scoring.incidents)}
      names={{ a: team(rubber.a_players, names.a), b: team(rubber.b_players, names.b) }}
    />
  )
}
