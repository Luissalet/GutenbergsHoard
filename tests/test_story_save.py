"""Atomic partial story save: compare-and-set under the publication lock (no DesignCraft needed)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gutenberg_hoard import publishing
from gutenberg_hoard.app import app as api


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GUTENBERG_DATA_DIR", str(tmp_path / "gutenberg-data"))
    monkeypatch.setenv("HOARD_EVENTS", "0")


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch):
    state = {"text": "Original words", "writes": []}

    def get_story(publication_id, story_id):
        with publishing._publication_lock(publication_id):
            return {"text": state["text"]}

    def native_actions(publication_id, actions, session_id=None):
        with publishing._publication_lock(publication_id):
            args = actions[0]["arguments"]
            assert actions[0]["name"] == "set_story_text" and args["story"] == 1
            state["writes"].append(args["text"])
            state["text"] = args["text"]
            return {"results": [], "undo_available": True}

    monkeypatch.setattr(publishing, "get_story", get_story)
    monkeypatch.setattr(publishing, "native_actions", native_actions)
    return state


def test_lock_is_reentrant_on_one_thread_and_released_afterwards():
    with publishing._publication_lock("pub1"):
        with publishing._publication_lock("pub1"):
            pass
    with publishing._publication_lock("pub1"):
        pass


def test_matching_base_text_saves_and_a_stale_one_is_refused(fake_engine):
    publishing.set_story_text("pub1", 1, "Mine", base_text="Original words")
    assert fake_engine["text"] == "Mine"
    with pytest.raises(publishing.StoryConflict):
        publishing.set_story_text("pub1", 1, "Stale overwrite", base_text="Original words")
    assert fake_engine["text"] == "Mine" and fake_engine["writes"] == ["Mine"]


def test_base_text_is_optional_for_callers_that_replace_blindly(fake_engine):
    publishing.set_story_text("pub1", 1, "Blind replace")
    assert fake_engine["text"] == "Blind replace"


def test_endpoint_maps_a_conflict_to_409(fake_engine):
    client = TestClient(api, base_url='http://127.0.0.1')
    ok = client.post("/api/publications/pub1/stories/1/text", json={"text": "A", "base_text": "Original words"})
    assert ok.status_code == 200
    stale = client.post("/api/publications/pub1/stories/1/text", json={"text": "B", "base_text": "Original words"})
    assert stale.status_code == 409 and "changed" in stale.json()["detail"]
    assert fake_engine["text"] == "A"
