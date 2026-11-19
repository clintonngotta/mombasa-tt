import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { HandCoins } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { decideOffer, describeSponsorship, listOffers, listSponsors, regionKeys } from "@/lib/regions"

/** Sponsors of a tournament (REQ-048): the accepted ones for everyone; offers waiting for the host's
 * competition staff, who accept or decline them. */
export function SponsorsPanel({ tournamentId, staff }: { tournamentId: string; staff: boolean }) {
  const queryClient = useQueryClient()
  const sponsors = useQuery({ queryKey: regionKeys.sponsors(tournamentId), queryFn: () => listSponsors(tournamentId) })
  const offers = useQuery({ queryKey: regionKeys.offers(tournamentId), queryFn: () => listOffers(tournamentId), enabled: staff })
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "accept" | "decline" }) => decideOffer(tournamentId, id, action),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: regionKeys.all }),
  })
  const waiting = (offers.data ?? []).filter((offer) => offer.status === "offered")
  if (!sponsors.data?.length && !waiting.length) return null

  return (
    <section aria-labelledby="sponsors-heading" className="flex flex-col gap-3">
      <h2 id="sponsors-heading" className="text-xl font-bold">
        Sponsors
      </h2>
      {decide.isError && <FormAlert>{errorMessage(decide.error)}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {sponsors.data?.map((sponsor) => (
          <li key={sponsor.id} className={ROW}>
            <HandCoins aria-hidden className="size-5 text-brand-blue" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">{sponsor.sponsor.name}</span>
              <span className="text-sm text-muted-foreground">{describeSponsorship(sponsor)}</span>
            </span>
          </li>
        ))}
        {waiting.map((offer) => (
          <li key={offer.id} className={`${ROW} border-dashed`}>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">{offer.sponsor.name} offers to sponsor</span>
              <span className="text-sm">{describeSponsorship(offer)}</span>
              {offer.conditions && <span className="text-sm text-muted-foreground">Conditions: {offer.conditions}</span>}
            </span>
            <Button disabled={decide.isPending} onClick={() => decide.mutate({ id: offer.id, action: "accept" })}>
              Accept
            </Button>
            <Button variant="outline" disabled={decide.isPending} onClick={() => decide.mutate({ id: offer.id, action: "decline" })}>
              Decline
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}
