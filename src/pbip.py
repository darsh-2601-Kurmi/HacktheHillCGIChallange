"""Power BI Project (PBIP): the nine-page Northwind diagnosis. Open powerbi/Northwind.pbip in Power BI Desktop,
click Refresh, then File > Save as to get a .pbix.

    python run.py pbip        writes powerbi/ (semantic model + nine-page report, light theme)

The semantic model (model.bim, TMSL) loads the CSVs as they are: headers promoted, types set, nothing else.
The DataFolder parameter holds the absolute path of data/; change it in Transform data > Manage parameters if
the project moves, or rerun this command. The report is written in PBIR (the documented JSON format), one file
per page and visual. Page titles quote numbers from src/facts.py, computed from the same files.
"""
from __future__ import annotations

import json
import shutil
import time
import uuid

import pandas as pd

from .facts import facts
from .config import DATA, EXPORTS, RAW, RAW_FILES, REGIONS, ROOT, SMART_REGIONS

OUT = ROOT / "powerbi"
NAME = "Northwind"
NS = uuid.UUID("5b1f3c44-8a55-4d2e-9f0e-0c1e5a7d9b21")
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
V = {"visual": "2.4.0", "page": "2.0.0", "report": "3.0.0"}
S_VIS = f"{SCHEMA}/item/report/definition/visualContainer/{V['visual']}/schema.json"
S_PAGE = f"{SCHEMA}/item/report/definition/page/{V['page']}/schema.json"

INK, INK2, MUTED, RULE, PAPER = "#0D1B26", "#3F4D59", "#6F7C87", "#D2DAE0", "#E9EEF1"
SCEN_SHORT = {"everything_max": "Everything at maximum", "recommended": "Recommended package",
              "routing_fix": "Routing fix only", "client_ai_plan": "Client's AI plan", "status_quo": "Status quo"}
BLUE, ORANGE, GREEN, PINK, GREY, PURPLE, CTX = "#2A78D6", "#E0612B", "#138A61", "#D0508C", "#7D8790", "#6B5BD6", "#B3BEC6"


def gid(*parts) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


# --------------------------------------------------------------------------- semantic model
TABLES = {  # model table -> CSV path relative to data/
    "complaint_360": "exports\\complaint_360.csv",
    "region_month": "exports\\region_month.csv",
    "backlog_month": "exports\\backlog_month.csv",
    "scenarios": "exports\\scenarios.csv",
    "lever_grid": "exports\\lever_grid.csv",
    "ai_pilot": "raw\\" + RAW_FILES["ai_pilot"],
}
DATES = {"date_opened", "date_closed"}
PCT0 = {"transfers_removed", "info_only_first_contact", "estimated_read_reduction", "smart_meter_penetration",
        "estimated_read_rate"}


def _columns(table: str, rel: str):
    df = pd.read_csv(DATA / rel.replace("\\", "/"), nrows=5000)
    cols = []
    for c, t in df.dtypes.items():
        t = str(t)
        if c in DATES:
            cols.append((c, "dateTime", "type date"))
        elif t == "int64":
            cols.append((c, "int64", "Int64.Type"))
        elif t == "float64":
            cols.append((c, "double", "type number"))
        else:
            cols.append((c, "string", "type text"))
    return cols


def _m_csv(rel: str, cols) -> list[str]:
    types = ", ".join(f'{{"{c}", {m}}}' for c, _, m in cols)
    return ["let",
            f'    Source = Csv.Document(File.Contents(DataFolder & "\\{rel}"), [Delimiter = ",", Encoding = 65001, '
            'QuoteStyle = QuoteStyle.Csv]),',
            "    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
            f'    Typed = Table.TransformColumnTypes(Headers, {{{types}}}, "en-US")',
            "in",
            "    Typed"]


def _col(table, name, dtype):
    c = {"name": name, "dataType": dtype, "sourceColumn": name, "lineageTag": gid(table, name),
         "summarizeBy": "none", "annotations": [{"name": "SummarizationSetBy", "value": "Automatic"}]}
    if dtype == "dateTime":
        c["formatString"] = "yyyy-mm-dd"
        c["annotations"].append({"name": "UnderlyingDateTimeDataType", "value": "Date"})
    elif name in PCT0:
        c["formatString"] = "0%"
    elif dtype == "int64":
        c["formatString"] = "0"
    return c


def _calc(table, name, expr, fmt=None, dtype="string"):
    c = {"type": "calculated", "name": name, "dataType": dtype, "isDataTypeInferred": True, "expression": expr,
         "lineageTag": gid(table, name), "summarizeBy": "none",
         "annotations": [{"name": "SummarizationSetBy", "value": "Automatic"}]}
    if fmt:
        c["formatString"] = fmt
    return c


