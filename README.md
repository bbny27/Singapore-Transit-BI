# Singapore Transit Intelligence — Power BI revamp

An editable **eight-page Power BI project**, backed by Python, SQLite, SQL analytical marts, independent Power Query M files and DAX. This revision continues the supplied September 13 project and retains its real observations. It changes the central question from “how much traffic?” to **“what patterns suggest a transport decision, and how strong is the evidence?”**

## Start on Windows

1. Extract the **entire ZIP**. Keep `transit_bi` and its subfolders together.
2. Open `transit_bi` in VS Code and run:

   ```powershell
   python make.py setup
   ```

   Alternatively, double-click `START_HERE.bat`. Python 3.11+ is sufficient for the main project. No npm, FastAPI, SQL Server, pyodbc or SQLite ODBC driver is needed.
3. Open **`powerbi\Transit.pbip`** in an up-to-date Power BI Desktop. If required, enable **Power BI Project** and **Store reports using enhanced metadata format (PBIR)** under File → Options and settings → Options → Preview features, restart Desktop, and reopen.
4. Click **Home → Refresh**. The supplied real data loads without an API key. The first opening can take time because the model includes the full hourly demand extract.
5. Optional: View → Themes → Browse for themes → select **`powerbi\Transit_Theme.json`**. The native report already has page, title, table and chart styling; the theme adds consistent defaults when you create new visuals.
6. Use the eight tabs. For station metrics, weekend ratios, and service comparisons, choose **one month**. Use station/stop **names** in slicers. Save As `.pbix` after opening if you prefer a single Desktop file.

`setup` exports analytical tables and fixes absolute paths for your computer. Re-running it preserves report visuals and custom model measures. **`python make.py report` intentionally regenerates the model and all report pages**, replacing personal report/model changes. Back up your customised Power BI folders before using that target.

**Verification boundary:** the included pipeline, analytical semantics, archive behavior, model bindings, and PBIR JSON contracts have been checked. Static chart previews have been rendered and inspected. Power BI Desktop cannot run in this Linux environment; the native report's final Desktop opening/rendering and DAX evaluation are not claimed as tested. This is a real `.pbip`/PBIR project, not an invented `.pbix` binary.

## Read the story

| Chapter | Question and implemented analysis | What to look at |
|---|---|---|
| 01 Demand | Where and when do people enter? | Holiday-adjusted entries/day; hourly entries/exits; computed monthly findings |
| 02 Station roles | Which stations behave like origins or destinations? | 24-hour curves; AM/PM balance; transparent functional rules; four shape clusters |
| 03 Daily transformation | Which places change at weekends? | Weekend/weekday daily-entry ratio; verified bus-stop map; diverging hourly net-flow matrix |
| 04 Flow | Where do riders go and do directions reverse? | Named OD endpoints; morning outward and evening reverse volumes; explicit OD coverage |
| 05 Service | Where should demand versus service be investigated? | Daily demand against distinct bus services; demand per service as a structural screening proxy |
| 06 Reliability | Is crowding persistent and supply regular? | Standing-share service/hour matrix; coverage thresholds; predicted-gap audit with sample windows |
| 07 Resilience | What loses connectivity if a service disappears? | Single-service link fragility map; directed graph service-removal scenarios weighted by observed OD |
| 08 Evidence & archive | What do we know, and what is missing? | Versioned monthly ledger; polling outcomes; first/last observations; holiday denominators |

The report deliberately shows **Insufficient history** for the supplied live observations. There is only one sampled date. Blank qualifying heatmap cells are correct; they do not mean uncrowded buses.

### Findings already supported by the supplied snapshot

For **August 2026**, using 20 weekdays and 11 weekend/holiday days:

- Jurong East has approximately **71,875 rail entries per weekday**, the highest among the supplied rail fare nodes.
- Stadium's entries per weekend/holiday day are approximately **2.77×** its weekday rate, among rail nodes with at least 1,000 weekday entries/day.
- **69 rail fare nodes** meet the AM-outward / PM-inward profile rule. “Residential-like” is an interpretation of the shape, not measured land use.

These are reproducible SQL results, not manually populated dashboard values. `docs/FINDINGS.md` explains the interpretation and next investigative steps.

## Bring over observations collected since the previous download

The supplied database is the recovered project snapshot. If your own copy has newer observations, **stop its collector first**, back it up, and copy that copy's `data\transit.sqlite` into this new project's `data` folder **before running setup**. If the old folder contains `transit.sqlite-wal`, use its backup command or close all database connections and checkpoint the database before copying; do not copy only an actively written SQLite main file. Preserve its `data\raw` folder as well if available. Keep your local key in `.env`, or set `LTA_ACCOUNT_KEY`.

