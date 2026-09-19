# DataInbox Pub/Sub Handler — Processing Design

## 0. Runtime shell (outside the pipeline)
- Long-lived streaming pull: `subscriber.subscribe(subscription_path, callback=...)`.
- `flow_control` with a capped `max_messages` so we don't lease more than we can process inside the ack deadline.
- Subscription has a **dead-letter topic** configured with a max delivery-attempts count. *(Prerequisite — must exist before go-live.)*
- The callback does exactly one thing: run the pipeline, then translate the result into `message.ack()` / `message.nack()`. No business logic in the callback.

## 1. Dispatch (explicit, boring)
- Parse `message.data` → `path`, `type`, `action`, `destination`, `username`, etc.
- `type × action` map decides the path:
  - `file`/`create`, `file`/`move`, `file`/`update` → **reconcile**
  - `file`/`destroy` → **destroy**
  - `dir`/`move` → **dir-reconcile** (fan out to children)
  - `dir`/`destroy` → **dir-destroy** (fan out to children)
  - `dir`/`create`, `dir`/`update` → **no-op**
  - `*`/`read` → **no-op**
  - anything unmatched → **no-op + alert** (Chatterbox `@channel`), then ack (don't DLQ unknown-but-harmless).
- Temp files (`~$` in path) → **no-op**, short-circuit before any Files.com/ClickUp calls.

## 2. Context object
- Created once per message. Holds: raw message fields; lazily-loaded `rfc_file`; lazily-resolved `DataFile`; a place for the resolved `category_id`; and a running record of which best-effort steps failed (for the final log).
- Lazy loading matters: `destroy` never loads a File object (it's gone); no-ops load nothing.

## 3. Identity resolution (shared sub-step)
`resolve_datafile(ctx)`:
1. **Primary** — `rfc_file.custom_metadata["task_id"]` → `DataFile(id=...)`.
2. **Fallback** — name (`ftp_filename`) + directory (`ftp_directory`) search on ClickUp.
3. On **fallback hit** → schedule a metadata **backfill** step so it's fast next time.
4. Result is one of: *found*, *not-found*, or *ambiguous* (multiple matches → alert, don't guess).
- Note: `destroy` is metadata-blind (file gone) → it uses the fallback path only.

---

## 4. RECONCILE path (create / move / rename / update)

Mental model: *read current file truth, read current DataFile truth, make the DataFile match.* Steps run in order; each is **[REQUIRED]** (failure → nack/retry) or **[BEST-EFFORT]** (failure → log, keep going).

1. **[REQUIRED]** Load `rfc_file` from `path` (for move, use `destination`). If Files.com 404s → nack (transient) unless clearly permanent.
2. **[REQUIRED]** Resolve DataFile identity (step 3 above).
3. **[REQUIRED]** Determine category — `categorize(filename, directory, rules)` (rules from Firestore cache; see §7).
4. **[REQUIRED]** Branch on identity:
   - **Not found →** build DataFile model (name, ftp_user, ftp_filename, ftp_directory, file_date, received, archived=False, category) and **create** on ClickUp. Capture new task_id.
   - **Found →** compute desired state from current file truth, **diff** against existing DataFile, **patch** only changed fields (name/ftp_filename on rename, ftp_directory on move, category if reclassified). If nothing changed → mark "already up to date," skip to ack.
5. **[REQUIRED]** **Backfill metadata** — write `task_id` to Files.com `custom_metadata` via the wrapper (see §8). Required because it's the thing that keeps future events fast/deterministic. (On a "found via metadata" path this is a no-op.)
6. **[BEST-EFFORT]** Link (client/DataCard) + assign-or-add-watcher.
7. **[BEST-EFFORT]** Decrypt tag if `.pgp` in filename.
8. **[BEST-EFFORT]** Debug tag if path under the test site / test account.
9. **[BEST-EFFORT]** Termed status — if directory contains `archived`/`termed` → set `TERMED CLIENT`.
10. **[BEST-EFFORT]** Completed-folder status check — if destination path contains `complete` → run the assignee-based status logic (old `set_status`).
11. **[BEST-EFFORT]** CoreDB sync — add-or-update DataFile mirror (idempotent).
12. **Ack** if all REQUIRED steps passed. Best-effort failures are logged together but don't block the ack.

## 5. DESTROY path (file)
1. Resolve DataFile by **name/path fallback only** (metadata is gone with the file).
2. If not found → log "already gone," **ack** (idempotent — a redelivered destroy shouldn't nack forever).
3. **[REQUIRED]** Tag DataFile `Deleted`.
4. **[BEST-EFFORT]** Log the delete payload to Firestore.
5. **[BEST-EFFORT]** CoreDB sync/mark.
6. Ack.

## 6. DIR paths (fan-out)
- **dir-move:** list children of the destination folder via the Files.com wrapper; for each child that carries a `task_id` in metadata, update its `ftp_directory`. (Children without metadata are the fallback tail — decide: skip and log, or search by name.)
- **dir-destroy:** list children, tag each `Deleted`, log once.
- Fan-out concern to note in the task: a folder with many children can blow the ack deadline — may need to process children in batches / re-lease. Flag as a known scaling edge, not a v1 blocker.

---

## 7. Categorization (separate workstream, Firestore-backed)
- **Storage:** rules live in Firestore, not `constants.py`. Each rule: `category_id`, match criteria (`substrings`, `folder_names`), and an **explicit numeric `priority`** (replaces the current reversed-dict-order precedence).
- **Function:** `categorize(filename, directory, rules) -> category_id` — pure, rules injected, default to `CLIENT_INBOX` when nothing matches.
- **Caching:** load rules into an in-process TTL cache (long-lived consumer — don't read Firestore per message; don't require a restart to pick up edits).
- **Tests:** fixture filenames/paths → expected category, with rules passed in. This is the deliverable that lets category changes stop being scary.

## 8. Files.com wrapper additions
- `set_custom_metadata(file_path, metadata: dict)` — generic; **read-merge-write** (confirm Files.com update semantics first — merge vs. replace) so we don't clobber other keys.
- `set_task_id(file_path, task_id)` — thin convenience wrapper over the above.
- Real **retry-and-verify** loop (read back to confirm), returns bool / raises on exhaustion. This replaces `set_task_id_on_filescom_file` and fixes its `return False`-inside-the-loop bug.

## 9. Cross-cutting requirements
- **Idempotency:** every path safe to run twice (redelivery is normal). Create checks-then-updates; tags/CoreDB are add-or-update; destroy is find-or-already-gone.
- **Ack/nack contract:** REQUIRED failure → nack (redeliver → eventually DLQ). BEST-EFFORT failure → log + ack. No-op → ack. Unknown-harmless → alert + ack.
- **Handlers no longer return `(status_code, dict)`** — that HTTP tuple is dead. They return a small result (or raise); the callback maps it to ack/nack.

## 10. Known bugs to retire in the rewrite (don't port)
- `set_task_id_on_filescom_file`: `return False` inside the retry loop.
- `create_data_file`: orphaned unreachable second `except` ("Error assigning group").
- Blocking `time.sleep` retry loop in `update_data_file` — deleted, made unnecessary by metadata identity.