# measures: (display folder, name, DAX, format string)
LAST_BM = "TOPN ( 1, ALL ( backlog_month[month] ), backlog_month[month], DESC )"
FIRST_BM = "TOPN ( 1, ALL ( backlog_month[month] ), backlog_month[month], ASC )"
LAST_RM = "TOPN ( 1, ALL ( region_month[month] ), region_month[month], DESC )"
FIRST_RM = "TOPN ( 1, ALL ( region_month[month] ), region_month[month], ASC )"
XY = """VAR t = ALL ( backlog_month )
VAR mx = AVERAGEX ( t, backlog_month[avg_days_to_close] )
VAR my = AVERAGEX ( t, backlog_month[regulator_satisfaction_score_of_5] )
VAR sxy = SUMX ( t, ( backlog_month[avg_days_to_close] - mx ) * ( backlog_month[regulator_satisfaction_score_of_5] - my ) )
VAR sxx = SUMX ( t, ( backlog_month[avg_days_to_close] - mx ) ^ 2 )
VAR syy = SUMX ( t, ( backlog_month[regulator_satisfaction_score_of_5] - my ) ^ 2 )"""
SINCE = "complaint_360[date_opened] >= DATE ( 2026, 3, 1 )"
K = '$#,0"k"'           # money in thousands: reads the same whatever the viewer's digit grouping (754k, not 7,54,461)
MEASURES = [
    ("A Volume", "Complaints", "COUNTROWS ( complaint_360 )", "#,0"),
    ("A Volume", "Open complaints", "CALCULATE ( [Complaints], complaint_360[is_open] = 1 )", "#,0"),
    ("A Volume", "Transferred", "CALCULATE ( [Complaints], complaint_360[transferred_between_systems] = 1 )", "#,0"),
    ("A Volume", "Transfer rate", "DIVIDE ( [Transferred] + 0, [Complaints] )", "0.0%"),
    ("B Transfers", "Avg days to close", "AVERAGE ( complaint_360[days_to_close] )", "0.0"),
    ("B Transfers", "Avg days transferred",
     "CALCULATE ( [Avg days to close], complaint_360[transferred_between_systems] = 1 )", "0.0"),
    ("B Transfers", "Avg days not transferred",
     "CALCULATE ( [Avg days to close], complaint_360[transferred_between_systems] = 0 )", "0.0"),
    ("B Transfers", "Days added by a transfer", "[Avg days transferred] - [Avg days not transferred]", "0.0"),
    ("B Transfers", "SLA breach rate", "AVERAGE ( complaint_360[sla_breach] )", "0.0%"),
    ("B Transfers", "Reopen rate", "AVERAGE ( complaint_360[reopened] )", "0.0%"),
    ("B Transfers", "Avg handling cost", "AVERAGE ( complaint_360[handling_unit_cost] )", "$#,0"),
    ("B Transfers", "Handling cost", "SUM ( complaint_360[handling_unit_cost] ) / 1000", K),
    ("B Transfers", "CaseTrack note",
     'CALCULATE ( SELECTEDVALUE ( complaint_360[source_system_notes] ), complaint_360[source_system] = "SYS-04" )', None),
    ("C Complaints", "Billing and metering share",
     'DIVIDE ( CALCULATE ( [Complaints], complaint_360[category_group] IN { "Billing", "Metering" } ), [Complaints] )',
     "0%"),
    ("C Complaints", "Billing fixed share",
     'VAR billing = CALCULATE ( [Complaints], complaint_360[category_group] = "Billing" )\n'
     'VAR fixed = CALCULATE ( [Complaints], complaint_360[category_group] = "Billing", '
     'complaint_360[resolution_action] IN { "Bill corrected and re-issued", "Refund or credit applied" } )\n'
     "RETURN DIVIDE ( fixed, billing )", "0%"),
    ("C Complaints", "Info-only complaints",
     "CALCULATE ( [Complaints], complaint_360[resolvable_by_information_only] = 1 )", "#,0"),
    ("C Complaints", "Info-only share", "DIVIDE ( [Info-only complaints], [Complaints] )", "0.0%"),
    ("C Complaints", "Avg days info-only",
     "CALCULATE ( [Avg days to close], complaint_360[resolvable_by_information_only] = 1 )", "0.0"),
    ("C Complaints", "Transfer rate info-only",
     "CALCULATE ( [Transfer rate], complaint_360[resolvable_by_information_only] = 1 )", "0.0%"),
    ("D Score", "Regulator score", "AVERAGE ( backlog_month[regulator_satisfaction_score_of_5] )", "0.00"),
    ("D Score", "Avg days (KPI)", "AVERAGE ( backlog_month[avg_days_to_close] )", "0.0"),
    ("D Score", "Open backlog", "AVERAGE ( backlog_month[backlog_end] )", "#,0"),
    ("D Score", "Score today", f"CALCULATE ( [Regulator score], {LAST_BM} )", "0.00"),
    ("D Score", "Score first month", f"CALCULATE ( [Regulator score], {FIRST_BM} )", "0.00"),
    ("D Score", "Days today", f"CALCULATE ( [Avg days (KPI)], {LAST_BM} )", "0.0"),
    ("D Score", "Score slope per day", XY + "\nRETURN DIVIDE ( sxy, sxx )", "0.0000"),
    ("D Score", "Score intercept",
     "VAR t = ALL ( backlog_month )\nRETURN AVERAGEX ( t, backlog_month[regulator_satisfaction_score_of_5] ) "
     "- [Score slope per day] * AVERAGEX ( t, backlog_month[avg_days_to_close] )", "0.000"),
    ("D Score", "Score fit r", XY + "\nRETURN DIVIDE ( sxy, SQRT ( sxx * syy ) )", "0.00"),
    ("D Score", "Days needed for 4.0", "DIVIDE ( 4 - [Score intercept], [Score slope per day] )", "0.0"),
    ("D Score", "Target 4.0", "IF ( NOT ISBLANK ( [Regulator score] ), 4 )", "0.0"),
    ("D Score", "Needed for 4.0", "IF ( NOT ISBLANK ( [Avg days (KPI)] ), [Days needed for 4.0] )", "0.0"),
    ("E Regions", "Smart-meter penetration", "AVERAGE ( region_month[smart_meter_penetration] )", "0%"),
    ("E Regions", "Estimated read rate", "AVERAGE ( region_month[estimated_read_rate] )", "0%"),
    ("E Regions", "Smart meters (smart regions)",
     'CALCULATE ( [Smart-meter penetration], Regions[Meters] = "Smart-meter region" )', "0%"),
    ("E Regions", "Estimated bills (smart regions)",
     'CALCULATE ( [Estimated read rate], Regions[Meters] = "Smart-meter region" )', "0%"),
    ("E Regions", "Estimated bills now (smart regions)", f"CALCULATE ( [Estimated bills (smart regions)], {LAST_RM} )",
     "0%"),
    ("E Regions", "Estimated read rate latest", f"CALCULATE ( [Estimated read rate], {LAST_RM} )", "0%"),
    ("E Regions", "Agents", "SUM ( region_month[agent_fte] )", "#,0"),
    ("E Regions", "Agents first month", f"CALCULATE ( [Agents], {FIRST_RM} )", "#,0"),
    ("E Regions", "Agents last month", f"CALCULATE ( [Agents], {LAST_RM} )", "#,0"),
    ("E Regions", "Complaints since Mar 2026", f"CALCULATE ( [Complaints], {SINCE} )", "#,0"),
    ("E Regions", "Avg days since Mar 2026", f"CALCULATE ( [Avg days to close], {SINCE} )", "0.0"),
    ("E Regions", "SLA breach since Mar 2026", f"CALCULATE ( [SLA breach rate], {SINCE} )", "0.0%"),
    ("E Regions", "Transfer rate since Mar 2026", f"CALCULATE ( [Transfer rate], {SINCE} )", "0.0%"),
    ("F AI pilot", "Containment", "AVERAGE ( ai_pilot[fully_contained_rate] )", "0.0%"),
    ("F AI pilot", "Repeat contact in 7 days", "AVERAGE ( ai_pilot[repeat_contact_within_7_days_rate] )", "0.0%"),
    ("F AI pilot", "Complaint after session", "AVERAGE ( ai_pilot[complaint_raised_after_session_rate] )", "0.0%"),
    ("F AI pilot", "Assistant CSAT", "AVERAGE ( ai_pilot[assistant_csat_of_5] )", "0.00"),
    ("G Scenarios", "Score plan method", "AVERAGE ( scenarios[score_static] )", "0.00"),
    ("G Scenarios", "Score backlog-aware", "AVERAGE ( scenarios[score_queue] )", "0.00"),
    ("G Scenarios", "Scenario backlog", "AVERAGE ( scenarios[backlog] )", "#,0"),
    ("G Scenarios", "Score month 12 plan", "CALCULATE ( [Score plan method], scenarios[month_index] = 12 )", "0.00"),
    ("G Scenarios", "Score month 12 backlog-aware",
     "CALCULATE ( [Score backlog-aware], scenarios[month_index] = 12 )", "0.00"),
    ("G Scenarios", "Backlog month 12", "CALCULATE ( [Scenario backlog], scenarios[month_index] = 12 )", "#,0"),
    ("G Scenarios", "Saving a year",
     "CALCULATE ( SUM ( scenarios[handling_saving] ), scenarios[month_index] = 12 ) * 12 / 1000", K),
    ("G Scenarios", "Reaches 4.0 (plan)",
     'VAR m = CALCULATE ( MIN ( scenarios[month_index] ), scenarios[score_static] >= 4 )\n'
     'RETURN IF ( ISBLANK ( m ), "Not reached", "Month " & m )', None),
    ("G Scenarios", "Reaches 4.0 (backlog-aware)",
     'VAR m = CALCULATE ( MIN ( scenarios[month_index] ), scenarios[score_queue] >= 4 )\n'
     'RETURN IF ( ISBLANK ( m ), "Not reached", "Month " & m )', None),
    ("H What-if", "Lever rows", "COUNTROWS ( lever_grid )", "#,0"),
    ("H What-if", "What-if score plan", "IF ( [Lever rows] = 1, SUM ( lever_grid[score_static_month12] ) )", "0.00"),
    ("H What-if", "What-if score backlog-aware",
     "IF ( [Lever rows] = 1, SUM ( lever_grid[score_queue_month12] ) )", "0.00"),
    ("H What-if", "What-if days", "IF ( [Lever rows] = 1, SUM ( lever_grid[avg_days_month12] ) )", "0.0"),
    ("H What-if", "What-if backlog", "IF ( [Lever rows] = 1, SUM ( lever_grid[backlog_month12] ) )", "#,0"),
    ("H What-if", "What-if saving a year",
     "IF ( [Lever rows] = 1, SUM ( lever_grid[annual_saving_full_effect] ) / 1000 )", K),
    ("H What-if", "What-if verdict",
     'IF ( [Lever rows] <> 1, "Pick one level on each of the four levers",\n'
     '    IF ( [What-if score plan] >= 4, "4.0 reached, even on the plan method",\n'
     '        IF ( [What-if score backlog-aware] >= 4, "4.0 only if the backlog clears", "4.0 not reached" ) ) )',
     None),
]


