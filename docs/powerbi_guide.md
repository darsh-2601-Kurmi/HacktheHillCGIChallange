# Northwind OneCase: Power BI build guide

Five pages that carry the diagnosis (at most 2 minutes of the pitch), built from the CSVs **as loaded**: no Power Query
steps, no transforms. Everything below is model work (relationships, DAX columns, measures) and visuals.
Every measure has a **check value**; if your number differs, stop and fix it before building visuals.

Needs Power BI Desktop from 2023 or later (the score fit uses `LINESTX`).

---

## Step 0. Two settings first (30 seconds)

1. **File → Options and settings → Options → CURRENT FILE → Data load**
   - Untick **Auto date/time**. This stops Power BI adding date hierarchies to every date column.
   - Untick **Autodetect new relationships after data is loaded**.
2. **View → Themes → Browse for themes** → `docs/powerbi_theme.json` (Northwind colours and fonts).

## Step 1. The six tables

Loaded with **Get data → Text/CSV → Load** (not *Transform data*). Power BI names each table after its file.

| Table | File | Rows | What it is |
|---|---|---:|---|
| `complaint_360` | `data/exports/complaint_360.csv` | 25,416 | One row per complaint, already joined to intake system, meter context, staffing and unit cost |
| `region_month` | `data/exports/region_month.csv` | 144 | Region × month: volumes, estimated read rate, smart-meter penetration, agents |
| `backlog_month` | `data/exports/backlog_month.csv` | 24 | The monthly KPI file plus the open backlog |
| `scenarios` | `data/exports/scenarios.csv` | 60 | 5 named scenarios × 12 months from the scenario engine |
| `lever_grid` | `data/exports/lever_grid.csv` | 375 | Every lever combination, month-12 outcomes (for what-if) |
| `northwind_ai_pilot_2025` | `data/raw/northwind_ai_pilot_2025.csv` | 9 | The 2025 AI pilot, month by month |

Check the row counts in **Data view** (bottom-left shows *Table: N rows*).

**About the `month` columns.** They hold text like `2024-10`. Power BI's automatic type detection may keep them as
**Text** or turn them into **Date** (shown as 01/10/2024). Both work with this guide: every visual below uses
`month` as a plain category. If a chart shows months out of order, click **More options (…) → Sort axis → month →
Sort ascending**.

## Step 2. Model

### 2a. Remove automatic relationships
**Model view** → click each relationship line Power BI created on load (likely `month` ↔ `month` lines between
`backlog_month`, `region_month`, `scenarios` and the AI pilot) → **Delete**. You should end with **no relationships**.

### 2b. Two helper tables
- **Modeling → New table**:
  ```DAX
  Regions = DISTINCT ( complaint_360[region] )
  ```
  Check: 6 rows.
- **Home → Enter data** → leave the grid empty → name it `_Measures` → **Load**. Every measure goes in here.
  Once it holds a measure, right-click its default column `Column1` → **Hide in report view**. The table then
  moves to the top of the Data pane.

### 2c. Two relationships
Model view → drag `Regions[region]` onto `complaint_360[region]`, then onto `region_month[region]`.
Both: **One to many (1:\*)**, cross-filter **Single**. These let one region axis drive both tables.

### 2d. Calculated columns
Select the table in the Data pane → **Table tools → New column**:

```DAX
-- on Regions
Meters =
IF (
    CALCULATE ( MAX ( region_month[smart_meter_penetration] ) ) > 0,
    "Smart-meter region",
    "No smart meters"
)
```
Check: Barrowdale and Dunmoor = "No smart meters"; the other four = "Smart-meter region".

```DAX
-- on complaint_360
Transferred? =
IF ( complaint_360[transferred_between_systems] = 1, "Transferred", "Not transferred" )
```
```DAX
-- on complaint_360
Intake system = complaint_360[source_system] & " " & complaint_360[source_system_name]
```
```DAX
-- on complaint_360 (needs date_opened typed as Date, which Power BI does on load)
Quarter =
FORMAT ( complaint_360[date_opened], "yyyy" ) & " Q" & FORMAT ( complaint_360[date_opened], "q" )
```

