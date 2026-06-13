"""
Checkpoint state for resumable pipeline stages.

State file: content/raw/{edition}-state.json
Schema: per-stage status (pending|partial|complete), per-stage done sets,
token tally per model, timestamps.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from edition import RAW_DIR


def _state_path(edition: str) -> Path:
    return RAW_DIR / f"{edition}-state.json"


def _empty_state(edition: str) -> dict:
    return {
        "edition": edition,
        "stages": {
            "discover": {"status": "pending", "done": []},
            "curate": {"status": "pending", "done": []},
            "finalize": {"status": "pending", "done_clusters": [], "assembly_done": False, "intro_done": False},
        },
        "token_tally": {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_state(edition: str) -> dict:
    path = _state_path(edition)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return _empty_state(edition)


def save_state(edition: str, state: dict):
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _state_path(edition)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def get_stage_status(state: dict, stage: str) -> str:
    return state.get("stages", {}).get(stage, {}).get("status", "pending")


def set_stage_status(state: dict, stage: str, status: str):
    state.setdefault("stages", {}).setdefault(stage, {})["status"] = status


def get_done_set(state: dict, stage: str) -> set[str]:
    items = state.get("stages", {}).get(stage, {}).get("done", [])
    return set(items)


def add_done(state: dict, stage: str, item_id: str):
    done = state.setdefault("stages", {}).setdefault(stage, {}).setdefault("done", [])
    if item_id not in done:
        done.append(item_id)


def get_done_clusters(state: dict) -> set[str]:
    items = state.get("stages", {}).get("finalize", {}).get("done_clusters", [])
    return set(items)


def add_done_cluster(state: dict, cluster_id: str):
    done = state.setdefault("stages", {}).setdefault("finalize", {}).setdefault("done_clusters", [])
    if cluster_id not in done:
        done.append(cluster_id)


def update_token_tally(state: dict, model: str, tokens: int):
    tally = state.setdefault("token_tally", {})
    tally[model] = tally.get(model, 0) + tokens
