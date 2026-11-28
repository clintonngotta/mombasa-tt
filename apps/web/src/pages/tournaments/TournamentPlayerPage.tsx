import { Link, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Building2, Trophy, UserRound } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { Avatar } from "@/components/profile/Avatar"
import { MatchCard } from "@/components/tournaments/MatchCard"
import { EntryStatusChip } from "@/components/tournaments/StatusChip"
import { buttonVariants } from "@/components/ui/button"
import { ApiError, errorMessage } from "@/lib/api"
import { POOL_LABEL } from "@/lib/entries"
import { DETAIL_LABEL, PUBLISHED_DETAILS, detailText } from "@/lib/profile"
import { getTournamentPlayer, tournamentPlayerKeys, type PlayerEvent } from "@/lib/tournamentPlayers"
import { getTournament, tournamentKeys } from "@/lib/tournaments"

const record = (won: number, lost: number) => `${won} won, ${lost} lost`

/**
 * One player in one tournament (TASK-148): who they are, as far as their profile lets the reader see,
 * and what they did here, event by event, with every match of the published draws.
 */
export function TournamentPlayerPage() {
  const { id = "", playerId = "" } = useParams()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const player = useQuery({ queryKey: tournamentPlayerKeys.detail(id, playerId), queryFn: () => getTournamentPlayer(id, playerId) })
  const back = <BackLink to={`/tournaments/${id}`}>{tournament.data?.name ?? "Tournament"}</BackLink>

  if (player.isPending) {
    return (
      <div className="flex max-w-[720px] flex-col gap-4">
        {back}
        <p className="text-muted-foreground">Loading player…</p>
      </div>
    )
  }
  if (player.isError) {
    const gone = player.error instanceof ApiError && player.error.status === 404
    return (
      <div className="flex max-w-[720px] flex-col gap-4">
        {back}
        <FormAlert>{gone ? "This player isn't in this tournament." : errorMessage(player.error, "We couldn't load this player.")}</FormAlert>
      </div>
    )
  }

  const data = player.data
  const profile = data.player
  const details = PUBLISHED_DETAILS.map((detail) => ({ detail, text: detailText(profile, detail) })).filter((d) => d.text)
  const timeZone = tournament.data?.timezone ?? "Africa/Nairobi"

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      {back}
      <header className="flex items-center gap-4">
        {profile.avatar ? (
          <Avatar link={profile.avatar} className="size-16" />
        ) : (
          <span className="flex size-16 shrink-0 items-center justify-center rounded-full bg-muted">
            <UserRound aria-hidden className="size-8 text-muted-foreground" />
          </span>
        )}
        <div className="flex min-w-0 flex-col gap-0.5">
          <h1 className="text-[28px] leading-8 font-bold break-words">{profile.display_name}</h1>
          {profile.nickname && <p className="text-muted-foreground">“{profile.nickname}”</p>}
          <p className="font-semibold">
            {tournament.data?.name ? `${tournament.data.name}: ` : ""}
            {record(data.won, data.lost)}
          </p>
        </div>
      </header>

      {(profile.clubs.length > 0 || details.length > 0 || data.has_player_page) && (
        <section aria-labelledby="profile-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
          <h2 id="profile-heading" className="text-xl font-bold">
            Profile
          </h2>
          {profile.clubs.length > 0 && (
            <ul className="flex flex-wrap gap-2" aria-label="Clubs">
              {profile.clubs.map((club) => (
                <li key={club} className="flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-semibold">
                  <Building2 aria-hidden className="size-4 text-brand-blue" /> {club}
                </li>
              ))}
            </ul>
          )}
          {details.length > 0 && (
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {details.map(({ detail, text }) => (
                <div key={detail} className={detail === "bio" ? "sm:col-span-2" : undefined}>
                  <dt className="text-sm text-muted-foreground">{DETAIL_LABEL[detail]}</dt>
                  <dd className="font-semibold whitespace-pre-line">{text}</dd>
                </div>
              ))}
            </dl>
          )}
          {data.has_player_page && (
            <Link to={`/players/${playerId}`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
              Player page
            </Link>
          )}
        </section>
      )}

      {data.events.map((shown) => (
        <EventRecord key={shown.event.id} tournamentId={id} shown={shown} timeZone={timeZone} />
      ))}
    </div>
  )
}

function EventRecord({ tournamentId, shown, timeZone }: { tournamentId: string; shown: PlayerEvent; timeZone: string }) {
  const place = [
    shown.seed ? `Seed ${shown.seed}` : "",
    shown.group_name,
    shown.group_rank ? `Placed ${shown.group_rank} so far` : "",
    shown.entry.pool ? POOL_LABEL[shown.entry.pool as keyof typeof POOL_LABEL] : "",
  ].filter(Boolean)
  return (
    <section aria-label={shown.event.name} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-bold break-words">{shown.event.name}</h2>
        <EntryStatusChip status={shown.entry_status} />
      </div>
      {shown.entry.players.length > 1 && <p className="text-muted-foreground">Entered as {shown.entry.title}</p>}
      {(place.length > 0 || shown.placement) && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {shown.placement && (
            <span className="inline-flex items-center gap-1 font-semibold text-success">
              <Trophy aria-hidden className="size-4" /> {shown.placement}
            </span>
          )}
          {place.length > 0 && <span className="text-muted-foreground">{place.join(" · ")}</span>}
        </p>
      )}
      {shown.matches.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card p-4 text-muted-foreground">No matches in a published draw yet.</p>
      ) : (
        <>
          <p className="font-semibold">{record(shown.won, shown.lost)}</p>
          <ul className="flex flex-col gap-2">
            {shown.matches.map((match) => (
              <li key={match.id}>
                <MatchCard
                  match={match}
                  heading={`${match.round_name}${match.result ? ` · ${match.result === "won" ? "Won" : "Lost"}` : ""}`}
                  to={`/tournaments/${tournamentId}/events/${shown.event.id}/matches/${match.id}`}
                  timeZone={timeZone}
                />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
