# Plan / Roadmap — filen-python

What's known to be unimplemented, broken, or worth porting from
the Dart sibling ([`filen-dart`](../filen-dart)). The terminal
goal is to mirror what was done for
[`internxt-cli`](../internxt-cli) — a tested CLI with a packaged
service layer, ready for either pip-installable distribution or
to underpin a future multi-provider tool (`cloud-python`).

**Playbook**: read these in `../internxt-cli/` before starting:
- `PLAN.md` — phase structure, audit conventions
- `HISTORY.md` — the actual sequence the Internxt audit took
- `LEARNINGS.md` — gotchas + lessons (including the WebDAV
  PROPPATCH lying-contract bug that filen-python likely inherited
  via the fork)

## Status snapshot (initial state, captured pre-audit)

**Repo state:**
- Forked from internxt-cli (requirements.txt comment confirms it).
  Inherited internxt-cli's pre-audit module structure but **none
  of internxt-cli's audit work** (which post-dated the fork).
- 10 git commits visible, all post-fork-feature work
  ("leverage tree", "better caching", "wildcard support",
  "fix webdav", etc.).
- `services/` already split into 7 modules: api (273 LOC),
  auth (225), crypto (203), drive (1784), network_utils (410),
  webdav_provider (393), webdav_server (146). Total ~3400 LOC.
- `cli.py`: 67KB / 1624 LOC, single `FilenCLI` class + `main()`.
- `config/config.py` for ConfigService (separate from services/).
- `utils/` directory exists but is **empty**.
- **No tests directory.** internxt-cli has 9+ test files in
  `tests/`; filen-python has zero.
- No `pyproject.toml`. `requirements.txt` is the only dep manifest.

**Key inherited gotchas (likely present, verify in Phase 1):**
- `webdav_provider.py` PROPPATCH handler likely has the
  `from wsgidav.util import rfc_1123_to_timestamp` import that
  never existed in any released wsgidav version. internxt-cli's
  LEARNINGS.md documents this — same fork-point shape.
- `services/__init__.py` may import dead modules.
- Dependency lockstep: `requests`, `cryptography`, `mnemonic`,
  `wsgidav`, `waitress` versions may have moved on since the
  fork — check for breaking-API surfaces.

**Done:** nothing.

**Open — load-bearing:**

The phases below are sized for one focused session each. Phases
have **dependencies** (Phase N requires Phase N-1) so a fresh
agent should execute them in order.

---

## Phase 1 — audit (~2 hours)

**Goal:** mirror internxt-cli's audit Phase 0–3. Find the inherited
bugs (likely present at the fork point), dead code, lying-contract
imports, dynamic-dispatch hazards.

**Steps:**
1. Add tooling to dev requirements:
   ```
   # Add to requirements.txt under "Development dependencies":
   pytest>=7.4.0
   pytest-cov>=4.1.0
   ruff>=0.1.0
   pyright>=1.1.0
   ```
2. Install + run:
   ```bash
   pip install -r requirements.txt
   ruff check . > audit-ruff.txt
   pyright services/ cli.py > audit-pyright.txt
   ```