### 2e. Column formats
Select the column → **Column tools → Format**:
- **Percentage, 0 decimals:** `region_month[smart_meter_penetration]`, `region_month[estimated_read_rate]`,
  `lever_grid[transfers_removed]`, `lever_grid[info_only_first_contact]`, `lever_grid[estimated_read_reduction]`
- **Whole number:** `lever_grid[calderfield_agents_restored]`

## Step 3. Measures

Click `_Measures` → **Table tools → New measure**, paste one measure at a time, then set its format in
**Measure tools → Format**. Each block lists the format and the value you should see.
For a check, drop the measure on a Card; for a split, put it in a table with the field shown.

### A. Volume and transfers

```DAX
Complaints = COUNTROWS ( complaint_360 )
```
Whole number, thousands separator. **Check 25,416.**

```DAX
Open complaints = CALCULATE ( [Complaints], complaint_360[is_open] = 1 )
```
**Check 1,599.**

```DAX
Transferred = CALCULATE ( [Complaints], complaint_360[transferred_between_systems] = 1 )
```
**Check 8,870.**

```DAX
Transfer rate = DIVIDE ( [Transferred], [Complaints] )
```
Percentage, 1 decimal. **Check 34.9%.** By `Intake system`: SYS-01 47.1%, SYS-03 46.4%, SYS-05 45.6%, **SYS-04 0.0%**.

### B. What a transfer costs

```DAX
Avg days to close = AVERAGE ( complaint_360[days_to_close] )
```
Decimal, 1 place. Blank on open cases, so this averages closed complaints. **Check 28.2.**

```DAX
Avg days transferred =
CALCULATE ( [Avg days to close], complaint_360[transferred_between_systems] = 1 )
```
**Check 38.2.**

```DAX
Avg days not transferred =
CALCULATE ( [Avg days to close], complaint_360[transferred_between_systems] = 0 )
```
**Check 23.0.**

```DAX
Days added by a transfer = [Avg days transferred] - [Avg days not transferred]
```
**Check 15.3.**

```DAX
SLA breach rate = AVERAGE ( complaint_360[sla_breach] )
```
Percentage, 1 decimal. **Check 76.8%.** By `Transferred?`: Transferred 88.7%, Not transferred 70.4%.

```DAX
Reopen rate = AVERAGE ( complaint_360[reopened] )
```
Percentage, 1 decimal. By `Transferred?`: **26.9% vs 8.4%.**

```DAX
Avg handling cost = AVERAGE ( complaint_360[handling_unit_cost] )
```
Currency, 0 decimals. By `Transferred?`: **$121 vs $68.**

```DAX
Handling cost = SUM ( complaint_360[handling_unit_cost] )
```
Currency, 0 decimals. **Check $2,198,398.**

```DAX
CaseTrack note =
CALCULATE (
    SELECTEDVALUE ( complaint_360[source_system_notes] ),
    complaint_360[source_system] = "SYS-04"
)
```
Text. **Check:** "Cases transferred in from other channels lose their history."

### C. What the complaints are about

```DAX
Estimate-driven share =
DIVIDE ( CALCULATE ( [Complaints], complaint_360[estimate_driven] = 1 ), [Complaints] )
```
Percentage, 0 decimals. **Check 63%.**

```DAX
Billing fixed share =
VAR billing =
    CALCULATE ( [Complaints], complaint_360[category_group] = "Billing" )
VAR fixed =
    CALCULATE (
        [Complaints],
        complaint_360[category_group] = "Billing",
        complaint_360[resolution_action]
            IN { "Bill corrected and re-issued", "Refund or credit applied" }
    )
RETURN
    DIVIDE ( fixed, billing )
```
Percentage, 0 decimals. **Check 59%.**

