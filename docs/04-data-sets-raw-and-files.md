# Chapter 04 — Data Sets, RAW & Files

**Goal:** land the raw source data (as a real extractor would) and the source
documents (P&ID, datasheet, 3D geometry) into CDF, governed by a data set.

---

## 4.1 [INFO] Why a data set, and its archive reality

A **data set** groups resources for governance: provenance ("where did this come
from"), access scoping, and lifecycle tracking. Several resources you deploy — the
transformations ([Chapter 05](05-transformations.md)) and the classic `FileMetadata`
for the 3D OBJ — reference `dts_<YOURNAME>_Training_TRN` through a `dataSetExternalId:`
field. **Two things are governed differently and carry no `dataSetExternalId` — that's
expected, not an omission:** RAW tables live inside your RAW *database*, and DMS-native
`CogniteFile` instances (the two PDFs) are scoped by your **space** (§4.4).

⚠️ `[COMMON MISTAKE]` Assuming you can delete a data set in teardown. **You can't —
CDF has no hard delete for data sets.** The best you can do is *archive* it (if your
ACL allows), which is why [teardown](15-teardown.md) treats "data set still present but
archived" as an acceptable end state, not a failure.

---

## 4.2 [INFO] Why RAW, and the CSV contract

RAW is CDF's staging area for **unmodified** source data — exactly what an extractor
would land before anything reshapes it. You're hand-authoring CSVs here to *simulate*
what an SAP/PI/NPDMS extractor would produce; the shape (one row per source record,
source-system column names) is deliberate practice for reading real extractor output
later.

📚 `[DOCS]` https://docs.cognite.com/cdf/dm/ · pattern reference: RAW is for staging,
Transformations (next chapter) are for reshaping into the model — never confuse a
Transformation with a general-purpose app runtime, and never skip RAW to reshape
inline from a source system.

⚠️ `[COMMON MISTAKE]` Naming a table file anything other than `*.Table.csv` /
`*.Table.yaml`. The `.Table.` segment in the filename is how the Toolkit recognizes it
as a RAW table upload — get the suffix wrong and the CSV silently doesn't upload.

### The four tables you'll load — exactly as they exist in this training story

**Assets** (hierarchy: FPSO → Area → System → Tag):

```csv
key,assetExternalId,name,description,parentExternalId,assetClass,level
TRN-FPSO,TRN-FPSO,TRN FPSO,Training FPSO - floating production storage and offloading unit,,Site,1
TRN-21,TRN-21,Area 21 - Separation,Process area 21 hosting first-stage separation,TRN-FPSO,Area,2
TRN-21-SEP,TRN-21-SEP,Separation System,First-stage crude separation and export system,TRN-21,System,3
21-VG-2001,21-VG-2001,21-VG-2001,First-stage three-phase separator,TRN-21-SEP,Tag,4
21-PA-2001A,21-PA-2001A,21-PA-2001A,Crude oil export pump A,TRN-21-SEP,Tag,4
21-PA-2001B,21-PA-2001B,21-PA-2001B,Crude oil export pump B (installed spare),TRN-21-SEP,Tag,4
21-HA-2001,21-HA-2001,21-HA-2001,Crude heater / shell-and-tube heat exchanger,TRN-21-SEP,Tag,4
21-XV-2001,21-XV-2001,21-XV-2001,Emergency shutdown valve on separator outlet,TRN-21-SEP,Tag,4
```

Note row 1: `parentExternalId` is **empty** for the root `TRN-FPSO`. This is
deliberate, real-world-shaped messiness, not a bug — see §4.5 and
[Chapter 05](05-transformations.md).

**Equipment** (5 physical items, each installed on a tag):

```csv
key,equipmentExternalId,name,description,tagExternalId,equipmentType,manufacturer,serialNumber
EQ-1001,EQ-1001,Separator V-2001,Three-phase horizontal separator,21-VG-2001,Vessel,Sulzer,SN-VG-77120
EQ-1002,EQ-1002,Export Pump A,Centrifugal crude oil export pump,21-PA-2001A,Pump,Flowserve,SN-PA-44821
EQ-1003,EQ-1003,Export Pump B,Centrifugal crude oil export pump (spare),21-PA-2001B,Pump,Flowserve,SN-PA-44822
EQ-1004,EQ-1004,Crude Heater E-2001,Shell and tube heat exchanger,21-HA-2001,HeatExchanger,Alfa Laval,SN-HA-31009
EQ-1005,EQ-1005,ESD Valve XV-2001,Fail-safe close emergency shutdown valve,21-XV-2001,Valve,Emerson,SN-XV-90233
```

**TimeSeries** (6 sensors — note which two carry the "aha" story):

```csv
key,tsExternalId,name,description,tagExternalId,sourceUnit,measurementType,isStep
21-PT-2001,21-PT-2001,21-PT-2001,Separator operating pressure,21-VG-2001,barg,Pressure,false
21-TT-2001,21-TT-2001,21-TT-2001,Separator outlet temperature,21-VG-2001,degC,Temperature,false
21-LT-2001,21-LT-2001,21-LT-2001,Separator oil interface level,21-VG-2001,%,Level,false
21-FT-2002,21-FT-2002,21-FT-2002,Export pump A discharge flow,21-PA-2001A,m3/h,Flow,false
21-VT-2002,21-VT-2002,21-VT-2002,Export pump A bearing vibration,21-PA-2001A,mm/s,Vibration,false
21-PT-2003,21-PT-2003,21-PT-2003,Export pump A discharge pressure,21-PA-2001A,barg,Pressure,false
```

`21-VT-2002` (vibration, ramping up) and `21-FT-2002` (flow, falling) on pump
`21-PA-2001A` are the two series [Chapter 11](11-datapoints.md) will animate into the
actual degradation story.

**WorkOrders** (3 SAP-shaped work orders):

```csv
key,workOrderNumber,title,description,status,orderType,priority,tagExternalId,plannedStart,plannedEnd,actualCost,currency
WO-1001,WO-1001,Replace mechanical seal on 21-PA-2001A,Rising bearing vibration and falling discharge flow indicate mechanical seal wear on export pump A.,IN_PROGRESS,PM02,1,21-PA-2001A,2026-07-20T06:00:00,2026-07-21T18:00:00,18500,EUR
WO-1002,WO-1002,Calibrate pressure transmitter 21-PT-2001,Annual calibration of the separator pressure transmitter.,OPEN,PM01,3,21-VG-2001,2026-08-03T08:00:00,2026-08-03T12:00:00,,EUR
WO-1003,WO-1003,Internal inspection of separator 21-VG-2001,Scheduled internal inspection during the planned shutdown window.,CLOSED,PM01,2,21-VG-2001,2026-06-10T06:00:00,2026-06-12T18:00:00,42000,EUR
```

Note `WO-1002`'s `actualCost` is **empty** — also deliberate, see §4.5.

---

## 4.3 [WRITE] RAW database + tables

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/raw/rwd_<YOURNAME>_Training_TRN.Database.yaml`

```yaml
dbName: rwd_<YOURNAME>_Training_TRN
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/raw/rwt_Training_TRN_Assets.Table.yaml`
(unscoped filename — see the `[COMMON MISTAKE]` below)

```yaml
dbName: rwd_<YOURNAME>_Training_TRN
tableName: rwt_Training_TRN_Assets
```

📝 `[WRITE]` the sibling CSV **with the byte-identical basename**,
`participants/<YOURNAME>/raw/rwt_Training_TRN_Assets.Table.csv` — content from the
**Assets** block in §4.2.

📝 `[WRITE]` repeat the same `.Table.yaml` / `.Table.csv` pair for
`rwt_Training_TRN_Equipment`, `rwt_Training_TRN_TimeSeries`, and
`rwt_Training_TRN_WorkOrders`, using the CSV blocks in §4.2. Each `.Table.yaml` has
the same shape:

```yaml
dbName: rwd_<YOURNAME>_Training_TRN
tableName: rwt_Training_TRN_<Suffix>
```

🛑 `[COMMON MISTAKE]` — **the `.Table.yaml` and its `.Table.csv` MUST share the exact
same basename**, differing only in extension (`rwt_Training_TRN_Assets.Table.yaml` ↔
`rwt_Training_TRN_Assets.Table.csv`). That pairing is how `cdf build` attaches the rows
to the table declaration. A `YOURNAME`-scoped YAML next to an unscoped CSV does **not**
pair: the Toolkit stages **only the YAML**, the table deploys **empty**, and your §4.6
row counts come back `0`. Keep **both** raw-table filenames unscoped (as the reference
does) and identical to each other — the table is namespaced by your scoped *database*,
not by its filename.

🔧 `[CHANGE]` Only `dbName:` (your RAW database — scoped, per §1.2). `tableName:`, both
raw-table **filenames**, and every CSV row stay literal and identical across
participants.

⚠️ `[COMMON MISTAKE]` Scoping `tableName` — or the table *filename* — with `<YOURNAME>`
(`rwt_<YOURNAME>_Training_TRN_Assets`). The table is already isolated by living inside
*your own* database (`rwd_<YOURNAME>_Training_TRN`) — same (container, key) logic as
§1.2, one level up. Scoping it again is the same anti-pattern as scoping an instance
externalId, **and** it desyncs the YAML/CSV basenames so the rows never upload.

---

## 4.4 [INFO] CogniteFile vs classic FileMetadata — and why this lab uses both

| | `CogniteFile` | classic `FileMetadata` |
|---|---|---|
| Has a DMS instance identity `(space, externalId)`? | Yes | No — classic numeric/external ID only |
| Used for | P&ID PDF, datasheet PDF — anything you want to *reference from a view* (e.g. `EquipmentHealthProfile.datasheetFile`) | The 3D source OBJ |
| Why used here | [Chapter 09](09-3d.md)'s 3D revision API needs a **classic** file ID to create a revision from — the DMS-only project has no classic `3dmodels/` Toolkit resource, so the OBJ is uploaded as a classic file and the 3D model/revision *shell* is created at runtime by your `Load3DRevision` function instead |

📚 `[DOCS]` https://docs.cognite.com/cdf/dm/ (CogniteFile) — cross-reference with the
Files section of https://docs.cognite.com/llms.txt for the classic Files API if you
want the full picture.

---

## 4.5 [ACTION] Get the binary assets and place them exactly here

🟢 `[ACTION]` Copy the three source files from the course assets folder into your own
`files/` directory (identical command on macOS Terminal and Windows Git Bash):

```bash
P=training/modules/participants/<YOURNAME>
cp docs/assets/TRN-21-SEP-PID.pdf             $P/files/
cp docs/assets/TRN-21-PA-2001A-Datasheet.pdf  $P/files/
cp docs/assets/TRN-21-SEP-3D.obj              $P/files/
cp docs/assets/TRN-21-SEP-3D.mtl              $P/files/
```

(Run from the repo root.)

✅ `[VERIFY]`

```bash
ls training/modules/participants/<YOURNAME>/files/
```

Expect `TRN-21-SEP-PID.pdf`, `TRN-21-PA-2001A-Datasheet.pdf`, `TRN-21-SEP-3D.obj`,
`TRN-21-SEP-3D.mtl`.

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/files/pid.CogniteFile.yaml`

```yaml
space: isp_<YOURNAME>_TRN
externalId: file_<YOURNAME>_TRN_PID_21_SEP
name: TRN-21-SEP-PID.pdf
description: P&ID for Area 21 separation system.
mimeType: application/pdf
directory: /<YOURNAME>/TRN/training
assets:
  - space: isp_<YOURNAME>_TRN
    externalId: TRN-21-SEP
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/files/datasheet.CogniteFile.yaml`

```yaml
space: isp_<YOURNAME>_TRN
externalId: file_<YOURNAME>_TRN_DS_21_PA_2001A
name: TRN-21-PA-2001A-Datasheet.pdf
description: Equipment datasheet for crude export pump 21-PA-2001A.
mimeType: application/pdf
directory: /<YOURNAME>/TRN/training
assets:
  - space: isp_<YOURNAME>_TRN
    externalId: 21-PA-2001A
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/files/model3d.FileMetadata.yaml`

```yaml
externalId: file_<YOURNAME>_TRN_3D_21_SEP
name: TRN-21-SEP-3D.obj
dataSetExternalId: dts_<YOURNAME>_Training_TRN
mimeType: application/octet-stream
directory: /<YOURNAME>/TRN/training
```

🔧 `[CHANGE]` `space:`, `externalId:`, and `directory:` — all scoped to `YOURNAME`
per the Files exception in §1.2. `assets:` targets are literal node references
(`TRN-21-SEP`, `21-PA-2001A`) inside **your own** instance space.

💡 `[GOOD TO KNOW]` — **how the Toolkit finds each binary (and why there is no
`$FILEPATH` key).** For every file YAML, `cdf build` locates the binary, then stages it
into `build/files/` **renamed to share the built YAML's stem** — e.g.
`1-pid-…PID_21_SEP.pdf` right beside `1-pid-…PID_21_SEP.CogniteFile.yaml`. At deploy the
Toolkit re-finds the binary as that same-stem sibling and uploads it as the file's
content. It finds the *source* binary by the YAML's **`name:`** field — and here `name:`
is exactly the binary filename (`TRN-21-SEP-PID.pdf`), so nothing else is needed. The
classic `FileMetadata` OBJ works identically: `name: TRN-21-SEP-3D.obj` is how its bytes
are located and uploaded at deploy — no special key.

🛑 `[COMMON MISTAKE]` — **Do NOT add a `$FILEPATH:` key** (some older guides still show
one). On Toolkit
0.8.125 `$FILEPATH` takes precedence and is resolved *literally, relative to the YAML's
own directory* — but build renamed the staged binary, so at deploy
`$FILEPATH: TRN-21-SEP-PID.pdf` resolves to `build/files/TRN-21-SEP-PID.pdf`, which no
longer exists. Deploy then dies with
`FileNotFoundError: build/files/TRN-21-SEP-PID.pdf`. Rely on `name:` (as shown above)
and the deploy resolves the staged binary correctly.

---

## 4.6 [ACTION] Build, dry-run, deploy

📝 `[WRITE]` **first** — the data set itself, because the resources above reference it:
`participants/<YOURNAME>/data_sets/dts_<YOURNAME>_Training_TRN.DataSet.yaml`

```yaml
externalId: dts_<YOURNAME>_Training_TRN
name: <YOURNAME> Training TRN
description: Hands-on training resources for <YOURNAME>.
metadata:
  course: cdf-data-modeling-handson
  participant: "<YOURNAME>"
```

Then build and deploy:

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf deploy --cdf-project <your-cdf-project> --dry-run --include data_sets --include raw --include files
uv run cdf deploy --cdf-project <your-cdf-project> --include data_sets --include raw --include files
```

💡 `[GOOD TO KNOW]` `cdf build` may print **ConsistencyError**s that the file `assets:`
targets (`TRN-21-SEP`, `21-PA-2001A`) don't exist yet — those asset *nodes* aren't
created until [Chapter 05](05-transformations.md). This is **expected** at this stage,
not a failure: DMS lets a file reference an asset node that doesn't exist yet, and the
link resolves once Chapter 05 loads the nodes. Deploy still succeeds; the warnings
clear after Ch05.

✅ `[VERIFY]` in CDF:

- **RAW explorer** → `rwd_<YOURNAME>_Training_TRN` → confirm row counts: Assets **8**,
  Equipment **5**, TimeSeries **6**, WorkOrders **3**
- **Files** → both PDFs open and render (not just "uploaded" — actually open them)
- The OBJ's classic file shows `uploaded: true` via SDK (`client.files.retrieve(external_id=...)`);
  you'll use its 3D revision in [Chapter 09](09-3d.md)

---

## Gate

**Do not proceed to Chapter 05 until:**

- RAW row counts are exactly 8 / 5 / 6 / 3
- Both PDFs open in Fusion and the OBJ's classic file shows uploaded
- Your data set exists; the transformations and the classic OBJ file reference it (RAW
  tables and the two `CogniteFile` PDFs are governed by your RAW database and your
  space respectively — §4.1, not a mistake)
- You can explain why the OBJ needed a classic `FileMetadata` file, not `CogniteFile`
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 05 — Transformations](05-transformations.md)
