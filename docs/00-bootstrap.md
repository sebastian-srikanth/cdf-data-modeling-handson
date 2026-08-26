# Chapter 00 — Bootstrap

**Goal:** go from "I only have Python and git" to a working Cognite Toolkit CLI that
can talk to `<your-cdf-project>`, with zero secrets in git.

You will not touch your own module yet — that's [Chapter 01](01-naming-isolation-and-setup.md).
This chapter only proves the tooling works. Every command below is given for
**macOS** and **Windows**; where a command is identical on both, it's shown once.

💡 `[GOOD TO KNOW]` — **Windows convention for this whole course:** use the **Git
Bash** terminal that ships with git for every command in every chapter, not
PowerShell/cmd. Git Bash gives you the same shell language as macOS Terminal, so
almost every command in this course is identical on both operating systems — the
handful of genuine exceptions (installers, mainly) are called out explicitly, like
the one PowerShell line in §0.4.

---

## 0.1 [INFO] Four ways to talk to CDF — and which one you're learning

| Layer | What it is | When you use it in this course |
|---|---|---|
| **UI** (Fusion) | The web app | Verifying every step visually |
| **REST API** | The actual HTTP surface everything else calls | Only for the [Document Parser API](10-datasheet-parsing.md) — it has no typed SDK method |
| **Python SDK** (`cognite-sdk`) | Typed Python client over the REST API | Notebooks and Function handlers |
| **Cognite Toolkit** (`cognite-toolkit`, CLI: `cdf`) | Infrastructure-as-code — YAML → `cdf build` → `cdf deploy` | Every deployable resource in your module |

The Toolkit does not replace the SDK — it *deploys the resources* (spaces, views,
transformations, functions, workflows…) that your SDK code and notebooks then *operate
on*. You will use both in this course, for different jobs.

📚 `[DOCS]` https://docs.cognite.com/cdf/deploy/cdf_toolkit/ (Toolkit hub) ·
https://docs.cognite.com/dev/sdks/python/ (Python SDK)

---

## 0.2 [ACTION] Get this repository onto your laptop

You have git already — you don't have a clone of this repository yet. Fix that now,
identical command on both OS, run inside Git Bash on Windows:

```bash
git clone https://github.com/sebastian-srikanth/cdf-data-modeling-handson.git
cd cdf-data-modeling-handson
```

Everything from here on assumes your terminal's current directory is the root of
this clone.

✅ `[VERIFY]` `git status` runs without error and shows you're on a branch.

⚠️ `[COMMON MISTAKE]` Downloading a ZIP of the repo from GitHub's web UI instead of
`git clone`. You need real git history and a real remote to open a PR later
([Chapter 14](14-pr-and-merge.md)) — a ZIP download gives you neither.

---

## 0.3 [INFO] The version you must use — and why it differs from other docs

This lab targets a specific Toolkit and Python version. Always trust the actual pin
files, not a prose doc — confirm them yourself:

🟢 `[ACTION]` From the repo root, confirm the real pin yourself:

```bash
grep -E "cognite-toolkit|requires-python" pyproject.toml
grep -A3 "\[modules\]" cdf.toml
grep function_runtime training/modules/reference/default.config.yaml
```

You should see:

```
cognite-toolkit==0.8.125
requires-python = ">=3.12,<3.14"
version = "0.8.125"
function_runtime: py311
```

⚠️ `[COMMON MISTAKE]` Three different Python versions appear in this one repo and they
mean three different things — do not conflate them:

| Python version | Where | Why |
|---|---|---|
| **3.12+** | Your local venv (`requires-python`) | What runs the Toolkit CLI on your laptop |
| **3.11** | `function_runtime: py311` in Cognite Functions | The *cloud* runtime your `handler.py` executes under — independent of your laptop's Python |
| — | — | Never assume the Function runtime matches your local interpreter; pin `requirements.txt` accordingly (see [Chapter 07](07-entity-matching.md) onward) |

---

## 0.4 [ACTION] Install `uv` and sync the repo's pinned dependencies

