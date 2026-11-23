---
proposal_id: "paste-note"
state: ACCEPTED
witness: independent
candidate: "1be7ce5 + uncommitted tree 6c928ea0913f6a6c681bbca48100af1c50d6b952 (excluding this ledger) @ worktree .claude/worktrees/paste-note, branch proposal/paste-note-build"
---

# Proposal: Paste a note into the app

## Proposal

### Intent

Allow a user to paste files into the app so they are saved as `.md`, and avoid file upload.

### Tentative primary claim

A user can paste a file's content into the app, and it is saved as a `.md` note.

### Why now

None stated.

### Known constraints

- Pasted content is saved as `.md`.
- The feature avoids file upload.
- There is no folder choice. Every pasted note is stored in a default folder for now.

### Non-goals

- File upload.
- Choosing a folder.

### Open choices

None. The human approved these defaults on 2026-11-23:

- Paste is text only. Pasting a file copied from Finder or the clipboard is out of scope.
- Saving does not ingest. The note is picked up by the next `ingest` or `watch` run.
- The user gives a title. The app builds a safe filename from the title and date, and stores the file in the default folder inside the data folder.
- The app never overwrites an existing note. A name collision gets a numeric suffix.
- Saving ships first. Automatic ingestion can be a later proposal.

The human decided on 2026-11-23: for the demo there are no users, it's just the root user. Saving has no permission check.

The human changed this Proposal on 2026-11-23: remove the optional folder and store everything in a default folder for now. The human also approved one `/notes/new` variant in `tests/test_web_navigation.py` and a new `tests/test_note_intake.py`.

## Frame

Candidate: `1be7ce5 + uncommitted prior build @ worktree .claude/worktrees/paste-note, branch proposal/paste-note-build`

### Verified reality
- Clean export of `1be7ce5`, full suite: 387 passed before this change; limit: exercises no note write.
- `src/stock_ontology/web/app.py` at `1be7ce5` — proves the app has no note-writing route, login, session identity, or CSRF protection; limit: a network or proxy outside this repository may still protect it.
- `src/stock_ontology/web/catalog.py:21,699-725` — proves `_general` is an existing folder name that the catalog labels as general and sorts after company folders; limit: the folder does not exist in `data/` yet.
- `README.md:23` — proves `_general/` is a documented notes location; limit: does not define it as a paste destination.
- `src/stock_ontology/pipeline.py:133-140` — proves ingestion scans recursively, skips hidden paths, and accepts `.md`; limit: a non-hidden partially written file would be read.
- `src/stock_ontology/web/navigation.py:180` and `tests/test_web_navigation.py:152` — prove a new HTML route needs a registry entry and a render variant; limit: JSON routes are not covered.
- `tests/test_i18n.py:45` — proves UI strings need keys in all six locales; limit: does not check translation quality.
- Inline FastAPI 0.165.0 probe of a JSON body model — proves `text/plain`, form-encoded, and missing content types return 422; limit: does not stop a same-origin or non-browser caller.

### Final primary claim
- The demo's root user can paste text and a title into the Notes section and save it, after which a new `.md` note exists in `_general/` under `ONTOLOGY_DATA_DIR`, appears in the catalog, and is picked up by the next `ingest` or `watch` run.

### Routing
- Witness: `independent`
- Why: the route adds the web app's first filesystem write to stored research notes, which feed ingestion and house consensus.
- Human-owned irreversible action: merging or deploying the candidate. A later `ingest` of pasted notes also makes paid LLM calls and changes `ontology.db`, and no stage runs it against live data.

### Decisive witness
- Layer: HTTP integration through FastAPI `TestClient` with a temporary data directory.
- Permanent owner: `tests/test_web.py`.
- Witness: a POST with no credentials creates the expected `_general/*.md` file with the pasted content, the catalog lists it, an offline `IngestionPipeline` run with a fake LLM ingests it, and the DB file is unchanged by the save itself.