def model_bim() -> dict:
    tables = []
    for t, rel in TABLES.items():
        cols = _columns(t, rel)
        columns = [_col(t, c, d) for c, d, _ in cols]
        if t == "complaint_360":
            columns += [
                _calc(t, "Transferred?", 'IF ( complaint_360[transferred_between_systems] = 1, "Transferred", '
                                         '"Not transferred" )'),
                _calc(t, "Intake system", 'complaint_360[source_system_name] & " (" & complaint_360[source_system] '
                                          '& ")"'),
                _calc(t, "Quarter", 'FORMAT ( complaint_360[date_opened], "yyyy" ) & " Q" & '
                                    'FORMAT ( complaint_360[date_opened], "q" )'),
            ]
        if t == "scenarios":
            cases = ", ".join(f'"{k}", "{v}"' for k, v in SCEN_SHORT.items())
            columns.append(_calc(t, "Scenario", f"SWITCH ( scenarios[scenario_id], {cases}, scenarios[scenario_name] )"))
        if any(c == "month" for c, _, _ in cols):              # a real date, so line charts get a date axis
            columns.append(_calc(t, "Month start", f"DATE ( VALUE ( LEFT ( {t}[month], 4 ) ), "
                                                   f"VALUE ( RIGHT ( {t}[month], 2 ) ), 1 )", "mmm yyyy", "dateTime"))
        tables.append({"name": t, "lineageTag": gid(t), "columns": columns,
                       "partitions": [{"name": t, "mode": "import",
                                       "source": {"type": "m", "expression": _m_csv(rel, cols)}}],
                       "annotations": [{"name": "PBI_ResultType", "value": "Table"}]})
    rows = ", ".join(f'{{"{r}", "{"Smart-meter region" if r in SMART_REGIONS else "No smart meters"}"}}'
                     for r in REGIONS)
    tables.append({"name": "Regions", "lineageTag": gid("Regions"),
                   "columns": [_col("Regions", "region", "string"), _col("Regions", "Meters", "string")],
                   "partitions": [{"name": "Regions", "mode": "import", "source": {"type": "m", "expression": [
                       "let", f"    Source = #table(type table [region = text, Meters = text], {{{rows}}})",
                       "in", "    Source"]}}],
                   "annotations": [{"name": "PBI_ResultType", "value": "Table"}]})
    mcol = _col("_Measures", "Column1", "string")
    mcol["isHidden"] = True
    tables.append({"name": "_Measures", "lineageTag": gid("_Measures"), "columns": [mcol],
                   "measures": [dict({"name": n, "expression": e.split("\n"), "displayFolder": f,
                                      "lineageTag": gid("m", n)}, **({"formatString": fs} if fs else {}))
                                for f, n, e, fs in MEASURES],
                   "partitions": [{"name": "_Measures", "mode": "import", "source": {"type": "m", "expression": [
                       "let", "    Source = #table(type table [Column1 = text], {})", "in", "    Source"]}}],
                   "annotations": [{"name": "PBI_ResultType", "value": "Table"}]})
    rels = [{"name": gid("rel", t), "fromTable": t, "fromColumn": "region", "toTable": "Regions", "toColumn": "region"}
            for t in ("complaint_360", "region_month")]
    folder = str(DATA)
    return {
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-US",
            "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-US",
            "tables": tables,
            "relationships": rels,
            "expressions": [{"name": "DataFolder", "kind": "m", "lineageTag": gid("DataFolder"),
                             "expression": f'"{folder}" meta [IsParameterQuery = true, Type = "Text", '
                                           'IsParameterQueryRequired = true]',
                             "annotations": [{"name": "PBI_ResultType", "value": "Text"}]}],
            "annotations": [{"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
                            {"name": "PBI_QueryOrder",
                             "value": json.dumps(["DataFolder", *TABLES, "Regions", "_Measures"])}],
        },
    }


# --------------------------------------------------------------------------- report helpers
def lit(v):
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, int):
        s = f"{v}L"
    elif isinstance(v, float):
        s = f"{v}D"
    else:
        s = "'" + str(v).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": s}}}


