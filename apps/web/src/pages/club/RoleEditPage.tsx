import { useState, type FormEvent } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { ApiError, errorMessage } from "@/lib/api"
import {
  can,
  clubKeys,
  createRole,
  deleteRole,
  listPermissions,
  listRoles,
  updateRole,
  useActiveMembership,
  type Membership,
  type Permission,
  type Role,
} from "@/lib/clubs"
import { AccessLost } from "@/components/clubs/AccessLost"

/** Create a role or edit one (REQ-005). Permissions the editor doesn't hold are shown but locked. */
export function RoleEditPage() {
  const { id } = useParams()
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "roles.manage")
  const roles = useQuery({ queryKey: clubKeys.roles(orgId), queryFn: () => listRoles(orgId), enabled: allowed && !!id })
  const role = id ? roles.data?.find((r) => r.id === id) : undefined

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to="/club/roles">Roles</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">{id ? (role?.name ?? "Role") : "New role"}</h1>
      {memberships.isSuccess && !allowed && <AccessLost />}
      {roles.isError && <FormAlert>{errorMessage(roles.error, "We couldn't load this role.")}</FormAlert>}
      {id && roles.isSuccess && !role && <FormAlert>This role no longer exists.</FormAlert>}
      {active && allowed && (!id || role) && <RoleForm key={role?.id ?? "new"} membership={active} role={role} />}
    </div>
  )
}

function RoleForm({ membership, role }: { membership: Membership; role?: Role }) {
  const orgId = membership.organization.id
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [name, setName] = useState(role?.name ?? "")
  const [permissions, setPermissions] = useState<Permission[]>(role?.permissions ?? [])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const catalog = useQuery({ queryKey: clubKeys.permissions, queryFn: listPermissions, staleTime: Infinity })
  const isAdminRole = role?.key === "admin"
  const deletable = role && role.key !== "admin" && role.key !== "member"

  const done = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: clubKeys.roles(orgId) }),
      queryClient.invalidateQueries({ queryKey: clubKeys.membersAll(orgId) }),
      queryClient.invalidateQueries({ queryKey: clubKeys.memberships }),
    ])
    navigate("/club/roles")
  }
  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), ...(isAdminRole ? {} : { permissions }) }
      return role ? updateRole(orgId, role.id, body) : createRole(orgId, body)
    },
    onSuccess: done,
  })
  const remove = useMutation({ mutationFn: () => deleteRole(orgId, role!.id), onSuccess: done })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  const fields = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const options = (catalog.data ?? []).map((p) => ({
    value: p.code,
    label: p.label,
    // Nobody grants or removes a permission they don't hold; the Admin role always has them all.
    disabled: isAdminRole || !membership.permissions.includes(p.code),
  }))

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      <Field label="Name" required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} error={fields.name} />
      {role?.key === "member" && <p className="text-sm text-muted-foreground">Everyone in the club has this role's permissions.</p>}
      {isAdminRole && <p className="text-sm text-muted-foreground">Admin always has every permission. You can rename it.</p>}
      {catalog.isPending && <p className="text-muted-foreground">Loading permissions…</p>}
      {catalog.isError && <FormAlert>{errorMessage(catalog.error, "We couldn't load the permission list.")}</FormAlert>}
      {catalog.isSuccess && (
        <ChoiceGroup
          multiple
          legend="Permissions"
          columns={2}
          options={options}
          value={permissions}
          onChange={setPermissions}
          error={fields.permissions}
        />
      )}
      {!isAdminRole && options.some((o) => o.disabled) && (
        <p className="text-sm text-muted-foreground">Greyed-out permissions are ones you don't hold, so you can't change them.</p>
      )}
      {save.isError && Object.keys(fields).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <Button type="submit" size="lg" disabled={save.isPending}>
        {save.isPending ? "Saving…" : role ? "Save role" : "Create role"}
      </Button>

      {deletable && (
        <section aria-label="Delete role" className="flex flex-col gap-2 border-t pt-4">
          {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
          {confirmDelete ? (
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex-1 text-sm">
                Delete {role.name}? {role.member_count > 0 && `${role.member_count} member(s) lose it. `}This can't be undone.
              </p>
              <Button type="button" variant="outline" onClick={() => setConfirmDelete(false)}>
                Keep
              </Button>
              <Button type="button" variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
                {remove.isPending ? "Deleting…" : "Delete role"}
              </Button>
            </div>
          ) : (
            <Button type="button" variant="ghost" className="self-start text-destructive" onClick={() => setConfirmDelete(true)}>
              Delete role
            </Button>
          )}
        </section>
      )}
    </form>
  )
}
