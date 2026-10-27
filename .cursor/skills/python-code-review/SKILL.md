---
name: python-code-review
description: >-
  Review all Python in the repo against global coding rules (.mdc) and project .cursor/rules.
  Produces or updates docs/REPOINDEX.md and docs/CODEREVIEW.md. Use for periodic Python health
  checks, pre-PR review, or when the user asks for a python code review (including legacy
  "agents-python-review" requests).
---

# Python code review (repo-wide)

Apply this skill to **every Python package and test tree in the repository**, not a single subdirectory.

---

## Default scope

Discover Python from the repo root. **Include** (when present):

| Path | Typical role |
|------|----------------|
| `src/` | Installable packages (e.g. `src/gmaps/`) |
| `tests/` | pytest suite |
| `benchmarks/` | Performance / regression harness |
| `scripts/` | CLI and maintenance scripts |
| `agents/` | Agent experiments and harness (optional) |
| `tools/` | Dev tooling |

**Exclude:** `.venv/`, `**/__pycache__/`, vendored third party, generated code unless the user asks.

If the user names a narrower scope (e.g. `src/gmaps/` only), honor it but note the reduced scope in `docs/CODEREVIEW.md`.

---

## Global rules to enforce

Cursor **skills do not auto-load** `.mdc` rule files. You must **read** the files in step 0 and record that in `docs/CODEREVIEW.md`.

Also read **project-local** rules when they exist: `.cursor/rules/*.mdc` (e.g. collaboration, project-specific security).

Tag findings as `<rule-id>/…` (see template below).

---

## Workflow

### 0. Load global standards (mandatory)

**Before** reviewing code, **read** these rule files from disk:

| Rule id | Read this file |
|---------|----------------|
| **clean-code** | `~/.cursor/rules/clean-code.mdc` |
| **security-standards** | `~/.cursor/rules/security-standards.mdc` |
| **python-standards** | `~/.cursor/rules/python-standards.mdc` |
| **python-tests** | `~/.cursor/rules/python-tests.mdc` |
| **fastapi-standards** | `~/.cursor/rules/fastapi-standards.mdc` (only if FastAPI routes exist under scope) |
| **collaboration** | `<repo>/.cursor/rules/collaboration.mdc`, else `~/.cursor/rules/` if duplicated |

In **`docs/CODEREVIEW.md`**, start with a **Global standards checklist** listing each file as **read** and bullet what you applied (type hints, docstrings, pytest, tenacity, secrets, logging). Mark **deferred** with reason (e.g. no FastAPI in repo).

Optional tooling (note pass/fail in checklist):

```bash
# Paths = discovered scope roots, space-separated
uv run ruff check src tests benchmarks scripts agents tools --statistics
uv run ruff format src tests benchmarks scripts agents tools --check --diff
```

If `ruff` is missing, say so and rely on manual review against **python-standards.mdc**.

### 1. Index the tree

Survey Python layout under scope. Document in **[`docs/REPOINDEX.md`](../../../docs/REPOINDEX.md)**:

- Package names, main modules, entrypoints (`__main__.py`, CLI in `pyproject.toml`)
- Test layout and how to run (`uv run pytest …`)
- Config/env (`.env-template`, settings modules)
- **Last review:** date + one-line delta since previous index

Create the file if missing; update on structural changes.

### 2. Optional: agents harness boundaries

**Only if** the repo has `agents/` **and**  
`.cursor/skills/agents-harness-conventions/scripts/agents_layout.sh`:

```bash
bash .cursor/skills/agents-harness-conventions/scripts/agents_layout.sh list
bash .cursor/skills/agents-harness-conventions/scripts/agents_layout.sh check-imports
```

Cross-experiment `*_core` imports → at least **high** severity (`agents/import-boundary/…`).

If the script or `agents/` is absent, skip this step and note **skipped** in the checklist.

Read **[`agents-harness-conventions`](../agents-harness-conventions/SKILL.md)** when reviewing qlab-style multi-experiment trees.

### 3. Review Python code

Review **all `.py` files in scope** against loaded global rules and project `.cursor/rules`.

**Prioritize:** public APIs, I/O boundaries (HTTP, Redis, DB), security-sensitive paths, `conftest.py`, and modules changed recently if the user pointed at a diff.

Minimum **python-standards** pass:

- Type hints on parameters and returns; prefer `X | None` over `Optional[X]`
- Google docstrings on public classes/functions (`Args` / `Returns` where non-obvious)
- Tests: pytest only; meaningful names; mock external services
- Error handling: no bare `except:`; narrow catches at boundaries; `logging.exception` where tracebacks help ops
- External I/O: **tenacity** (or equivalent) with explicit retriable exceptions — flag ad-hoc retry loops
- Validation: **Pydantic** where the codebase already uses it
- **security-standards:** no secrets in code/logs; env-based config

### 4. Write findings

Append or replace content in **[`docs/CODEREVIEW.md`](../../../docs/CODEREVIEW.md)**.

Use one `#` heading per source file (path from repo root). Group multiple issues under the same file.

**Entry template:**

```markdown
# path/from/repo/root/src/...

## Line XX: <rule-id>/<short title>
Correction urgency: xhigh | high | moderate | low

```python
# relevant snippet
```

<What is wrong and which rule it breaks.>

<Suggested correction — minimal diff preferred.>
```

**Rule id examples:**

| Id | Meaning |
|----|---------|
| `security-standards/…` | Secrets, `.env`, logging, TLS |
| `clean-code/…` | Naming, size, duplication |
| `python-standards/…` | Types, docstrings, ruff-style |
| `python-tests/…` | pytest layout, fixtures, isolation |
| `fastapi-standards/…` | Routers, schemas, DI |
| `agents/import-boundary/…` | Cross-experiment imports (when agents harness present) |
| `collaboration/…` | Process only when relevant |

**Urgency:**

- **xhigh** — silent failure, data leak, or security
- **high** — broken behavior or boundary violation
- **moderate** — maintenance debt
- **low** — stylistic

If **no violations**, write a dated summary stating clean review and listing scope paths.

### 5. Do not auto-fix

**Review-only** unless the user explicitly asks to implement fixes. Do not commit `docs/CODEREVIEW.md` unless the user asks.

---

## Scope reminders

- Default: **all project Python** under `src/`, `tests/`, `benchmarks/`, `scripts/`, `tools/`, `agents/`.
- Nested experiment scaffolding (qlab-style) is optional; use **agents-harness-conventions** only when that tree exists.
- Do not review unrelated repos unless the user specifies a path.