```DAX
Info-only complaints =
CALCULATE ( [Complaints], complaint_360[resolvable_by_information_only] = 1 )
```
**Check 5,865.**

```DAX
Info-only share = DIVIDE ( [Info-only complaints], [Complaints] )
```
Percentage, 1 decimal. **Check 23.1%.**

```DAX
Avg days info-only =
CALCULATE ( [Avg days to close], complaint_360[resolvable_by_information_only] = 1 )
```
**Check 28.0.**

```DAX
Transfer rate info-only =
CALCULATE ( [Transfer rate], complaint_360[resolvable_by_information_only] = 1 )
```
**Check 34.4%.**

### D. The score and the days (from `backlog_month`)

```DAX
Regulator score = AVERAGE ( backlog_month[regulator_satisfaction_score_of_5] )
```
Decimal, 2 places.

```DAX
Avg days (KPI) = AVERAGE ( backlog_month[avg_days_to_close] )
```
Decimal, 1 place. This is the KPI file's number: days for complaints **closed** in that month.

```DAX
Open backlog = AVERAGE ( backlog_month[backlog_end] )
```
Whole number.

```DAX
Score today =
VAR lastMonth = TOPN ( 1, ALL ( backlog_month[month] ), backlog_month[month], DESC )
RETURN
    CALCULATE ( [Regulator score], lastMonth )
```
**Check 2.58.**

```DAX
Days today =
VAR lastMonth = TOPN ( 1, ALL ( backlog_month[month] ), backlog_month[month], DESC )
RETURN
    CALCULATE ( [Avg days (KPI)], lastMonth )
```
**Check 38.2.**

```DAX
Score slope per day =
MAXX (
    LINESTX ( ALL ( backlog_month ),
        backlog_month[regulator_satisfaction_score_of_5],
        backlog_month[avg_days_to_close] ),
    [Slope1]
)
```
Decimal, 4 places. **Check −0.0691.**

```DAX
Score intercept =
MAXX (
    LINESTX ( ALL ( backlog_month ),
        backlog_month[regulator_satisfaction_score_of_5],
        backlog_month[avg_days_to_close] ),
    [Intercept]
)
```
Decimal, 3 places. **Check 5.316.**

```DAX
Score fit r =
- SQRT (
    MAXX (
        LINESTX ( ALL ( backlog_month ),
            backlog_month[regulator_satisfaction_score_of_5],
            backlog_month[avg_days_to_close] ),
        [CoefficientOfDetermination]
    )
)
```
Decimal, 2 places. **Check −0.98.** (The sign is negative because the slope is negative.)

```DAX
Days needed for 4.0 = DIVIDE ( 4 - [Score intercept], [Score slope per day] )
```
Decimal, 1 place. **Check 19.0.**

### E. Meters and regions

```DAX
Smart-meter penetration = AVERAGE ( region_month[smart_meter_penetration] )
```
Percentage, 0 decimals.

```DAX
Estimated read rate = AVERAGE ( region_month[estimated_read_rate] )
```
Percentage, 0 decimals.

```DAX
Estimated read rate latest =
VAR lastMonth = TOPN ( 1, ALL ( region_month[month] ), region_month[month], DESC )
RETURN
    CALCULATE ( [Estimated read rate], lastMonth )
```
By `Regions[region]`: **Barrowdale 62%, Dunmoor 62%**, Ashford 25%, Calderfield 21%, Eastmarch 18%, Fenwick 26%.

```DAX
Agents = SUM ( region_month[agent_fte] )
```
Whole number. Calderfield: **73 in Oct 2024, 37 in Sep 2026.**

```DAX
Avg days since Mar 2026 =
CALCULATE ( [Avg days to close], complaint_360[date_opened] >= DATE ( 2026, 3, 1 ) )
```
By region: **33.5 to 34.8** (Calderfield 33.8).

