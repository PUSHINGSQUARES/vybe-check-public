# Candidate Verification

The contract in `tools/acceptance_contract.json` contains 75 active release criteria. Source controls prove authoring behaviour. Every release criterion remains OPEN until independently reviewed final evidence exists.

## Reviewed Inputs

Prepare a schema-one `final-native-execution-plan` in an isolated evidence directory. Bind the exact candidate tuple: version, source SHA256, wheel SHA256, and sdist SHA256. The `source`, `wheel`, and `sdist` fields are regular-file references containing relative `path`, exact `size`, and `sha256`. Bind `frozen_source_inventory` to a separately reviewed inventory with the source artifact SHA256 and exact file size/hash entries. Include the frozen tools and all required test files. References cannot escape the evidence directory or follow links.

The `operations` array identifies each authorised operation by `kind`, actual native `system`, explicit installed `interpreter`, and `environment_owner`. Provision the disposable virtual environment and its dependencies separately. The environment must live beneath the evidence directory, have a distinct base interpreter, and contain the required installed runtime. The producer verifies its origin before native work. An installation cell may use a separately provisioned clean environment. Update operations require a bound `prior_wheel` and its distinct `prior_version`.

Review the plan and its SHA256 independently. A supplied hash establishes byte identity, not authenticity of invented observations. Source `PYTHONPATH`, authoring mode, wrong hosts, changed tools, and incompatible installed origins cannot execute final operations.

## Execute Required Producers

```sh
python tools/verify_host.py execute-plan --plan CHOSEN_PLAN --plan-sha256 REVIEWED_SHA256 --kind CHOSEN_KIND
```

The equivalent module entry is `python -m tools.acceptance_producers`. Run it from the frozen source checkout using the installed interpreter. Each operation runs in its own bounded installed interpreter child. Package mutations require a separate disposable interpreter. Six fresh roots and actual child terminal metadata are recorded, with inherited terminal I/O and no conversation capture. Each run creates exclusive evidence and a complete reviewable manifest, with its path, size, and SHA256 printed. The producer assembles records automatically. Review the resulting manifest before using it as prior evidence in another plan. Retain each attempt, including refusals. Never replace a failed receipt.

| Kind | Actual operation and additional inputs |
| --- | --- |
| `installed-cell` | Install the exact bound wheel with explicit pip argv, observe CPython/OS/dependency/import/wheel bytes, and launch the installed CLI. Repeat for all 12 native OS/Python cells. |
| `agent-installation` | Observe the chosen native executable bytes/version, install its explicit managed registration, run eight foreground interactive scenarios, and collect human-reviewed discovery/outcome notes. Supply `agent`, `managed_scope`, `agent_executable`, exact `agent_executable_digest`, `agent_version`, reviewed `interactive_arguments`, bound `agent_configuration`, and `persistence_review`. The latter binds the reviewer, official source URL, notes, and `conversation_transcripts: Disabled` configuration for that exact version. It must include `observation_kind: human-reviewed-outcome`, `verified_version`, exact `verified_arguments`, and the bound configuration SHA256. The producer installs and rereads those exact native configuration bytes before every launch. No headless agent mode is allowed. |
| `native-store` | Store and consume an invented random sentinel through the actual host adapter. Supply the criterion. `DoD-11.1` performs real unregister; `DoD-11.2` performs unregister and pip uninstall, then consumes the same sentinel through the retained adapter. Use a separate disposable environment for uninstall. Platform criteria are `DoD-43`, `DoD-44`, and `DoD-45`. |
| `native-unavailable` | On a separate explicitly locked/unavailable Linux service, observe service state twice, attempt the actual native read, refine a baseline session, and observe zero provider attempts. Permission errors propagate. The producer never locks, unlocks, or reconfigures an operator service. |
| `installed-lifecycle` | For `DoD-9.3`/`DoD-10.2`, unregister the owned registration and run pip uninstall. Verify retained creative state/media using copied compatible verifier bytes, actual import absence, and preserved modified/unrelated files. For `DoD-12`, observe the distinct prior runtime, run explicit pip upgrade, update the registration, and observe the new wheel/version. |
| `provider` | Supply `route`, bound `anonymous_input`, original `approval`, dated `cost_receipt`, `state_root`, and `session`. The producer recomputes consent before native credential access, reserves one attempt through the real judgement path, and sanitises the observed response. There is no retry, fallback, raw body, key, or provider prose capture. |
| `local-study` | Supply isolated `state_root`, `session`, `version`, an existing `checkpoint`, and `approval: Two real local studies explicitly approved`. Run actual unsupported-core, missing-checkpoint, and unavailable controls before two explicit generations. Decode the same bytes through HTTP and the browser. A separate outcome-only visual review must bind the candidate and both output ID/hash pairs. |

Native agent reviews describe outcomes and saved version artifacts, never conversation transcripts. The foreground terminal remains visible. Review files contain `observation_kind: human-reviewed-outcome`, reviewer, notes, invented-input status, and the scenario facts defined by `validate_scenario`. The review explicitly binds the generated creative results. The producer separately records input/review/version-log provenance and retains exact copies of the reviewed result bytes. The native agent's chosen no-transcript persistence configuration must be independently reviewed before execution.

Provider billing remains unavailable while the runtime lacks a complete verified primary rate bound. The producer preserves that refusal before credentials or transport. User-authored rates cannot override it. Missing provider identity or usage is recorded as observed absence. Both independent routes require their own actual attempt and record.

