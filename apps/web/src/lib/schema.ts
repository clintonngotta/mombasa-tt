// Types generated from the API's OpenAPI schema (services/api/openapi.yaml). Regenerate with `pnpm gen:api`;
// CI fails when the committed schema or these types drift from the API (TASK-006).
import type { components } from "@/lib/api-schema"

export type Schemas = components["schemas"]

/** DRF page envelope used by every paginated list endpoint. */
export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] }