```DAX
SLA breach since Mar 2026 =
CALCULATE ( [SLA breach rate], complaint_360[date_opened] >= DATE ( 2026, 3, 1 ) )
```
By region: **91% to 94%** (Calderfield 93.2%).

### F. The 2025 AI pilot

```DAX
Containment = AVERAGE ( northwind_ai_pilot_2025[fully_contained_rate] )
```
```DAX
Repeat contact in 7 days = AVERAGE ( northwind_ai_pilot_2025[repeat_contact_within_7_days_rate] )
```
```DAX
Complaint after session = AVERAGE ( northwind_ai_pilot_2025[complaint_raised_after_session_rate] )
```
Those three: Percentage, 1 decimal.
```DAX
Assistant CSAT = AVERAGE ( northwind_ai_pilot_2025[assistant_csat_of_5] )
```
Decimal, 2 places. **Checks, Jan → Sep 2025:** containment 16.0% → 10.4%, repeat contact 31.0% → 44.6%,
complaint after session 11.0% → 14.2%, CSAT 2.60 → 2.04.

### G. Scenarios

```DAX
Score plan method = AVERAGE ( scenarios[score_static] )
```
```DAX
Score backlog-aware = AVERAGE ( scenarios[score_queue] )
```
Both: Decimal, 2 places.
```DAX
Scenario backlog = AVERAGE ( scenarios[backlog] )
```
Whole number.
```DAX
Score month 12 plan = CALCULATE ( [Score plan method], scenarios[month_index] = 12 )
```
```DAX
Score month 12 backlog-aware = CALCULATE ( [Score backlog-aware], scenarios[month_index] = 12 )
```
```DAX
Backlog month 12 = CALCULATE ( [Scenario backlog], scenarios[month_index] = 12 )
```
```DAX
Saving a year = CALCULATE ( SUM ( scenarios[handling_saving] ), scenarios[month_index] = 12 ) * 12
```
Currency, 0 decimals.
```DAX
Reaches 4.0 (plan) =
VAR m = CALCULATE ( MIN ( scenarios[month_index] ), scenarios[score_static] >= 4 )
RETURN IF ( ISBLANK ( m ), "Not reached", "Month " & m )
```
```DAX
Reaches 4.0 (backlog-aware) =
VAR m = CALCULATE ( MIN ( scenarios[month_index] ), scenarios[score_queue] >= 4 )
RETURN IF ( ISBLANK ( m ), "Not reached", "Month " & m )
```
**Checks by scenario:**

| Scenario | Month 12 plan | Month 12 backlog-aware | 4.0 (backlog-aware) | Backlog month 12 | Saving a year |
|---|---:|---:|---|---:|---:|
| Status quo | 2.68 | 1.93 | Not reached | 2,271 | $0 |
| Client's plan: AI assistant only | 2.74 | 2.40 | Not reached | 1,905 | $36,561 |
| Routing fix only (OneCase) | 3.00 | 4.50 | Month 8 | 312 | $236,720 |
| Recommended | 3.23 | 4.76 | Month 5 | 224 | $524,333 |
| Everything at maximum | 3.41 | 4.76 | Month 4 | 161 | $754,461 |

`Reaches 4.0 (plan)` is "Not reached" for every scenario. That is the headline finding.

### H. What-if (from `lever_grid`)

