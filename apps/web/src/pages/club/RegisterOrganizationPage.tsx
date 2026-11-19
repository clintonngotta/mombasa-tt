import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { TextAreaField } from "@/components/forms/SelectField"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { LocationFields } from "@/components/forms/LocationFields"
import { PlaceFinderFields } from "@/components/forms/PlaceFinderFields"
import { placeFinderBody, placeFinderErrors, placeFinderFrom } from "@/lib/place"
import { ApiError, errorMessage } from "@/lib/api"
import { KIND_LABEL, clubKeys, createOrganization, setActiveOrganization, type OrganizationInput, type OrganizationKind } from "@/lib/clubs"
import { locationErrors } from "@/lib/geography"

const KIND_OPTIONS = (Object.keys(KIND_LABEL) as OrganizationKind[]).map((value) => ({ value, label: KIND_LABEL[value] }))

export function RegisterOrganizationPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form, setForm] = useState<Omit<OrganizationInput, "directions" | "latitude" | "longitude">>({ name: "", town: "", country: "", region: "", description: "", kind: "club" })
  const [finder, setFinder] = useState(placeFinderFrom())
  const [submitted, setSubmitted] = useState(false)
  const location = { country: form.country, region: form.region, city: form.town }
  const missingLocation = { ...locationErrors(location), ...placeFinderErrors(finder) }

  const create = useMutation({
    mutationFn: createOrganization,
    onSuccess: async (organization) => {
      await queryClient.invalidateQueries({ queryKey: clubKeys.all })
      setActiveOrganization(organization.id)
      navigate("/club")
    },
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitted(true)
    if (Object.keys(missingLocation).length > 0) return
    create.mutate({ ...form, name: form.name.trim(), town: form.town.trim(), ...placeFinderBody(finder) })
  }

  const fields = create.error instanceof ApiError ? create.error.fieldErrors() : {}
  const hasFieldErrors = Object.keys(fields).length > 0

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Register an organization</h1>
        <p className="text-muted-foreground">You become its first admin and can then invite members and approve join requests.</p>
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
        <Field
          label="Name"
          required
          maxLength={120}
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          error={fields.name}
        />
        <LocationFields
          value={location}
          onChange={({ country, region, city }) => setForm({ ...form, country, region, town: city })}
          errors={submitted ? { ...fields, ...missingLocation } : fields}
          cityLimit={80}
        />
        <PlaceFinderFields value={finder} onChange={setFinder} errors={submitted ? { ...fields, ...missingLocation } : fields} place={form.kind === "facility" ? "facility" : "club"} />
        <TextAreaField
          label="About"
          optional
          rows={3}
          maxLength={2000}
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          error={fields.description}
          hint="Players looking for a club read this. You can change it later."
        />
        <ChoiceGroup
          legend="Type"
          columns={3}
          options={KIND_OPTIONS}
          value={form.kind}
          onChange={(kind) => setForm({ ...form, kind })}
        />
        {create.isError && !hasFieldErrors && <FormAlert>{errorMessage(create.error)}</FormAlert>}
        <Button type="submit" size="lg" disabled={create.isPending}>
          {create.isPending ? "Registering…" : "Register"}
        </Button>
      </form>
    </div>
  )
}