def solid(hex_):
    return {"solid": {"color": lit(hex_)}}


def M(name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": name}}


def C(table, name):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def P(field, display=None):
    if "Measure" in field:
        ref = f'_Measures.{field["Measure"]["Property"]}'
    else:
        ref = f'{field["Column"]["Expression"]["SourceRef"]["Entity"]}.{field["Column"]["Property"]}'
    p = {"field": field, "queryRef": ref, "nativeQueryRef": ref.split(".", 1)[1]}
    if display:
        p["displayName"] = display
    return p


def scope(column_field, value):
    return {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0, "Left": column_field,
                                                 "Right": {"Literal": {"Value": "'" + value.replace("'", "''") + "'"}}}}}]}


def para(text, size=11, bold=False, color=INK, italic=False):
    st = {"fontFamily": "Segoe UI Semibold" if bold else "Segoe UI", "fontSize": f"{size}pt", "color": color}
    if bold:
        st["fontWeight"] = "bold"
    if italic:
        st["fontStyle"] = "italic"
    return {"textRuns": [{"value": text, "textStyle": st}]}


class Page:
    def __init__(self, key, display, eyebrow, title):
        self.key, self.display, self.visuals, self.z = key, display, [], 0
        self.text("head", 24, 10, 1232, 70, [para(eyebrow.upper(), 9, True, MUTED), para(title, 19, True)],
                  frame=False)

    def add(self, name, x, y, w, h, vtype, roles=None, *, title=None, sub=None, objects=None, sort=None,
            frame=True, extra_vco=None):
        self.z += 1
        vis = {"visualType": vtype}
        if roles:
            vis["query"] = {"queryState": {r: {"projections": ps} for r, ps in roles.items()}}
            if sort:
                field, direction = sort
                vis["query"]["sortDefinition"] = {"sort": [{"field": field, "direction": direction}],
                                                  "isDefaultSort": False}
        if objects:
            vis["objects"] = objects
        vco = {}
        if title is not None:
            vco["title"] = [{"properties": {"show": lit(True), "text": lit(title), "fontColor": solid(INK),
                                            "fontSize": lit(12.0), "bold": lit(True), "titleWrap": lit(True)}}]
        else:
            vco["title"] = [{"properties": {"show": lit(False)}}]
        if sub:
            vco["subTitle"] = [{"properties": {"show": lit(True), "text": lit(sub), "fontColor": solid(MUTED),
                                               "fontSize": lit(9.0)}}]
        vco["background"] = [{"properties": {"show": lit(frame), "color": solid("#FFFFFF"),
                                             "transparency": lit(0.0)}}]
        vco["border"] = [{"properties": {"show": lit(frame), "color": solid(RULE), "radius": lit(8.0)}}]
        vco["padding"] = [{"properties": {"top": lit(8.0), "bottom": lit(8.0), "left": lit(10.0), "right": lit(10.0)}}]
        vco.update(extra_vco or {})
        vis["visualContainerObjects"] = vco
        name = f"{self.key}_{name}"
        self.visuals.append({"$schema": S_VIS, "name": name,
                             "position": {"x": round(x, 2), "y": round(y, 2), "z": self.z * 1000,
                                          "height": round(h, 2), "width": round(w, 2), "tabOrder": self.z * 1000},
                             "visual": vis})

    def text(self, name, x, y, w, h, paragraphs, frame=True):
        self.add(name, x, y, w, h, "textbox", objects={"general": [{"properties": {"paragraphs": paragraphs}}]},
                 frame=frame)

    def card(self, name, x, y, w, h, measure, label, wrap=False, size=26.0):
        objs = {"labels": [{"properties": {"fontSize": lit(size), "color": solid(INK), "labelDisplayUnits": lit(1.0),
                                           "fontFamily": lit("Segoe UI Semibold")}}],
                "categoryLabels": [{"properties": {"show": lit(True), "color": solid(INK2), "fontSize": lit(10.0)}}]}
        if wrap:
            objs["wordWrap"] = [{"properties": {"show": lit(True)}}]
        self.add(name, x, y, w, h, "card", {"Values": [P(M(measure), label)]}, objects=objs)

    def line(self, name, x, y, w, h, cat, measures, *, title, sub=None, series=None, colors=None, series_colors=None,
             y_range=None, ref=None):
        roles = {"Category": [P(cat)], "Y": [P(M(m), d) for m, d in measures]}
        if series:
            roles["Series"] = [P(series)]
        objs = {"categoryAxis": [{"properties": {"showAxisTitle": lit(False), "fontSize": lit(9.0)}}],
                "valueAxis": [{"properties": {"showAxisTitle": lit(False), "fontSize": lit(9.0)}}],
                "legend": [{"properties": {"show": lit(True), "position": lit("Top"), "fontSize": lit(9.0),
                                           "showTitle": lit(False)}}],
                "lineStyles": [{"properties": {"strokeWidth": lit(3.0)}}]}
        if y_range:
            objs["valueAxis"][0]["properties"].update({"start": lit(float(y_range[0])), "end": lit(float(y_range[1]))})
        points = []
        for m, color in (colors or {}).items():
            points.append({"selector": {"metadata": f"_Measures.{m}"}, "properties": {"fill": solid(color)}})
        for value, color in (series_colors or {}).items():
            points.append({"selector": scope(series, value), "properties": {"fill": solid(color)}})
        if points:
            objs["dataPoint"] = points
        if ref:
            objs["y1AxisReferenceLine"] = [{"selector": {"id": "1"}, "properties": {
                "show": lit(True), "displayName": lit(ref[1]), "value": lit(float(ref[0])), "lineColor": solid(INK),
                "style": lit("dashed"), "transparency": lit(30.0), "dataLabelShow": lit(True),
                "dataLabelColor": solid(INK), "dataLabelText": lit("Name"), "dataLabelHorizontalPosition": lit("right"),
                "dataLabelVerticalPosition": lit("above")}}]
        self.add(name, x, y, w, h, "lineChart", roles, title=title, sub=sub, objects=objs, sort=(cat, "Ascending"))

    def bars(self, name, x, y, w, h, cat, measure, *, title, sub=None, vtype="clusteredBarChart", x_range=None,
             color=BLUE, highlight=None, sort_desc=True, display=None, label_units=None):
        objs = {"labels": [{"properties": {"show": lit(True), "fontSize": lit(9.0), "color": solid(INK)}}],
                "categoryAxis": [{"properties": {"showAxisTitle": lit(False), "fontSize": lit(9.0),
                                                 "maxMarginFactor": lit(45)}}],
                "valueAxis": [{"properties": {"showAxisTitle": lit(False), "fontSize": lit(8.0)}}],
                "dataPoint": [{"properties": {"fill": solid(color)}}]}
        if label_units:
            objs["labels"][0]["properties"]["labelDisplayUnits"] = lit(label_units)
        if x_range:
            objs["valueAxis"][0]["properties"].update({"start": lit(float(x_range[0])), "end": lit(float(x_range[1]))})
        for value, hc in (highlight or {}).items():
            objs["dataPoint"].append({"selector": scope(cat, value), "properties": {"fill": solid(hc)}})
        sort = (M(measure), "Descending") if sort_desc else (cat, "Ascending")
        self.add(name, x, y, w, h, vtype, {"Category": [P(cat)], "Y": [P(M(measure), display)]}, title=title, sub=sub,
                 objects=objs, sort=sort)

    def table(self, name, x, y, w, h, fields, *, title, sub=None, sort=None):
        objs = {"columnHeaders": [{"properties": {"fontSize": lit(10.0), "fontColor": solid(INK2), "bold": lit(True),
                                                  "wordWrap": lit(True)}}],
                "values": [{"properties": {"fontSize": lit(11.0), "fontColor": solid(INK)}}],
                "grid": [{"properties": {"rowPadding": lit(4.0), "gridHorizontal": lit(True),
                                         "gridHorizontalColor": solid(RULE)}}],
                "total": [{"properties": {"totals": lit(False)}}]}
        self.add(name, x, y, w, h, "tableEx", {"Values": [P(f, d) for f, d in fields]}, title=title, sub=sub,
                 objects=objs, sort=sort)

    def slicer(self, name, x, y, w, h, field, title):
        objs = {"data": [{"properties": {"mode": lit("Basic")}}],
                "general": [{"properties": {"orientation": lit(1.0)}}],
                "selection": [{"properties": {"strictSingleSelect": lit(True), "selectAllCheckboxEnabled": lit(False)}}],
                "header": [{"properties": {"show": lit(True), "text": lit(title), "fontColor": solid(INK),
                                           "textSize": lit(11.0), "bold": lit(True)}}],
                "items": [{"properties": {"textSize": lit(11.0), "fontColor": solid(INK)}}]}
        self.add(name, x, y, w, h, "slicer", {"Values": [P(field)]}, objects=objs)


