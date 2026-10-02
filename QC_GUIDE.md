# Candidate QC Guide

Version `0.1.0rc1` is a public source release candidate. Final installed, native-store, and cross-platform verification remains pending.

## Start A Fresh Workshop

Clone this repository into a new folder. Use CPython 3.11 through 3.14 and a dedicated virtual environment. Installing the package and dependencies can use the network.

On macOS or Linux, run these commands from the clone:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
python -m vybe_check --help
python -m vybe_check --root .qc-state examples copy --out qc-examples
python -m vybe_check --root .qc-state new --title "Ceramic workshop"
```

Choose a new `qc-examples` folder. Copy refuses an existing destination. Replace `SESSION_ID` below with the actual ID printed by `new`.

```sh
python -m vybe_check --root .qc-state show SESSION_ID
python -m vybe_check --root .qc-state event SESSION_ID --revision 0 --action direct_image --payload-file qc-examples/ceramic-image.json
python -m vybe_check --root .qc-state board --session SESSION_ID --port 8766
```

Open the printed URL. Keep that terminal running. If the chosen port is occupied, choose another port without stopping an unknown listener. Use a second activated terminal for further commands.

Windows setup and the complete walkthrough are in [Quickstart](docs/quickstart.md).

## Check The Creative Flow

- [ ] The image brief is useful as an image-only endpoint.
- [ ] Drafts remain drafts until explicitly agreed.
- [ ] Refinement appends a version and preserves the earlier version.
- [ ] Supplied, inferred, and proposed details remain distinguishable.
- [ ] The board displays the saved brief, prompt, and references without clipping.
- [ ] The agreed image prompt exports correctly.
- [ ] A requested video continuation supports preserve, evolve, and multishot directions, with coherent DOP choices and durations.
- [ ] Stopping the board with Ctrl+C and reopening it preserves saved state.

Export the agreed ceramic image in the second terminal:

```sh
python -m vybe_check --root .qc-state export SESSION_ID --target image --version 1
```

For agent-assisted refinement, register only the agent you use, in a project you choose. Follow the project registration instructions in [Quickstart](docs/quickstart.md), refresh that agent's skill discovery, and use Vybe-Check with this isolated workshop root. Review the bundled skill at [SKILL.md](src/vybe_check/skill/SKILL.md).

## Optional Capabilities

Local look studies require your own compatible ComfyUI service and checkpoint. Enable them explicitly using the documented workflow. No generation runs automatically. Check [Privacy](docs/privacy.md) before adding references.

Optional Jev advice requires native credential storage, reviewed outbound text, verified billing bounds, and explicit approval. This candidate currently refuses when the billing maximum cannot be verified. Core prompt refinement needs no API key or paid generation.

## Release Checks Still Open

Source authoring checks do not certify final installed packages, all supported OS/Python combinations, native credential stores, actual agent discovery, real local model studies, or provider calls. Those checks remain pending. The package is a prerelease candidate.

Keep personal references, `.qc-state`, generated assets, credentials, and local review logs out of commits and issues. Share an outcome or a minimal reproducible problem. Conversation transcripts are not required.

Record QC findings against this candidate commit. Stable package publication remains subject to final release checks.
