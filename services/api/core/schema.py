from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "core.authentication.SessionAuthentication"
    name = "sessionAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "cookie", "name": "sessionid"}


REF_PREFIX = "#/components/schemas/"

ERROR_SCHEMA = {
    "type": "object",
    "description": "Envelope of every API error (REQ-032); see core.exceptions.api_exception_handler.",
    "properties": {
        "code": {"type": "string", "description": "Stable machine-readable code, e.g. `validation_error`"},
        "message": {"type": "string"},
        "fields": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Per-field messages for validation errors; empty otherwise",
        },
        "request_id": {"type": "string", "nullable": True},
    },
    "required": ["code", "fields", "message", "request_id"],
}


def _refs(node) -> set[str]:
    """Component names referenced anywhere inside an OpenAPI fragment."""
    if isinstance(node, dict):
        found = {node["$ref"].removeprefix(REF_PREFIX)} if isinstance(node.get("$ref"), str) else set()
        for value in node.values():
            found |= _refs(value)
        return found
    if isinstance(node, list):
        return set().union(*map(_refs, node)) if node else set()
    return set()


def _closure(names: set[str], schemas: dict) -> set[str]:
    """`names` plus every component they reference, transitively."""
    seen: set[str] = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        pending.extend(_refs(schemas[name]) - seen)
    return seen


def contract_hook(result, generator, request, public):
    """Postprocess the schema so generated clients match what the API actually sends.

    - Every property of a response-only component is required: DRF serializers always render every
      declared field, but drf-spectacular marks fields with model defaults as optional. Components used
      in request bodies keep their real optionality.
    - The shared error envelope is published as `ApiError` and documented as every operation's 4XX reply.
    """
    schemas = result.setdefault("components", {}).setdefault("schemas", {})
    operations = [
        op for item in result.get("paths", {}).values() for op in item.values() if "responses" in op
    ]

    used_in_requests = _closure(
        set().union(*(_refs(op.get("requestBody", {})) for op in operations)), schemas
    )
    used_in_responses = _closure(set().union(*(_refs(op["responses"]) for op in operations)), schemas)
    for name in used_in_responses - used_in_requests:
        if "properties" in schemas[name]:
            schemas[name]["required"] = sorted(schemas[name]["properties"])

    schemas["ApiError"] = ERROR_SCHEMA
    error_reply = {
        "description": "Error envelope",
        "content": {"application/json": {"schema": {"$ref": f"{REF_PREFIX}ApiError"}}},
    }
    for op in operations:
        op["responses"].setdefault("4XX", error_reply)
    return result
