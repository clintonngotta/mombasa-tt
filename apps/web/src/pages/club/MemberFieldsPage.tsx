import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, EyeOff, Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { can, clubKeys, FIELD_KIND_LABEL, listMemberFields, setMemberFieldRetired, useActiveMembership, type MemberField } from "@/lib/clubs"
import { cn } from "@/lib/utils"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { OrganizationName } from "@/components/clubs/KindBadge"

const summary = (field: MemberField) =>
  [FIELD_KIND_LABEL[field.kind], field.required ? "required" : "optional", field.visibility === "staff" ? "staff only" : "members fill this in"].join(
    " · "
  )

/** The organization's custom member fields (REQ-005): active ones to edit, retired ones to restore. */
export function MemberFieldsPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "members.manage")
  const queryClient = useQueryClient()
  const fields = useQuery({ queryKey: clubKeys.memberFields(orgId), queryFn: () => listMemberFields(orgId), enabled: allowed })
  const restore = useMutation({
    mutationFn: (id: string) => setMemberFieldRetired(orgId, id, false),
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.all }),
  })
  const accessLost = useAdminAccessLost(fields.error, restore.error)
  // Cached definitions outlive a role change; once access is gone, show none of them.
  const visible = allowed && !accessLost ? (fields.data ?? []) : []
  const current = visible.filter((field) => !field.retired_at)
  const retired = visible.filter((field) => field.retired_at)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[32px] leading-9 font-bold">Member fields</h1>
          {active && <p className="text-muted-foreground"><OrganizationName organization={active.organization} /></p>}
        </div>
        {allowed && (
          <Link to="/club/fields/new" className={buttonVariants({ variant: "outline" })}>
            <Plus aria-hidden className="size-5" /> New field
          </Link>
        )}
      </div>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {fields.isPending && allowed && <p className="text-muted-foreground">Loading fields…</p>}
      {fields.isError && !accessLost && <FormAlert>{errorMessage(fields.error, "We couldn't load member fields.")}</FormAlert>}
      <p className="text-sm text-muted-foreground">
        Extra details your club keeps about each member, such as a membership number or shirt size. Members see and fill in
        their own answers unless a field is staff only. Staff-only fields are seen by people who manage members.
      </p>
      {allowed && !accessLost && fields.isSuccess && current.length === 0 && <p className="text-muted-foreground">No member fields yet.</p>}
      <ul className="flex flex-col gap-2">
        {current.map((field) => (
          <li key={field.id}>
            <Link to={`/club/fields/${field.id}`} className={cn(ROW, "min-h-12 outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="flex items-center gap-1 font-semibold">
                  {field.visibility === "staff" && <EyeOff aria-hidden className="size-4 text-muted-foreground" />}
                  {field.label}
                </span>
                <span className="text-sm text-muted-foreground">{summary(field)}</span>
              </span>
              <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>

      {retired.length > 0 && (
        <section aria-labelledby="retired-fields-heading" className="flex flex-col gap-3">
          <h2 id="retired-fields-heading" className="text-xl font-bold">
            Retired
          </h2>
          <p className="text-sm text-muted-foreground">No longer shown or asked for. Answers already given are kept.</p>
          {restore.isError && !accessLost && <FormAlert>{errorMessage(restore.error)}</FormAlert>}
          <ul className="flex flex-col gap-2">
            {retired.map((field) => (
              <li key={field.id} className={ROW}>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="font-semibold">{field.label}</span>
                  <span className="text-sm text-muted-foreground">{summary(field)}</span>
                </span>
                <Button
                  variant="outline"
                  aria-label={`Restore ${field.label}`}
                  disabled={restore.isPending && restore.variables === field.id}
                  onClick={() => restore.mutate(field.id)}
                >
                  Restore
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