This repository already pins exact versions of `cognite-toolkit` and `cognite-sdk` in
`pyproject.toml` / `uv.lock`. You install **from those locks**, not from PyPI latest —
that's what makes "works on my machine" true for every participant at once.

```bash
# macOS (Terminal)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows (PowerShell — this one step only; then go back to Git Bash)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen your terminal (Git Bash on Windows) so `uv` is on your `PATH`, then
from the repo root:

```bash
uv sync
```

📚 `[DOCS]` https://docs.astral.sh/uv/getting-started/installation/

✅ `[VERIFY]`

```bash
uv run cdf --version
```

Expected output contains `0.8.125`. If you see a different version, you are not
running inside this repo's venv — re-run `uv sync` from the repo root.

💡 `[GOOD TO KNOW]` The generic Cognite docs show `pip install cognite-toolkit` or
`poetry add cognite-toolkit` for a brand-new project
(📚 https://docs.cognite.com/cdf/deploy/cdf_toolkit/guides/setup). You don't do that
here — this repo already exists and already pins a version. Installing the Toolkit
a second way (global pip, a different venv) is how people end up debugging a "works
for me, not for you" bug that's actually just two different Toolkit versions
producing slightly different `build/` output.

---

## 0.5 [INFO] `cdf.toml` — every key explained

This file already exists at the repo root. You do **not** create a new one and you do
**not** run `cdf repo init` (that command bootstraps a *brand-new* Toolkit repo — this
one already exists). Read it to understand what it's telling the CLI:

```toml
[cdf]
default_organization_dir = "training"
default_env = "REFERENCE-training"

[modules]
version = "0.8.125"

[plugins]
run = true
dump = true
data = true

[alpha_flags]
profile = true
streams = true
search-config = true
data_products = true
signals = true

[library.cognite]
url = "https://github.com/cognitedata/library/releases/download/latest/packages.zip"
checksum = "sha256:..."
```

| Key | Meaning |
|---|---|
| `default_organization_dir` | Which top-level folder holds your modules and configs — `training/` in this repo. `cdf build` looks here unless you pass `--organization-dir` |
| `default_env` | Which `config.<name>.yaml` to use when you omit `--config-yaml`. It points at the *reference* config, not yours. **You will always pass your own `--config-yaml training/config.<YOURNAME>-training.yaml` explicitly**, so this default never silently deploys the reference module over your work |
| `[modules].version` | The Toolkit modules-schema version. Managed by `cdf modules upgrade` — never hand-edit |
| `[plugins]` | Optional CLI subcommand families. `run` enables `cdf run function` / workflow execution helpers; `dump` enables `cdf dump` (pull resources from CDF into YAML); `data` enables `cdf data purge` (used in teardown, [Chapter 13](13-cross-cutting-mastery.md)) |
| `[alpha_flags]` | Feature-gated Toolkit capabilities still in alpha (search-config, data products, signals, streams, profiling). Irrelevant to this course — listed here because they're project-wide, not per-module |
| `[library.cognite]` | Where `cdf modules add`-style community/reference modules get pulled from. You will not use this in this course |

⚠️ `[COMMON MISTAKE]` Editing `cdf.toml` to add your own section "just for testing." It
is a **repo-wide** file — every config and every module in the repo reads it. Everything
you need to vary lives in your own `config.<YOURNAME>-training.yaml` instead.

📚 `[DOCS]` https://docs.cognite.com/cdf/deploy/cdf_toolkit/guides/usage

---

## 0.6 [ACTION] Auth — create your `.env` (no secrets in docs, no secrets in git)

Two identities exist in this lab and you will only fully understand the trap in
[Chapter 02](02-auth-and-security.md) — for now, just get logged in.

🟢 `[ACTION]`

```bash
cp .env.example .env
```

Then open the repo-root `.env` and replace **every** `<angle-bracket>` value with
one from your own CDF project and identity provider. `PREREQUISITES.md` at the repo
root explains where each value comes from and what access it needs. If someone set the
project up for you, they can hand you a filled-in `.env` instead.

```bash
CDF_CLUSTER=<your-cluster>
CDF_PROJECT=<your-cdf-project>
CDF_URL=https://<your-cluster>.cognitedata.com
PROVIDER=entra_id
LOGIN_FLOW=interactive