Local controls perform capability GET requests and refuse any generation POST. Baseline refinement sends no automatic request. Synthetic transport, checkpoint bytes, provider responses, and native adapters remain labelled `authoring-synthetic` and cannot satisfy final gates. The old dedicated diagnostic entries do not replace these candidate-bound producers.

## Named Probes And Runtime Origins

Set `VYBE_ACCEPTANCE_PLAN` and `VYBE_ACCEPTANCE_PLAN_SHA256` to the independently reviewed plan to connect named matrix, platform, agent/scenario, native, lifecycle, provider, and local-study gates directly to their producers. Completed separately reviewed records may be bound in the plan's `records` array, including other native hosts. Current-host operations execute before validation. Missing operations or incomplete other-host records fail.

Alternatively, use the reviewed automatically produced final manifest through `VYBE_ACCEPTANCE_MANIFEST` and `VYBE_ACCEPTANCE_MANIFEST_SHA256`. Native interactive execution must occur in a visible terminal before a captured pytest run; that run consumes its independently reviewed outcome records. No manual wrapper or invented JSON observations can substitute for the operation.

```sh
python tools/verify_host.py --interpreter CHOSEN_PYTHON --wheel CHOSEN_WHEEL --version 0.1.0rc1 --cwd CHOSEN_SOURCE --out NEW_EVIDENCE --run-probes --manifest CHOSEN_MANIFEST --manifest-sha256 REVIEWED_SHA256
```

`run_probes` itself verifies the independent source inventory against actual test/tool bytes and emits its own bound frozen inventory. It then runs the exact native node set once, preserving real pytest phases, JUnit, command output, and terminal observations. Wrong artifact tuples, swapped origins, missing phases, failures, and skips prevent a successful runtime record. All three native OS runtime records and all 12 installation cells are required.

The source controls include an actual pytest child, the real board tab selector, synthetic HTTP capability refusals, two registered/decoded browser outputs, retained-verifier execution, same-sentinel operation ordering, and sanitised producer/schema interoperability. Synthetic schema controls are explicitly refused by final acceptance before their separate schema-only assertions.

## Aggregate

```sh
python tools/verify_host.py aggregate
```

Aggregation requires the exact 75 IDs, matrix, agents/scenarios, runtime origins, native store preservation, lifecycle, provider routes, and local studies. Source migration interruption already executes its actual backup/publication seam through the named probe. Final history, scan, freeze, and release report interfaces remain pending until their later authoring tasks and final barrier. Missing native access or approval remains pending/failing. Source authoring never closes real acceptance.


## Native Agent Creative Result Contract

Outcome notes stay outcome-only. Do not include transcripts. Each scenario review requires `results` and an ordered `reviewed_result_sha256` list. Input instruction packets, human review notes, and native executable version output are provenance. They cannot satisfy resulting creative artifact requirements.

Each result descriptor contains:

- `kind`: `prompt`, `version`, or `session`.
- `artifact`: A relative regular-file reference with exact `path`, `size`, and `sha256`, within the isolated evidence root.
- `prompt_pointers`: A nonempty array of JSON pointers to saved creative prompt text.
- `version_pointers`: JSON pointers to saved version or session identifiers. Required for `version` and `session` results.
- `reviewed_versions`: The ordered identifier values observed at those pointers.
- `fact_bindings`: Explicit mappings from scenario fact names to fields in retained result JSON. Each mapping contains `fact`, `operation`, and, for `value` or `length`, `pointer`.

`value` compares a saved value with the corresponding reviewed fact, including its type. `length` counts a saved creative collection. `bytes_sha256` hashes the entire bound result file. Fact names containing `/` identify nested video facts. Pointers use JSON pointer escaping (`~0` and `~1`). No code or expressions are evaluated.

| Scenario | Required creative bindings |
| --- | --- |
| `empty_brief` | `proposed_concepts`, `alternates`, and `agreed_versions`, bound to the saved concept collections or values. |
| `one_question` | A resulting creative prompt and its reviewed file hash. Question counts remain human observations. |
| `complete_brief` | `image_versions`, bound to saved image versions. Redundant question counts remain human observations. |
| `image_only` | A `session` result with `agreed_images` and `video_versions` bound to its saved state. |
| `draft_refinement` | `version` results binding `new_version_id`, `prior_version_id`, and both prior file hashes. Retain the actual prior and new creative version bytes. |
| `video_modes` | `version` results binding each mode's `duration`, `anchor_id`, `locks`, and ordered `durations`. |
| `model_advice` | A resulting advice/prompt artifact binding `input_mode`, `official_source_url`, `checked_date`, and `uncertainty`. |
| `unavailable_optional` | A creative result binding `image_refinements`. Optional availability remains a human observation. |

For example, a native saved session can use `/image_versions/0/prompt`, `/id`, and `/image_versions/0/version` directly. The `image_only` count bindings can use `length` on `/image_versions` and `/video_versions`, after the reviewer confirms that the image versions represent agreed output. A generic saved prompt/version JSON export may use its own explicit field layout. Retain the actual creative export, rather than a second review-note file containing claims about it.

The producer verifies the bindings before retaining copies and again afterwards. The aggregator repeats the checks against retained regular bytes and the saved original review. Missing results, provenance-only results, notes in place of results, changed identifiers, mismatched facts, altered review selectors, and tampered bytes refuse acceptance. The saved review fixes facts, selectors, identifiers, and hashes; retention may change only artifact locations.

This is a practical local evidence contract. Hashes prove byte identity and consistency with review, rather than native execution or authorship. Native launch, registration, discovery, no-transcript configuration, and human creative judgement still require their separate real-host evidence. Synthetic authoring controls leave all 75 release criteria OPEN.