# --------------------------------------------------------------------------- pages
def pages(F) -> list[Page]:
    s, t, nt, m, io, st = F["score"], F["cmp"]["t"], F["cmp"]["nt"], F["meters"], F["info"], F["staff"]
    rec = F["scen"]["recommended"]
    others = [r["rate"] for r in F["intake"] if r["sys"] != "SYS-04"]
    cal = st["agents"]["Calderfield"]
    days = [v["days"] for v in st["since"].values()]
    r_txt = f'r = {s["r"]:.2f}'.replace("-", "−")
    BM, RM, CX, SC, LG, AI = "backlog_month", "region_month", "complaint_360", "scenarios", "lever_grid", "ai_pilot"
    MS = "Month start"
    out = []
    X0, W = 24, 1232

    # 1 Summary
    p = Page("summary", "Summary", f'Northwind complaints · {F["period"][0]} to {F["period"][1]}',
             "The regulator score fell every month for two years, in step with how long complaints take to close")
    kp = [("Complaints", "Complaints"), ("Open complaints", "Still open"), ("Transfer rate", "Passed between systems"),
          ("Days today", "Days to close, Sep 2026"), ("Score today", "Regulator score, Sep 2026"),
          ("Days needed for 4.0", "Days to close needed for 4.0")]
    cw = (W - 5 * 12) / 6
    for i, (meas, label) in enumerate(kp):
        p.card(f"k{i}", X0 + i * (cw + 12), 92, cw, 104, meas, label)
    finds = [
        ("1 · The score follows the days", r_txt,
         f'Score {s["score"][0]:.2f} → {s["score"][-1]:.2f} while days to close rose {s["days"][0]:.1f} → '
         f'{s["days"][-1]:.1f}. 4.0 needs about {s["days_for_4"]:.0f} days.'),
        ("2 · Transfers come from the intake system", f'0% vs {min(others) * 100:.0f}–{max(others) * 100:.0f}%',
         f'CaseTrack never passes a complaint on; the other three intake systems pass on almost half. '
         f'A transfer adds {t["days"] - nt["days"]:.1f} days.'),
        ("3 · Billing ignores the smart meters", f'{m["pen"][0] * 100:.0f}% → {m["pen"][-1] * 100:.0f}%',
         f'Smart meters spread in four regions, yet estimated bills stayed at {m["est"][0] * 100:.0f}–'
         f'{m["est"][-1] * 100:.0f}%. {F["bill_meter_share"] * 100:.0f}% of complaints are billing and metering.'),
        ("4 · 1 in 4 only needed an answer", f'{io["share"] * 100:.1f}%',
         f'They still took {io["days"]:.1f} days. The 2025 AI assistant pilot got worse every month.'),
        ("5 · Calderfield is not the cause", f'{cal[0]:.0f} → {cal[-1]:.0f} agents',
         "It lost half its agents, yet its days to close match every other region."),
        ("6 · 4.0 needs the backlog to clear", f'4.0 by month {rec["reach_queue"]}',
         f'Per-case fixes alone stop at {rec["m12_static"]:.2f} (plan method). If the backlog clears as history '
         f'suggests, the recommended package reaches 4.0 in month {rec["reach_queue"]}.'),
    ]
    fw, fh = (W - 2 * 12) / 3, (704 - 212 - 12) / 2
    for i, (head, big, body) in enumerate(finds):
        p.text(f"f{i}", X0 + (i % 3) * (fw + 12), 212 + (i // 3) * (fh + 12), fw, fh,
               [para(head, 12, True), para(big, 24, True, BLUE), para(body, 11, False, INK2)])
    out.append(p)

    # 2 Score
    p = Page("score", "Score", "Finding 1 · The score", "The regulator score follows days to close")
    p.line("score", X0, 92, 608, 300, C(BM, MS), [("Regulator score", "Score"), ("Target 4.0", "Target")],
           title=f'Regulator score fell every month: {s["score"][0]:.2f} → {s["score"][-1]:.2f}',
           sub="Regulator satisfaction score (of 5), by month", colors={"Regulator score": BLUE, "Target 4.0": GREY})
    p.line("days", X0 + 624, 92, 608, 300, C(BM, MS), [("Avg days (KPI)", "Days to close"),
                                                              ("Needed for 4.0", "Needed for 4.0")],
           title=f'Days to close: {s["days"][-1]:.1f} now, {s["days_for_4"]:.1f} needed for 4.0',
           sub="Average days to close, complaints closed that month",
           colors={"Avg days (KPI)": ORANGE, "Needed for 4.0": GREY})
    p.add("scatter", X0, 404, 740, 300, "scatterChart",
          {"Category": [P(C(BM, "month"))], "X": [P(M("Avg days (KPI)"), "Days to close")],
           "Y": [P(M("Regulator score"), "Score")]},
          title=f"The score tracks days to close ({r_txt})",
          sub=f'Each dot is one month. Fit: score = {s["intercept"]:.3f} − {abs(s["slope"]):.3f} × days. '
              "A correlation, not proof of cause.",
          objects={"dataPoint": [{"properties": {"fill": solid(BLUE)}}],
                   "trend": [{"properties": {"show": lit(True), "lineColor": solid(INK), "style": lit("dashed")}}],
                   "categoryAxis": [{"properties": {"showAxisTitle": lit(True), "start": lit(0.0)}}],
                   "valueAxis": [{"properties": {"showAxisTitle": lit(True)}}]})
    p.line("backlog", X0 + 752, 404, 480, 300, C(BM, MS), [("Open backlog", "Open complaints")],
           title=f'The open backlog grew from {s["backlog"][0]:,} to {s["backlog"][-1]:,}',
           sub=f'Open complaints at month end. Days to close move with it (r = {s["r_backlog"]:.2f})',
           colors={"Open backlog": PURPLE})
    out.append(p)

    # 3 Transfers
    p = Page("transfers", "Transfers", "Finding 2 · Transfers",
             "Whether a complaint gets transferred depends on the system that took it in")
    p.bars("intake", X0, 92, 600, 300, C(CX, "Intake system"), "Transfer rate",
           title=f'CaseTrack 0%, the other intake systems {min(others) * 100:.0f}–{max(others) * 100:.0f}%',
           sub="Share of complaints transferred, by the system that took the complaint in", x_range=(0, 0.5),
           color=ORANGE, highlight={"CaseTrack (SYS-04)": BLUE})
    p.card("note", X0 + 616, 280, 616, 112, "CaseTrack note", "CaseTrack (SYS-04) system note, in the data pack",
           wrap=True, size=15.0)
    p.table("cmp", X0 + 616, 92, 616, 176,
            [(C(CX, "Transferred?"), ""), (M("Complaints"), "Complaints"), (M("Avg days to close"), "Avg days to close"),
             (M("SLA breach rate"), "Missed SLA"), (M("Reopen rate"), "Reopened"),
             (M("Avg handling cost"), "Handling cost")],
            title=f'A transfer adds {t["days"] - nt["days"]:.1f} days, and more breaches, reopens and cost',
            sub="All complaints; days to close counts closed complaints only")
    lo, hi = F["flat_lo"] * 100, F["flat_hi"] * 100
    for i, (col, label, x, w) in enumerate([("category", "Category", X0, 470), ("channel", "Channel", X0 + 482, 250),
                                            ("priority", "Priority", X0 + 744, 226),
                                            ("Quarter", "Quarter opened", X0 + 982, 250)]):
        p.bars(f"flat{i}", x, 404, w, 300, C(CX, col), "Transfer rate", title=f"By {label.lower()}",
               sub=f"Flat: {lo:.0f}–{hi:.0f}% whatever the complaint" if i == 0 else None, x_range=(0, 0.5),
               sort_desc=False)
    out.append(p)

    # 4 Billing
    p = Page("billing", "Billing", "Finding 3 · Billing and meters",
             "Billing and metering drive the volume, and billing still ignores the smart meters")
    hl = {r["label"]: ORANGE for r in F["categories"] if r["grp"] in ("Billing", "Metering")}
    p.bars("cats", X0, 92, 740, 330, C(CX, "category"), "Complaints",
           title=f'Billing and metering: {F["bill_meter_share"] * 100:.0f}% of complaints',
           sub="Complaints by category, all 24 months. Orange: billing and metering", color=GREY, highlight=hl,
           label_units=1.0)
    ch = (330 - 2 * 12) / 3
    for i, (meas, label) in enumerate([("Billing and metering share", "Complaints about bills and meter reads"),
                                       ("Billing fixed share", "Billing complaints ending in a correction or refund"),
                                       ("Estimated bills now (smart regions)",
                                        "Bills on an estimate in smart-meter regions, Sep 2026")]):
        p.card(f"k{i}", X0 + 752, 92 + i * (ch + 12), 480, ch, meas, label)
    p.line("meters", X0, 434, 740, 270, C(RM, MS),
           [("Smart meters (smart regions)", "Homes with a smart meter"),
            ("Estimated bills (smart regions)", "Bills on an estimate")],
           title=f'Smart meters {m["pen"][0] * 100:.0f}% → {m["pen"][-1] * 100:.0f}%; estimated bills '
                 f'{m["est"][0] * 100:.0f}% → {m["est"][-1] * 100:.0f}%',
           sub="Average of the four smart-meter regions (Ashford, Calderfield, Eastmarch, Fenwick)",
           colors={"Smart meters (smart regions)": BLUE, "Estimated bills (smart regions)": ORANGE}, y_range=(0, 1))
    top2 = [r["region"] for r in m["latest"] if r["est"] >= 0.5]
    p.bars("regions", X0 + 752, 434, 480, 270, C("Regions", "region"), "Estimated read rate latest",
           title=f'{" and ".join(top2)}: no smart meters, '
                                               f'{max(r["est"] for r in m["latest"]) * 100:.0f}% estimated',
           sub=f'Share of bills on an estimate, by region, {m["last_month"]}', highlight={r: ORANGE for r in top2},
           x_range=(0, 0.8))
    out.append(p)

    # 5 Answers & AI
    p = Page("answers", "Answers & AI", "Finding 4 · Answers and the AI pilot",
             "A quarter of complaints only needed an answer, and the AI pilot made things worse")
    cw = (W - 3 * 12) / 4
    for i, (meas, label) in enumerate([("Info-only complaints", "Complaints that only needed an answer"),
                                       ("Info-only share", "Share of all complaints"),
                                       ("Avg days info-only", "Average days to close them"),
                                       ("Transfer rate info-only", "Transferred between systems")]):
        p.card(f"k{i}", X0 + i * (cw + 12), 92, cw, 104, meas, label)
    ai = F["ai"]
    p.line("ai", X0, 208, 740, 496, C(AI, MS),
           [("Containment", "Fully contained"), ("Repeat contact in 7 days", "Repeat contact in 7 days"),
            ("Complaint after session", "Complaint after session")],
           title=f'AI pilot: contained {ai["fully_contained_rate"][0] * 100:.1f}% → '
                 f'{ai["fully_contained_rate"][-1] * 100:.1f}%, repeat contact '
                 f'{ai["repeat_contact_within_7_days_rate"][0] * 100:.1f}% → '
                 f'{ai["repeat_contact_within_7_days_rate"][-1] * 100:.1f}%',
           sub="Share of assistant sessions, by month, 2025. The assistant could not see a bill breakdown or case history",
           colors={"Containment": BLUE, "Repeat contact in 7 days": ORANGE, "Complaint after session": PURPLE},
           y_range=(0, 0.5))
    p.line("csat", X0 + 752, 208, 480, 496, C(AI, MS), [("Assistant CSAT", "CSAT")],
           title=f'Assistant CSAT {ai["assistant_csat_of_5"][0]:.2f} → {ai["assistant_csat_of_5"][-1]:.2f}',
           sub="Customer satisfaction with the assistant (of 5), by month, 2025", colors={"Assistant CSAT": PINK})
    out.append(p)

    # 6 Calderfield
    p = Page("calderfield", "Calderfield", "Finding 5 · Staffing",
             "Calderfield lost half its agents, and its results match every other region")
    p.line("agents", X0, 92, 740, 300, C(RM, MS), [("Agents", "Agents")], series=C("Regions", "region"),
           title=f"Calderfield lost half its agents ({cal[0]:.0f} → {cal[-1]:.0f})…",
           sub="Contact-centre agents (FTE) by region, by month",
           series_colors={r: (ORANGE if r == "Calderfield" else CTX) for r in REGIONS})
    p.bars("days", X0 + 752, 92, 480, 300, C("Regions", "region"), "Avg days since Mar 2026",
           title=f"…yet its days to close match every region ({min(days):.1f}–{max(days):.1f})",
           sub="Average days to close, complaints opened since March 2026", color=GREY,
           highlight={"Calderfield": ORANGE}, sort_desc=False, x_range=(0, 40))
    p.table("tbl", X0, 404, W, 300,
            [(C("Regions", "region"), "Region"), (M("Agents first month"), "Agents Oct 2024"),
             (M("Agents last month"), "Agents Sep 2026"), (M("Complaints since Mar 2026"), "Complaints since Mar 2026"),
             (M("Avg days since Mar 2026"), "Days to close"), (M("SLA breach since Mar 2026"), "Missed SLA"),
             (M("Transfer rate since Mar 2026"), "Transferred")],
            title="Region by region since March 2026",
            sub="Regions that kept their staff have the same days to close, breach rate and transfer rate")
    out.append(p)

    # 7 Reaching 4.0
    p = Page("reach", "Reaching 4.0", "Finding 6 · Reaching 4.0",
             "Per-case fixes alone don't reach 4.0; clearing the backlog does")
    names = SCEN_SHORT
    scol = {names["recommended"]: ORANGE, names["routing_fix"]: BLUE, names["everything_max"]: GREEN,
            names["client_ai_plan"]: PINK, names["status_quo"]: GREY}
    best = max(v["m12_static"] for v in F["scen"].values())
    for i, (meas, ttl, sub) in enumerate([
            ("Score plan method", f"Plan method: nothing reaches 4.0 (best {best:.2f})",
             "Regulator score, next 12 months, per-case savings only. Dashed line: target 4.0"),
            ("Score backlog-aware", f'Backlog-aware: the recommended package reaches 4.0 in month {rec["reach_queue"]}',
             "Regulator score, next 12 months, as the open backlog clears. Dashed line: target 4.0")]):
        p.line(f"line{i}", X0 + i * 624, 92, 608, 330, C(SC, MS), [(meas, "Score")],
               series=C(SC, "Scenario"), title=ttl, sub=sub, series_colors=scol, y_range=(1, 5),
               ref=(4, "Target 4.0"))
    p.table("tbl", X0, 434, W, 270,
            [(C(SC, "Scenario"), "Scenario"), (M("Score month 12 plan"), "Score, month 12 (plan method)"),
             (M("Score month 12 backlog-aware"), "Score, month 12 (backlog-aware)"),
             (M("Reaches 4.0 (backlog-aware)"), "Reaches 4.0 (backlog-aware)"),
             (M("Backlog month 12"), "Open backlog, month 12"), (M("Saving a year"), "Handling saving a year")],
            title="The five scenarios at month 12",
            sub=f'Backlog-aware: days also fall {F["queue_slope"]:.4f} per open complaint cleared (history, '
                f'r = {F["queue_r"]:.2f}). Source: scenario engine and assumptions.yaml',
            sort=(M("Score month 12 plan"), "Descending"))
    out.append(p)

    # 8 What-if
    p = Page("whatif", "What-if", "Try it · What-if",
             "What does each fix buy? Pick one level on each lever")
    for i, (col, label) in enumerate([("transfers_removed", "Transfers removed (OneCase)"),
                                      ("info_only_first_contact", "Answered at first contact"),
                                      ("estimated_read_reduction", "Estimate complaints avoided"),
                                      ("calderfield_agents_restored", "Calderfield agents restored")]):
        p.slicer(f"s{i}", X0, 92 + i * 124, 600, 112, C(LG, col), label)
    p.card("verdict", X0 + 616, 92, 616, 100, "What-if verdict", "Verdict at month 12", wrap=True, size=18.0)
    p.card("plan", X0 + 616, 204, 302, 112, "What-if score plan", "Score, month 12 (plan method)")
    p.card("queue", X0 + 930, 204, 302, 112, "What-if score backlog-aware", "Score, month 12 (backlog-aware)")
    cw = (616 - 24) / 3
    for i, (meas, label) in enumerate([("What-if days", "Days to close, month 12"),
                                       ("What-if backlog", "Open backlog, month 12"),
                                       ("What-if saving a year", "Handling saving a year")]):
        p.card(f"k{i}", X0 + 616 + i * (cw + 12), 328, cw, 112, meas, label, size=22.0)
    p.text("how", X0 + 616, 452, 616, 252, [
        para("How to read it", 12, True),
        para(f'Each lever has five levels (Calderfield agents: 0, 17 or 35). The grid holds all {len(F["grid"]["rows"])} '
             "combinations, run through the same scenario engine as the Reaching 4.0 page.", 11, False, INK2),
        para("Plan method: per-case savings subtracted from today's days to close. Backlog-aware: days also fall as "
             "the open backlog clears.", 11, False, INK2),
        para(f'Try 100% / 50% / 50% / 0: plan {F["grid"]["rows"]["100|50|50|0"][0]:.2f}, backlog-aware '
             f'{F["grid"]["rows"]["100|50|50|0"][1]:.2f}. Today: {s["score"][-1]:.2f}.', 11, True, INK)])
    out.append(p)

    # 9 Method
    p = Page("method", "Method", "Method and data", "Where every number comes from")
    r = F["rows"]
    p.text("data", X0, 92, 608, 612, [
        para("Data, loaded as-is (headers and types only)", 12, True),
        para(f'complaint_360: {r["complaint_360"]:,} rows, one per complaint, joined to its intake system, meter '
             "context, staffing and unit cost.", 11, False, INK2),
        para(f'backlog_month: {r["backlog_month"]} rows, the monthly KPI file plus the open backlog.', 11, False, INK2),
        para(f'region_month: {r["region_month"]} rows, region × month volumes, estimated reads, smart meters, agents.',
             10, False, INK2),
        para(f'scenarios: {r["scenarios"]} rows, five scenarios × 12 months from the scenario engine.', 11, False, INK2),
        para(f'lever_grid: {r["lever_grid"]} rows, every lever combination at month 12.', 11, False, INK2),
        para(f'ai_pilot: {r["ai_pilot"]} rows, the 2025 AI assistant pilot (data/raw).', 11, False, INK2),
        para("Regions: the six regions and whether they have smart meters (typed in the model).", 11, False, INK2),
        para(" ", 8),
        para("Where the files live", 12, True),
        para("The DataFolder parameter points at the project's data folder. If you move the project, change it in "
             "Transform data > Manage parameters, or rerun python run.py pbip.", 11, False, INK2),
    ])
    p.text("defs", X0 + 624, 92, 608, 612, [
        para("Definitions", 12, True),
        para("Transferred: passed from one system to another (transferred_between_systems = 1).", 11, False, INK2),
        para("Days to close: opened to closed; open complaints are left out of every average.", 11, False, INK2),
        para("Only needed an answer: flagged resolvable by information only (closed complaints).", 11, False, INK2),
        para("Handling cost: $121 for a transferred complaint, $68 otherwise (data pack unit costs).", 11, False, INK2),
        para(" ", 8),
        para("Models", 12, True),
        para(f'Score = {s["intercept"]:.3f} − {abs(s["slope"]):.4f} × days to close, least squares over 24 months '
             f'({r_txt}). 4.0 needs {s["days_for_4"]:.1f} days. Measures: Score slope per day, Score intercept, '
             "Score fit r.", 11, False, INK2),
        para("Plan method: each fix removes its per-case delay from today's mix of complaints.", 11, False, INK2),
        para(f'Backlog-aware: days also move with the open backlog (+{F["queue_slope"]:.4f} days per open complaint, '
             f'r = {F["queue_r"]:.2f}).', 11, False, INK2),
        para(" ", 8),
        para("Notes", 12, True),
        para("Findings 1–5 use only the Northwind data pack; the app's synthetic bills are not used. Payback is not "
             "shown: build and run costs are still TBD in assumptions.yaml.", 11, False, INK2),
    ])
    out.append(p)
    return out


THEME = {
    "name": "Northwind light",
    "dataColors": [BLUE, ORANGE, GREEN, "#EDA100", PINK, PURPLE, GREY, "#0F6283"],
    "background": "#FFFFFF", "foreground": INK, "tableAccent": BLUE,
    "good": GREEN, "neutral": GREY, "bad": "#C2302A",
    "textClasses": {
        "callout": {"fontSize": 26, "fontFace": "Segoe UI Semibold", "color": INK},
        "title": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": INK},
        "header": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": INK},
        "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": INK2},
    },
    "visualStyles": {
        "*": {"*": {
            "background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}}, "transparency": 0}],
            "border": [{"show": True, "color": {"solid": {"color": RULE}}, "radius": 8}],
            "dropShadow": [{"show": False}],
        }},
        "page": {"*": {
            "background": [{"color": {"solid": {"color": PAPER}}, "transparency": 0}],
            "outspace": [{"color": {"solid": {"color": PAPER}}, "transparency": 0}],
        }},
    },
}


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _clear(out):
    """Remove the previous build. OneDrive can hold a folder for a moment, so retry, then fall back to
    deleting files only (every folder is written again below)."""
    for _ in range(5):
        try:
            if out.exists():
                shutil.rmtree(out)
            return
        except PermissionError:
            time.sleep(1.5)
    for f in out.rglob("*"):
        if f.is_file():
            f.unlink()


