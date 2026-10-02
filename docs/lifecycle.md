# Update And Keep Your Readable State

Constraint: Stop the visible board before maintenance. Keep the previous wheel and your existing state root. Updating the Python package and updating an agent skill registration are separate explicit operations.

## Explicit Update

Use the same Python environment that runs your candidate. Replace `ROOT`, `CHOSEN_WHEEL`, and `SESSION_ID` with your chosen state directory, saved wheel, and existing session ID.

1. Stop this candidate's visible board with **Ctrl+C** in its terminal.
2. Create a complete private backup with an explicit root:

   ```sh
   vybe-check --root ROOT backup
   ```

3. Install the chosen wheel in the same environment:

   ```sh
   python -m pip install CHOSEN_WHEEL
   ```

4. Update each selected agent and scope explicitly. For a Codex user registration:

   ```sh
   vybe-check --root ROOT update-registration --agent codex --scope user
   ```

   For a Claude project registration, specify the project directory:

   ```sh
   vybe-check --root ROOT update-registration --agent claude --scope project --project PROJECT
   ```

5. Reopen the same session:

   ```sh
   vybe-check --root ROOT board --session SESSION_ID
   ```

The board never invokes pip, checks for updates, or changes registrations at startup. A failed update reports a conflict. It retains the old registration and any staged new bytes for review. It never reports success for an interrupted publication.

## What The Backup Contains

Each backup has a fresh `before-update-` identifier under the chosen root's `backups` directory. It contains the complete validated session JSON, matching registry JSON, optional `comfyui.json`, and a complete size and SHA256 inventory. It preserves image versions, pending drafts, references, and studies. Media and source bytes stay at their original referenced locations. Credentials never enter a backup.

Unknown state members, links, hard links, special files, malformed JSON, missing session or registry partners, and unreadable or inconsistent media references cause refusal. Incomplete backup directories remain for review, without a complete manifest. They are never treated as successful backups. Stop the board and resolve the discrepancy before trying again. Don't discard preserved files to make validation pass.

On POSIX, new backup directories use mode `0700`, and files use `0600`. On Windows, use a private user-owned application-data directory or an explicit root with suitable inherited ACLs. Unix modes do not establish Windows ACL privacy.

Schema one remains readable without rewriting live state. Its migration is an identity operation after a complete locked backup. A later schema migration must validate a complete staged generation, retain the whole old readable generation, and publish one atomic generation pointer. Partial in-place multi-file migration is not supported.

## Interrupted Registration Recovery

A registration archive sits outside the discoverable skills folder. Its transaction records the original target, trusted receipt, device, inode, and complete owned tree. Recovery checks every byte against the old version's external receipt. Updating the package does not reinterpret old registration ownership as current package bytes.

Select the saved transaction ID in a terminal command. `TRANSACTION_ID` is the 32-character hexadecimal suffix of its `archive-` directory name, inside the derived registration metadata folder:

```sh
vybe-check --root ROOT recover-registration --agent codex --scope user --transaction TRANSACTION_ID
```

Use the same agent, scope, and project selection as the interrupted operation. Recovery accepts an ID, never an arbitrary archive path or browser-selected location. This command recovers interrupted transactions. A successfully completed update retains its prior archive for review; it does not authorise overwriting the current registration.

If a target already contains a conflicting or partly published generation, recovery refuses. It leaves that target and both generations intact. There is no replacing move, copy-and-delete fallback, automatic cleanup, or forced rollback.

## Rollback

If the chosen candidate fails to start, stop it, reinstall the saved previous wheel in the same Python environment, and reopen the same state root and session:

```sh
python -m pip install PREVIOUS_WHEEL
vybe-check --root ROOT board --session SESSION_ID
```

Schema-one updates retain the original live state bytes and readable backups. Do not replace them with an incomplete backup. If registration publication was interrupted and its target is absent, use its saved transaction ID to recover the old owned tree. If either target generation conflicts, retain all bytes and resolve the discrepancy before changing registrations.

## Unregister And Uninstall

Unregister each selected agent skill explicitly:

```sh
vybe-check --root ROOT unregister --agent codex --scope user
```

Then remove the Python package from that same environment:

```sh
python -m pip uninstall vybe-check
```

Unregister preserves the whole owned registration in an archive. Modified and unrelated registrations stay untouched, with conflicts reported. Package uninstall is a separate pip operation. Workshop sessions, prompt versions, referenced source media, studies, archives, backups, and native credentials remain. The package never calls credential deletion.

## Evidence Limits

Source tests simulate version updates, interruption, rollback readability, and registration conflicts in invented disposable roots. They don't prove actual wheel replacement, pip uninstall, host-native credential preservation, native filesystem or ACL behaviour on another host, or real model generation. Those require separate installed and platform acceptance runs.

## Related Guidance

Use the [Quickstart](quickstart.md) to create and reopen sessions, and [Privacy](privacy.md) to review retained data and optional services. Registration can refuse filesystems that introduce unowned metadata before publication, preserving old and staged bytes. Native filesystem support remains subject to final installed host checks.
