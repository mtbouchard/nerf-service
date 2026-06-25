# nerf-service — TODO

---

# ☀️ Morning worklist — finish the World Labs (Marble) backend

The whole feature is scaffolded and wired; the only unimplemented piece is the 3
functions in `worldlabs_backend.py`. Work test-first: each milestone turns a red test
green. Run all commands **from the `nerf-service/` directory**.

Reference (peek if stuck): `solution_worldlabs_backend.py` — a complete working version.
Don't copy it wholesale unless you want to; the goal is to implement it yourself.

### M0 — Baseline (2 min)
- **Do:** confirm the starting state.
- **Verify:** `../.venv/bin/python -m pytest -q`
- **Done when:** everything passes EXCEPT the 7 tests in `tests/test_worldlabs_backend.py`
  (those fail with `NotImplementedError` — that's expected; they're your targets).

### M1 — Implement `upload_image()` (prepare_upload + PUT)
- **Do:** in `worldlabs_backend.py`, follow the TODOs: `httpx.post` to
  `/marble/v1/media-assets:prepare_upload` (header `WLT-Api-Key`), then `httpx.put` the
  raw bytes to `upload_info["upload_url"]` with its `required_headers`; return the
  `media_asset["id"]`. (You'll need to `import httpx`.)
- **Verify:** `../.venv/bin/python -m pytest tests/test_worldlabs_backend.py::test_upload_image_prepares_and_puts -q`
- **Done when:** that test is green.

### M2 — Implement `submit()` (multi-image generate)
- **Do:** build `multi_image_prompt` with evenly-spread azimuths
  (`azimuth = int(i * 360 / N)`), POST to `/marble/v1/worlds:generate`, return
  `operation_id`.
- **Verify:** `../.venv/bin/python -m pytest tests/test_worldlabs_backend.py::test_submit_builds_even_azimuths -q`
- **Done when:** green (asserts azimuths `[0, 90, 180, 270]` and the asset ids/order).

### M3 — Implement `fetch_status()` (poll + map state)
- **Do:** GET `/marble/v1/operations/{id}`; if not `done` map
  `IN_QUEUE→pending` / else `running`; if `done` with `error` → `("failed", msg, None)`;
  if `done` ok → `("done", None, response["world_marble_url"])`.
- **Verify:** `../.venv/bin/python -m pytest tests/test_worldlabs_backend.py -q`
- **Done when:** all 7 backend tests green.

### M4 — Full suite green (the implementation gate)
- **Verify:** `../.venv/bin/python -m pytest -q`
- **Done when:** **everything** passes (app + runpod + worldlabs wiring + backend internals).
  This is the milestone that says "the code is correct without spending a cent."

### M5 — Validate live credentials (free — no world generated)
- **Do:** create a key at platform.worldlabs.ai, add `WLT_API_KEY=...` to `.env`.
- **Verify:** `../.venv/bin/python scripts/check_worldlabs.py`
- **Done when:** prints `SUCCESS: WLT_API_KEY is valid.` + a credit balance.
  (If it complains about `dotenv`, instead run with the key inline:
  `WLT_API_KEY=... ../.venv/bin/python scripts/check_worldlabs.py`.)

### M6 — Live end-to-end (costs credits, ~5 min generation)
- **Do (terminal A):** start the API in worldlabs mode:
  `NERF_BACKEND=worldlabs WLT_API_KEY=... ../.venv/bin/python -m uvicorn app:app --port 8000`
- **Do (terminal B):** upload a few overlapping photos, submit, and poll. Quickest is the
  existing client: `SERVER_URL=http://127.0.0.1:8000 ../.venv/bin/python client/client.py <frames_dir>`
- **Verify the world URL** (the real payoff): once `/jobs/<id>` shows `done`, grab the
  result redirect target:
  `curl -si http://127.0.0.1:8000/jobs/<id>/result | grep -i location`
  → open that `marble.worldlabs.ai/world/...` URL in a browser.
- **Done when:** the Location header is a Marble world URL that loads a navigable scene.
- ⚠️ **Note:** `client/client.py` was written for the `.ply` flow — in worldlabs mode its
  final "download" step will save the redirected web page, not a file. That's fine for the
  smoke test (upload→submit→poll all exercise the real API); the meaningful output is the
  world URL from the redirect. See the optional polish below.

### M7 — Commit (and decide on deploy)
- **Do:** commit the feature + the still-uncommitted hero images. Suggested:
  `git add app.py .env.example worldlabs_backend.py solution_worldlabs_backend.py tests/test_worldlabs.py tests/test_worldlabs_backend.py scripts/check_worldlabs.py scripts/render_splat.py assets/ TODO.md`
  then commit.
- **Deploy is optional:** Render is live on `runpod` mode today. Don't flip it to worldlabs
  unless you want the public demo to generate (paid) worlds. Safer to keep runpod live and
  treat worldlabs as a local/branch demo for now.

### Optional polish (only if time)
- Make `client/client.py` worldlabs-aware: when `result_format == "world"`, print the
  world URL (from the `/result` redirect Location) instead of writing bytes to `scene.ply`.
- Backend-aware landing already done; nothing required there.

---

## 1. Persist job state (don't keep it only in memory)  — HIGH

**Problem.** Job and upload state live in process memory (`jobs` / `uploads` dicts in
`app.py`). When the API process restarts, all of it is lost. We hit this live on Render:
a job that was happily polling `running` was wiped when the instance recycled, so
`GET /jobs/<id>` started returning `404 job not found` — even though the GPU worker had
already finished and uploaded the result to R2.

**Why it matters.** The whole point of the 202 + poll design is that work outlives a single
request. With in-memory state, an API restart (deploy, recycle, crash, or free-tier
spin-down) breaks every in-flight job. It also means we can't run more than one API
instance (each would have its own dict).

**Proposed fix (no new infra — reuse R2).** Make the API effectively stateless for runpod
jobs by persisting a small record per job to object storage:
- On `POST /nerfify` (runpod): after submitting, write `jobs/<job_id>.json` to R2 with
  `{ runpod_id, result_key, image_ids, status }`.
- On `GET /jobs/<job_id>` (runpod): if the job isn't in memory, load it from
  `jobs/<job_id>.json`; rebuild the in-memory `Job`; then refresh status from RunPod and
  write the updated status back.
- On `GET /jobs/<job_id>/result` (runpod): same fallback — load from R2 if not in memory.
- Add `storage.put_json()` / `storage.get_json()` / `storage.object_exists()` helpers.
- Treat the in-memory dicts as a cache, not the source of truth.

**Alternatives if we outgrow R2-as-store:** a small Redis (Render add-on / Upstash) or a
Postgres table. R2 is enough for now and adds no moving parts.

## 2. Harden the client poll loop  — MEDIUM

**Problem.** `client/client.py` calls `.json()` on every `/jobs` response. During the Render
restart above, Render returned a non-JSON 502 HTML page and the client crashed with
`JSONDecodeError` mid-poll.

**Fix.** In the poll loop, tolerate transient failures: check status code, catch JSON/HTTP
errors, log a warning, and keep polling (with a small backoff and a max-retries guard)
instead of aborting the whole run.

## 3. (Optional) Auth on /nerfify  — LOW (revisit if cost becomes a concern)

The public endpoint is unauthenticated, so anyone can trigger GPU jobs. Currently bounded
by RunPod max-workers / execution-timeout / credit balance. If abuse shows up, add a simple
shared-secret header check (or per-key quota) on `POST /nerfify`.
