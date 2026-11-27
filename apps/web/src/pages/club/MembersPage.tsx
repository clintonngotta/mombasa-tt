import { useDeferredValue, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { ApiError, errorMessage } from "@/lib/api"
import { InviteLink } from "@/components/guests/InviteLink"
import {
  addMember,
  can,
  clubKeys,
  getMemberValues,
  listMembers,
  listRoles,
  nominateAdmin,
  type AdminNominationKind,
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
import { OrganizationName } from "@/components/clubs/KindBadge"

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
      <p className="text-muted-foreground"><OrganizationName organization={membership.organization} /></p>
      <AdminPanel membership={membership} />
      {can(membership, "members.manage") && <AddMember membership={membership} />}
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

/** Add someone to the club directly. They are a member at once and get a link to set a password and sign
 * in; somebody already on Coast TT uses the same link to sign in and take the membership. */
function AddMember({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ display_name: "", email: "", phone: "" })
  const add = useMutation({
    mutationFn: (sent: typeof form) => addMember(orgId, { display_name: sent.display_name, email: sent.email, phone: sent.phone || null }),
    onSuccess: () => {
      setForm({ display_name: "", email: "", phone: "" })
      setOpen(false)
      void queryClient.invalidateQueries({ queryKey: clubKeys.membersAll(orgId) })
    },
  })
  const fieldErrors = add.error instanceof ApiError ? add.error.fieldErrors() : {}
  const added = add.data
  const hasFieldError = Object.keys(fieldErrors).length > 0

  return (
    <>
      {added?.invite_link && (
        <InviteLink
          member
          link={added.invite_link}
          name={added.display_name}
          club={membership.organization.name}
          phone={add.variables?.phone || null}
          emailed={!!add.variables?.email}
          onDone={() => add.reset()}
        />
      )}
      {!open ? (
        <Button variant="outline" className="self-start" onClick={() => setOpen(true)}>
          Add a member
        </Button>
      ) : (
        <form
          className="flex flex-col gap-3 rounded-xl border bg-card p-4"
          onSubmit={(e) => {
            e.preventDefault()
            add.mutate({ display_name: form.display_name.trim(), email: form.email.trim(), phone: form.phone.trim() })
          }}
        >
          <h2 className="text-lg font-bold">Add a member</h2>
          <p className="text-sm text-muted-foreground">
            They join the club now and get a link to set a password and sign in. If they already use Coast TT, the same link
            signs them in and adds the membership to their account.
          </p>
          <Field label="Name" required maxLength={80} value={form.display_name} onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))} error={fieldErrors.display_name} />
          <div className="flex flex-wrap gap-3">
            <Field label="Email" type="email" optional className="min-w-[200px] flex-1" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} error={fieldErrors.email} hint="We email the link." />
            <Field label="Phone" type="tel" inputMode="tel" optional className="min-w-[160px] flex-1" value={form.phone} onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))} error={fieldErrors.phone} hint="You share the link by WhatsApp or SMS." />
          </div>
          {add.isError && !hasFieldError && <FormAlert>{errorMessage(add.error, "We couldn't add the member.")}</FormAlert>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={add.isPending || !form.display_name.trim() || (!form.email.trim() && !form.phone.trim())}>
              {add.isPending ? "Adding…" : "Add and send link"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </form>
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
    mutationFn: (kind: AdminNominationKind) => nominateAdmin(orgId, member.id, kind),
    onSuccess: () => setConfirmAdmin(false),
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.admin(orgId) }),
  })
  const iAmAdmin = membership.roles.some((role) => role.key === "admin")
  const memberIsAdmin = member.roles.some((role) => role.key === "admin")

  // Offer only what the server would allow: roles whose permissions the actor holds can be toggled.
  const assignable = roles.filter((role) => role.key !== "member")
  // The Admin role is given only by nomination (REQ-045), never in the role editor.
  const options = assignable.map((role) => ({
    value: role.id,
    label: role.name,
    description:
      role.key === "admin" ? "Changes by nomination: use Make admin" : withinAuthority(membership, role.permissions) ? undefined : "Has permissions you don't hold",
    disabled: role.key === "admin" || !withinAuthority(membership, role.permissions),
  }))
  const heldPermissions = roles.filter((role) => member.roles.some((r) => r.id === role.id)).flatMap((r) => r.permissions)
  const canRemove =
    roles.length > 0 && can(membership, "members.manage") && !isSelf && !memberIsAdmin && withinAuthority(membership, heldPermissions)

  return (
    <li className={ROW}>
      <span className="flex min-w-0 flex-1 basis-full flex-col sm:basis-0">
        <span className="truncate font-semibold">
          {name}
          {isSelf && <span className="font-normal text-muted-foreground"> (you)</span>}
        </span>
        <span className="text-sm text-muted-foreground">
          {roleNames(member.roles)}
          {member.is_guest && " · added by staff, hasn't signed in yet"}
        </span>
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
          {iAmAdmin && !isSelf && !member.is_guest && !memberIsAdmin && (
            <Button variant="outline" aria-label={`Make ${name} an admin`} onClick={() => setConfirmAdmin(true)}>
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
        <div className="flex w-full flex-col gap-2">
          <p className="text-sm">
            Nominate {name} as a club admin? Nothing changes until they accept, and you can cancel until then. Add them to be an admin beside you (a club has up to
            three), or hand over your own place and keep only your other roles.
          </p>
          {nominate.isError && <FormAlert>{errorMessage(nominate.error)}</FormAlert>}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setConfirmAdmin(false)}>
              Keep
            </Button>
            <Button disabled={nominate.isPending} aria-label={`Add ${name} as an admin`} onClick={() => nominate.mutate("addition")}>
              {nominate.isPending && nominate.variables === "addition" ? "Nominating…" : "Add as admin"}
            </Button>
            <Button variant="outline" disabled={nominate.isPending} aria-label={`Hand over my admin place to ${name}`} onClick={() => nominate.mutate("nomination")}>
              {nominate.isPending && nominate.variables === "nomination" ? "Nominating…" : "Hand over my place"}
            </Button>
          </div>
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