### Guardrail claims
- A save never overwrites an existing note, including under concurrent saves of the same title.
- A save can never create a file outside `_general/` under `ONTOLOGY_DATA_DIR`, whatever the title or any extra request field such as `folder`, including when `_general` is a symlink that leaves the data folder.
- The web app still never writes `ontology.db`, and ingestion never sees a partially written pasted note.

### Supporting obligations
- Build the filename from the date and a slug of the title, with a fallback for titles that produce an empty slug. Unit test in `tests/test_note_intake.py`.
- Write to a hidden temp file in `_general/`, then publish with an atomic no-overwrite operation.
- Reject blank titles and empty, oversized, or non-UTF-8-encodable content with a clear error. Unit test in `tests/test_note_intake.py`.
- Keep every UI string in all six locales, and remove strings that only served the folder field.

### Allowed scope
- Reuse: the catalog's existing `_general` folder, the Notes workflow in `web/navigation.py`, and the JSON POST pattern in `web/app.py`.
- Cheaper alternative: saving to the data folder root needs no folder, but rejected because the human asked for a default folder. A CLI command is rejected because the claim is pasting into the app.
- Include: one note-writing helper under `web/`, one Notes page for pasting, one JSON save route, navigation and locale entries, minimal CSS, witnesses in `tests/test_web.py`, one `/notes/new` variant in `tests/test_web_navigation.py`, new `tests/test_note_intake.py`, and updates to `docs/architecture/web.md` and README.
- Exclude/protect: file upload, a folder field or parameter, Finder or clipboard file paste, editing or deleting notes, automatic ingestion, any DB write from the web app, login or user accounts, and new dependencies. The `search.py` path helper stays unchanged, because a fixed folder no longer needs its extraction.

### Invariants changed
- `src/stock_ontology/web/app.py:1,101` and `src/stock_ontology/cli.py:604` — today: the web app is described as read-only; after: it is read-only for `ontology.db` and may add new note files only. `AGENTS.md`'s rule that only ingestion writes to the DB is unchanged.

### Decisions required
- None. The default folder is `_general`, the location the catalog and README already define for notes not tied to a company. Residual risk: with a non-local `--host`, anyone who can reach the app can add notes that later flow into ingestion and house consensus.

## Proof

Candidate: `clean git archive of 1be7ce5 plus only tests/test_web.py (sha256 d131311e205da6fa4c996dc103eeab8dbda503c04ebb8cc616a50faae9562eaf), at /private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-JbyZNV/45d06d98-3236-45e4-a646-fe0bcf424330/scratchpad/paste-note-prove-red`

**Protected witness**
- Primary, root user pastes a note into `_general/`: `tests/test_web.py` / `test_paste_note_saves_md_lists_in_catalog_and_next_ingest_reads_it`
  - Defect and boundary: the app has no way to save pasted text as a note; browser form to HTTP route to filesystem to catalog to ingestion.
  - Assertion: the catalog links to `/notes/new`, the form has a textarea and no folder control, a POST with no credentials returns 201 with `_general/<date>_<slug>.md`, exactly one file is added with the exact content, existing files are unchanged, the catalog lists and opens it, `ontology.db` is byte- and mtime-identical after the save, and an offline `IngestionPipeline` with a fake LLM reads it; proves the primary claim; limit: does not drive browser JavaScript, and does not run `watch` or a live provider.
- Never overwrites: `tests/test_web.py` / `test_paste_note_never_overwrites_including_concurrent_same_title`
  - Defect and boundary: a name collision could replace a stored note; concurrent HTTP requests to the filesystem.
  - Assertion: 24 concurrent same-title saves return distinct `_general/` files, each with its own content, and the earlier note is intact; proves no overwrite under this race; limit: one process and one local filesystem.
- Extra `folder` field cannot choose a location: `tests/test_web.py` / `test_paste_note_extra_folder_field_cannot_move_the_note_out_of_general` (11 cases)
  - Defect and boundary: a request field could redirect the write; JSON body to filesystem path.
  - Assertion: after a positive-control save, a request with `folder` either returns 201 with its one new file directly in `_general/`, or returns 400/422 and changes nothing. Existing files and the outside directory are unchanged; proves there is no folder choice at the HTTP boundary; limit: covers the listed values and does not dictate ignoring versus rejecting.
