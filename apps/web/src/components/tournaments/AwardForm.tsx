import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trophy } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { addAward, ceremonyKeys, getCeremony, type Ceremony } from "@/lib/ceremony"
import { listTournamentUmpires, umpireKeys } from "@/lib/reservations"

/** Awards the organizers give themselves; "Something else" lets them name their own (user request, 2026-11-28). */
const KINDS = ["Best player", "Best umpire", "Most improved player", "Fair play", "Best young player", "Best coach", "Best club", "Player of the tournament", "Sponsor's prize"]

/** Keeps the ceremony the server sent back and refreshes players' honours. */
function useSetCeremony(tournamentId: string) {
  const queryClient = useQueryClient()
  return (fresh: Ceremony) => {
    queryClient.setQueryData(ceremonyKeys.detail(tournamentId), fresh)
    return queryClient.invalidateQueries({ queryKey: ceremonyKeys.honours })
  }
}

/**
 * Add one of the organizers' own awards: best player, best umpire, fair play or anything they name. The
 * recipient is a name, or one of the tournament's umpires, so a best umpire's award goes to their account.
 */
export function NewAward({ tournamentId, onAdded }: { tournamentId: string; onAdded?: () => void }) {
  const set = useSetCeremony(tournamentId)
  const [open, setOpen] = useState(false)
  const [preset, setPreset] = useState("")
  const [title, setTitle] = useState("")
  const [name, setName] = useState("")
  const [umpire, setUmpire] = useState("")
  const [prize, setPrize] = useState("")
  const [presenter, setPresenter] = useState("")
  const umpires = useQuery({ queryKey: umpireKeys.roster(tournamentId), queryFn: () => listTournamentUmpires(tournamentId), enabled: open })
  const add = useMutation({
    mutationFn: () =>
      addAward(tournamentId, {
        title: title.trim(),
        prize: prize.trim(),
        presenter: presenter.trim(),
        ...(umpire ? { recipient_id: umpire } : { recipient_name: name.trim() }),
      }),
    onSuccess: async (fresh) => {
      setPreset("")
      setTitle("")
      setName("")
      setUmpire("")
      setPrize("")
      setPresenter("")
      setOpen(false)
      await set(fresh)
      onAdded?.()
    },
  })
  const fields: Record<string, string | undefined> = add.error instanceof ApiError ? add.error.fieldErrors() : {}
  if (!open) {
    return (
      <Button variant="outline" className="self-start" onClick={() => setOpen(true)}>
        <Plus aria-hidden className="size-4" /> Add an award
      </Button>
    )
  }
  const roster = umpires.data ?? []
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        add.mutate()
      }}
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
    >
      <h3 className="text-lg font-bold">Add an award</h3>
      {add.isError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <SelectField
        label="Award"
        options={[...KINDS, ""].map((value) => ({ value, label: value || "Something else" }))}
        value={preset}
        onChange={(value) => {
          setPreset(value)
          setTitle(value)
        }}
      />
      {!preset && <Field label="Name of the award" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} error={fields.title} placeholder="Best doubles pair, Spirit of the game" />}
      {roster.length > 0 && (
        <SelectField
          label="One of this tournament's umpires"
          optional
          options={[{ value: "", label: "No, someone else" }, ...roster.map((person) => ({ value: person.user_id, label: person.display_name }))]}
          value={umpire}
          onChange={setUmpire}
          hint="The award then shows among their honours."
          error={fields.recipient_id}
        />
      )}
      {!umpire && <Field label="Recipient" optional maxLength={120} value={name} onChange={(e) => setName(e.target.value)} hint="Leave empty to name them on the day." error={fields.recipient_name} />}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Prize" optional maxLength={200} value={prize} onChange={(e) => setPrize(e.target.value)} placeholder="Trophy, medal, KES 5,000" />
        <Field label="Presented by" optional maxLength={120} value={presenter} onChange={(e) => setPresenter(e.target.value)} placeholder="Regional chair, sponsor" />
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={add.isPending || !title.trim()}>
          Add
        </Button>
        <Button type="button" variant="outline" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

/** On the announcements page: the organizers' own awards, which a tournament announcement lists under "Awards". */
export function AwardsPanel({ tournamentId }: { tournamentId: string }) {
  const ceremony = useQuery({
    queryKey: ceremonyKeys.detail(tournamentId),
    queryFn: () => getCeremony(tournamentId).catch((error) => (error instanceof ApiError && error.status === 404 ? null : Promise.reject(error))),
  })
  const special = (ceremony.data?.awards ?? []).filter((award) => award.kind === "special")
  return (
    <section aria-labelledby="awards-heading" className="flex flex-col gap-3 rounded-xl border p-4">
      <h2 id="awards-heading" className="flex items-center gap-2 text-2xl font-bold">
        <Trophy aria-hidden className="size-6 text-brand-gold" /> Awards
      </h2>
      <p className="text-sm text-muted-foreground">
        Best player, best umpire, fair play or any award you name. An announcement of the whole tournament lists them under "Awards", after the podiums; generate it again after adding one.
      </p>
      {ceremony.isError && <FormAlert>{errorMessage(ceremony.error)}</FormAlert>}
      {special.length > 0 && (
        <ul className="flex flex-col gap-1">
          {special.map((award) => (
            <li key={award.id}>
              <span className="font-semibold">{award.title}</span>: {award.receives || <span className="text-muted-foreground">to be named</span>}
              {award.prize && <span className="text-muted-foreground"> ({award.prize})</span>}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-start gap-2">
        <NewAward tournamentId={tournamentId} />
        <Link to={`/tournaments/${tournamentId}/ceremony`} className={buttonVariants({ variant: "ghost" })}>
          Award ceremony
        </Link>
      </div>
    </section>
  )
}