def build(out=OUT) -> list[Page]:
    F = facts()
    _clear(out)
    sm, rp = out / f"{NAME}.SemanticModel", out / f"{NAME}.Report"
    _write(out / f"{NAME}.pbip", {"$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
                                  "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
                                  "settings": {"enableAutoRecovery": True}})
    _write(sm / "definition.pbism", {"$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
                                     "version": "4.0", "settings": {}})
    _write(sm / "model.bim", model_bim())
    for folder, kind in ((sm, "SemanticModel"), (rp, "Report")):
        _write(folder / ".platform", {
            "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": kind, "displayName": NAME},
            "config": {"version": "2.0", "logicalId": gid("item", kind)}})
    _write(rp / "definition.pbir", {"$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
                                    "version": "4.0",
                                    "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    d = rp / "definition"
    _write(d / "version.json", {"$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json",
                                "version": "2.0.0"})
    theme_file = "NorthwindLight.json"
    _write(rp / "StaticResources" / "RegisteredResources" / theme_file, THEME)
    _write(d / "report.json", {
        "$schema": f"{SCHEMA}/item/report/definition/report/{V['report']}/schema.json",
        "themeCollection": {"customTheme": {"name": theme_file, "reportVersionAtImport": V,
                                            "type": "RegisteredResources"}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": theme_file, "path": theme_file, "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True},
    })
    ps = pages(F)
    _write(d / "pages" / "pages.json", {"$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
                                        "pageOrder": [p.key for p in ps], "activePageName": ps[0].key})
    for p in ps:
        _write(d / "pages" / p.key / "page.json", {
            "$schema": S_PAGE, "name": p.key, "displayName": p.display, "displayOption": "FitToPage",
            "height": 720, "width": 1280,
            "objects": {"background": [{"properties": {"color": solid(PAPER), "transparency": lit(0.0)}}],
                        "outspace": [{"properties": {"color": solid(PAPER), "transparency": lit(0.0)}}]}})
        for v in p.visuals:
            _write(d / "pages" / p.key / "visuals" / v["name"] / "visual.json", v)
    (out / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
    return ps


def main() -> int:
    ps = build()
    print(f"wrote {OUT / (NAME + '.pbip')}: {len(ps)} pages, {sum(len(p.visuals) for p in ps)} visuals, "
          f"{len(MEASURES)} measures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
