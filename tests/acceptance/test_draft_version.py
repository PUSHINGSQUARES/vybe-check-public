"""Explicit draft parents, strict refusal, compatibility, and inheritance."""
import copy
import json
import pytest
from vybe_check.workshop import SessionStore
from test_layout import workshop


@pytest.fixture
def parents(tmp_path):
    store = SessionStore(tmp_path / "state")
    session = store.create("Invented ceramic treatments")
    def apply(action, payload):
        nonlocal session
        session = store.apply(session["id"], session["revision"], action, payload)
        return session
    apply("direct_image", {"brief": {"outcome": "Ceramic light study", "subject_action": "Potter holds a bowl", "visual_priority": "Hands", "frame": "Medium shot", "light": "Soft light"},
        "locks": ["Blue bowl"], "provenance": [{"kind": "supplied", "text": "First reference", "source": "Invented brief"}],
        "settings": {"seed": 11, "model": "First fixture", "aspect_ratio": "4:3"}, "shots": [
        {"id": "old-main", "title": "First treatment", "prompt": "Blue bowl in soft light", "settings": {"seed": 12}},
        {"id": "old-detail", "title": "First detail", "prompt": "Blue rim", "settings": {"seed": 13}}]})
    apply("add_video_version", {"mode": "preserve", "duration": 12, "motion": "Gentle turn", "camera": "Locked camera", "settings": {"fps": 24, "sound": "Quiet room"}})
    apply("propose_brief", {"brief": {"outcome": "Second ceramic study", "subject_action": "Potter holds amber bowl", "visual_priority": "Rim"}, "locks": ["Amber bowl"], "provenance": [{"kind": "proposed", "text": "Second reference", "source": "Invented second brief"}]})
    apply("agree_brief", {})
    apply("add_image_version", {"settings": {"seed": 21, "model": "Second fixture", "aspect_ratio": "16:9"}, "shots": [
        {"id": "new-main", "title": "Second treatment", "prompt": "Amber bowl in hard light", "settings": {"seed": 22}},
        {"id": "new-detail", "title": "Second detail", "prompt": "Amber rim", "settings": {"seed": 23}}]})
    apply("add_video_version", {"mode": "evolve", "duration": 20, "motion": "Rapid turn", "camera": "Moving camera", "settings": {"fps": 60, "sound": "Wind"}})
    return store, session


def saved_bytes(store, identifier):
    return store._session_path(identifier).read_bytes(), store._registry_path(identifier).read_bytes()


@pytest.mark.parametrize("target", ["image", "video"])
def test_explicit_parent_save_and_agent_accept_inherit_older_truth(parents, target):
    store, before = parents
    payload = {"target": target, "text": "Revise the older treatment", "base_version": 1}
    if target == "image": payload["shot_id"] = "old-main"
    registry = saved_bytes(store, before["id"])[1]
    saved = store.apply(before["id"], before["revision"], "draft_edit", payload)
    assert saved["drafts"][-1]["base_version"] == 1
    assert saved["revision"] == before["revision"] + 1
    assert {k:v for k,v in saved.items() if k not in {"revision", "drafts"}} == {k:v for k,v in before.items() if k not in {"revision", "drafts"}}
    assert saved_bytes(store, before["id"])[1] == registry
    accepted = store.apply(before["id"], saved["revision"], "accept_draft", {"draft_id": saved["drafts"][-1]["id"]})
    old = before[target + "_versions"][0]
    latest = before[target + "_versions"][-1]
    result = accepted[target + "_versions"][-1]
    for key in ("settings", "locks", "provenance"):
        assert old[key] != latest[key], key
        assert result[key] == old[key], key
    if target == "image":
        assert result["source_image_version"] == 1
        assert result["shots"][1] == old["shots"][1]
        assert result["shots"][0]["settings"] == old["shots"][0]["settings"]
        assert result["shots"][0]["id"] == "old-main"
        assert "Revise the older treatment" in result["shots"][0]["prompt"]
    else:
        assert result["source_video_version"] == 1 and result["source_image_version"] == 1
        for key in ("mode", "duration", "motion", "camera"):
            assert result[key] == old[key] and old[key] != latest[key]
    assert accepted["drafts"][-1]["status"] == "accepted"


@pytest.mark.parametrize("target", ["image", "video"])
@pytest.mark.parametrize("invalid", [None, "1", 1.0, True, False, 0, -1, 999, [], {}])
def test_invalid_explicit_parent_refuses_without_writes(parents, target, invalid):
    store, session = parents
    before = saved_bytes(store, session["id"])
    payload = {"target": target, "text": "Preserve this refusal", "base_version": invalid}
    if target == "image": payload["shot_id"] = "old-main"
    with pytest.raises(ValueError): store.apply(session["id"], session["revision"], "draft_edit", payload)
    assert saved_bytes(store, session["id"]) == before


