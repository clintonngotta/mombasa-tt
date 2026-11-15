import { FormAlert } from "@/components/forms/Field"

/** Shown when the server refuses a staff action because the player's roles changed. */
export function AccessLost() {
  return <FormAlert>Your role in this organization no longer allows this.</FormAlert>
}
