"""Contract fixtures (TASK-006, EVAL-032): the committed schema matches the API, and every error reply
uses the published ApiError envelope."""

from pathlib import Path

import pytest
import yaml
from django.core.management import call_command

from .helpers import logged_in, make_user

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "openapi.yaml"


@pytest.fixture(scope="module")
def schema(tmp_path_factory):
    out = tmp_path_factory.mktemp("schema") / "openapi.yaml"
    call_command("spectacular", "--fail-on-warn", "--file", str(out))
    return out.read_text()


def test_committed_schema_is_current(schema):
    assert SCHEMA_FILE.read_text() == schema, "openapi.yaml is stale; regenerate it (see README)"


def test_every_operation_documents_the_error_envelope(schema):
    doc = yaml.safe_load(schema)
    assert set(doc["components"]["schemas"]["ApiError"]["required"]) == {
        "code",
        "message",
        "fields",
        "request_id",
    }
    for path, item in doc["paths"].items():
        for method, op in item.items():
            assert op["responses"]["4XX"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ApiError"
            }, f"{method.upper()} {path}"


def test_response_components_mark_every_field_required(schema):
    organization = yaml.safe_load(schema)["components"]["schemas"]["Organization"]
    assert set(organization["required"]) == set(organization["properties"])  # incl. defaulted `kind`


def _assert_envelope(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"code", "message", "fields", "request_id"}
    assert body["code"] == code
    assert isinstance(body["message"], str) and body["message"]
    assert body["request_id"] == response["X-Request-ID"]
    return body


@pytest.mark.django_db
def test_error_fixtures_share_one_envelope(client):
    _assert_envelope(client.get("/api/v1/me/profile/"), 401, "not_authenticated")

    player = logged_in(make_user("kofi@example.com"))
    body = _assert_envelope(
        player.post("/api/v1/organizations/", {"name": ""}, format="json"), 400, "validation_error"
    )
    assert set(body["fields"]) == {"name", "town"}

    _assert_envelope(
        player.get("/api/v1/organizations/00000000-0000-0000-0000-000000000000/"), 404, "not_found"
    )

    org = player.post(
        "/api/v1/organizations/", {"name": "Kilindini TT", "town": "Mombasa"}, format="json"
    ).json()
    outsider = logged_in(make_user("outsider@example.com"))
    _assert_envelope(
        outsider.get(f"/api/v1/organizations/{org['id']}/join-requests/"), 403, "not_organization_admin"
    )