- `_general` symlink cannot redirect a save: `tests/test_web.py` / `test_paste_note_refuses_general_symlink_that_leaves_the_folder` (external, dangling external, inside data dir)
  - Defect and boundary: a linked `_general` could send the write elsewhere; HTTP route to filesystem link resolution.
  - Assertion: the save returns 4xx, the data tree is unchanged, and the external target stays empty or absent; proves a symlinked `_general` is refused; limit: does not cover a swap between the check and the write, or symlinked parents of the data dir.
- Hostile title stays in `_general/`: `tests/test_web.py` / `test_paste_note_hostile_title_stays_a_visible_file_in_general` (6 cases)
  - Defect and boundary: a title could become a path; JSON body to filename.
  - Assertion: the save returns 201 with a visible `.md` directly in `_general/`, exact content, and nothing new outside the data dir; proves the title cannot escape; limit: covers the listed titles.
- No partial note reaches ingestion: `tests/test_web.py` / `test_paste_note_is_never_visible_to_ingestion_partially_written`
  - Defect and boundary: a non-hidden file could be read mid-write; filesystem publish to the ingestion scan rule.
  - Assertion: a concurrent watcher using the scan's visibility rule never sees incomplete content across 30 large saves, all files are in `_general/`, and no temp file remains; proves atomic visibility in this run; limit: a timing-based observation, not a proof over all interleavings, and it replicates the scan rule rather than calling the scan.
- The web app never writes `ontology.db`: covered by the primary witness digest check; limit: checks the save path only.
- Protected paths: `tests/test_web.py`.
- Protected revision: uncommitted `tests/test_web.py`, sha256 `d131311e205da6fa4c996dc103eeab8dbda503c04ebb8cc616a50faae9562eaf`; byte-identical copy at `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-JbyZNV/45d06d98-3236-45e4-a646-fe0bcf424330/scratchpad/paste-note-prove-red/tests/test_web.py`.

**Red evidence**
- From the clean export: `env -u ONTOLOGY_DATA_DIR UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run pytest tests/test_web.py -k paste_note -q --tb=line -p no:cacheprovider` → 23 failed, 32 deselected. The primary fails because `/catalog` has no `href="/notes/new"`. The other 22 fail with `404 == 201` or an all-201 check on `POST /api/notes`, because the route is missing; log: `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-JbyZNV/45d06d98-3236-45e4-a646-fe0bcf424330/scratchpad/paste-note-red.log`.
- Same export, `-k "not paste_note"` → 32 passed, so the failures are not setup or unrelated failures.
- RED limit: every guardrail case stops at the missing route, so RED shows the behavior is absent but does not exercise each guardrail's later assertions.
- Satisfiability check, not product proof: a scratch copy of the prior build, patched to always use `_general`, refuse a symlinked `_general`, and drop the folder control → 23 passed; log: `/private/tmp/claude-502/-Users-jasonbxu--claude-spares-spare-JbyZNV/45d06d98-3236-45e4-a646-fe0bcf424330/scratchpad/paste-note-sat.log`.
- Independence limit: this stage read the prior build's `src/stock_ontology/web/note_intake.py` and route lines while authoring, and kept its `POST /api/notes` and `{"file": ...}` contract, which the Frame does not name.

**Supporting test plan**
- Filename from date and title slug, with a fallback for an empty slug → Build: `tests/test_note_intake.py`; catches unsafe or empty filenames.
- Blank title, and empty, oversized, or non-UTF-8-encodable content rejected with a clear error → Build: `tests/test_note_intake.py`; catches invalid saves.
- `/notes/new` render variant → Build: `tests/test_web_navigation.py`; catches an unregistered Notes route.
- UI strings in all six locales, folder-only strings removed → Build: existing `tests/test_i18n.py`; catches missing or stale keys.

## Build

