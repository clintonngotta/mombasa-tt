"""The Python score validator against the shared fixtures (REQ-012, EVAL-012, TASK-023).

packages/scoring/fixtures holds the hand-worked fixtures F-SC1 to F-SC10 (listed in test.md) and
parity.json: random streams with a digest of the state after every event as the TypeScript reducer
computed it. Both implementations run the same files, so they agree after every event.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from scoring.engine import Scoring, ScoringError, check_config, games_needed, replay

# In the checkout the fixtures sit beside the TypeScript reducer. The compose API container sees only
# services/api, so compose.yml mounts them and says where through SCORING_FIXTURES.
HERE = Path(__file__).resolve()
CHECKOUT = HERE.parents[3] if len(HERE.parents) > 3 else HERE.parent
FIXTURES = Path(os.environ.get("SCORING_FIXTURES") or CHECKOUT / "packages/scoring/fixtures")
HAND_WORKED = sorted(FIXTURES.glob("f-sc*.json"))


def events_of(step: dict) -> list[dict]:
    if "points" in step:
        return [{"type": "point", "side": side} for side in step["points"]]
    return [step["event"]]


def digest(state: dict) -> str:
    """The fingerprint packages/scoring/test/fixtures.ts computes: canonical JSON, SHA-256, 12 hex."""
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def test_the_shared_fixtures_are_there():
    assert len(HAND_WORKED) == 26, f"expected the scoring fixtures in {FIXTURES}"


@pytest.mark.parametrize("path", HAND_WORKED, ids=lambda path: path.stem)
def test_hand_worked_fixture(path):
    fixture = json.loads(path.read_text())
    scoring = Scoring(fixture["config"])
    for number, step in enumerate(fixture["steps"], start=1):
        if "error" in step:
            before = json.dumps(scoring.state, sort_keys=True)
            with pytest.raises(ScoringError) as refused:
                scoring.push(step["event"])
            assert refused.value.code == step["error"], f"step {number}"
            assert json.dumps(scoring.state, sort_keys=True) == before, f"step {number}: state changed"
            continue
        for event in events_of(step):
            scoring.push(event)
        for field, value in step.get("expect", {}).items():
            assert scoring.state[field] == value, f"step {number}: {field}"


def parity_matches() -> list[dict]:
    return json.loads((FIXTURES / "parity.json").read_text())


def test_random_streams_give_the_state_the_typescript_reducer_recorded_after_every_event():
    matches = parity_matches()
    assert len(matches) >= 24
    compared = 0
    for number, match in enumerate(matches, start=1):
        scoring = Scoring(match["config"])
        for at, sent in enumerate(match["events"], start=1):
            where = f"match {number}, event {at} ({sent['event']})"
            if "error" in sent:
                with pytest.raises(ScoringError) as refused:
                    scoring.push(sent["event"])
                assert refused.value.code == sent["error"], where
                continue
            assert digest(scoring.push(sent["event"])) == sent["digest"], f"{where}: {scoring.state}"
            compared += 1
    assert compared > 1500


def test_no_stream_ends_in_an_impossible_score():
    for match in parity_matches():
        accepted = [sent["event"] for sent in match["events"] if "error" not in sent]
        needed = games_needed(match["config"]["best_of"])
        for state in replay(match["config"], accepted):
            for a, b in state["games"]:
                assert max(a, b) >= 11 and abs(a - b) >= 2
                assert max(a, b) == 11 or abs(a - b) == 2
            a, b = state["points"]
            assert not (max(a, b) >= 11 and abs(a - b) >= 2)
            assert sum(state["games_won"]) == len(state["games"])
            # Played to its end exactly when a side has the games needed; a retirement or a
            # disqualification ends it earlier, with the points played and nothing made up.
            played = state["status"] == "completed" and state["outcome"] == "played"
            assert played == (max(state["games_won"]) == needed)
            assert (state["status"] == "completed") == (state["outcome"] is not None)
            if state["status"] == "in_progress":
                assert state["server"][0] != state["receiver"][0]


@pytest.mark.parametrize(
    "config", [{"best_of": 4, "doubles": False}, {"best_of": 5}, {"best_of": "5", "doubles": False}, None]
)
def test_a_configuration_the_rules_dont_know_is_refused(config):
    with pytest.raises(ScoringError) as refused:
        check_config(config)
    assert refused.value.code == "invalid_config"
    with pytest.raises(ScoringError):
        Scoring(config)


def test_a_refused_event_leaves_the_state_object_alone():
    scoring = Scoring({"best_of": 5, "doubles": False})
    scoring.push({"type": "start", "server": "a1", "a_end": "left"})
    before = scoring.state
    with pytest.raises(ScoringError):
        scoring.push({"type": "start", "server": "a1", "a_end": "left"})
    assert scoring.state is before
    scoring.push({"type": "point", "side": "a"})
    assert before["points"] == [0, 0]  # earlier states are never edited in place
