"""Real browser acceptance. Default imports must come from an installed candidate.

A source-only authoring run must explicitly supply VYBE_LAYOUT_SOURCE_ORIGIN.
Synthetic studies exercise media transport, never model generation.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import threading
import tempfile
from urllib.parse import urlsplit

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright, expect


def test_width_360(browser_page, tmp_path, monkeypatch):
    monkeypatch.setenv('VYBE_LAYOUT_EVIDENCE_DIR',str(tmp_path/'width-360-evidence'))
    test_measured_layout(browser_page,360)


def test_width_640(browser_page, tmp_path, monkeypatch):
    monkeypatch.setenv('VYBE_LAYOUT_EVIDENCE_DIR',str(tmp_path/'width-640-evidence'))
    test_measured_layout(browser_page,640)


def test_width_1024(browser_page, tmp_path, monkeypatch):
    monkeypatch.setenv('VYBE_LAYOUT_EVIDENCE_DIR',str(tmp_path/'width-1024-evidence'))
    test_measured_layout(browser_page,1024)


def test_keyboard(browser_page, workshop):
    test_keyboard_draft_copy_export_and_conflict(browser_page,workshop)

LONG = ("A potter turns a blue bowl under soft reflected light.\n" * 150) + "END OF LONG PROMPT"
LABEL = "Ceramic" * 80


@pytest.fixture
def workshop(tmp_path):
    import vybe_check
    from vybe_check.workshop import SessionStore
    from vybe_check.studio.server import create_server
    origin = Path(vybe_check.__file__).resolve().parent
    source_origin = os.environ.get("VYBE_LAYOUT_SOURCE_ORIGIN")
    if source_origin:
        assert origin == Path(source_origin).resolve()
    else:
        assert not origin.is_relative_to(Path(__file__).resolve().parents[2] / "src"), "Installed candidate required"
    assert Path(__import__("vybe_check.studio.server", fromlist=["server"]).__file__).resolve().parent == origin / "studio"
    store = SessionStore(tmp_path / "state")
    session = store.create("Ceramic light study")
    def apply(action, payload):
        nonlocal session
        session = store.apply(session["id"], session["revision"], action, payload)
        return session
    apply("direct_image", {"brief": {"outcome": LONG, "subject_action": "Potter turns a bowl", "visual_priority": "Hands", "frame": "Medium shot", "light": "Soft reflected light", LABEL: LABEL},
        "shots": [{"id": "one", "title": LABEL, "prompt": LONG}, {"id": "two", "title": "Rim detail", "prompt": "Blue rim in soft light"}]})
    apply("add_video_version", {"mode": "preserve", "duration": 15, "motion": "Slow rotation", "camera": "Locked camera", "prompt": LONG})
    apply("draft_edit", {"target": "image", "shot_id": "one", "text": "An existing alternative draft"})
    image = tmp_path / "synthetic-study.png"
    pixels = Image.new("RGB", (48, 32))
    pixels.putdata([(x * 5 % 256, y * 7 % 256, (x+y)*3 % 256) for y in range(32) for x in range(48)])
    pixels.save(image)
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    apply("register_reference", {"path": str(image), "label": LABEL, "role": "Colour reference"})
    apply("record_preview", {"path": str(image), "prompt_version": 1, "shot_id": "one", "model": "Synthetic fixture", "workflow": "Transport fixture", "limitations": ["Synthetic fixture, no model generation"]})
    class SyntheticPreview:
        calls = 0
        def capability(self):
            return {"available": True, "wholly_local": True, "backend": "Synthetic fixture", "model": "Transport fixture", "reference_modes": ["Text"], "limitations": ["No model generation"]}
        def generate(self, target, identifier, revision, version, shot):
            self.calls += 1
            return target.apply(identifier, revision, "record_preview", {"path": str(image), "prompt_version": version, "shot_id": shot, "model": "Synthetic fixture", "workflow": "Transport fixture", "limitations": ["Synthetic fixture, no model generation"]})
    adapter = SyntheticPreview()
    server = create_server(0, root=store.root, store=store, preview=adapter, active_id=session["id"])
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield {"store": store, "id": session["id"], "initial": session, "url": f"http://127.0.0.1:{server.server_port}/?session={session['id']}", "digest": digest, "adapter": adapter}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)
        assert not thread.is_alive()


@pytest.fixture
def browser_page(workshop):
    with sync_playwright() as playwright:
        options = {"headless": True}
        executable = os.environ.get("VYBE_LAYOUT_BROWSER_EXECUTABLE")
        if executable:
            options["executable_path"] = executable
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(viewport={"width": 1024, "height": 900}, device_scale_factor=1, accept_downloads=True)
        origin = urlsplit(workshop["url"])
        context.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).netloc == origin.netloc else route.abort())
        page = context.new_page()
        page.set_default_timeout(3000)
        page.goto(workshop["url"])
        expect(page.locator("#session-title")).to_have_text("Ceramic light study")
        try:
            yield page, browser
        finally:
            context.close()
            browser.close()


def evidence(page, browser, name, full_page=True):
    values = page.evaluate("""() => ({width:innerWidth,height:innerHeight,scale:devicePixelRatio,
        documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,
        overflowX:getComputedStyle(document.documentElement).overflowX,
        bodyOverflowX:getComputedStyle(document.body).overflowX,
        controls:[...document.querySelectorAll('button,select,textarea,a')].filter(el=>el.getClientRects().length).map(el=>{
            const r=el.getBoundingClientRect();return {id:el.id,text:el.textContent.slice(0,60),x:r.x,width:r.width,right:r.right};})})""")
    values["browser"] = browser.version
    folder = Path(os.environ.get("VYBE_LAYOUT_EVIDENCE_DIR", tempfile.mkdtemp(prefix="vybe-layout-evidence-")))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (name + ".png")
    assert not target.exists(), "Screenshot evidence must not be overwritten"
    page.screenshot(path=str(target), full_page=full_page)
    values["full_page"] = full_page
    values["screenshot"] = target.name
    values["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    (folder / (name + ".json")).write_text(json.dumps(values, indent=2) + "\n")
    print(json.dumps(values))
    return values


@pytest.mark.parametrize("width", [360, 640, 1024])
def test_measured_layout(browser_page, width):
    page, browser = browser_page
    page.set_viewport_size({"width": width, "height": 900})
    failures = []
    for name in ("brief", "image", "video", "references"):
        page.locator(f'[data-tab="{name}"]').click()
        if name == "references":
            page.locator("#preview-grid img").scroll_into_view_if_needed()
            expect(page.locator("#preview-grid img")).to_have_js_property("naturalWidth", 48)
        facts = evidence(page, browser, f"layout-{width}-{name}")
        assert facts["width"] == width and facts["height"] == 900 and facts["scale"] == 1
        if facts["documentWidth"] > width:
            failures.append(f"{name}: document width {facts['documentWidth']} > {width}")
        assert facts["overflowX"] != "hidden" and facts["bodyOverflowX"] != "hidden"
        for control in facts["controls"]:
            assert control["x"] >= -0.5 and control["right"] <= width + 0.5, control
        if name in ("image", "video"):
            editor = page.locator(f"#{name}-prompt")
            assert "END OF LONG PROMPT" in editor.input_value()
            scroll = editor.evaluate("el => {el.scrollTop=el.scrollHeight;return {top:el.scrollTop,height:el.scrollHeight,client:el.clientHeight};}")
            assert scroll["top"] > 0 and scroll["top"] + scroll["client"] >= scroll["height"] - 1
            editor.scroll_into_view_if_needed()
            evidence(page, browser, f"layout-{width}-{name}-end", full_page=False)
    assert not failures, failures
    expect(page.get_by_role("tab", name="Image", exact=True)).to_have_attribute("aria-controls", "view-image")
    page.get_by_role("tab", name="Image", exact=True).click()
    expect(page.get_by_role("textbox", name="Image prompt", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Save draft", exact=True)).to_be_visible()


def key_to(page, selector):
    for _ in range(40):
        if page.locator(selector).first.evaluate("el=>el===document.activeElement"):
            return
        page.keyboard.press("Tab")
    pytest.fail("Keyboard did not reach " + selector)


def test_keyboard_draft_copy_export_and_conflict(browser_page, workshop):
    page, _ = browser_page
    page.keyboard.press("Tab")
    key_to(page, '[data-tab="brief"]')
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    expect(page.get_by_role("tab", name="Image", exact=True)).to_have_attribute("aria-selected", "true")
    key_to(page, "#image-prompt")
    page.keyboard.press("Tab")
    expect(page.locator("#copy-image")).to_be_focused()
    assert page.locator("#copy-image").evaluate("el=>getComputedStyle(el).outlineStyle") != "none"
    page.keyboard.press("Shift+Tab")
    expect(page.locator("#image-prompt")).to_be_focused()
    key_to(page, "#image-draft")
    page.keyboard.insert_text("Different browser draft")
    page.keyboard.press("Tab")
    expect(page.locator("#send-image-draft")).to_be_focused()
    before = workshop["store"].read(workshop["id"])
    with page.expect_response(lambda r: r.url.endswith("/api/event") and r.request.method == "POST") as response:
        page.keyboard.press("Enter")
    assert response.value.status == 200
    body = response.value.request.post_data_json
    assert body["action"] == "draft_edit" and body["payload"] == {"target": "image", "text": "Different browser draft", "shot_id": "one", "base_version": 1}
    after = workshop["store"].read(workshop["id"])
    assert after["revision"] == before["revision"] + 1
    assert after["image_versions"] == before["image_versions"] and after["video_versions"] == before["video_versions"]
    assert after["drafts"][-1]["text"] == "Different browser draft"
    assert str(after["revision"]) in page.locator("#image-draft-state").inner_text()
    # Clipboard permission is intentionally refused; verify an honest selectable fallback.
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value:{writeText:async()=>{throw Error('Permission refused');}}, configurable:true}); document.execCommand=()=>false;")
    key_to(page, "#copy-image")
    page.keyboard.press("Enter")
    expect(page.get_by_role("status")).to_contain_text("Clipboard unavailable")
    fallback = page.get_by_role("textbox", name="Agreed prompt for manual copy", exact=True)
    agreed = before["image_versions"][0]["shots"][0]["prompt"]
    expect(fallback).to_have_value(agreed)
    assert fallback.evaluate("el => el.selectionStart===0 && el.selectionEnd===el.value.length")
    key_to(page, "#download-image")
    with page.expect_download() as download:
        page.keyboard.press("Enter")
    assert Path(download.value.path()).read_text() == agreed + "\n"
    # Advance disk while the browser still holds its revision, then press Save once.
    page.locator("#image-draft").fill("Keep this unsaved conflict edit")
    newer = workshop["store"].apply(workshop["id"], after["revision"], "draft_edit", {"target": "image", "shot_id": "one", "text": "Another editor's draft"})
    requests = []
    page.on("request", lambda r: requests.append(r.post_data_json) if r.method == "POST" else None)
    with page.expect_response(lambda r: r.url.endswith("/api/event") and r.status == 409):
        page.locator("#send-image-draft").click()
    expect(page.get_by_role("status")).to_contain_text("Review")
    expect(page.locator("#revision-label")).to_have_text(f"Revision {newer['revision']}")
    expect(page.locator("#image-draft")).to_have_value("Keep this unsaved conflict edit")
    page.wait_for_timeout(4500)
    assert len(requests) == 1
    assert workshop["store"].read(workshop["id"]) == newer


def test_registered_study_bytes_and_keyboard_controls(browser_page, workshop):
    page, _ = browser_page
    key_to(page, '[data-tab="brief"]')
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    image = page.locator("#preview-grid img")
    image.scroll_into_view_if_needed()
    expect(image).to_have_js_property("naturalWidth", 48)
    initial = workshop["initial"]
    url = f"/media/{initial['id']}/{initial['previews'][0]['id']}"
    assert image.get_attribute("src") == url
    response = page.request.get(workshop["url"].split("/?")[0] + url)
    raw = response.body()
    assert response.status == 200 and hashlib.sha256(raw).hexdigest() == workshop["digest"]
    decoded = Image.open(io.BytesIO(raw)); decoded.load()
    assert decoded.size == (48, 32) and len(set(decoded.tobytes()[i:i+3] for i in range(0, len(decoded.tobytes()), 3))) > 100
    expect(page.locator("#preview-grid")).to_contain_text("generated")
    expect(page.locator("#preview-grid")).to_contain_text("Synthetic fixture, no model generation")
    key_to(page, "#reference-grid a")
    assert page.locator("#reference-grid a").get_attribute("href").startswith("/media/")
    key_to(page, "#request-preview")
    page.keyboard.press("Enter")
    expect(page.locator("#preview-grid img")).to_have_count(2)
    assert workshop["adapter"].calls == 1
    key_to(page, "#preview-grid button")
    page.keyboard.press("Enter")
    expect(page.locator("#preview-grid")).to_contain_text("promoted")
    assert len(workshop["store"].read(workshop["id"])["visual_locks"]) == 1


def test_clipboard_failure_is_honest(browser_page, workshop):
    page, _ = browser_page
    page.locator('[data-tab="image"]').click()
    page.locator("#image-draft").fill("Different draft for manual copy")
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value:{writeText:async()=>{throw Error('Permission refused');}}, configurable:true}); document.execCommand=()=>false;")
    page.locator("#copy-image").click()
    expect(page.get_by_role("status")).to_contain_text("Clipboard unavailable")
    agreed = workshop["initial"]["image_versions"][0]["shots"][0]["prompt"]
    expect(page.get_by_role("textbox", name="Agreed prompt for manual copy", exact=True)).to_have_value(agreed)


def test_saved_draft_revision_is_visible(browser_page, workshop):
    page, _ = browser_page
    page.locator('[data-tab="image"]').click()
    page.locator("#image-draft").fill("Alternative blue bowl draft")
    with page.expect_response(lambda r: r.url.endswith("/api/event") and r.request.method=="POST") as response:
        page.locator("#send-image-draft").click()
    assert response.value.status==200
    after = workshop["store"].read(workshop["id"])
    assert after["drafts"][-1]["text"]=="Alternative blue bowl draft"
    expect(page.locator("#image-draft-state")).to_contain_text(f"revision {after['revision']}")


def test_video_keyboard_copy_export_and_draft(browser_page, workshop):
    page, _ = browser_page
    key_to(page, '#tab-brief')
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    expect(page.get_by_role("tab", name="Video", exact=True)).to_have_attribute("aria-selected", "true")
    key_to(page, "#video-prompt")
    page.keyboard.press("Tab")
    expect(page.locator("#copy-video")).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(page.locator("#video-prompt")).to_be_focused()
    key_to(page, "#video-draft")
    page.keyboard.insert_text("Alternative video draft")
    page.keyboard.press("Tab")
    expect(page.locator("#send-video-draft")).to_be_focused()
    before = workshop["store"].read(workshop["id"])
    with page.expect_response(lambda r: r.url.endswith("/api/event") and r.request.method=="POST") as response:
        page.keyboard.press("Enter")
    assert response.value.status == 200
    assert response.value.request.post_data_json["payload"] == {"target": "video", "text": "Alternative video draft", "base_version": 1}
    after = workshop["store"].read(workshop["id"])
    assert after["revision"] == before["revision"] + 1
    assert after["video_versions"] == before["video_versions"] and after["image_versions"] == before["image_versions"]
    expect(page.locator("#video-draft-state")).to_contain_text(f"revision {after['revision']}")
    agreed = before["video_versions"][0]["prompt"]
    page.evaluate("window.copiedFixture=null; Object.defineProperty(navigator, 'clipboard', {value:{writeText:async value=>{window.copiedFixture=value;}}, configurable:true});")
    key_to(page, "#copy-video")
    page.keyboard.press("Enter")
    expect(page.get_by_role("status")).to_have_text("Agreed prompt copied.")
    assert page.evaluate("window.copiedFixture") == agreed
    key_to(page, "#download-video")
    with page.expect_download() as download:
        page.keyboard.press("Enter")
    assert Path(download.value.path()).read_text() == agreed + "\n"
    # Return to the tablist without a pointer and exercise both boundary keys.
    key_to(page, "#tab-video")
    page.keyboard.press("Home")
    expect(page.get_by_role("tab", name="Brief", exact=True)).to_have_attribute("aria-selected", "true")
    page.keyboard.press("ArrowLeft")
    expect(page.get_by_role("tab", name="References", exact=True)).to_have_attribute("aria-selected", "true")


def test_selected_series_title_is_readable(browser_page):
    page, browser = browser_page
    page.set_viewport_size({"width": 360, "height": 900})
    page.get_by_role("tab", name="Image", exact=True).click()
    # Native option text may truncate, so the selected title needs wrapped visible text.
    expect(page.locator("#image-note")).to_contain_text(LABEL)
    assert page.locator("#image-note").evaluate("el=>getComputedStyle(el).overflowWrap") == "anywhere"
    page.locator("#image-note").scroll_into_view_if_needed()
    facts = evidence(page, browser, "selected-series-title", full_page=False)
    assert facts["documentWidth"] == 360
    page.locator("#image-shot").select_option("two")
    expect(page.locator("#image-note")).to_contain_text("Rim detail")
    expect(page.locator("#image-prompt")).to_have_value("Blue rim in soft light")


@pytest.mark.parametrize("target", ["image", "video"])
def test_displayed_older_version_is_draft_parent(browser_page, workshop, target):
    page, browser = browser_page
    store, identifier = workshop["store"], workshop["id"]
    session = store.read(identifier)
    session = store.apply(identifier, session["revision"], "add_image_version", {"shots": [
        {"id": "one", "title": "Second treatment", "prompt": "Amber bowl under hard light"},
        {"id": "two", "title": "Second detail", "prompt": "Amber rim"}], "settings": {"seed": 42}})
    session = store.apply(identifier, session["revision"], "add_video_version", {
        "mode": "evolve", "duration": 20, "motion": "Rapid turn", "camera": "Moving camera", "settings": {"fps": 60}})
    page.reload()
    expect(page.locator("#revision-label")).to_have_text(f"Revision {session['revision']}")
    page.get_by_role("tab", name=target.capitalize(), exact=True).click()
    page.locator(f"#{target}-version").select_option("1")
    agreed = page.locator(f"#{target}-prompt").input_value()
    page.locator(f"#{target}-draft").fill("Revise the first treatment only")
    before = store.read(identifier)
    registry = store._registry_path(identifier).read_bytes()
    posts = []
    page.on("request", lambda r: posts.append(r.post_data_json) if r.method == "POST" else None)
    with page.expect_response(lambda r: r.url.endswith("/api/event") and r.request.method == "POST") as response:
        page.locator(f"#send-{target}-draft").click()
    after = store.read(identifier)
    page.locator(f"#{target}-draft").scroll_into_view_if_needed()
    facts = evidence(page, browser, f"older-{target}-parent", full_page=False)
    details = {"target": target, "displayed_version": page.locator(f"#{target}-version").input_value(),
        "displayed_prompt": agreed, "parsed_request": response.value.request.post_data_json,
        "status": response.value.status, "draft": after["drafts"][-1], "disk_revision": after["revision"], "viewport": facts}
    folder = Path(os.environ["VYBE_LAYOUT_EVIDENCE_DIR"])
    (folder / f"older-{target}-result.json").write_text(json.dumps(details, indent=2) + "\n")
    print(json.dumps(details))
    assert response.value.status == 200
    assert after["drafts"][-1]["base_version"] == 1, details
    assert len(posts) == 1 and posts[0]["action"] == "draft_edit"
    assert posts[0]["payload"]["base_version"] == 1
    assert after["revision"] == before["revision"] + 1
    assert {k:v for k,v in after.items() if k not in {"revision", "drafts"}} == {k:v for k,v in before.items() if k not in {"revision", "drafts"}}
    assert store._registry_path(identifier).read_bytes() == registry
    assert after["drafts"][:-1] == before["drafts"]
    expect(page.locator(f"#{target}-prompt")).to_have_value(agreed)
    page.locator(f"#{target}-draft").fill("A different unsaved draft")
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value:{writeText:async value=>{window.copiedFixture=value;}}, configurable:true});")
    page.locator(f"#copy-{target}").click()
    expect(page.get_by_role("status")).to_have_text("Agreed prompt copied.")
    assert page.evaluate("window.copiedFixture") == agreed
    with page.expect_download() as download:
        page.locator(f"#download-{target}").click()
    assert Path(download.value.path()).read_text() == agreed + "\n"
