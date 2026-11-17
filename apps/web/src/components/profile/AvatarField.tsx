import { useRef, useState, type ChangeEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Avatar } from "@/components/profile/Avatar"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { AVATAR_TYPES, MAX_AVATAR_BYTES, playerKeys, profileKeys, removeAvatar, uploadAvatar, type Profile } from "@/lib/profile"

/** Choose, replace or remove the profile picture. Saves straight away, separately from the profile form. */
export function AvatarField({ avatar }: { avatar: Profile["avatar"] }) {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [tooBig, setTooBig] = useState(false)

  const settle = (next: (profile: Profile) => Profile) => {
    queryClient.setQueryData<Profile>(profileKeys.me, (profile) => profile && next(profile))
    return queryClient.invalidateQueries({ queryKey: playerKeys.all })
  }
  const upload = useMutation({ mutationFn: uploadAvatar, onSuccess: (profile) => settle((old) => ({ ...old, avatar: profile.avatar })) })
  const remove = useMutation({ mutationFn: removeAvatar, onSuccess: () => settle((old) => ({ ...old, avatar: null })) })
  const busy = upload.isPending || remove.isPending

  function onChoose(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = "" // choosing the same file again should still fire
    if (!file) return
    remove.reset()
    upload.reset()
    setTooBig(file.size > MAX_AVATAR_BYTES)
    if (file.size <= MAX_AVATAR_BYTES) upload.mutate(file)
  }

  const failed = upload.error ?? remove.error
  const message = tooBig
    ? "Choose an image under 5 MB."
    : failed && ((failed instanceof ApiError && failed.fieldErrors().file) || errorMessage(failed, "We couldn't save your photo. Try again."))

  return (
    <section aria-labelledby="avatar-heading" className="flex flex-col gap-3">
      <p id="avatar-heading" className="font-semibold">
        Profile photo <span className="font-normal text-muted-foreground">(optional)</span>
      </p>
      <div className="flex flex-wrap items-center gap-4">
        <Avatar link={avatar} className="size-20" />
        <div className="flex flex-wrap gap-2">
          <input ref={input} type="file" accept={AVATAR_TYPES} className="sr-only" tabIndex={-1} aria-hidden onChange={onChoose} />
          <Button type="button" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
            {upload.isPending ? "Uploading…" : avatar ? "Change photo" : "Choose photo"}
          </Button>
          {avatar && (
            <Button type="button" variant="ghost" disabled={busy} onClick={() => { setTooBig(false); upload.reset(); remove.mutate() }}>
              {remove.isPending ? "Removing…" : "Remove photo"}
            </Button>
          )}
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        JPEG, PNG or WebP, up to 5 MB. Other players see it only while you're listed in the player directory. Location and camera details
        saved in the photo are removed.
      </p>
      {message && <FormAlert>{message}</FormAlert>}
    </section>
  )
}
