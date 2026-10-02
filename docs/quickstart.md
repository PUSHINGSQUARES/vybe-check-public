# Quickstart

## Create An Environment

Install CPython 3.11 through 3.14, then create a virtual environment in a folder you choose. Use the same activated environment for every command below.

macOS and Linux:

```sh
python3 -m venv .venv
. .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If your Windows policy refuses activation, use `.venv\Scripts\python.exe` for Python and `.venv\Scripts\vybe-check.exe` for workshop commands. Replace the wheel path with the exact candidate file you chose. The following POSIX path is a placeholder; Windows users supply their chosen Windows path.

```sh
python -m pip install /path/to/chosen/vybe_check-0.1.0rc1-py3-none-any.whl
python -m vybe_check --help
vybe-check install --agent codex --scope user
vybe-check install --agent claude --scope user
vybe-check examples copy --out examples
vybe-check new --title "Ceramic workshop"
```

Choose a new `examples` directory. Copy refuses an existing destination and retains partial output if writing fails. Resources come from the installed package, not your current directory. The output lists the copied filenames and absolute destination. Installing dependencies or updating with pip may use the network; ordinary core refinement needs no provider, credential, or remote runtime.

Registration is explicit for each agent. Install only the agents you use. Restart or refresh that agent's skill discovery according to its current instructions. Project-only registration requires an explicit project:

```sh
vybe-check install --agent codex --scope project --project PROJECT
```

Replace `PROJECT` with your chosen project directory. A filesystem that adds unowned metadata files can cause registration to refuse before publication. The old registration and staged bytes remain. Registration on those filesystems is unverified; don't remove unknown files to force success.

## Refine An Image

Replace `SESSION_ID` with the actual ID printed by `new`. Read its current revision with `show`. The fresh session starts at revision zero:

```sh
vybe-check show SESSION_ID
vybe-check event SESSION_ID --revision 0 --action direct_image --payload-file examples/ceramic-image.json
vybe-check board --session SESSION_ID --port 8766
```

Open the **printed board URL**. The board command stays in the foreground. Use another activated terminal for commands while it runs. Stop it with **Ctrl+C**, then rerun the board command with the same session ID and root to reopen saved state. A port conflict requires a different chosen port; don't stop an unknown listener.

Export the first agreed image version:

```sh
vybe-check export SESSION_ID --target image --version 1
```

An optional `--out chosen.json` creates a new file and refuses replacement. The ceramic payload supplies outcome, subject/action, visual priority, frame, light, prompt, locks, and supplied/inferred/proposed provenance. These labels describe the invented user's request and example choices, not real reference photographs. The PNG reference is generated programmatically from simple shapes and colour, not by an image model. It establishes no exact person or object fidelity.

To show the generic ceramic reference on the board, create a new `ceramic-reference-event.json` containing the object below. Replace `COPIED_REFERENCE_PATH` with the full path to `ceramic-reference.png` in the emitted copy destination. Its label makes its programmatic origin explicit. The event marks it as a supplied local file, not a model-generated study:

```json
{"path": "COPIED_REFERENCE_PATH", "label": "Programmatic generic ceramic reference", "role": "Colour and geometry only", "source_kind": "supplied_reference"}
```

```sh
vybe-check show SESSION_ID
vybe-check event SESSION_ID --revision CURRENT_REVISION --action register_reference --payload-file ceramic-reference-event.json
```

Use the same steps with `kite-reference.png` and a "Programmatic generic kite reference" label in the kite session. The board's References tab serves the registered PNG bytes. Inspect the fixture before describing it.

Ask the agent to refine the agreed image using the canonical skill. Browser edits are **drafts**, not agreement. Saving a draft retains its base version; explicit acceptance appends an agreed version. Before each event, use `show` and pass its current revision. A stale revision refuses without changing state. If continuity locks change in a series, supply a complete replacement series rather than a partial patch. Image-only refinement and export are a complete endpoint.

## Optional Video Continuation

Start a separate session titled "Kite over salt flat" and apply `examples/kite-image.json` with `direct_image` at its fresh revision zero. Only continue to video when requested. Choose one of `kite-preserve.json`, `kite-evolve.json`, or `kite-multishot.json`, then apply it with `add_video_version` at the current revision.

Each example lasts **15 seconds**. Preserve holds one continuous direction. Evolve progresses through ordered beats. Multishot provides connected views. DOP context covers camera movement, framing, motivated light, fabric, and horizon continuity. The selected agreed image supplies the anchors. Sound intent stays separate in `settings.sound`; remove it if sound wasn't requested. Video is prompt authoring, not video generation or a model-availability claim.

```sh
vybe-check event SESSION_ID --revision CURRENT_REVISION --action add_video_version --payload-file examples/kite-preserve.json
vybe-check export SESSION_ID --target video --version 1
```

## Optional Setup After The Baseline

Local studies require your own loopback ComfyUI service, compatible core nodes, and an installed checkpoint. Use `preview capability` before requesting a run. Create your state root's `comfyui.json` as an object with exactly `base_url`, `workflow`, `prompt_node`, and `checkpoint`. Set `base_url` to your chosen loopback ComfyUI URL, `prompt_node` to `"2"`, and `workflow` to the JSON object copied in `examples/comfy-core.json`. Set both `checkpoint` and workflow node one's `ckpt_name` to the same installed checkpoint filename. No nested file path is accepted for that filename. Keep the rest of the supported graph intact. Review [Privacy](privacy.md). Enable board study requests explicitly with `board --local-studies`. The packaged core workflow is a template; capability inspection must verify the actual nodes and checkpoint. Text-only studies explore composition and colour and cannot certify exact identity, objects, or supplied-reference fidelity. No generation runs automatically.

Optional advice needs the `judge` extra in the same environment and current verified billing bounds. In a visible terminal, use `key setup --route typesafe` or `key setup --route openrouter`. Native-store denial or unavailability refuses; no plaintext fallback exists. Inspect `judge quote` outbound text before approving a bounded attempt. Review [Privacy](privacy.md) first. Advice availability and prices remain unverified until actual current checks succeed.

Keep sessions under the resolved application-data root or use `--root CHOSEN_ROOT` before every subcommand. Keep that same root when reopening, updating, or exporting. See [Lifecycle](lifecycle.md) for backup, update-registration, unregister, and separate pip uninstall.
