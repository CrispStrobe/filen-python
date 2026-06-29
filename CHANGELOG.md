# Changelog

## 0.2.0 — Bounded chunk + file-level concurrency

Chunk and file transfers now run with **bounded concurrency** instead of
one-at-a-time — the single biggest throughput win for the client.

### Added
- **Bounded chunk concurrency (Step 1):** `upload_file_chunked` runs chunk POSTs on
  a bounded `ThreadPoolExecutor` (`max_concurrent_chunks`, default 4) with in-flight
  capped by a semaphore; `download_file` fetches chunks concurrently with
  fixed-offset writes.
- **File-level concurrency (Step 2):** batch directory upload/download transfer
  multiple whole files at once under one shared in-flight budget.

### Fixed
- Resume tracks a completed-index **set** (`ChunkUploadException.completed_chunks`)
  — safe with out-of-order chunk completion — and reuses the original file key on
  restart, so already-uploaded chunks stay decryptable.

### Preserved
- In-order whole-file SHA-512 hashing (parallel uploads produce the identical hash
  to the sequential path); tiny files stay on the simple sequential path.

### CI
- Added GitHub Actions: ruff lint (blocking), mypy + bandit (advisory), and a
  pytest matrix (3.10–3.12) with coverage.