The grid holds one row per lever combination. When every lever slicer has exactly one value picked, one row is
left and these measures read it.
```DAX
Lever rows = COUNTROWS ( lever_grid )
```
```DAX
What-if score plan = IF ( [Lever rows] = 1, SUM ( lever_grid[score_static_month12] ) )
```
```DAX
What-if score backlog-aware = IF ( [Lever rows] = 1, SUM ( lever_grid[score_queue_month12] ) )
```
```DAX
What-if days = IF ( [Lever rows] = 1, SUM ( lever_grid[avg_days_month12] ) )
```
```DAX
What-if backlog = IF ( [Lever rows] = 1, SUM ( lever_grid[backlog_month12] ) )
```
```DAX
What-if saving a year = IF ( [Lever rows] = 1, SUM ( lever_grid[annual_saving_full_effect] ) )
```
```DAX
What-if verdict =
IF (
    [Lever rows] <> 1,
    "Pick one value on each of the four levers",
    IF (
        [What-if score plan] >= 4,
        "4.0 reached",
        IF (
            [What-if score backlog-aware] >= 4,
            "4.0 only if the backlog clears",
            "4.0 not reached"
        )
    )
)
```
**Checks** (transfers / info-only / estimates / agents → plan score, backlog-aware score, days, backlog, saving):
- 0 / 0 / 0 / 0 → 2.68, 1.93, 38.2, 2,271, $0
- 100% / 0 / 0 / 0 → 3.04, 4.53, 33.0, 312, $263,022
- 100% / 50% / 50% / 0 → 3.23, 4.76, 30.3, 231, $525,342
- 100% / 100% / 100% / 35 → 3.41, 4.76, 27.6, 161, $754,461

**Optional tidy-up:** in Model view, select measures and set **Properties → Display folder** to
`A Volume`, `B Transfers`, `C Complaints`, `D Score`, `E Regions`, `F AI pilot`, `G Scenarios`, `H What-if`.

---

## Step 4. Pages and visuals

Page setup for a projector: **Format page → Canvas settings → 16:9**. Keep text at 12 pt or larger and card values
at 28 pt or larger. Each title states the finding, not the chart type (**Format visual → General → Title**).

### Page 1 · "The score follows the days"
1. **Six cards** across the top (**Card** visual, one measure each):
   `Complaints` (25,416) · `Open complaints` (1,599) · `Transfer rate` (34.9%) · `Days today` (38.2) ·
   `Score today` (2.58) · `Days needed for 4.0` (19.0).
   Rename each card's label: right-click the field in the well → **Rename for this visual**, e.g. "Days to close today".
2. **Line chart**, left half.
   X-axis: `backlog_month[month]`. Y-axis: `Regulator score`.
   **Analytics** pane (magnifier icon) → **Constant line → Add** → Value `4` → Data label **On**, text "Target 4.0".
   If `month` is a Date: **Format → X-axis → Type: Categorical**.
   Title: *"Regulator score has fallen every month: 4.30 → 2.58"*.
3. **Line chart**, right half.
   X-axis: `backlog_month[month]`. Y-axis: `Avg days (KPI)`. Constant line `19`, label "Needed for 4.0".
   Title: *"Days to close: 38.2 now, 19 needed for 4.0"*.
4. **Scatter chart** below.
   X-axis: `Avg days (KPI)`. Y-axis: `Regulator score`. Values: `backlog_month[month]`.
   **Analytics → Trend line → On**.
   Next to it, a **Card** with `Score fit r` (−0.98), plus a **Text box**:
   "score ≈ 5.316 − 0.069 × days (24 months). A correlation, not proof of cause."
   Title: *"Score tracks days to close (r = −0.98)"*.
   (Two separate line charts, not one chart with two y-axes: the scales differ and a dual axis misleads.)

### Page 2 · "Transfers come from the intake system"
1. **Clustered bar chart**, left.
   Y-axis: `complaint_360[Intake system]`. X-axis: `Transfer rate`.
   **Data labels → On**. **… → Sort axis → Transfer rate → descending**.
   **Format → X-axis → Range**: Minimum 0, Maximum 0.5.
   Title: *"By intake system: CaseTrack 0%, the rest 46–47%"*.
   Check: CaseTrack 0.0%; Aurora Billing 47.1%; Northwind Connect 46.4%; CallCentre One 45.6%.
