import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { ApiError, errorMessage } from "@/lib/api"
import { KIND_LABEL, clubKeys, createOrganization, setActiveOrganization, type OrganizationInput, type OrganizationKind } from "@/lib/clubs"

const KIND_OPTIONS = (Object.keys(KIND_LABEL) as OrganizationKind[]).map((value) => ({ value, label: KIND_LABEL[value] }))

export function RegisterOrganizationPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form, setForm] = useState<OrganizationInput>({ name: "", town: "", kind: "club" })

  const create = useMutation({
    mutationFn: createOrganization,
    onSuccess: async (organization) => {
      await queryClient.invalidateQueries({ queryKey: clubKeys.memberships })
      setActiveOrganization(organization.id)
      navigate("/club")
    },
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    create.mutate({ ...form, name: form.name.trim(), town: form.town.trim() })
  }

  const fields = create.error instanceof ApiError ? create.error.fieldErrors() : {}
  const hasFieldErrors = Object.keys(fields).length > 0

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <Link to="/club" className="flex items-center gap-1 self-start text-sm font-semibold text-muted-foreground hover:text-foreground">
        <ArrowLeft aria-hidden className="size-4" /> Club
      </Link>
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
        <Field
          label="Town"
          required
          maxLength={80}
          value={form.town}
          onChange={(e) => setForm({ ...form, town: e.target.value })}
          error={fields.town}
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
