# Runtime Events

Use an explicit local root when running a workshop. `new` prints a session ID and revision. `show SESSION_ID` reads the current revision. Apply one event using `event SESSION_ID --revision REVISION --action ACTION --payload-file event.json`. Pass arguments as separate values. A stale revision refuses without changing saved state.

The JSON blocks below are complete event payloads with invented creative material. Save a chosen block to a JSON file. Read the resulting revision before the next event. Settings remain separate from prose. Image-only work is a complete endpoint.

## Propose, Resolve, And Agree

`propose_brief`:

```json
{
  "title": "Ceramic portrait",
  "brief": {
    "outcome": "Quiet ceramic portrait",
    "subject_action": "A potter holds a blue bowl",
    "visual_priority": "Hands and glaze",
    "composition": "Hands in the lower third",
    "camera": "Eye-level portrait lens",
    "light": "Motivated window light",
    "colour": "Cool glaze against warm clay",
    "texture": "Visible clay and skin texture",
    "emotional_read": "Patient concentration"
  },
  "locks": ["Blue glaze", "Unmarked bowl"],
  "open_choices": ["Window light or silhouette"],
  "provenance": [
    {"text": "Blue bowl", "kind": "supplied", "source": "User description"},
    {"text": "Clay texture", "kind": "inferred", "source": "Ceramic subject"},
    {"text": "Warm background", "kind": "proposed", "source": "Colour separation"}
  ]
}
```

Surface the choice in conversation. `resolve_choices` records the explicit answer as supplied provenance and clears the outstanding choices:

```json
{"resolution": "Use window light and keep the bowl unmarked", "locks": ["Blue glaze", "Unmarked bowl", "Window light"]}
```

`agree_brief` requires no unresolved choices:

```json
{}
```

## Complete Explicit Image Request

A complete brief plus an explicit prompt request counts as agreement. `direct_image` handles it in a new gathering session without another interview:

```json
{
  "title": "Ceramic portrait",
  "brief": {"outcome": "Quiet portrait", "subject_action": "A potter holds a bowl", "visual_priority": "Hands", "frame": "Close portrait", "light": "Window light"},
  "prompt": "Eye-level close portrait of a potter holding a bowl. Prioritise the hands and glaze. Motivate soft side light from a window. Warm clay background, visible surface texture, patient concentration.",
  "locks": ["Blue glaze", "Unmarked bowl"],
  "settings": {"aspect_ratio": "3:4", "resolution": "1080p", "seed": 42, "batch_size": 1, "style_strength": 0.4},
  "provenance": [{"text": "Bowl and window light", "kind": "supplied", "source": "Explicit prompt request"}],
  "note": "Initial agreed direction"
}
```

## Series And Revision

`add_image_version` after agreement can produce a series:

```json
{
  "shots": [
    {"id": "wide", "title": "Workshop", "prompt": "Wide portrait of the potter holding the bowl beside the window.", "settings": {"seed": 7}},
    {"id": "hands", "title": "Hands", "prompt": "Close view of the hands holding the bowl in window light.", "settings": {"seed": 42}}
  ],
  "settings": {"aspect_ratio": "3:4", "resolution": "1080p"},
  "provenance": [{"text": "Wide and detail views", "kind": "proposed", "source": "Series composition"}],
  "note": "Two complementary frames"
}
```

Revise one stable shot ID with `add_image_version`. If newly agreed continuity locks differ from the selected series, supply an explicit complete replacement series. Partial edits refuse without changing saved state; the runtime does not rewrite existing creative prose. Older-draft acceptance retains its named base locks and series:

```json
{"shot_id": "hands", "prompt": "Closer hands with the bowl rim visible and gentle window falloff.", "settings": {"seed": 43}, "note": "Prioritise the rim"}
```

`select_image_version` changes the selected direction without changing older records:

```json
{"version": 1}
```

`draft_edit` records browser prose and snapshots its base version. A series draft needs a known shot ID. A single-image draft omits it:

```json
{"target": "image", "text": "Closer hands with more space above the bowl.", "shot_id": "hands"}
```

`accept_draft` uses the returned pending draft ID. This invented ID illustrates the format; use the actual ID from `show`:

```json
{"draft_id": "11111111111111111111111111111111"}
```

Acceptance requires an agreed brief. It appends a version from the draft's snapshot, preserving its settings, series IDs, provenance, and source lineage even if newer versions exist. It does not overwrite earlier versions.

## Optional Video Modes

Continue only when requested. The selected image anchors locks, settings, and provenance. Motion additions are proposed unless their supplied provenance is recorded. Sound is a separate setting and is included only when requested. Each payload below uses `add_video_version`:

```json
{"mode": "preserve", "duration": 15, "motion": "The potter gently lifts the bowl", "camera": "Slow forward movement", "settings": {"fps": 24}, "provenance": [{"text": "Gentle lift", "kind": "proposed", "source": "Motion direction"}]}
```

```json
{"mode": "evolve", "duration": 15, "motion": "The potter turns the bowl to reveal the glaze", "camera": "Subtle arc around the hands", "prompt": "Hold the final gaze", "settings": {"sound": "Requested quiet room tone", "fps": 24}, "provenance": [{"text": "Quiet room tone", "kind": "supplied", "source": "User sound request"}, {"text": "Bowl turn", "kind": "proposed", "source": "Motion direction"}]}
```

```json
{"mode": "multishot", "duration": 15, "motion": "The potter rotates the bowl while maintaining its position", "camera": "Wide establishing frame, medium movement, close detail", "settings": {"fps": 24}, "provenance": [{"text": "Three connected views", "kind": "proposed", "source": "Sequence direction"}]}
```

Preserve uses one continuous interval from zero to 15 seconds. Evolve and multishot use ordered boundaries at zero, five, 10, and 15 seconds. Durations are integers from one to 60. Evolve and multishot require at least three seconds. Custom prose supplements the timed sequence and cannot bypass mode or continuity validation.

## Reference Registration

`register_reference` is the agent-facing path-bearing input for supplied media. This invented relative path is a user-chosen file, not a source-path default:

```json
{"path": "example-reference.png", "label": "Glaze reference", "role": "Colour and surface", "source_kind": "supplied_reference"}
```

The returned opaque reference ID and label enter creative state. The path remains in the private local media registry. Inspect supplied media before describing it. Do not export reference contents or registry records.

## Study Recording And Promotion

A requested local study is an exploratory generated asset, not proof of identity or exact objects. `record_preview` is an internal runtime media-registration event. Its path is the fresh generated output chosen by the local runtime, not an agent default:

```json
{"path": "example-study.png", "prompt_version": 1, "model": "Installed local checkpoint", "workflow": "Compatible core workflow", "source_reference_ids": [], "limitations": ["Exploratory composition only", "Cannot certify exact identity or object"]}
```

For a series study, include its exact `shot_id`. The runtime validates the named image and shot before registration. Use `promote_preview` only after the user explicitly promotes the returned study ID:

```json
{"preview_id": "22222222222222222222222222222222"}
```

Promotion retains generated provenance and the original prompt version. It adds a visual lock and preserves the asset.

## Requested Advice

`record_advice` is declared but refuses until the advice validator is available. It records a validated result and makes no provider call. Do not invent a result to bypass that refusal. This invented event illustrates the recording schema:

```json
{"source_image_version": 1, "route": "local", "model": "Example candidate", "payload_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "questions": ["Does the verified input mode match the requested still input?"], "answers": ["Unverified fit remains uncertain"]}
```

Advice must not change prompt bytes, settings, or locks. Model advice requires a user request, current official evidence, and a recorded date. Weak or failed advice returns to the conversation.

## Explicit Export

`export SESSION_ID --target image --version 1` prints the selected agreed version as JSON. `--out chosen.json` creates a new file exclusively and refuses to replace an existing file. Omitting `--version` chooses the latest version for the requested target.

Exports contain only schema version, target, version, prompt, shots, settings, locks, and source image version. Video exports also contain mode and duration. Nested strings are cleaned for local paths and credential patterns. Creative prose is retained; pattern cleaning cannot identify every human name. Exports never include the whole session, registry, reference contents, nonce, or media assets.