The migration is additive. It retains existing monthly facts and arrival/crowd history, adds archives and analytical tables, and does not generate synthetic observations. Existing monthly data whose original ZIP is unavailable is archived as a clearly labelled **legacy SQL extract**. It is never presented as an original source file.

## Collect and preserve new data

Configure your existing key once:

```powershell
python transit.py configure
```

Input is hidden: paste the key and press Enter. The terminal displaying nothing is normal. `.env` is private and is excluded from the project bundle.

```powershell
python transit.py live                       # one observation cycle + exports
python make.py collect                       # keep collecting while computer is awake
python make.py archive                       # catch up available recent monthly releases
python transit.py monthly --month 202608     # import a specific cached/available month
python transit.py monthly --month 202608 --refresh-source
python make.py refresh                       # rebuild marts and CSVs, preserve report edits
python make.py backup                        # SQLite online backup to data/backups
```

The collector polls the six configured stops every 60 seconds and six configured rail lines every ten minutes. It retains **all returned raw JSON payloads in SQL** and normalized arrival/crowd rows. NextBus2/3 remain archived even though the crowding calculation uses NextBus only. Failed and empty requests remain in the collection log. Unknown loads do not become zero loads.

With `archive_monthly: true`, the collector checks missing releases on startup and at most once per 24 hours. It requests each of the last three completed months and all four passenger datasets, skipping already-imported scopes. LTA's documented window is up to three months, with previous-month data normally available by the 10th; unavailable files are logged and retried in the next cycle. Monthly catch-up runs synchronously and can pause live collection while large files download/import. For uninterrupted sampling, set `archive_monthly` false and schedule `python make.py archive` as a separate daily task. The separate job should not overlap another monthly archive job.

All **new ODBus imports default to full scope**. The supplied August ODBus facts retain the original watched-endpoint scope until a full reimport succeeds. The `od_scope` column and release ledger make this visible. Neither total bus demand nor train OD is restricted to those watched endpoints.

Original monthly ZIP bytes are stored in the `releases` SQL table with SHA-256 checksums. Reimporting identical bytes does not duplicate the archive; changed bytes create another retained version. Canonical monthly fact tables expose the latest successful import. `--refresh-source` requests source bytes again without deleting older SQL archive versions. `data/raw` is a convenience cache, not the sole archive.

Power BI uses **Import mode**. The collector does not automatically refresh an open Desktop report: wait for “SQL exports refreshed”, then click Home → Refresh. The API key never enters the Power BI model.

## Make targets and optional previews

Windows does **not** need GNU Make. Use `python make.py TARGET`; a conventional `Makefile` offers the same targets where Make is installed.

| Target | Action |
|---|---|
| `setup`, `refresh` | Rebuild SQL marts/CSV outputs; configure model paths without replacing report edits |
| `report` | Rebuild everything including generated model and report layout |
| `check` | Run offline semantic regression tests, integrity, checksums and binding/input checks |
| `preview` | Render four analytical PNG previews using Matplotlib |
| `collect` | Continuous live collection with configured monthly archival |
| `archive` | Catch up recent available monthly releases |
| `backup` | Consistent online SQLite backup |

```powershell
python -m pip install -r requirements.txt
python make.py preview
python make.py check
# Optional developer validation of Microsoft's JSON contracts:
python -m pip install -r requirements-dev.txt
python scripts/validate_report.py
```

Pre-rendered PNGs are in `charts`. They illustrate the SQL findings and design palette; they are **not screenshots of Power BI Desktop**.

## Maps, missing data and the previous fixes

- All geographical maps use validated bus-stop coordinates. Latitude and longitude are typed as decimal numbers, classified as Latitude/Longitude, and aggregated with **minimum**, not summed.
- Each map groups by a unique name-plus-code label. Different stops with the same description stay separate.
- Rail name mappings are included for profiles and flows. **Rail coordinates are not fabricated**; rail records cannot enter the map-only table.
- Two bus codes in the old monthly release (`07522`, `70372`) are missing from its BusStops reference. They retain explicit unresolved names and remain in demand totals, but are excluded from geographical maps.
- A map can require internet access and the Desktop map visual security setting. Its adjacent table remains usable if map rendering is disabled.
- Every generated M query directly reads its own CSV. No `Nodes = Nodes` dependency, bundled-query copy/paste, or self-reference is required. The authoritative individual queries are in `powerbi\powerquery`.
- Empty/unknown source values become null before number conversion; five-digit stop codes and multi-code rail station IDs remain text.

Read `docs/EXPLAINED.md` for the code, SQL and analytical walkthrough, `docs/OPERATIONS.md` for scheduling/recovery, and `docs/VALIDATION.md` for checks and remaining limits.
