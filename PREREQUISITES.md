# Prerequisites

Read this before Chapter 00. It is the honest list of what you need — this course
runs real jobs against a real CDF project, and "I have a CDF login" is **not**
enough on its own.

---

## 1. On your laptop

| Requirement | Notes |
|---|---|
| **Python 3.12 or 3.13** | The Toolkit CLI runs on this. Not the same as the Function runtime — see Chapter 00 §0.3 |
| **git** | You need real history and a real remote for Chapter 14 |
| **A terminal** | macOS: Terminal. Windows: **Git Bash** (ships with git) — not PowerShell/cmd |
| **A browser** | Every `[VERIFY]` step is confirmed visually in CDF Fusion |

`uv` is installed in Chapter 00 §0.4 — you do not need it beforehand.

---

## 2. A CDF project you can write to

You need the project name and its cluster:

```
CDF_PROJECT   e.g. my-company-dev
CDF_CLUSTER   e.g. westeurope-1, api, az-eastus-1
CDF_URL       https://<cluster>.cognitedata.com
```

> ⚠️ A **private-link** project uses a different host (e.g. `https://p001.plink.<cluster>.cognitedata.com`).
> Ask whoever administers the project which URL applies.

**Use a development or sandbox project.** The course creates spaces, data models,
RAW databases, files, transformations, Cognite Functions, 3D revisions, and time
series. Chapter 15 tears them all down again, but you should not be doing any of
this in production.

---

## 3. Two identities — and the access each one needs

Chapter 02 explains *why* there are two. What you need to obtain is:

### 3a. An interactive (public) client — this is you, in a browser

Used by `cdf build` / `deploy` / `clean` / `purge`.

- Must be registered with redirect URI **`http://localhost:53000`**
- On Entra ID this is an app registration with a *public client* / *mobile & desktop*
  platform configuration
- You sign in as yourself; no secret involved

### 3b. A confidential service principal — client ID **and secret**

Used **only** inside the `authentication:` block of a transformation, so
transformations can run unattended after your browser token expires.

This is the single secret in the entire course. If you cannot create a service
principal in your identity provider, or have one created for you, **Chapter 05
onward will not work** — a transformation with no unattended identity cannot run.

### 3c. CDF capabilities (ACLs) both identities need

Grant these to the CDF group(s) backing both identities. Each is used by a specific
chapter; missing one produces a `403` at that point and nowhere earlier.

| Capability | Actions | Needed by |
|---|---|---|
| `dataModelsAcl` | READ, WRITE | Ch 03 — spaces, containers, views, data models |
| `dataModelInstancesAcl` | READ, WRITE | Ch 05, 08, 10 — writing nodes and edges |
| `rawAcl` | READ, WRITE | Ch 04, 05 — RAW db/tables |
| `filesAcl` | READ, WRITE | Ch 04, 10 — PID / datasheet / 3D uploads |
| `datasetsAcl` | READ, WRITE | Ch 04 — the training data set |
| `transformationsAcl` | READ, WRITE | Ch 05 — deploy and run four transformations |
| `timeSeriesAcl` | READ, WRITE | Ch 11 — vibration / flow datapoints |
| `functionsAcl` | READ, WRITE | Ch 07–11 — five Cognite Functions |
| `entitymatchingAcl` | READ, WRITE | Ch 07 — `fit` / `predict`, **and deleting your model** |
| `diagramParsingAcl` | READ, WRITE | Ch 08 — submit `diagrams.detect` and poll it |
| `annotationsAcl` | READ, WRITE | Ch 08 — write and read annotation edges |
| `threedAcl` | READ, WRITE | Ch 09 — create and process the 3D revision |
| `workflowOrchestrationAcl` | READ, WRITE | Ch 12 — deploy and trigger the workflow |
| `locationFiltersAcl` | READ, WRITE | Ch 06 — your scoped view of the graph |
| `projectsAcl` | READ (LIST) | `cdf auth verify` reporting your own groups |

⚠️ An ACL is `(actions, scope)`, not a yes/no switch. `dataModelInstancesAcl.WRITE`
scoped to the wrong space fails exactly like not having it at all. If you scope
rather than grant `all`, the scopes must cover the spaces, data sets, and RAW
databases your `YOURNAME` produces (Chapter 01 tells you what those are named).

Verify what you actually hold before Chapter 03:

```bash
uv run cdf auth verify --dry-run
```

Read the capability list it prints. That report — not the exit code — is the answer.

---

## 4. Optional and preview capabilities

Two chapters depend on things that may not be enabled on an arbitrary project:

| Chapter | Depends on | If unavailable |
|---|---|---|
| **10 — Datasheet parsing** | **Document Parser API**, a Cognite **public-preview / Early-Adopter** capability | The chapter's *second* technique fails. The first (regex) still works and upserts the same node — do that one and read the rest |
| **09 — 3D** | 3D model processing enabled on the project | Skip the chapter; nothing later in the course depends on the 3D revision existing |

Check the current Cognite documentation for the Document Parser API's status before
relying on it — preview features change.

Everything else in the course uses generally-available CDF functionality.

---

## 5. Sanity check before you start

```bash
git clone https://github.com/sebastian-srikanth/cdf-data-modeling-handson.git
cd cdf-data-modeling-handson
cp .env.example .env
# ...fill in every <angle-bracket> value...
uv sync
uv run cdf --version        # expect 0.8.125
uv run cdf auth verify --dry-run
```

If `auth verify` reaches your project and lists capabilities that cover the table in
§3c, you are ready for [Chapter 00](docs/00-bootstrap.md).
