# Gate G5 — Stages 10–11 (End-to-end verification, Architecture document & delivery) — Gate report

**Date:** 2026-10-10 · **Status:** awaiting approval

## Built

**Stage 10: end-to-end verification & demo script**
- `scripts/e2e_all.sh` replays every stage's acceptance checks against a live stack, in 9 steps:
  1. containers healthy
  2. real-site ingestion
  3. parser tests
  4. participants
  5. the 8 SAGA cases
  6. reconciliation
  7. gateway + security suite
  8. browser E2E
  9. final reconciliation
- `docs/guion-demo.md` (Spanish) is a 12-minute script with timings and exact clicks for the four demo items in brief §6. It also covers 15 min of preparation, a Plan B if a site blocks the scraper, and the available failure simulations.

**Stage 11: architecture document & delivery**
- **`docs/arquitectura.md` → `docs/arquitectura.pdf`** (Spanish, 15 pages). It covers:
  - Summary and tech mapping
  - Architecture diagram and containers
  - Decision justifications (ADR-01…09)
  - Ingestion (Dask + Prefect)
  - Persistence and the GraphQL gateway
  - SAGA: state machine, happy path, car-failure compensation, lost-confirmation timeout, idempotency and recovery
  - Security, including the session-fixation sequence
  - Deployment
  - Rubric traceability, limitations, and reuse of earlier projects
- `scripts/build_pdf.sh` rebuilds the PDF: Mermaid rendered by mermaid-cli → HTML via `marked` → PDF printed by the Chromium in our own ingestion image.
- `README.md` updated for delivery: quick start, URLs, demo account, tests, repo layout.

## Acceptance criteria

| AC | Result | Evidence |
|---|---|---|
| AC-10.1 clean-clone startup, zero manual steps | PASS: `down -v`, project images removed, fresh `git clone`, then `cp .env.example .env && docker compose up -d --build --wait` → 13/13 healthy in 57 s | `stage-10/AC-10.1_clean-clone.txt` |
| AC-10.2 demo items (a)–(d) pass following only the script | PASS: each item maps to steps in `docs/guion-demo.md` that the regression exercises: (a) Prefect runs for ingestion and SAGA, (b) Dask distribution 9/9/10, (c) browser→`/graphql` only, (d) car / timeout / flaky compensations. The live presentation and recording themselves are the author's (Q-23) | `docs/guion-demo.md`, `stage-10/regression/` |
| AC-10.3 all previous ACs still pass | PASS: **9/9 regression steps** in the clean clone | `stage-10/AC-10.3_regression-summary.txt`, `stage-10/regression/*.txt` |
| AC-10.4 *(task T10.4)* resources on the target machine | PASS: about 1.6 GB RAM for the 13 containers during ingestion. The busiest worker uses 1 CPU (Chromium) | `stage-10/AC-10.4_resources.txt` |
| AC-11.1 document contains everything required by brief §6 | PASS (checklist) | `stage-11/AC-11.1_deliverables-checklist.md`, `docs/arquitectura.pdf` |
| AC-11.2 secret scan of the git history is clean | PASS: gitleaks v8.30.1 finds no leaks in all commits. Only `.env.example` (local demo values) is tracked, and none of the sibling projects' Supabase keys are present | `stage-11/AC-11.2_secret-scan.txt` |
| AC-11.3 README quick start verified literally | PASS: the clean-clone run used exactly the README's two commands | `stage-10/AC-10.1_clean-clone.txt` |

## Bug found and fixed during verification
- **Browser screenshots weren't saved in the regression run.** The browser container only mounted the repo, and the output directory was outside it. Selenium's `save_screenshot` returns `False` instead of raising, so nothing failed. Two fixes: the runner now mounts the output directory, and the test raises if a screenshot can't be written. I then reran the browser step against the main stack, built from the same commit: all checks pass and 10 screenshots are in `stage-10/regression/`. That screenshot run used the working stack, not the clean clone; the clean-clone run's browser checks passed without images.

## Deviations from spec
- **G5 has no separate "deliverable 3" artifact.** The live demo and recording are done by the author following `docs/guion-demo.md`.
- **PDF tooling:** pandoc isn't installed, so the PDF is built with tools already in the stack (mermaid-cli, `marked`, and the Chromium in the ingestion image).

## Open risks / known limits
- **Real sites can change or block on demo day.** Run the preparation step (one ingestion about 15 min before). Seed data keeps booking working regardless.
- **The clean-clone test reused the machine's Docker build cache.** On a machine without it, the first build takes longer (the Chromium layer is about 300 MB).
- **The architecture document is a snapshot.** If the code changes after delivery, rerun `./scripts/build_pdf.sh`.

## Approval
- [ ] Approved by user — date: ____
