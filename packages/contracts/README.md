# @mombasa-tt/contracts

TypeScript types generated from the API's OpenAPI schema (`services/api/openapi.yaml`). Shared by the web app now and
by the native client later (REQ-001). Do not edit `api-schema.d.ts` by hand: regenerate it from `apps/web` with
`pnpm gen:api`. CI fails when it drifts from the committed schema.

The event's `admission` field carries the [open or organizer-approved registration rule](../../spec.md#req-008). The registration window has its own fields.