3. Triage findings. Look specifically for:
   - **Dead imports** (the `rfc_1123_to_timestamp` shape — see
     `../internxt-cli/LEARNINGS.md` "On `package:file` and the
     WebDAV `@override` bug"). Run:
     ```bash
     grep -rn "from wsgidav" services/
     grep -rn "from .* import" services/ | grep -i "dead\|removed\|deprecated"
     ```
   - **Cross-module mutable globals** (the audit pattern from
     internxt-cli Phase 0).
   - **Bare `except:` clauses** that swallow real errors.
4. Cross-reference findings against
   `../internxt-cli/HISTORY.md`'s Phase 0–3 commit messages —
   anything internxt-cli fixed there is a candidate for being
   present here too (since filen-python was forked before
   those fixes landed).
5. Write `LEARNINGS.md` (mirror
   `../internxt-cli/LEARNINGS.md`'s structure). Include:
   - "On the audit itself" — what tooling caught what
   - "On the trust roots" — Filen's crypto stack (PBKDF2-HMAC-SHA512,
     AES-GCM-256, RSA-OAEP)
   - "On rate limiting and eventual consistency"
6. Each genuine bug gets its own commit in this phase.

**Acceptance:**
- `ruff check .` passes (or has only intentionally-deferred
  lints documented in `pyproject.toml` / `ruff.toml`).
- `pyright services/ cli.py` passes (or has documented
  deferrals).
- `LEARNINGS.md` exists with at least 4 sections.
- All inherited bugs are fixed and committed (referencing the
  internxt-cli equivalent commit where applicable).

---

## Phase 2 — test infrastructure (~3 hours)

**Goal:** establish the testing scaffolding internxt-cli has.
filen-python has *zero* tests; even minimal coverage is a big win.

**Steps:**
1. Mirror `../internxt-cli/tests/` structure:
   ```
   tests/
     __init__.py
     conftest.py           # fixtures: tmp_dir, mock_api_client, etc.
     test_crypto.py        # trust roots — PBKDF2 known vectors,
                           # AES-GCM round-trips, RSA keypair gen
     test_auth_login.py    # mocked login flow
     test_auth_refresh.py  # token refresh + bridge auth pair
     test_api_client.py    # network_utils retry / backoff logic
     test_api_endpoints.py # endpoint helpers via unittest.mock
     test_checkpoints_and_sanitize.py # batch state + filename safety
     test_live_smoke.py    # opt-in via .env (FILEN_EMAIL/PASSWORD)
   ```
2. Test the trust roots first — `test_crypto.py`. Filen uses
   PBKDF2-HMAC-SHA512 → AES-GCM-256 with per-file derived keys.
   Pin the algorithm + parameters with known-vector tests so a
   future "let's upgrade the crypto lib" commit doesn't silently
   change the encryption format. Internxt's equivalent has 35+
   tests; aim for similar coverage.
3. `conftest.py` provides:
   - `tmp_dir` fixture using `tmp_path`
   - `mock_api_client` using `unittest.mock.patch`
   - A `live_test` decorator that auto-skips without
     `FILEN_EMAIL` / `FILEN_PASSWORD` (mirror internxt-cli's
     `liveTest()` helper from `tests/conftest.py`)
4. `test_live_smoke.py`:
   - Loads `.env` from the repo root (and from `../filen-dart/.env`
     as a fallback so creds can be shared across the two repos).
   - Sentinel folder `/__test_filen_python_smoke__/<run-id>/`.
   - `tearDownAll`-equivalent cleanup via pytest fixture finalizer.
   - 5–10 round-trip tests (login, list, upload, download, trash).
5. `pytest.ini` or `pyproject.toml` configures:
   - `testpaths = tests`
   - `addopts = -ra --strict-markers`
   - Markers: `live` (opt-in), `slow`
6. `.env.example` showing `FILEN_EMAIL=` / `FILEN_PASSWORD=`.
7. `.gitignore` ensures `.env` is ignored.

**Acceptance:**
- `pytest tests/test_crypto.py tests/test_auth_*.py
  tests/test_api_*.py tests/test_checkpoints_and_sanitize.py`
  passes (at least 30 tests, no live calls).
- `pytest tests/test_live_smoke.py` cleanly skips without creds,
  runs end-to-end with creds.
- `pytest --cov=services` reports a coverage figure (initial
  baseline; later Phase 4 adds per-module thresholds).

---

## Phase 3 — feature parity audit vs filen-dart (~3 hours)

**Goal:** identify and port any feature in filen-dart that's
missing from filen-python (and vice versa). filen-dart's commit
log shows recent additions ("trash handling", "resumes",
"webdav fixes", "faster") that may not have made it back to
Python.

**Steps:**
1. Compare module surfaces:
   - `filen-python/services/api.py` vs `filen-dart/api.dart`
     (after filen-dart Phase 3)
   - `services/drive.py` (32 defs) vs `drive.dart`
   - `services/auth.py` (10 defs) vs `auth.dart`
   - `services/crypto.py` (12 defs) vs `crypto.dart`
   - `services/network_utils.py` (9 defs) vs
     `download.dart`/`upload.dart`
   - `services/webdav_provider.py` (39 defs) vs `webdav_filesystem.dart`
2. Per-method-name checklist: for each Dart public method, is
   there a Python equivalent? Capture gaps in a per-phase commit
   message.
3. Likely gap-categories (based on filen-dart's commit log):
   - Recent **resume support** improvements
   - Recent **trash handling** additions
   - Recent **WebDAV fixes** (PROPPATCH, MKCOL behavior)
   - **Faster** — any chunking / parallelism improvements
4. Port each gap as its own commit. Add a test for each port
   (unit test if possible, live test otherwise).

**Acceptance:**
- `LEARNINGS.md` updated with feature comparison table.
- Each ported feature has at least one test.
- No Dart-side feature is silently dropped without justification
  written here.

---

## Phase 4 — package as installable (~2 hours)

**Goal:** make filen-python `pip install`-able so it can be
consumed as a library (not just run as `python cli.py`). Required
groundwork for the future `cloud-python` umbrella tool.

**Steps:**
1. Write `pyproject.toml` (PEP 621 metadata):
   ```toml
   [build-system]
   requires = ["setuptools>=65", "setuptools-scm"]
   build-backend = "setuptools.build_meta"

   [project]
   name = "filen-cli"
   version = "0.1.0"
   description = "Filen.io CLI client for Python (unofficial)"
   requires-python = ">=3.9"
   dependencies = [
     "cryptography>=41.0.0",
     "mnemonic>=0.20",
     "requests>=2.31.0",
     "click>=8.1.0",
     "tqdm>=4.66.0",
     "WsgiDAV>=4.3.0",
     "waitress",
     "pyOpenSSL>=23.0.0",
   ]

   [project.optional-dependencies]
   dev = ["pytest>=7.4.0", "pytest-cov>=4.1.0", "ruff>=0.1.0"]

   [project.scripts]
   filen = "cli:main"
   ```
2. Move existing modules into a proper package layout if needed
   (current layout is already mostly compliant — `services/` and
   `config/` are namespace-importable). Verify with:
   ```bash
   pip install -e .
   filen --help
   ```
3. Update `cli.py` imports if needed so `from services.foo import bar`
   still works after install.
4. Add `MANIFEST.in` if any non-py files need to ship.
5. `pip install --dry-run .` should succeed.

**Acceptance:**
- `pip install -e .` works in a fresh venv.
- `filen --help` invokes the CLI from anywhere on PATH.
- `python -c "from services.drive import drive_service"` works
  from any cwd.

---

## Phase 5 — cloud-python rewire (CONDITIONAL, ~3 hours)

**Goal:** there is no `cloud-python` consumer YET — but if/when
one exists (the Option C umbrella tool from the strategic
discussion), this phase mirrors what internxt's Phase 6.b/6.c
did for cloud-dart.

**Skip this phase entirely if cloud-python doesn't exist.**

If it does:
1. Audit cloud-python's embedded copy of filen (similar to
   `../internxt-dart/AUDIT_6B.md` for cloud-dart).
2. Replace the embedded code with a `from filen_cli.services
   import drive_service` import.
3. Wire any cloud-python-specific config (URLs, alternate auth) at
   construction.
4. Add a smoke test in cloud-python.

**Acceptance:**
- cloud-python's embedded copy is gone.
- All cloud-python tests pass.

---

## Phase 6 — CI + GitHub Actions (~30 min)

Mirror `../internxt-cli/.github/workflows/` (if it has one — if
not, mirror the shape of internxt-dart's CI translated to Python):

```yaml
name: CI
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -e .[dev]
      - run: ruff check .
      - run: pytest tests/ -m "not live" --cov=services --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with: { file: ./coverage.xml }
```

Live tests skip via `pytest -m "not live"` (the marker added in
Phase 2). CI doesn't get real Filen creds — same security stance
as internxt-cli.

**Acceptance:**
- `.github/workflows/ci.yml` exists, runs on push + PR to main.
- First CI run completes successfully.

---

## Estimates

| Phase | Effort |
|---|---|
| 1. audit + LEARNINGS | ~2h |
| 2. test infrastructure | ~3h |
| 3. feature parity vs Dart | ~3h |
| 4. package as installable | ~2h |
| 5. cloud-python rewire | conditional ~3h (skip if no consumer) |
| 6. CI | ~30 min |
| **Total** | **~10.5 hours** (excluding Phase 5) |

Significantly tighter than internxt-cli's audit arc because:
- The module split (Phase 4-equivalent on the Dart side) is
  already done — `services/` exists.
- Many gotchas are documented in
  `../internxt-cli/LEARNINGS.md` and apply directly (the fork
  point inherited them).
- No multi-repo divergence to chase yet — there's no
  cloud-python.

## Reference checklist for the executing agent

Before starting any phase:
- [ ] `cd /Users/christianstrobele/code/filen-python`
- [ ] Read this file's "Status snapshot" + the relevant Phase
- [ ] Skim `../internxt-cli/LEARNINGS.md` for inherited gotchas
- [ ] Check git status; commit any in-progress work first
- [ ] Activate the right Python venv

After completing a phase:
- [ ] Update this file's status snapshot ("Done:" section grows)
- [ ] If a new gotcha was discovered, add it to LEARNINGS.md
- [ ] Commit + push + verify CI (once Phase 6 is done)

## Out of scope (explicit non-goals)

- **GUI** — wrong tool for a CLI library.
- **Sync engine** — that's the official Filen client.
- **Cross-account migration** — interesting separate project.
- **Mobile platforms** — Python on mobile is impractical; the Dart
  port covers that surface.

## After Phase 4 ships

The `cloud-python` umbrella idea (Option C from the strategic
discussion that produced this plan) becomes feasible. A new
repository at `~/code/cloud-python` would:

- Depend on `internxt-cli` + `filen-cli` as installable packages.
- Provide a uniform `cloud --provider=internxt|filen ls /path` etc.
- Mirror cloud-dart's `CloudStorageClient` interface but in Python,
  CLI-only.

Don't start cloud-python until Phase 4 lands here AND
internxt-cli is pip-installable — it'd be built on unstable
foundations otherwise. (internxt-cli is currently `python cli.py`,
not pip-installable; that's the matching prerequisite.)

---

# Performance: connection reuse & concurrency (added 2026-06-29)

Chunk upload/download was **sequential** AND opened a **fresh TCP+TLS
connection per 1 MB chunk**. For a 1 GB file (~1000 chunks) that's ~1000
handshakes, serialized. Two independent wins: (0) reuse connections, then
(1) overlap chunks. Applies symmetrically to the sibling `filen-dart`.

## Step 0 — connection reuse ✅ DONE & TESTED
- `APIClient` holds one pooled `requests.Session` (`services/api.py`), used by
  `_request` and shared with chunk transfers via `self.api.session.get/post`
  (`services/drive.py`). Dead function-local `import requests` removed.
- (dart sibling: chunk uploads now go through the pooled `api.client` instead of
  the one-shot top-level `http.post` in `lib/upload.dart`; downloads already did.)
- Tests: `tests/test_connection_reuse.py` (6 unit) + `tests/test_live_roundtrip.py`
  (2 live, saved-session). All green. (dart: `test/connection_reuse_test.dart`
  2 unit + `live_smoke` 7 live.)
- Recovers the bulk of the loss at ~5% of the risk — no architecture change,
  resume feature untouched.

## Step 1 — bounded chunk concurrency ✅ DONE & TESTED
- `services/drive.py`: `upload_file_chunked` now runs chunk POSTs on a bounded
  `ThreadPoolExecutor` (`max_concurrent_chunks`, default 4). A sequential
  producer reads+hashes plaintext in order; only the network POST is parallel.
  In-flight is capped by a `threading.Semaphore` (≈ N×(1 MB plaintext + 1 MB
  encrypted)). `download_file` fetches chunks concurrently and writes each at
  its fixed offset. Tiny files (≤ 2 chunks) keep the sequential path.
- Resume is now a **set**: `ChunkUploadException.completed_chunks` (+ `file_key`,
  so resumed chunks share one key); batch state persists `completedChunks`.
  `last_successful_chunk` kept as the contiguous-prefix high-water mark.
- Tests: `tests/test_chunk_concurrency.py` (7 unit) + `tests/test_live_concurrency.py`
  (4 live). All green; live throughput ~1.27× on a 16 MB file.

Goal: N chunks in flight (start N=4–8), **semaphore-bounded** — never unbounded
(→ server throttling + memory blowup). Mirrors filen-sdk-ts's `MAX_UPLOAD_THREADS`.
- python: `ThreadPoolExecutor(max_workers=N)` — uploads are I/O-bound so the GIL
  releases during socket I/O. (asyncio+aiohttp is a larger rewrite; defer.)
- dart: N chunk `Future`s gated by a semaphore + the existing `MemoryGate`
  (already byte-budget aware — repurpose from per-file to per-chunk).

**Three constraints — do NOT just flip sequential→parallel:**
1. **In-order hashing.** The file hash is a running SHA-512 over *plaintext
   chunks in order*. Keep a sequential producer that reads+hashes in order, then
   hands `(index, plaintext)` to the bounded upload pool. Reading+hashing is
   cheap (disk/CPU); only the slow network upload is parallelized.
2. **Resume becomes a set, not a high-water mark.** Today `resume_from_chunk=N`
   assumes all `<N` are done. With out-of-order completion, track
   `completed_chunks: Set[int]`; `ChunkUploadException(last_successful_chunk)`
   carries the completed set instead. Protocol allows arbitrary chunk order.
3. **Bound by BYTES in flight, not thread count** (critical on mobile/CrispCloud).
   N concurrent chunks ≈ N×(1 MB plaintext + ~1 MB encrypted) live. Keep the
   degree configurable, modest default on mobile.

Skip concurrency for **tiny files** (≤ a few chunks) — branch on size.

## Step 2 — file-level concurrency ⬜ TODO (sync / many small files)
Parallelize whole FILES (not just chunks) in batch directory upload/download — the
bigger real-world win when syncing many files. Reference: internxt-cli already does
this (`cli.py` `ThreadPoolExecutor` + `--workers`, gated by
`DriveService._mem_acquire`/`_mem_release`) — port that pattern.

Files/functions:
- `services/drive.py` → `upload(...)` (~line 833): the per-file `for task in tasks:`
  loop. Run the per-file body on a `ThreadPoolExecutor(max_workers=W)` (W configurable,
  default 4). Each file ALSO uses Step 1 chunk concurrency internally, so cap the
  PRODUCT: total in-flight ≈ W files × N chunks. Either lower per-file
  `max_concurrent_chunks` when W>1, or share ONE global byte-budget semaphore across
  all files (preferred — mirrors filen-dart's single shared `MemoryGate`, below).
- `services/drive.py` → `download_path(...)` (~line 1024): same treatment for the
  per-file download loop.

CONSTRAINTS:
1. `batch_state` / `save_state_callback` is shared mutable state — guard task-status
   writes with a `threading.Lock` (files complete out of order).
2. Cap TOTAL bytes in flight across files × chunks (ONE shared budget), not per file —
   else W×N×2 MB blows memory on mobile (CrispCloud).
3. Conflict-check + `create_folder_recursive` / `_invalidate_cache` are shared — lock,
   or pre-resolve parent folders once before fan-out.
4. Keep progress output readable under concurrency (per-file lines interleave — lock
   prints or give each worker a tqdm position).

Tests (mirror `tests/test_chunk_concurrency.py` + `tests/test_live_concurrency.py`):
Unit: a many-file batch never exceeds W concurrent files AND the global byte budget;
state writes are race-free. Live: a directory of many files round-trips and is faster
than the W=1 baseline.

## Test matrix — unit + live for everything
Unit (hermetic; mocked session / MockClient):
- [x] chunk POST/GET routes through the pooled session
- [x] bounded pool never exceeds N concurrent in-flight (assert peak concurrency)
- [x] in-order hash: parallel uploads still produce the correct whole-file SHA-512
- [x] resume-as-set: restart skips exactly completed indices, retries the gaps
- [x] tiny-file path stays sequential
- [x] memory ceiling: gate blocks once byte budget is exceeded
Live (real backend, saved `~/.filen-cli` session):
- [x] round-trip small file
- [x] round-trip large multi-chunk file (8–16 MB); verify hash + content
- [x] interrupted upload resumes and completes (kill mid-way, restart)
- [x] concurrent throughput sanity (large file faster than sequential baseline)
- [x] directory of many small files round-trips

## Order of work
Step 0 (done) → Step 1 in **filen-python first** (simpler: ThreadPoolExecutor) →
port to filen-dart with MemoryGate → Step 2. Validate each against the matrix
before advancing.