2. **Four small clustered bar charts** in a 2×2 grid, each with X-axis `Transfer rate` and X range 0 to 0.5, so all
   five charts share one scale. Y-axes: `category` · `channel` · `priority` · `Quarter`.
   Group title (a text box): *"Everything else: flat at 33–37%"*.
   Checks: category 32.9–37.0%, channel 33.0–35.3%, priority 34.5–35.9%, quarter 33.9–35.9%.
3. **Matrix**, bottom.
   Rows: `complaint_360[Transferred?]`. Values: `Complaints`, `Avg days to close`, `SLA breach rate`,
   `Reopen rate`, `Avg handling cost`.
   Check: Transferred **8,870 · 38.2 · 88.7% · 26.9% · $121**; Not transferred **16,546 · 23.0 · 70.4% · 8.4% · $68**.
   Title: *"A transferred complaint takes 15 days longer, misses SLA 89% of the time and costs $53 more"*.
4. **Card** with `CaseTrack note`, titled "CaseTrack (SYS-04) system note".
   **Format → Callout value → Text wrap On**, 14 pt.

### Page 3 · "Billing and metering drive the volume; billing ignores the smart meters"
1. **Clustered bar chart**: Y-axis `complaint_360[category]`, X-axis `Complaints`, sorted descending, data labels on.
   Check: top bar Billing - disputed amount **8,060**.
   Title: *"Billing and metering: 63% of complaints"*.
2. **Two cards**: `Estimate-driven share` (63%) and `Billing fixed share` (59%, labelled
   "billing complaints ending in a correction or refund").
3. **Line chart**: X-axis `region_month[month]`. Y-axis: `Smart-meter penetration` **and** `Estimated read rate`
   (both percentages, so one axis is fine).
   **Filters on this visual**: drag `Regions[Meters]` in → tick "Smart-meter region" only.
   Check: penetration **30% → 81%**, estimated reads **21% → 23%** (range 19–25%).
   Title: *"Smart meters went from 30% to 81%; estimated bills did not fall"*.
4. **Clustered column chart**: X-axis `Regions[region]`. Y-axis `Estimated read rate latest`. Sorted descending.
   **Format → Columns → Color → fx** → Format style *Rules* on `Estimated read rate latest`: ≥ 0.5 → #C2302A,
   otherwise #2A78D6.
   Title: *"Barrowdale and Dunmoor: no smart meters, 62% estimated"*.

### Page 4 · "Answers, the AI pilot, and Calderfield"
1. **Four cards**: `Info-only complaints` (5,865) · `Info-only share` (23.1%) · `Avg days info-only` (28.0) ·
   `Transfer rate info-only` (34.4%). Group title (text box):
   *"1 in 4 complaints only needed an answer. They still took 28 days and were transferred just as often"*.
2. **Line chart**: X-axis `northwind_ai_pilot_2025[month]`. Y-axis: `Containment`, `Repeat contact in 7 days`,
   `Complaint after session`. Title: *"The 2025 AI pilot got worse every month"*.
3. **Line chart** beside it: same X-axis, Y-axis `Assistant CSAT`. Title: *"Pilot CSAT 2.60 → 2.04"*.
   (A separate chart because CSAT is on a 1–5 scale, not a percentage.)
4. **Line chart**: X-axis `region_month[month]`, Y-axis `Agents`, Legend `Regions[region]`.
   **Format → Lines → Colors**: Calderfield #EB6834, all others #B9C3CA (grey), so Calderfield stands out.
   Title: *"Calderfield lost half its agents (73 → 37)…"*.
5. **Clustered column chart**: X-axis `Regions[region]`, Y-axis `Avg days since Mar 2026`,
   Tooltips `SLA breach since Mar 2026`. Data labels on. Y range from 0.
   Title: *"…yet its days to close match every other region (33.5–34.8)"*.

