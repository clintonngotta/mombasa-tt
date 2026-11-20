import { useDeferredValue, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { errorMessage } from "@/lib/api"
import {
  can,
  clubKeys,
  getMemberValues,
  listMembers,
  listRoles,
  nominateAdmin,
  removeMember,
  roleNames,
  saveMemberValues,
  setMemberRoles,
  useActiveMembership,
  withinAuthority,
  type Member,
  type Membership,
  type Role,
} from "@/lib/clubs"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { MemberFieldValuesForm } from "@/components/clubs/MemberFieldValuesForm"
import { AdminPanel } from "@/components/clubs/AdminPanel"

/** Members of the active organization, their roles and, for member managers, their custom field values (REQ-005).
 * Never contact details. */
export function MembersPage() {
  const { memberships, active } = useActiveMembership()
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Members</h1>
      {memberships.isPending && <p className="text-muted-foreground">Loading…</p>}
      {memberships.isSuccess && !can(active, "members.manage", "roles.manage") && <AccessLost />}
      {active && can(active, "members.manage", "roles.manage") && <MemberList key={active.organization.id} membership={active} />}
    </div>
  )
}

function MemberList({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const [term, setTerm] = useState("")
  const search = useDeferredValue(term.trim())
  const members = useQuery({ queryKey: clubKeys.members(orgId, search), queryFn: () => listMembers(orgId, search) })
  // Needed by both permissions: role editing, and knowing whom a members-only manager may remove.
  const roles = useQuery({ queryKey: clubKeys.roles(orgId), queryFn: () => listRoles(orgId) })
  const accessLost = useAdminAccessLost(members.error, roles.error)
  const items = members.data?.results ?? []

  return (
    <>
      <p className="text-muted-foreground">{membership.organization.name}</p>
      <AdminPanel membership={membership} />
      <Field label="Search members" type="search" value={term} onChange={(e) => setTerm(e.target.value)} hint="By display name" />
      {accessLost && <AccessLost />}
      {members.isPending && <p className="text-muted-foreground">Loading members…</p>}
      {members.isError && !accessLost && <FormAlert>{errorMessage(members.error, "We couldn't load members.")}</FormAlert>}
      {members.isSuccess && items.length === 0 && <p className="text-muted-foreground">No members match.</p>}
      <ul className="flex flex-col gap-2">
        {items.map((member) => (
          <MemberRow key={member.id} member={member} membership={membership} roles={roles.data ?? []} />
        ))}
      </ul>
      {members.data && members.data.count > items.length && (
        <p className="text-sm text-muted-foreground">
          Showing {items.length} of {members.data.count}. Search to narrow the list.
        </p>
      )}
    </>
  )
}

function MemberRow({ member, membership, roles }: { member: Member; membership: Membership; roles: Role[] }) {
  const orgId = membership.organization.id
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [confirmAdmin, setConfirmAdmin] = useState(false)
  const [selected, setSelected] = useState<string[]>(member.roles.map((r) => r.id))
  const name = member.display_name || "Unnamed player"
  const isSelf = member.id === membership.id
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: clubKeys.membersAll(orgId) }),
      queryClient.invalidateQueries({ queryKey: clubKeys.roles(orgId) }),
      queryClient.invalidateQueries({ queryKey: clubKeys.memberships }),
    ])

  const save = useMutation({
    mutationFn: () => setMemberRoles(orgId, member.id, selected),
    onSuccess: () => setEditing(false),
    onSettled: refresh,
  })
  const remove = useMutation({ mutationFn: () => removeMember(orgId, member.id), onSettled: refresh })
  const nominate = useMutation({
    mutationFn: () => nominateAdmin(orgId, member.id),
    onSuccess: () => setConfirmAdmin(false),
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.admin(orgId) }),
  })
  const iAmAdmin = membership.roles.some((role) => role.key === "admin")

  // Offer only what the server would allow: roles whose permissions the actor holds can be toggled.
  const assignable = roles.filter((role) => role.key !== "member")
  // The Admin role moves only by nomination (REQ-045), never in the role editor.
  const options = assignable.map((role) => ({
    value: role.id,
    label: role.name,
    description:
      role.key === "admin" ? "Changes by nomination: use Make admin" : withinAuthority(membership, role.permissions) ? undefined : "Has permissions you don't hold",
    disabled: role.key === "admin" || !withinAuthority(membership, role.permissions),
  }))
  const heldPermissions = roles.filter((role) => member.roles.some((r) => r.id === role.id)).flatMap((r) => r.permissions)
  const canRemove =
    roles.length > 0 && can(membership, "members.manage") && !isSelf && withinAuthority(membership, heldPermissions)

  return (
    <li className={ROW}>
      <span className="flex min-w-0 flex-1 basis-full flex-col sm:basis-0">
        <span className="truncate font-semibold">
          {name}
          {isSelf && <span className="font-normal text-muted-foreground"> (you)</span>}
        </span>
        <span className="text-sm text-muted-foreground">{roleNames(member.roles)}</span>
      </span>
      {!editing && !confirmRemove && !showDetails && !confirmAdmin && (
        <div className="flex gap-2">
          {can(membership, "members.manage") && (
            <Button variant="outline" aria-label={`Club details for ${name}`} onClick={() => setShowDetails(true)}>
              Details
            </Button>
          )}
          {can(membership, "roles.manage") && roles.length > 0 && (
            <Button
              variant="outline"
              aria-label={`Change roles for ${name}`}
              onClick={() => {
                // Start from the latest list data, not what the row held when it first rendered.
                setSelected(member.roles.map((r) => r.id))
                setEditing(true)
              }}
            >
              Roles
            </Button>
          )}
          {iAmAdmin && !isSelf && (
            <Button variant="outline" aria-label={`Make ${name} the admin`} onClick={() => setConfirmAdmin(true)}>
              Make admin
            </Button>
          )}
          {canRemove && (
            <Button variant="ghost" aria-label={`Remove ${name}`} onClick={() => setConfirmRemove(true)}>
              Remove
            </Button>
          )}
        </div>
      )}

      {editing && (
        <form
          className="flex w-full flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <ChoiceGroup multiple legend={`Roles for ${name}`} options={options} value={selected} onChange={setSelected} />
          <p className="text-sm text-muted-foreground">Everyone also has the Member role's permissions.</p>
          {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
          <div className="flex gap-2">
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save roles"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setSelected(member.roles.map((r) => r.id))
                save.reset()
                setEditing(false)
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      )}

      {/* Checked on every render: cached values must go as soon as the permission does. */}
      {showDetails && can(membership, "members.manage") && <MemberDetails orgId={orgId} member={member} name={name} onClose={() => setShowDetails(false)} />}

      {confirmAdmin && (
        <div className="flex w-full flex-wrap items-center gap-2">
          <p className="flex-1 text-sm">
            Nominate {name} as the club admin? Once they accept, they take over and you keep only your other roles. You can cancel until then.
          </p>
          {nominate.isError && <FormAlert>{errorMessage(nominate.error)}</FormAlert>}
          <Button variant="outline" onClick={() => setConfirmAdmin(false)}>
            Keep
          </Button>
          <Button disabled={nominate.isPending} onClick={() => nominate.mutate()}>
            {nominate.isPending ? "Nominating…" : "Nominate"}
          </Button>
        </div>
      )}

      {confirmRemove && (
        <div className="flex w-full flex-wrap items-center gap-2">
          <p className="flex-1 text-sm">Remove {name} from the club? Their roles end; they can ask to join again.</p>
          {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
          <Button variant="outline" onClick={() => setConfirmRemove(false)}>
            Keep
          </Button>
          <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {remove.isPending ? "Removing…" : "Remove"}
          </Button>
        </div>
      )}
    </li>
  )
}

/** Staff view of one member's custom field values, staff-only fields included. */
function MemberDetails({ orgId, member, name, onClose }: { orgId: string; member: Member; name: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  const key = clubKeys.memberValues(orgId, member.id)
  const details = useQuery({ queryKey: key, queryFn: () => getMemberValues(orgId, member.id) })
  const accessLost = useAdminAccessLost(details.error)
  return (
    <section aria-label={`Club details for ${name}`} className="flex w-full flex-col gap-3">
      {details.isPending && <p className="text-muted-foreground">Loading details…</p>}
      {accessLost && <AccessLost />}
      {details.isError && !accessLost && <FormAlert>{errorMessage(details.error, "We couldn't load these details.")}</FormAlert>}
      {details.isSuccess && details.data.length === 0 && (
        <p className="text-sm text-muted-foreground">
          This club has no member fields yet.{" "}
          <Link to="/club/fields" className="font-semibold text-brand-blue">
            Add fields
          </Link>
        </p>
      )}
      {details.isSuccess && !accessLost && details.data.length > 0 ? (
        <MemberFieldValuesForm
          entries={details.data}
          markStaffOnly
          save={(values) => saveMemberValues(orgId, member.id, values)}
          onSaved={(entries) => {
            queryClient.setQueryData(key, entries)
            // The member's own view of the same answers (if it's this player) is now stale.
            void queryClient.invalidateQueries({ queryKey: clubKeys.myFieldValues(member.id) })
          }}
          onCancel={onClose}
        />
      ) : (
        <Button variant="outline" className="self-start" onClick={onClose}>
          Close
        </Button>
      )}
    </section>
  )
}
