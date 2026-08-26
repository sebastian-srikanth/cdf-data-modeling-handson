# Chapter 02 — Auth & Security

**Goal:** understand the two identities this lab uses and *why* they exist, memorize
the one trap that takes down almost every first-time Toolkit user, wire up the `.env`
that feeds both, prove your own login works *before* you waste an hour, and know
exactly which permissions bite at which step.

No lab resources to write in this chapter — but this is the chapter that prevents you
from losing an afternoon to a "permissions" error that isn't actually about
permissions. Read it slowly. Auth is where confident people lose the most time.

---

## 2.1 [INFO] Two identities, one trap

CDF never trusts "a person" or "a script" — it trusts an **identity** that presents a
short-lived access token minted by your identity provider (here, Microsoft Entra ID).
This lab uses **two** of them, and they are not interchangeable.


| Identity                                                                                     | OAuth flow                                                                      | Used for                                                                                                                                                                               | Has a secret?                                                                               |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **Interactive user login** (`IDP_CLIENT_ID`, `LOGIN_FLOW=interactive`)                       | Authorization-code / device-code — *you* prove who you are in a browser         | Running the Toolkit CLI (`cdf build`, `cdf deploy`, `cdf clean`, `cdf data purge`, `cdf auth verify`) **and** every SDK call you make in a notebook                                    | **No** — it's a *public* client. It cannot hold a secret; it gets a token by you logging in |
| **Confidential service principal** (`TRAINING_CDF_CLIENT_ID` / `TRAINING_CDF_CLIENT_SECRET`) | Client-credentials — the *app* proves who it is with a secret, no human present | **Only** inside a Transformation's `authentication:` block, so the transformation can run unattended (on a schedule, or triggered by a workflow) long after your browser token expired | **Yes** — a client secret. Never used for interactive login                                 |


💡 `[GOOD TO KNOW]` **Why can't one identity do both?** A public client (interactive)
*cannot safely hold a secret* — it runs on your laptop, in a browser, in places a
secret would leak from. So it authenticates by making a human log in. That's perfect
for you driving the CLI, and useless for a transformation that must run at 03:00 with
nobody watching. A confidential client (the SP) *can* hold a secret because it only
ever runs server-side inside CDF — so it's the right identity for unattended jobs, and
the wrong identity to hand a human CLI. Two jobs, two identities. This is not a CDF
quirk; it's how OAuth 2.0 separates public from confidential clients everywhere.

### ⚠️ 🔒 The headline trap — `[COMMON MISTAKE]` / `[SECURITY]`

This single mistake accounts for more lost lab time than everything else combined:

```yaml
# WRONG — deploys fine, fails at runtime
authentication:
  clientId: ${IDP_CLIENT_ID}          # ← your interactive login client
  clientSecret: ${IDP_CLIENT_SECRET}  # ← doesn't even exist — a public client has no secret
```

If you put your **interactive** client ID into a Transformation's `authentication:`
block, `cdf deploy` will **succeed**. The Toolkit validates YAML *shape* at deploy
time, not that the credential actually works when the job runs. The failure surfaces
much later — when the transformation *executes* — and it is disguised:

```
Authentication error / insufficient access
```

That message screams "permissions." It is lying. It is a **wrong-identity** problem:
you configured a public interactive client (which has no secret and is not meant to run
unattended) where a confidential service principal belongs. No amount of ACL-granting
will fix it, because the credential itself can't authenticate.

The fix is always the same — use the SP:

```yaml
# RIGHT — the exact block you'll write for real in Chapter 05
authentication:
  clientId: ${TRAINING_CDF_CLIENT_ID}
  clientSecret: ${TRAINING_CDF_CLIENT_SECRET}
  tokenUri: ${IDP_TOKEN_URL}
  cdfProjectName: ${CDF_PROJECT}
  scopes: ${IDP_SCOPES}
```

✅ `[VERIFY]` **How to diagnose it in 30 seconds.** The `${...}` variables are resolved
into literal values at **build** time, so the built artefact tells you the truth. After
`cdf build`, open the generated transformation under `build/` and read the resolved
`authentication.clientId`:

```bash
grep -A6 'authentication:' build/transformations/tra_*Load_Assets*.yaml
```

If the resolved `clientId` is your interactive client (`IDP_CLIENT_ID`'s value), that's
your bug — before it ever reaches runtime. If it's the SP's client id, you're clean.

You'll write the correct block for real in [Chapter 05](05-transformations.md). Bookmark
this section — come back the instant any transformation run fails with an auth-shaped
error.

---



## 2.2 [ACTION] The `.env` that feeds both identities

Both identities are configured in **one** repo-root `.env` file, created from the
provided `.env.example`. `${VAR}` references in your YAML resolve against it at build
time; the Toolkit also reads it to log you in.

🟢 `[ACTION]` From the repo root:

```bash
cp .env.example .env
# then open .env and fill in every <angle-bracket> value (see PREREQUISITES.md)
```

Here is every variable and *which identity it belongs to* — this mapping is the whole
point:

```bash
# ── Shared: which project, which cluster ──────────────────────────────
CDF_CLUSTER=<your-cluster>
CDF_PROJECT=<your-cdf-project>
CDF_URL=https://<your-cluster>.cognitedata.com
PROVIDER=entra_id            # identity provider family (Entra ID / Azure AD)
LOGIN_FLOW=interactive       # ← tells the Toolkit to log YOU in via browser

# ── Identity 1: interactive PUBLIC client (runs the Toolkit + your SDK) ─
IDP_CLIENT_ID=<your-interactive-client-id>   # public app registration
IDP_TENANT_ID=<your-tenant-id>
IDP_SCOPES=https://<your-cluster>.cognitedata.com/.default
IDP_AUTHORITY_URL=https://login.microsoftonline.com/<your-tenant-id>
# IDP_TOKEN_URL is DERIVED — see the [COMMON MISTAKE] below
IDP_TOKEN_URL=${IDP_AUTHORITY_URL}/oauth2/v2.0/token

# ── Identity 2: confidential SP (only inside Transformation auth blocks) ─
TRAINING_CDF_CLIENT_ID=<your-sp-client-id>
TRAINING_CDF_CLIENT_SECRET=<your-sp-client-secret>   # the ONLY secret in this lab
```

⚠️ `[COMMON MISTAKE]` `IDP_TOKEN_URL` **is derived, not given.** In `.env.example` it is
a *comment* (`# Derive: IDP_TOKEN_URL=...`). The transformation `authentication:` block
references `${IDP_TOKEN_URL}` — if you never actually set it in `.env`, the variable
resolves to empty and your transformation authenticates against `""`. Set it explicitly
(as shown above) or export it. It is `${IDP_AUTHORITY_URL}/oauth2/v2.0/token`.

💡 `[GOOD TO KNOW]` **Notice both identities share the same** `IDP_SCOPES`
**(**`.../.default`**) and token endpoint.** They differ only in *client id* and *whether a
secret is present*. That's exactly why the trap in §2.1 is so easy to fall into — the
two blocks look almost identical. The client id is the tell.

📚 `[DOCS]`

- Toolkit auth & `.env`: [https://docs.cognite.com/cdf/deploy/cdf_toolkit/references/configs](https://docs.cognite.com/cdf/deploy/cdf_toolkit/references/configs)
- OAuth client credentials vs interactive: [https://docs.cognite.com/cdf/access/concepts/authentication](https://docs.cognite.com/cdf/access/concepts/authentication)

---



## 2.3 [VERIFY] Prove your own login works *before* you build anything

The single best habit in this whole course: verify your identity resolves *before* you
spend twenty minutes authoring YAML. The Toolkit has a purpose-built command.

🟢 `[ACTION]`

```bash
uv run cdf auth verify --dry-run
```

Use `--dry-run` — it inspects and reports but **changes nothing** in CDF. That matters
because of the prompt described below.

✅ `[VERIFY]` A healthy run:

- opens a browser (or prints a device-code URL) for your **interactive** login,
- confirms it reached `<your-cdf-project>`,
- prints the **groups and capabilities** your login actually has.

Read that capability list. It is *your* identity's — **not** the SP's from §2.4. If a
capability the lab needs is missing here, you will hit a `403` later on a job call
(entity matching, diagram detect, doc parser) even though the transformation — which
runs as the SP — works fine. Catch it now (§2.5), and don't lose an hour to it in
Chapter 07.

### ⚠️ The "update group?" prompt and the two warnings — expected, not a failure

`cdf auth verify` does **two** jobs: it verifies your login (what you care about), and
it offers to *reconcile the shared Toolkit access group* `cognite_toolkit_service_principal`
(an admin action you should decline). As a participant on interactive login you will
almost always see this tail after the success lines:

```
WARNING: client is not a member of cognite_toolkit_service_principal
WARNING: missing subscribeSignalsAcl READ/WRITE
Do you want to update the group ...?  [y/N]
```

⚠️ `[COMMON MISTAKE]` Treating this as a `FAIL`. It is not. **Answer** `n`**.** Here's why
each line is benign for you:

- *"not a member of* `cognite_toolkit_service_principal`*"* — correct. You log in as
**yourself** (interactive), isolated by your own participant group + your own space
([Chapter 01](01-naming-isolation-and-setup.md)). You are not, and should not be, a
member of the named Toolkit **service-principal** group. Membership in it is not what
authorizes your lab work — your group's capabilities are (§2.4).
- *"missing* `subscribeSignalsAcl`*"* — this lab never uses signal subscriptions. The
capability is irrelevant to every step you'll do. Ignore it.
- *"Do you want to update the group?"* — this offers to **mutate a shared admin group**.
A participant must never accept it. `--dry-run` already blocks any change; answering
`n` is belt-and-braces.

**The pass condition is the block *above* the prompt**, not a zero exit code: it reached
`<your-cdf-project>` and listed your capabilities. If you see that, this step
passed — proceed.

⚠️ `[COMMON MISTAKE]` Reaching for `--no-prompt` to make it non-interactive. That flag
makes the command **hard-fail (exit 1)** the moment *any* expected capability is missing
— including the benign `subscribeSignalsAcl` — so it turns a healthy check into a red
one. For an unattended/CI run, use `--dry-run` and answer `n` (or feed `n` on stdin),
and judge success by the capability report, not the exit codif a job 403s, your login group may lack capabilitiese.

💡 `[GOOD TO KNOW]` "It authenticated, so I'm fine" is the wrong lesson. Authentication
proves *who you are*; it says nothing about *what you're allowed to do*. `cdf auth verify` shows both — read the capabilities, not just the green checkmark or the exit
code.

---



## 2.4 [INFO] The permissions that actually bite — and where

The confidential SP (`TRAINING_CDF_CLIENT_ID`) holds a broad set of capabilities. The
subset that matters for this lab:

```
dataModelsAcl            dataModelInstancesAcl     filesAcl
threedAcl                timeSeriesAcl             transformationsAcl
functionsAcl             workflowOrchestrationAcl  entitymatchingAcl
diagramParsingAcl        annotationsAcl            datasetsAcl
rawAcl                   locationFiltersAcl
```

💡 `[GOOD TO KNOW]` **An ACL is not a yes/no switch — it is** `(actions, scope)`**.** Each
capability grants specific *actions* (`READ`, `WRITE`, sometimes more) over a specific
*scope* (`all`, or narrowed to certain data sets / spaces / RAW tables). Two failure
modes follow from this, and both look like "permission denied":

- **Wrong action:** you hold `READ` but the step needs `WRITE` (e.g. deploying a data
model, upserting an instance).
- **Wrong scope:** you hold `dataModelInstancesAcl.WRITE` but scoped to *some other*
space, and you try to write into `isp_<YOURNAME>_TRN`. In production this is the
#1 auth gotcha. In this lab the SP is scoped broadly enough that you won't hit it —
but *know it exists*, because the day you leave the lab it will find you.



### The bite table — which permission each lab step needs


| Capability                                    | Lab step that needs it                                                                                                                                              | What the failure looks like if it's missing/underscoped                      |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `dataModelsAcl` (WRITE)                       | Deploy spaces, containers, views, data models — [Ch 03](03-data-modeling.md)                                                                                        | `cdf deploy` 403 on the data-modeling resources                              |
| `dataModelInstancesAcl` (WRITE, space-scoped) | Transformations writing nodes ([Ch 05](05-transformations.md)); EHP upsert ([Ch 10](10-datasheet-parsing.md)); annotation edges ([Ch 08](08-diagram-annotation.md)) | `instances.apply` 403 — silent-looking, surfaces at run time                 |
| `rawAcl` (WRITE)                              | Create RAW db/tables + read them in transformations — [Ch 04](04-data-sets-raw-and-files.md)/[05](05-transformations.md)                                            | RAW upload or transformation source read fails                               |
| `filesAcl` (WRITE + READ)                     | Upload PID/datasheet/3D bytes ([Ch 04](04-data-sets-raw-and-files.md)); doc parser reads the file ([Ch 10](10-datasheet-parsing.md))                                | file upload fails; or doc-parser job can't read the source                   |
| `datasetsAcl` (WRITE)                         | Create the training data set — [Ch 04](04-data-sets-raw-and-files.md)                                                                                               | data set create 403                                                          |
| `transformationsAcl` (WRITE)                  | Deploy + run the four transformations — [Ch 05](05-transformations.md)                                                                                              | deploy or manual run 403                                                     |
| `timeSeriesAcl` (WRITE)                       | `GenerateDatapoints` writes the vibration/flow series — [Ch 11](11-datapoints.md)                                                                                   | datapoint write 403                                                          |
| `functionsAcl` (WRITE)                        | Deploy + call all five Functions — [Ch 07](07-entity-matching.md)–[11](11-datapoints.md)                                                                            | function deploy or call 403                                                  |
| `entitymatchingAcl` (WRITE)                   | `fit` / `predict` **and deleting your model** — [Ch 07](07-entity-matching.md)                                                                                      | job 403; or you can't clean up (models are global — you *must* delete yours) |
| `diagramParsingAcl`                           | Submit `diagrams.detect` **and poll its status** — [Ch 08](08-diagram-annotation.md)                                                                                | detect submit 403, or status poll 403 mid-job                                |
| `annotationsAcl` (WRITE + READ)               | Write `CogniteDiagramAnnotation` edges + read detect results — [Ch 08](08-diagram-annotation.md)                                                                    | annotations don't persist, or detect result read fails                       |
| Document Parser = Data Models (R+W) + Files (R) | Start/read a parse job needs Data Models **read** + Files **read**; approve/persist the result needs Data Models **write** — [Ch 10](10-datasheet-parsing.md) (public preview) | doc-parser start or write returns 403 |
| `threedAcl` (WRITE)                           | Create + process the 3D revision — [Ch 09](09-3d.md)                                                                                                                | revision create/process 403                                                  |
| `workflowOrchestrationAcl` (WRITE)            | Deploy + run the workflow — [Ch 12](12-workflows.md)                                                                                                                | workflow deploy or trigger 403                                               |
| `locationFiltersAcl` (WRITE)                  | Deploy your "only my graph" filter — [Ch 06](06-location-filters.md)                                                                                                | location filter deploy 403                                                   |


⚠️ `[COMMON MISTAKE]` **Diagram detect needs *two* ACLs, not one.** The job runs under
`diagramParsingAcl`, but the annotations it produces (and the reads you do to *poll*
progress) need `annotationsAcl`. Missing the second one gives you a job that submits
happily and then appears to "do nothing" — a classic Chapter 08 head-scratcher.

### ⚠️ Document Parser capabilities (public preview)

The Document Parser you use in [Chapter 10](10-datasheet-parsing.md) is a Cognite
**public-preview / Early-Adopter** feature and may change. Per Cognite's capability
documentation, its access is granted through capabilities you already use elsewhere in
this lab: **Data Models read** (start a parse job, read results), **Data Models write**
(approve and persist a result into a data-model instance), and **Files read** (read the
source document). Grant those three — there is no separate "document parser" ACL to
hunt for.

📚 `[DOCS]` Access control & capabilities:
[docs.cognite.com/cdf/access](https://docs.cognite.com/cdf/access/) · Document Parser:
[Parse documents](https://docs.cognite.com/cdf/integration/guides/contextualization/parse_documents/)

---



## 2.5 [COMMON MISTAKE] "It works in the transformation but 403s in my notebook"

Your interactive login (§2.3) is a *different identity* from the confidential SP in
§2.4. The SP runs your transformations; **you** run every SDK call in the notebooks
([Ch 07](07-entity-matching.md) onward) and every "call this function once" click in
the UI. So a job-based call can `403` in your notebook even though the equivalent runs
fine inside a transformation:

> "The transformation loaded fine, but when I run the same detect call myself in the
> notebook, I get 403."

That is **not** a bug — it's two identities with two capability sets. The transformation
ran as the **SP** (which holds the capability); the notebook ran as **you** (whose login
may not). If you hit it, your login is missing a capability the call needs — commonly
`entitymatchingAcl`, `diagramParsingAcl` + `annotationsAcl`, `functionsAcl`, `filesAcl`,
or `dataModelInstancesAcl`. Run `cdf auth verify` (§2.3) to see what your login holds,
then ask your CDF administrator to grant the missing capability.

---



## 2.6 [SECURITY] Secrets discipline

🔒 `[SECURITY]` — first-class, not an afterthought:

- **One secret exists in this entire lab:** `TRAINING_CDF_CLIENT_SECRET`. It lives in
`.env` and **nowhere else** — never in Slack, chat, a notebook cell, a commit, a
screenshot, or this documentation.
- `.env` **is git-ignored.** Confirm it: `git check-ignore .env` should print `.env`.
If it doesn't, stop and fix your `.gitignore` before you commit anything.
- `gitleaks` **(pre-commit) scans *commits*, not your life.** It catches a secret you
try to *commit* — it does **not** scan clipboard history, chat messages, or a secret
you paste into a shared doc. It's a backstop, not a substitute for discipline.
- **Never echo it.** `cat .env`, `env | grep SECRET`, or printing it in a notebook can
land the secret in your terminal scrollback, shell history, or a saved `.ipynb`
output. If you must check it's set, test the *effect* (`cdf auth verify`, a
transformation run), not the *value*.
- **Least privilege is a mindset, not a lab step.** The SP's capabilities are what
*this training project* needs — they are not a template to copy into other projects
"to be safe." When you leave the lab, grant the *minimum* actions and the *narrowest*
scope a job needs, and widen only when something concretely fails.
- **If a secret ever leaks, it's rotated, not hidden.** Deleting the message/commit
does not un-leak it. Rotate the SP secret in your identity provider immediately so it can be
rotated. (This won't happen if you keep it in `.env`.)

📚 `[DOCS]` Managing secrets & least privilege: [https://docs.cognite.com/cdf/access/](https://docs.cognite.com/cdf/access/)

---



## Gate

**Do not proceed to Chapter 03 until you can answer, without looking back:**

- Which identity runs `cdf deploy`? Does it have a secret, and *why not / why*?
- Which identity goes inside a Transformation's `authentication:` block, and why must
it be the confidential one?
- When someone swaps them by mistake, is it a **deploy-time** error or a **runtime**
error — and how do you catch it in `build/` before it ever runs?
- `cdf auth verify` shows *your* capabilities or the *SP's*? Why does that distinction
cause the "works in the transformation but 403s in my notebook" confusion?
- Diagram detect needs which **two** ACLs? Which capabilities does the Document Parser
  (public preview) require?
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 03 — Data Modeling](03-data-modeling.md)