@pytest.mark.parametrize("shot", [None, "new-main", "unknown"])
def test_series_shot_validates_against_explicit_parent(parents, shot):
    store, session = parents
    before = saved_bytes(store, session["id"])
    payload = {"target": "image", "text": "Ambiguous edit", "base_version": 1}
    if shot is not None: payload["shot_id"] = shot
    with pytest.raises(ValueError): store.apply(session["id"], session["revision"], "draft_edit", payload)
    assert saved_bytes(store, session["id"]) == before


@pytest.mark.parametrize("target", ["image", "video"])
def test_omitted_parent_keeps_agent_default(parents, target):
    store, session = parents
    payload = {"target": target, "text": "Agent default treatment"}
    if target == "image": payload["shot_id"] = "new-main"
    saved = store.apply(session["id"], session["revision"], "draft_edit", payload)
    assert saved["drafts"][-1]["base_version"] == 2


def test_empty_image_draft_compatibility_and_explicit_refusal(tmp_path):
    store = SessionStore(tmp_path / "state"); session = store.create()
    saved = store.apply(session["id"], 0, "draft_edit", {"text": "Unresolved initial idea"})
    assert saved["drafts"][-1]["base_version"] is None
    before = saved_bytes(store, session["id"])
    for payload in ({"target": "image", "base_version": 1}, {"target": "video"}):
        with pytest.raises(ValueError): store.apply(session["id"], saved["revision"], "draft_edit", {"text": "No parent exists", **payload})
        assert saved_bytes(store, session["id"]) == before


@pytest.mark.parametrize("target", ["image", "video"])
def test_wrong_target_only_version_refused(parents, target):
    store, session = parents
    if target == "video":
        session = store.apply(session["id"], session["revision"], "add_image_version", {"shots": [{"id": "third", "title": "Third", "prompt": "Green bowl"}]})
    else:
        session = store.apply(session["id"], session["revision"], "add_video_version", {"mode": "preserve", "motion": "Third turn", "camera": "Third camera"})
    before = saved_bytes(store, session["id"])
    payload = {"target": target, "text": "Wrong target", "base_version": 3}
    if target == "image": payload["shot_id"] = "new-main"
    with pytest.raises(ValueError): store.apply(session["id"], session["revision"], "draft_edit", payload)
    assert saved_bytes(store, session["id"]) == before


@pytest.mark.parametrize("target", ["image", "video"])
def test_explicit_parent_api_refusal_preserves_nonce_revision_and_permissions(workshop, target):
    import http.client
    from urllib.parse import urlsplit
    store, identifier = workshop["store"], workshop["id"]
    before = saved_bytes(store, identifier)
    origin = workshop["url"].split("/?")[0]
    def post(body):
        connection = http.client.HTTPConnection(urlsplit(origin).netloc, timeout=3)
        try:
            connection.request("POST", "/api/event", json.dumps(body), {"Content-Type": "application/json", "Origin": origin})
            response=connection.getresponse(); return response.status, json.loads(response.read())
        finally: connection.close()
    body={"session_id":identifier,"expected_revision":workshop["initial"]["revision"],"nonce":store.nonce_for(identifier),"action":"draft_edit","payload":{"target":target,"text":"A draft", "base_version":1}}
    if target=="image": body["payload"]["shot_id"]="one"
    for invalid in (None,"1",1.0,True,False,0,-1,999):
        refused=copy.deepcopy(body); refused["payload"]["base_version"]=invalid
        assert post(refused)[0]==400
        assert saved_bytes(store,identifier)==before
    refused=copy.deepcopy(body);refused["nonce"]="Invalid nonce"
    assert post(refused)[0]==403 and saved_bytes(store,identifier)==before
    refused=copy.deepcopy(body);refused["expected_revision"]-=1
    assert post(refused)[0]==409 and saved_bytes(store,identifier)==before
    status,result=post(body); assert status==200
    saved=store.read(identifier); assert saved["drafts"][-1]["base_version"]==1
    refusal=copy.deepcopy(body);refusal["expected_revision"]=saved["revision"];refusal["action"]="accept_draft";refusal["payload"]={"draft_id":saved["drafts"][-1]["id"]}
    after=saved_bytes(store,identifier)
    assert post(refusal)[0]==400 and saved_bytes(store,identifier)==after