# Interactive public client — used by cdf build / deploy / clean / purge (no secret)
IDP_CLIENT_ID=<your-interactive-client-id>
IDP_TENANT_ID=<your-tenant-id>
IDP_SCOPES=https://<your-cluster>.cognitedata.com/.default
IDP_AUTHORITY_URL=https://login.microsoftonline.com/<your-tenant-id>

# Confidential SP — used ONLY in Transformation authentication: blocks
TRAINING_CDF_CLIENT_ID=<your-sp-client-id>
TRAINING_CDF_CLIENT_SECRET=<your-sp-client-secret>
```

⚠️ `[COMMON MISTAKE]` `.env` is already covered by `.gitignore` in this repo — but
that does not protect you from **pasting** the secret into a chat window, an issue, or
this document. `.gitignore` stops commits, not pastes. Never paste `TRAINING_CDF_CLIENT_SECRET` anywhere except your local `.env`.

✅ `[VERIFY]`

```bash
uv run cdf auth verify --dry-run
```

This confirms the **interactive** identity (`IDP_CLIENT_ID`) can reach
`<your-cdf-project>` and reports which capabilities/groups it holds. You are
not using the confidential SP here — that identity is never used for login, only
inside Transformations ([Chapter 02](02-auth-and-security.md)). `--dry-run` guarantees
the command **changes nothing** in CDF.

⚠️ `[COMMON MISTAKE]` **The warnings and the "update group?" prompt are expected — do
not let them abort you.** After the success lines (project config OK, project list
includes `<your-cdf-project>`, IdP OK), the command may warn that you are
*not a member of* `cognite_toolkit_service_principal` and that a capability such as
`subscribeSignalsAcl` is missing, then ask **"Do you want to update the group…?"**.
Answer **`n`**. You are a *participant* on interactive login — you are **not** the admin
of that shared Toolkit group and must not modify it, and this lab never uses
`subscribeSignalsAcl`. The step has **passed** if the block *above* the prompt reached
the training project and listed your capabilities; the prompt is an optional
group-reconcile offer, not a gate. (Do **not** use `--no-prompt` to silence it — that
flag makes the command *hard-fail* on any missing capability. Use `--dry-run` and
answer `n`.) Why your login is a different identity from that group:
[Chapter 02](02-auth-and-security.md) §2.3 and §2.5.

📚 `[DOCS]` https://docs.cognite.com/cdf/deploy/cdf_toolkit/guides/auth

---

## 0.7 [INFO] The organization directory and what `cdf build` actually does

`training/` is the **organization directory** (`default_organization_dir` in
`cdf.toml`). Inside it:

```
training/
├── config.<env>.yaml           # one per participant — yours: config.<YOURNAME>-training.yaml
└── modules/
    ├── reference/              # the finished answer key
    └── participants/<YOURNAME>/  # your module