Candidate: `1be7ce5 + uncommitted tree 6c928ea0913f6a6c681bbca48100af1c50d6b952 (excluding this ledger) @ worktree .claude/worktrees/paste-note, branch proposal/paste-note-build`

### Files changed

- `src/stock_ontology/web/note_intake.py` — validates input, refuses a symlinked `_general`, and publishes through a hidden temp file and `os.link`; satisfies the primary, no-overwrite, containment, and no-partial-note claims.
- `src/stock_ontology/web/app.py` — adds `GET /notes/new` and `POST /api/notes` with no folder field, and updates the read-only wording named in Invariants changed.
- `src/stock_ontology/web/navigation.py` — registers the page and adds "Paste a note" to the Notes left nav.
- `src/stock_ontology/web/templates/note_new.html`, `src/stock_ontology/web/static/note_new.js`, `src/stock_ontology/web/static/library.css` — the paste form with title and text only.
- `src/stock_ontology/locales/{en,zh,ko,ja,es,fr}.json` — new UI strings in all six locales, with no folder strings.
- `src/stock_ontology/cli.py` — updates the `serve` read-only wording named in Invariants changed.
- `tests/test_note_intake.py` — human-approved unit tests for slugs, collisions, invalid input, the size limit, and a blocked default folder.
- `tests/test_web_navigation.py` — human-approved `/notes/new` render variant.
- `docs/architecture/web.md` — documents the page, route, default folder, and root-user limit.
- `README.md` — adds one Web UI constraint for the atomic, no-overwrite note write.

### Unit evidence

- Protected witness compared before and after implementation: `tests/test_web.py` sha256 `d131311e205da6fa4c996dc103eeab8dbda503c04ebb8cc616a50faae9562eaf`, unchanged.
- `uv run pytest tests/test_note_intake.py -q --tb=line` — RED before implementation: collection error, because `DEFAULT_NOTE_FOLDER` did not exist.
- `uv run pytest tests/test_note_intake.py -q --tb=short` — GREEN: 14 passed.
- Browser check on a scratch data copy: the form has no folder control, saving redirected to the rendered note, the file landed in `_general/`, the console had no errors, and the scratch DB hash was unchanged.

### Green evidence

- Decisive witness: `uv run pytest -q -k paste_note --tb=short` — 23 passed.
- Gate: `uv run pytest -q` — 425 passed.
- `uv run ruff check src/stock_ontology/web/note_intake.py tests/test_note_intake.py` — pass. `uv run ruff check src` reports 38 errors, the same count as the base tree.

### Intervention record

- None. The repository has no intervention ledger.

### Deviations

- None.

## Audit

Candidate: `1be7ce58d84586342fbc3a22cf35bd3061128f5c + uncommitted tree 6c928ea0913f6a6c681bbca48100af1c50d6b952 (excluding docs/proposals/paste-note.md), branch proposal/paste-note-build, recomputed with a temporary GIT_INDEX_FILE before and after the audit runs`

Independence: fresh-context — `the auditing context did not build the candidate. It started from the ledger path, candidate identity, and repository. It read the Build section as a claim only and reran all evidence from a clean export of the candidate tree.`

Primary-claim verdict: PROVED — evidence: `tests/test_web.py::test_paste_note_saves_md_lists_in_catalog_and_next_ingest_reads_it` passes on the exported candidate and failed on a clean `1be7ce5` export carrying the protected test file. It covers the Notes link, a form with no folder control, a credential-free 201 save, one exact `_general/*.md` file, catalog listing and opening, and an offline fake-LLM `IngestionPipeline.run()` reading the note. `IngestionPipeline.watch` calls the same `run()` at `src/stock_ontology/pipeline.py:741`. limit: the witness does not drive `note_new.js` in a browser. This audit read that script but did not run it, and it did not run a live `watch` loop or live provider.