### Page 5 · "Is 4.0 reachable?"
1. **Line chart**, top left.
   X-axis: `scenarios[month_index]` (**Format → X-axis → Type: Categorical**). Y-axis: `Score plan method`.
   Legend: `scenarios[scenario_name]`. Constant line `4`, label "Target 4.0". Y-axis range 1 to 5.
   **Format → Lines → Colors**: Recommended #EB6834, Routing fix #2A78D6, Everything at maximum #1BAF7A,
   Client's plan #E87BA4, Status quo #898781.
   Title: *"Per-case fixes alone: nothing reaches 4.0 (best 3.41)"*.
2. **Line chart**, top right. Same setup, with Y-axis `Score backlog-aware`.
   Title: *"If the backlog clears as 24 months of history suggest: 4.0 by month 5"*.
3. **Table**, bottom left. Columns: `scenarios[scenario_name]`, `Score month 12 plan`, `Score month 12 backlog-aware`,
   `Reaches 4.0 (backlog-aware)`, `Backlog month 12`, `Saving a year`. Check against the table in Step 3G.
   **Format → Cell elements → Background color → fx** on `Score month 12 backlog-aware`: rules ≥ 4 → #E7F5EC.
4. **What-if** block, bottom right.
   - **Four slicers**, one each on `lever_grid[transfers_removed]`, `lever_grid[info_only_first_contact]`,
     `lever_grid[estimated_read_reduction]`, `lever_grid[calderfield_agents_restored]`.
     For each: **Format → Slicer settings → Options → Style: Tile**, and **Selection → Single select: On**.
     Rename headers: "Transfers removed", "Answered at first contact", "Estimate complaints avoided",
     "Calderfield agents restored".
   - **Cards**: `What-if score plan`, `What-if score backlog-aware`, `What-if days`, `What-if backlog`,
     `What-if saving a year`.
   - A **Card** with `What-if verdict` (text).
   - Pick 100% / 50% / 50% / 0 and check: **3.23 · 4.76 · 30.3 · 231 · $525,342** · "4.0 only if the backlog clears".
5. **Text box** under the charts (the honest caveat):
   "Plan method subtracts per-case savings from today's 38.2 days. Backlog-aware also lets days fall as the open
   backlog clears (+0.017 days per open case, r = 0.98). Source: scenario engine, assumptions.yaml."

---

## Step 5. Finish

1. **Page names**: double-click each tab → "1 Score", "2 Transfers", "3 Billing & meters", "4 Answers, AI, Calderfield",
   "5 Reaching 4.0".
2. **Navigation**: Insert → Buttons → Navigator → **Page navigator**, placed top-right of every page (copy and paste it).
3. **Edit interactions**: on page 5, select a slicer → **Format → Edit interactions** → set the scenario charts and the
   table to **None**, so the lever slicers only drive the what-if cards.
4. **Hide** `_Measures[Column1]`, and hide the raw ID columns you don't use (right-click → Hide in report view).
5. **Presenting**: File → Export → PDF as a backup (the in-app `/impact` page is the live fallback). In Desktop,
   collapse the Filters, Visualizations and Data panes and set **View → Page view → Fit to page**. If you publish to
   the Power BI service, present with **View → Full screen**.

## 2-minute path through the report

| Time | Page | Say |
|---|---|---|
| 0:00 | 1 | "Score tracks days to close, r = −0.98. 4.0 needs 19 days; we're at 38.2." |
| 0:25 | 2 | "Transfers are 33–37% whatever the complaint, but 0% from CaseTrack and 46–47% from the other three intake systems. A transfer adds 15 days, and CaseTrack's own note says history is lost." |
| 0:55 | 3 | "63% is billing and metering. Smart meters went 30% to 81%; estimated bills didn't move." |
| 1:20 | 4 | "A quarter only needed an answer. The AI pilot got worse every month, and Calderfield is a red herring." |
| 1:40 | 5 | "No single fix reaches 4.0. The recommended package gets 3.23, and 4.0 by month 5 if the backlog clears." |
