import { useState } from "react"
import { Download, Share, SquarePlus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { isAppleMobile, isStandalone, promptInstall, useAppUpdate } from "@/lib/pwa"

/**
 * How to put Coast TT on the home screen, for the browser in hand (REQ-035): the browser's own button
 * where it offers one, the Share menu on iPhone and iPad, the browser menu elsewhere. Installing is never
 * needed: everything works in the browser too.
 */
export function InstallApp() {
  const { installable } = useAppUpdate()
  const [installed, setInstalled] = useState(false)
  if (installed || isStandalone()) return null

  return (
    <section aria-labelledby="install-heading" className="flex flex-col gap-2 rounded-xl border p-4">
      <h2 id="install-heading" className="flex items-center gap-2 font-semibold">
        <Download aria-hidden className="size-5 text-brand-blue" /> Put Coast TT on your home screen
      </h2>
      <p className="text-sm text-muted-foreground">It opens like an app and keeps working when the connection drops. You don't have to install it: everything works in the browser too.</p>
      {installable ? (
        <Button className="self-start" onClick={() => void promptInstall().then(setInstalled)}>
          Install Coast TT
        </Button>
      ) : isAppleMobile() ? (
        <ol className="flex list-decimal flex-col gap-1 pl-5 text-sm">
          <li>
            Tap <Share aria-label="Share" className="inline size-4 align-text-bottom" /> Share in the browser's toolbar.
          </li>
          <li>
            Choose <SquarePlus aria-hidden className="inline size-4 align-text-bottom" /> Add to Home Screen, then Add.
          </li>
        </ol>
      ) : (
        <p className="text-sm">Open your browser's menu and choose Install app or Add to Home screen.</p>
      )}
    </section>
  )
}
