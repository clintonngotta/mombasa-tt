import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useId, useState, type FormEvent } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Field, FieldError, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { Toggle } from "@/components/forms/Toggle"
import { ApiError, errorMessage } from "@/lib/api"
import {
  can,
  clubKeys,
  createMemberField,
  FIELD_KIND_LABEL,
  listMemberFields,
  setMemberFieldRetired,
  updateMemberField,
  useActiveMembership,
  type MemberField,
  type MemberFieldKind,
} from "@/lib/clubs"
import { AccessLost } from "@/components/clubs/AccessLost"

const KIND_OPTIONS = (Object.keys(FIELD_KIND_LABEL) as MemberFieldKind[]).map((kind) => ({ value: kind, label: FIELD_KIND_LABEL[kind] }))

const VISIBILITY_OPTIONS: { value: MemberField["visibility"]; label: string; description: string }[] = [
  { value: "member", label: "Member and staff", description: "Each member sees and fills in their own answer" },
  { value: "staff", label: "Staff only", description: "Only people who manage members see it" },
]

/** Create a custom member field or edit one (REQ-005). The type is fixed after creation. */
export function MemberFieldEditPage() {
  const { id } = useParams()
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "members.manage")
  const fields = useQuery({ queryKey: clubKeys.memberFields(orgId), queryFn: () => listMemberFields(orgId), enabled: allowed && !!id })
  // Cached definitions outlive a role change; without the permission, show none of them.
  const field = id && allowed ? fields.data?.find((f) => f.id === id && !f.retired_at) : undefined

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to="/club/fields">Member fields</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">{id ? (field?.label ?? "Member field") : "New member field"}</h1>
      {memberships.isSuccess && !allowed && <AccessLost />}
      {fields.isError && <FormAlert>{errorMessage(fields.error, "We couldn't load this field.")}</FormAlert>}
      {id && allowed && fields.isSuccess && !field && <FormAlert>This field is retired or no longer exists.</FormAlert>}
      {active && allowed && (!id || field) && <FieldForm key={field?.id ?? "new"} orgId={orgId} field={field} />}
    </div>
  )
}

function FieldForm({ orgId, field }: { orgId: string; field?: MemberField }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const optionsId = useId()
  const draft = useDraft(`member-field:${field?.id ?? "new"}`)
  const [label, setLabel] = useDraftState(draft, "label", field?.label ?? "")
  const [kind, setKind] = useDraftState<MemberFieldKind | "">(draft, "kind", field?.kind ?? "")
  const [options, setOptions] = useDraftState(draft, "options", field?.options.join("\n") ?? "")
  const [required, setRequired] = useDraftState(draft, "required", field?.required ?? false)
  // New fields start staff-only, like the API: nothing is shown to members until someone chooses to.
  const [visibility, setVisibility] = useDraftState<MemberField["visibility"]>(draft, "visibility", field?.visibility ?? "staff")
  const [confirmRetire, setConfirmRetire] = useState(false)

  const done = async () => {
    // Definitions shape every value form, so refresh everything club-related.
    await queryClient.invalidateQueries({ queryKey: clubKeys.all })
    navigate("/club/fields")
  }
  const save = useMutation({
    mutationFn: () => {
      const body = {
        label: label.trim(),
        required,
        visibility,
        ...(kind === "choice" ? { options: options.split("\n").map((o) => o.trim()).filter(Boolean) } : {}),
      }
      return field ? updateMemberField(orgId, field.id, body) : createMemberField(orgId, { ...body, kind: (kind || undefined) as MemberFieldKind })
    },
    onSuccess: () => {
      draft.clear()
      return done()
    },
  })
  const retire = useMutation({ mutationFn: () => setMemberFieldRetired(orgId, field!.id, true), onSuccess: done })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const optionsErrorId = `${optionsId}-error`

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      <Field
        label="Label"
        required
        maxLength={80}
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        error={errors.label}
        hint="What members and staff see, e.g. Membership number"
      />
      {field ? (
        <p className="text-sm text-muted-foreground">
          Type: {FIELD_KIND_LABEL[field.kind]}. The type can't change; retire this field and add a new one instead.
        </p>
      ) : (
        <ChoiceGroup legend="Type" columns={3} options={KIND_OPTIONS} value={kind} onChange={setKind} error={errors.kind} />
      )}
      {kind === "choice" && (
        <div className="flex flex-col gap-2">
          <Label htmlFor={optionsId} className="text-base font-semibold">
            Options
          </Label>
          <textarea
            id={optionsId}
            rows={5}
            value={options}
            aria-invalid={errors.options ? true : undefined}
            aria-describedby={errors.options ? optionsErrorId : undefined}
            onChange={(e) => setOptions(e.target.value)}
            className="w-full rounded-lg border border-input bg-card px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive"
          />
          {errors.options ? (
            <FieldError id={optionsErrorId}>{errors.options}</FieldError>
          ) : (
            <p className="text-sm text-muted-foreground">
              One per line, at least two. Removing an option keeps the answers members already gave.
            </p>
          )}
        </div>
      )}
      <ChoiceGroup legend="Who sees it" options={VISIBILITY_OPTIONS} value={visibility} onChange={setVisibility} error={errors.visibility} />
      {field?.visibility === "staff" && visibility === "member" && (
        <p role="status" className="text-sm font-semibold text-warning">
          Each member will see the answer staff already recorded for them under this field.
        </p>
      )}
      <Toggle
        checked={required}
        onChange={setRequired}
        label="Required"
        description="An answer can't be left blank or cleared when these details are saved."
      />
      {save.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <DraftBar draft={draft} />
      <Button type="submit" size="lg" disabled={save.isPending}>
        {save.isPending ? "Saving…" : field ? "Save field" : "Create field"}
      </Button>

      {field && (
        <section aria-label="Retire field" className="flex flex-col gap-2 border-t pt-4">
          {retire.isError && <FormAlert>{errorMessage(retire.error)}</FormAlert>}
          {confirmRetire ? (
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex-1 text-sm">
                Retire {field.label}? It stops showing for members and staff. Answers are kept, and you can restore it later.
              </p>
              <Button type="button" variant="outline" onClick={() => setConfirmRetire(false)}>
                Keep
              </Button>
              <Button type="button" variant="destructive" disabled={retire.isPending} onClick={() => retire.mutate()}>
                {retire.isPending ? "Retiring…" : "Retire field"}
              </Button>
            </div>
          ) : (
            <Button type="button" variant="ghost" className="self-start text-destructive" onClick={() => setConfirmRetire(true)}>
              Retire field
            </Button>
          )}
        </section>
      )}
    </form>
  )
}
