import { useRef, useState, type ChangeEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ImagePlus, Images, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, apiOriginUrl, errorMessage } from "@/lib/api"
import { addOrganizationImage, clubKeys, listOrganizationImages, removeOrganizationImage, type OrganizationImage } from "@/lib/clubs"

const IMAGE_TYPES = "image/jpeg,image/png,image/webp"
const MAX_IMAGE_BYTES = 5 * 1024 * 1024
/** A signed link lasts a few minutes. A picture that fails to load asks for fresh links, but not more
 * often than this, so a picture that is really gone can't keep the page asking. */
const REFRESH_AFTER_MS = 30_000

/**
 * The pictures a club, team or facility shows of itself (REQ-058): its hall, its players, a trophy. Anyone
 * signed in sees them; with `manage` (holders of roles.manage) pictures are added and removed here.
 * Without pictures and without `manage`, nothing is drawn.
 */
export function OrganizationGallery({ orgId, manage = false }: { orgId: string; manage?: boolean }) {
  const queryClient = useQueryClient()
  const key = clubKeys.images(orgId)
  const gallery = useQuery({ queryKey: key, queryFn: () => listOrganizationImages(orgId), enabled: !!orgId })
  const input = useRef<HTMLInputElement>(null)
  const [caption, setCaption] = useState("")
  const [refused, setRefused] = useState("")
  const add = useMutation({
    mutationFn: (file: File) => addOrganizationImage(orgId, file, caption.trim()),
    onSuccess: (data) => {
      queryClient.setQueryData(key, data)
      setCaption("")
    },
  })
  const remove = useMutation({
    mutationFn: (imageId: string) => removeOrganizationImage(orgId, imageId),
    onSuccess: (data) => queryClient.setQueryData(key, data),
  })

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = "" // so choosing the same file again still fires
    if (!file) return
    if (file.size > MAX_IMAGE_BYTES) return setRefused("Choose an image under 5 MB.")
    setRefused("")
    add.mutate(file)
  }

  function onBroken() {
    if (Date.now() - gallery.dataUpdatedAt > REFRESH_AFTER_MS) void gallery.refetch()
  }

  const images = gallery.data?.images ?? []
  const limit = gallery.data?.limit ?? 0
  if (!manage && images.length === 0) return null
  const failed = add.error ?? remove.error
  const fileError = failed instanceof ApiError ? (failed.fieldErrors().file ?? failed.fieldErrors().caption) : undefined

  return (
    <section aria-labelledby="pictures-heading" className="flex flex-col gap-3">
      <h2 id="pictures-heading" className="flex items-center gap-2 text-xl font-bold">
        <Images aria-hidden className="size-5 text-brand-blue" /> Pictures
      </h2>
      {manage && (
        <p className="text-sm text-muted-foreground">
          Shown on your profile to players on Coast TT: your hall, your players, a trophy. Up to {limit || 12} pictures; JPEG, PNG or WebP up to 5 MB each. Location
          and camera details are removed.
        </p>
      )}
      {gallery.isError && <FormAlert>{errorMessage(gallery.error, "We couldn't load the pictures.")}</FormAlert>}
      {images.length > 0 && (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {images.map((image, index) => (
            <li key={image.id} className="flex flex-col gap-1">
              <Picture image={image} number={index + 1} onBroken={onBroken} />
              {manage && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="self-start text-muted-foreground"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(image.id)}
                  aria-label={`Remove picture ${index + 1}${image.caption ? `: ${image.caption}` : ""}`}
                >
                  <Trash2 aria-hidden className="size-4" /> Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {manage && gallery.isSuccess && (
        <div className="flex flex-col gap-3 rounded-xl border bg-card p-4">
          {images.length >= limit ? (
            <p className="text-sm text-muted-foreground">You have {limit} pictures, the most a profile shows. Remove one to add another.</p>
          ) : (
            <>
              <Field
                label="Caption for the next picture"
                optional
                maxLength={120}
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                hint="For example: Friday league night."
              />
              <input ref={input} type="file" accept={IMAGE_TYPES} className="sr-only" tabIndex={-1} aria-hidden onChange={onPick} />
              <Button type="button" variant="outline" className="self-start" disabled={add.isPending} onClick={() => input.current?.click()}>
                <ImagePlus aria-hidden className="size-5" />
                {add.isPending ? "Uploading…" : "Add a picture"}
              </Button>
              <p className="text-sm text-muted-foreground">
                {images.length} of {limit} used.
              </p>
            </>
          )}
          {refused && <FormAlert>{refused}</FormAlert>}
          {failed && <FormAlert>{fileError ?? errorMessage(failed, "We couldn't save that. Try again.")}</FormAlert>}
        </div>
      )}
    </section>
  )
}

/** One picture as a 4:3 tile that opens at full size. */
function Picture({ image, number, onBroken }: { image: OrganizationImage; number: number; onBroken: () => void }) {
  const src = apiOriginUrl(image.file.url)
  const name = image.caption || `Picture ${number}`
  return (
    <Dialog>
      <DialogTrigger
        render={<button type="button" aria-label={`View ${name}`} className="block w-full cursor-zoom-in overflow-hidden rounded-xl border bg-muted outline-none focus-visible:ring-3 focus-visible:ring-ring/50" />}
      >
        <img src={src} alt={image.caption} loading="lazy" onError={onBroken} className="aspect-[4/3] w-full object-cover" />
      </DialogTrigger>
      {image.caption && <p className="text-sm break-words text-muted-foreground">{image.caption}</p>}
      <DialogContent className="w-auto max-w-[calc(100vw-1rem)] p-2 sm:max-w-[calc(100vw-4rem)]">
        <DialogTitle className="sr-only">{name}</DialogTitle>
        <img src={src} alt={image.caption} onError={onBroken} className="max-h-[calc(100dvh-5rem)] max-w-full rounded-lg object-contain" />
        {image.caption && <p className="px-1 pt-2 text-sm">{image.caption}</p>}
      </DialogContent>
    </Dialog>
  )
}
