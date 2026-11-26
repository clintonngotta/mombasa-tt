import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Landmark, Map } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { Segmented } from "@/components/forms/Segmented"
import { ApiError, api, errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { countryName } from "@/lib/geography"
import { bodyKeys, createGoverningBody, listGoverningBodies, type GoverningBodyInput } from "@/lib/regions"

type Kind = GoverningBodyInput["kind"]
type Option = { value: string; label: string }
const KINDS: { value: Kind; label: string }[] = [
  { value: "regional_body", label: "Regional" },
  { value: "national_body", label: "National" },
]

/** Platform super admins create each region's and country's governing body and name its first admin
 * (REQ-045, TASK-107). The body's admin then runs it like a club, and gives its officials the Official
 * role, which approves the jurisdiction's tournaments. Countries and regions come from the platform's
 * catalogue, the only places a body can be for. */
export function GoverningBodies() {
  const queryClient = useQueryClient()
  const bodies = useQuery({ queryKey: bodyKeys.all, queryFn: listGoverningBodies })
  const countries = useQuery({ queryKey: ["catalogue", "countries"], queryFn: () => api<Option[]>("/geography/countries/") })
  const [kind, setKind] = useState<Kind>("regional_body")
  const [country, setCountry] = useState("")
  const [region, setRegion] = useState("")
  const [name, setName] = useState("")
  const [adminEmail, setAdminEmail] = useState("")
  const regions = useQuery({
    queryKey: ["catalogue", "country", country],
    queryFn: () => api<{ regions: { name: string }[] }>(`/geography/countries/${encodeURIComponent(country)}/`),
    enabled: !!country && kind === "regional_body",
  })
  const create = useMutation({
    mutationFn: () =>
      createGoverningBody({
        kind,
        country,
        name: name.trim(),
        admin_email: adminEmail.trim(),
        ...(kind === "regional_body" ? { region } : {}),
      }),
    onSuccess: async () => {
      setName("")
      setAdminEmail("")
      setRegion("")
      await queryClient.invalidateQueries({ queryKey: bodyKeys.all })
    },
  })
  const fields = create.error instanceof ApiError ? create.error.fieldErrors() : {}

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    create.mutate()
  }

  return (
    <section aria-labelledby="bodies-admin-heading" className="flex flex-col gap-3">
      <h2 id="bodies-admin-heading" className="text-xl font-bold">
        Governing bodies
      </h2>
      <p className="text-sm text-muted-foreground">
        Each region and the country have one body. Its admin runs it and gives officials the Official role, which approves the region's or the country's tournaments.
      </p>
      {bodies.isError && <FormAlert>{errorMessage(bodies.error, "We couldn't load the bodies.")}</FormAlert>}
      {bodies.isSuccess && bodies.data.length === 0 && <p className="text-muted-foreground">No bodies yet.</p>}
      {bodies.isSuccess && bodies.data.length > 0 && (
        <ul className="flex flex-col gap-2">
          {bodies.data.map((body) => {
            const Icon = body.kind === "national_body" ? Landmark : Map
            return (
              <li key={body.id} className={ROW}>
                <Icon aria-hidden className="size-5 shrink-0 text-brand-blue" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-semibold">{body.name}</span>
                  <span className="text-sm text-muted-foreground">
                    {body.kind === "national_body" ? `National body · ${countryName(body.country)}` : `Regional body · ${body.region}, ${countryName(body.country)}`}
                  </span>
                </span>
              </li>
            )
          })}
        </ul>
      )}

      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4 rounded-xl border bg-card p-4">
        <h3 className="font-semibold">Create a body</h3>
        <Segmented label="Kind of body" options={KINDS} value={kind} onChange={(value) => { setKind(value); setRegion("") }} />
        <div className="grid items-start gap-3 sm:grid-cols-2">
          <SelectField
            label="Country"
            value={country}
            onChange={(code) => { setCountry(code); setRegion("") }}
            options={countries.data ?? []}
            placeholder={countries.isPending ? "Loading countries…" : "Choose a country"}
            disabled={countries.isPending}
            error={fields.country}
          />
          {kind === "regional_body" && (
            <SelectField
              label="Region"
              value={region}
              onChange={setRegion}
              options={(regions.data?.regions ?? []).map((r) => ({ value: r.name, label: r.name }))}
              placeholder={country && regions.isPending ? "Loading regions…" : "Choose a region"}
              disabled={!country || regions.isPending}
              error={fields.region}
            />
          )}
        </div>
        <Field label="Name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} error={fields.name} placeholder={kind === "national_body" ? "Kenya Table Tennis Association" : "Mombasa County Table Tennis"} />
        <Field label="First admin's email" type="email" required maxLength={254} autoComplete="off" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} error={fields.admin_email} hint="They need an account. They become the body's admin at once." />
        {create.isError && Object.keys(fields).length === 0 && <FormAlert>{errorMessage(create.error, "We couldn't create the body.")}</FormAlert>}
        {create.isSuccess && <p role="status" className="text-sm text-success">{create.data.name} is ready.</p>}
        <Button type="submit" className="self-start" disabled={create.isPending || !country || !name.trim() || !adminEmail.trim() || (kind === "regional_body" && !region)}>
          {create.isPending ? "Creating…" : "Create body"}
        </Button>
      </form>
    </section>
  )
}
