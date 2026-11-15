from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "core.authentication.SessionAuthentication"
    name = "sessionAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "cookie", "name": "sessionid"}


def require_response_fields(result, generator, request, public):
    """Mark every property of a response component as required.

    DRF serializers always render every declared field, but drf-spectacular marks fields with model
    defaults as optional, so generated clients would treat e.g. `kind` as possibly missing. Request
    components (split out by COMPONENT_SPLIT_REQUEST and suffixed `Request`) keep their real optionality.
    """
    for name, schema in result.get("components", {}).get("schemas", {}).items():
        if name.endswith("Request") or "properties" not in schema:
            continue
        schema["required"] = sorted(schema["properties"])
    return result