```

`cdf build` reads your `config.<YOURNAME>-training.yaml`, walks every module path
listed under `selected:`, resolves `{{ variable }}` template substitutions, and writes
the resolved result into a local `build/` directory — the exact YAML/SQL/Python that
`cdf deploy` will send to CDF. Two mechanics worth understanding now, in detail once
you hit them for real:

- **`$FILEPATH`** in a `.CogniteFile.yaml` / `.FileMetadata.yaml` tells `cdf build` to
  copy a real binary (PDF, OBJ) alongside the resolved YAML into `build/` — see
  [Chapter 04](04-data-sets-raw-and-files.md).
- **`queryFile`** in a `.Transformation.yaml` points at a sibling `.sql` file; `cdf
  build` inlines it and resolves its own `{{ variable }}` placeholders — see
  [Chapter 05](05-transformations.md).

`build/` is disposable and gitignored — you never hand-edit it. If it looks wrong,
fix the source YAML and rebuild.

The core command set you'll use throughout this course:

| Command | What it does |
|---|---|
| `cdf build --config-yaml <path>` | Resolve templates → `build/` (no network calls) |
| `cdf deploy --cdf-project <p> --dry-run` | Show what *would* change in CDF, changes nothing |
| `cdf deploy --cdf-project <p>` | Apply the build to CDF |
| `cdf clean --cdf-project <p>` | Delete the resources listed in the current `build/` |
| `cdf data purge space <space>` | Manually-confirmed, destructive deletion of a space's instances (teardown only — [Chapter 13](13-cross-cutting-mastery.md)) |

✅ `[VERIFY]` — prove the CLI and the build machinery are wired, without touching your
own module yet:

```bash
uv run cdf build --help
```

You should see the `cdf build` options print. That confirms the Toolkit's build command
is installed and runnable.

⚠️ `[COMMON MISTAKE]` Trying to smoke-test by building the one config that *is*
committed, `training/config.REFERENCE-training.yaml`. That builds the **finished
reference implementation** — the answer key — not your work. Participant configs are
deliberately not committed (you author your own in
[Chapter 01](01-naming-isolation-and-setup.md) §1.5), so there is nothing here to "build
as a smoke test" yet — **your first real `cdf build` is
[Chapter 01](01-naming-isolation-and-setup.md) §1.6**, against the
`config.<YOURNAME>-training.yaml` you write. Don't block Chapter 00 waiting for a build
to pass, and don't peek at the reference before you've written your own.

💡 `[GOOD TO KNOW]` If your particular checkout *does* include an existing config, you
may optionally build it for a fuller smoke
test. A healthy result is the line **`Finished building. Built N modules`** — judge
success on that, not on the process exit code. In some local setups a networking error
(`[Errno 48] Address already in use`) prints *after* that line; that is a post-build
login-loopback collision from running `cdf` repeatedly, **not** a build failure — the
`build/` directory has already been produced. Never run `cdf deploy` against anyone
else's module — you have no reason to, and you have not been asked to.

---

## 0.8 [DOCS] Resource-type map — which YAML suffix means what

You will author most of these rows across this course. Bookmark this table.

| YAML suffix | CDF resource |
|---|---|
| `.Space.yaml` | Data modeling space |
| `.Container.yaml` | Container (storage contract) |
| `.View.yaml` | View (read/query contract) |
| `.DataModel.yaml` | Data model (published set of views) |
| `.DataSet.yaml` | Data set |
| `.Database.yaml` | RAW database |
| `.Table.yaml` (+ sibling `.csv`) | RAW table |
| `.CogniteFile.yaml` | Data-modeling-native file (DMS instance) |
| `.FileMetadata.yaml` | Classic file (no DMS instance) |
| `.Transformation.yaml` (+ sibling `.sql`) | Transformation |
| `.Function.yaml` (+ `handler.py`, `requirements.txt`) | Cognite Function |
| `.Workflow.yaml` | Workflow |
| `.WorkflowVersion.yaml` | Workflow version (the task DAG) |
| `.LocationFilter.yaml` | Location filter |

📚 `[DOCS]` full reference: https://docs.cognite.com/cdf/deploy/cdf_toolkit/references/resource_library

---

## Gate

**Do not proceed to Chapter 01 until:**

- `git --version` works and you're inside your own clone of this repository
- `uv run cdf --version` prints `0.8.125`
- `uv run cdf auth verify --dry-run` reached `<your-cdf-project>` and listed
  your capabilities (the block *above* the group-update prompt — answering `n` to
  "update the group?" and the `subscribeSignalsAcl` warning are both expected)
- `uv run cdf build --help` runs — you understand there is **no committed root config to
  build here yet**, and your first real build is [Chapter 01](01-naming-isolation-and-setup.md) §1.6
- You can explain, in one sentence, the difference between the Toolkit and the SDK
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 01 — Naming, isolation & your module](01-naming-isolation-and-setup.md)