Guardrail verdicts:
- A save never overwrites an existing note, including concurrent same-title saves: PROVED — evidence: `test_paste_note_never_overwrites_including_concurrent_same_title` passes, and a mutant replacing `os.link` with `os.replace` fails it. limit: one process and one local filesystem.
- A save cannot create a file outside `_general/`, whatever the title or extra field, including a symlinked `_general`: PROVED — evidence: the 11 `folder` cases, 3 symlink cases, and 6 hostile-title cases pass. Mutants that remove the symlink check, use the raw title, or write to the data root fail them. Extra probes with long Unicode titles and a lone-surrogate title stayed in `_general/` with filenames of at most 215 bytes. limit: a swap of `_general` between `is_symlink()` and the write is not covered, as Proof states.
- The web app never writes `ontology.db`: PROVED — evidence: the primary witness compares DB bytes and mtime across the save, and a mutant touching the DB after save fails it. The route calls only `save_pasted_note`. limit: the digest check covers the save path, and other routes rely on the existing read-only DB open.
- Ingestion never sees a partially written pasted note: PROVED — evidence: `test_paste_note_is_never_visible_to_ingestion_partially_written` passes, and a mutant making the temp file a visible `.md` fails it. `_scan_files` skips hidden path parts at `src/stock_ontology/pipeline.py:134-136`, and publish uses a hidden temp file plus `os.link`. limit: the witness is timing-based and replicates the scan rule. It does not prove every interleaving or crash durability, because the write has no `fsync`.

Scope and duty verdict: scope HELD; duties HELD — evidence: all 18 changed files fall inside Frame's Allowed scope. `tests/test_web.py` matches protected sha256 `d131311e205da6fa4c996dc103eeab8dbda503c04ebb8cc616a50faae9562eaf`. `tests/test_web_navigation.py` adds only the approved `/notes/new` variant. The listed read-only wording changes in `web/app.py` and `cli.py` were made. No dependency, folder field, upload, edit, delete, auto-ingest, or auth code was added. The new `README.md` constraint has `**Why:**` and two existing `**Guarded by:**` tests. Slug, invalid-input, size, and locale obligations pass in `tests/test_note_intake.py` and `tests/test_i18n.py`. limit: translation quality was not reviewed.

Test homes: `tests/test_web.py` — permanent HTTP-integration owner named by Frame for the protected witnesses; `tests/test_note_intake.py` — human-approved unit owner for the new `web/note_intake.py` helper; `tests/test_web_navigation.py` — permanent owner of the route render-variant registry.

Full gates: PASS — `uv run --offline --frozen pytest -q -p no:cacheprovider --tb=short` on the exported candidate: 425 passed; `pytest tests/test_web.py -k paste_note`: 23 passed; `pytest tests/test_note_intake.py tests/test_i18n.py tests/test_web_navigation.py`: 60 passed; RED on the `1be7ce5` export plus protected test: 23 failed, and `-k "not paste_note"`: 32 passed; `ruff check src/stock_ontology/web/note_intake.py tests/test_note_intake.py`: pass; `ruff check src`: 38 errors on both candidate and base. limit: the repository's required gate is the offline pytest suite. Ruff on `src` is not clean, and its count was compared with base rather than rule by rule.

Residual risks:
- With a non-local `--host`, anyone who can reach the app can add notes that later flow into paid ingestion and house consensus. Frame accepted this for the root-user demo, and `docs/architecture/web.md` warns about it.
- Non-JSON content types return 422 and create nothing, which blocks simple cross-site form posts, but there is no CSRF token or origin check.
- The 1 MB limit runs after the JSON body is parsed, so an oversized request still consumes memory first.
- A crash shortly after publish could leave an incomplete note because the write has no `fsync`.
- A filesystem without hard-link support would fail the save with a server error. The form would show the generic error.

Recommendation: ACCEPT
Packet: No candidate change is required. Merging, deploying, and running `ingest` on live data remain separate human decisions. Any source or test change creates a new candidate and requires re-audit of the changed tree.

## Revisions

<!-- Append-only, written by the orchestrator. One entry per audit REVISE and the
work that answered it. Never delete an entry, never edit an earlier one, and never
move Frame, Proof, Build or Audit history into it. Empty until the first REVISE. -->
