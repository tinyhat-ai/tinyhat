#!/usr/bin/env python3
"""Render the Tinyhat report from a snapshot + an agent-written analysis.

Inputs:
- snapshot.json   (from gather_snapshot.py) — facts only
- analysis.json   (from the agent at invocation time) — editorial layer

If analysis.json is missing, this script falls back to sensible defaults
derived from the snapshot so the pipeline is always runnable end-to-end.
The fallbacks make the report useful but generic; the agent's job is to
replace the "what stands out" list and skill recommendations with
observations tied to *this* week's data.

Outputs:
- <output-dir>/report.md
- <output-dir>/report.html
- run-stamp.txt   (only if <output-dir> is the latest directory)
- archive/YYYY-MM-DD/report.{md,html}   (only when --archive is passed)

Retention: after writing, if --archive was used, the archive directory is
pruned back to at most 31 dated directories.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import tempfile
import webbrowser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PLUGIN_ROOT / "skills" / "review" / "templates"
DEFAULT_HOME_ROOT = Path.home() / ".claude" / "tinyhat"
DEFAULT_SNAPSHOT_PATH = Path(tempfile.gettempdir()) / "tinyhat-snapshot.json"
DEFAULT_ANALYSIS_PATH = Path(tempfile.gettempdir()) / "tinyhat-analysis.json"


# ---------------------------------------------------------------------------
# Fallback analysis — used when the agent hasn't written one.
# ---------------------------------------------------------------------------

def _format_compact(value: float) -> str:
    v = float(value)
    av = abs(v)
    if av >= 1_000_000_000:
        out = f"{v / 1_000_000_000:.2f}B"
    elif av >= 1_000_000:
        out = f"{v / 1_000_000:.1f}M"
    elif av >= 1_000:
        out = f"{v / 1_000:.1f}k"
    else:
        return f"{v:.0f}"
    return out.replace(".0B", "B").replace(".0M", "M").replace(".0k", "k")


def _fallback_headline(snapshot: dict) -> str:
    s = snapshot["stats"]
    return f"You have {s['installed_count']} skills installed. You used {s['active_count']} of them in the last {snapshot['meta']['window_days']} days."


def _fallback_standouts(snapshot: dict) -> list[str]:
    s = snapshot["stats"]
    out: list[str] = []
    if s["sessions_total"]:
        pct = 100 * s["sessions_with_skills"] / s["sessions_total"]
        phrase = "still a minority pattern" if pct < 35 else "already a visible pattern"
        out.append(
            f"Skills are {phrase}: {s['sessions_with_skills']} of {s['sessions_total']} recent sessions showed at least one detected skill."
        )
    if s["skill_runs_total"] and s["turns_total"]:
        per_1k = s["skill_runs_total"] * 1000 / s["turns_total"]
        out.append(
            f"The {s['skill_runs_total']} skill runs sit inside {s['sessions_total']} sessions, {s['turns_total']:,} turns, and {s['tokens_total_compact']} total token activity, or about {per_1k:.2f} skill runs per 1k turns."
        )
    counts = Counter(snapshot.get("skill_counts") or {})
    if counts:
        total = sum(counts.values())
        top3 = sum(n for _, n in counts.most_common(3))
        if total:
            out.append(
                f"Usage is concentrated: the top 3 skills account for {100 * top3 / total:.0f}% of the {total} skill runs detected."
            )
    if s["installed_count"]:
        dormant = s["installed_count"] - s["active_count"]
        out.append(
            f"Most of the surface looks dormant: {dormant} of {s['installed_count']} installed skills had no detected use in the last {snapshot['meta']['window_days']} days."
        )
    return out[:5]


def _fallback_recommendations(snapshot: dict) -> list[dict]:
    sessions = snapshot.get("sessions", [])
    recs: list[dict] = []

    impl = [
        r for r in sessions
        if r["tool_uses"].get("Edit", 0) >= 15 and r["tool_uses"].get("Bash", 0) >= 15
    ]
    if len(impl) >= 2:
        te = sum(r["tool_uses"].get("Edit", 0) for r in impl)
        tb = sum(r["tool_uses"].get("Bash", 0) for r in impl)
        recs.append({
            "name": "implement-feature",
            "confidence": "high",
            "headline": "Shape the heavy implementation runs you already do.",
            "why": f"{len(impl)} recent sessions leaned hard on Edit + Bash ({te} edits, {tb} shell calls), which points to a repeatable build-fix-verify workflow worth turning into a skill.",
            "triggers": ["implement", "fix", "add support for", "update the code"],
        })

    explore = [
        r for r in sessions
        if r["tool_uses"].get("Read", 0) >= 25 and r["tool_uses"].get("Grep", 0) >= 5
    ]
    if len(explore) >= 2:
        tr = sum(r["tool_uses"].get("Read", 0) for r in explore)
        tg = sum(r["tool_uses"].get("Grep", 0) for r in explore)
        recs.append({
            "name": "explore-codebase",
            "confidence": "high" if len(explore) >= 5 else "medium",
            "headline": "Standardize the understand-before-editing workflow.",
            "why": f"{len(explore)} recent sessions were dominated by Read + Grep ({tr} reads, {tg} searches). A focused exploration skill could make those investigations faster and more consistent.",
            "triggers": ["how does", "where is", "trace", "walk me through"],
        })

    research = [
        r for r in sessions
        if r["tool_uses"].get("WebSearch", 0) + r["tool_uses"].get("WebFetch", 0) >= 4
    ]
    if len(research) >= 2:
        tw = sum(r["tool_uses"].get("WebSearch", 0) + r["tool_uses"].get("WebFetch", 0) for r in research)
        recs.append({
            "name": "research-and-write-brief",
            "confidence": "medium",
            "headline": "Turn repeated research-plus-writing into one polished move.",
            "why": f"{len(research)} recent sessions mixed web lookups with writing ({tw} web calls). That pattern usually benefits from a dedicated research-to-brief skill.",
            "triggers": ["research", "look up", "summarize", "write a brief"],
        })
    return recs[:3]


def _fallback_dormant_commentary(snapshot: dict) -> str:
    s = snapshot["stats"]
    dormant = s["installed_count"] - s["active_count"]
    if not dormant:
        return "Nothing dormant — every installed skill fired at least once in the window."
    by_origin = snapshot.get("dormant_by_origin", {})
    top = sorted(by_origin.items(), key=lambda kv: -len(kv[1]))[:2]
    phrases = ", ".join(f"{len(v)} from {k}" for k, v in top) or "mixed origins"
    return (
        f"{dormant} of {s['installed_count']} installed skills showed no detected use. "
        f"The bulk is {phrases} — worth a look when you trim."
    )


def _fallback_coverage_note(snapshot: dict) -> str:
    c = snapshot["coverage"]
    parts = [
        f"Scanned {c['cli_transcripts']} Claude Code transcripts and {c['cowork_transcripts']} Cowork transcripts from local disk.",
    ]
    if c["gstack_telemetry_present"]:
        parts.append(f"Found local GStack telemetry ({c['gstack_events']} recent events) and kept the ranking anchored to transcript-backed inventory matches.")
    else:
        parts.append("No local GStack telemetry file was used in this run.")
    if c["unknown_event_count"]:
        parts.append(f"Ignored {c['unknown_event_count']} events under {c['unknown_name_count']} unknown names.")
    if c["bare_read_skill_md_count"]:
        parts.append(f"Dropped {c['bare_read_skill_md_count']} bare Read SKILL.md events as likely false positives.")
    parts.append("Counts use only local data and blend direct Skill calls with likely Read SKILL.md matches, so ties and one-off rows are directional.")
    return " ".join(parts)


def analysis_with_fallbacks(snapshot: dict, analysis: dict | None) -> dict:
    analysis = dict(analysis or {})
    analysis.setdefault("headline", _fallback_headline(snapshot))
    analysis.setdefault("headline_sub", "Everything else on this page is supporting evidence for that headline.")
    analysis.setdefault("what_stands_out", _fallback_standouts(snapshot))
    analysis.setdefault("dormant_commentary", _fallback_dormant_commentary(snapshot))
    analysis.setdefault("skill_recommendations", _fallback_recommendations(snapshot))
    analysis.setdefault("coverage_note", _fallback_coverage_note(snapshot))
    return analysis


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _md_table_rows(rows: list[list[str]]) -> str:
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def render_markdown(snapshot: dict, analysis: dict) -> str:
    tpl = (TEMPLATE_DIR / "report.md.tmpl").read_text(encoding="utf-8")
    s = snapshot["stats"]
    meta = snapshot["meta"]

    generated = datetime.fromisoformat(meta["generated_at"])
    window_label = f"last {meta['window_days']} days"

    standouts = "\n".join(f"- {line}" for line in analysis["what_stands_out"]) or "- (no observations)"

    top_rows: list[list[str]] = []
    for s_row in snapshot.get("top_skills", [])[:6]:
        summary = s_row["summary"] or "No short description found in the local skill file."
        top_rows.append([
            f"`{s_row['skill']}`", summary.replace("|", "\\|"),
            str(s_row["runs"]), s_row["last_used"] or "—",
        ])
    top_skills_table = _md_table_rows(top_rows) if top_rows else "| (no active skills) |  |  |  |"

    unused_count = s["installed_count"] - s["active_count"]
    unused_pct = int(100 * unused_count / s["installed_count"]) if s["installed_count"] else 0
    dormant_rows: list[list[str]] = []
    for origin, names in sorted(snapshot.get("dormant_by_origin", {}).items(), key=lambda kv: -len(kv[1])):
        dormant_rows.append([origin, str(len(names))])
    dormant_table = _md_table_rows(dormant_rows) if dormant_rows else "| (none) | 0 |"

    rec_lines = []
    for rec in analysis["skill_recommendations"]:
        rec_lines.append(f"- `{rec['name']}` — {rec['why']}")
    recommendations_md = "\n".join(rec_lines) or "- No clear recommendation stood out from recent session patterns."

    coverage_md = f"- {analysis['coverage_note']}"

    out = tpl
    substitutions = {
        "WINDOW_LABEL": window_label,
        "GENERATED_AT": generated.strftime("%Y-%m-%d %H:%M UTC"),
        "HEADLINE": analysis["headline"],
        "INSTALLED_COUNT": s["installed_count"],
        "ACTIVE_COUNT": s["active_count"],
        "SKILL_RUNS_TOTAL": s["skill_runs_total"],
        "SESSIONS_TOTAL": s["sessions_total"],
        "SESSIONS_WITH_SKILLS": s["sessions_with_skills"],
        "TURNS_TOTAL": f"{s['turns_total']:,}",
        "TOKENS_TOTAL_COMPACT": s["tokens_total_compact"],
        "STANDOUTS_MD": standouts,
        "TOP_SKILLS_TABLE": top_skills_table,
        "UNUSED_COUNT": unused_count,
        "UNUSED_PCT": unused_pct,
        "DORMANT_COMMENTARY": analysis["dormant_commentary"],
        "DORMANT_TABLE": dormant_table,
        "RECOMMENDATIONS_MD": recommendations_md,
        "COVERAGE_MD": coverage_md,
    }
    for key, value in substitutions.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _svg_bar_chart(
    points: list[dict], key: str, color: str, value_label: str,
    *, label_key: str = "date", width: int = 520, height: int = 240,
    y_axis_title: str | None = None, x_axis_title: str | None = None,
) -> str:
    if not points:
        return '<p class="small">No data available.</p>'
    margin_left = 50 if y_axis_title else 36
    margin_right = 12
    margin_top = 18
    margin_bottom = 44 if x_axis_title else 32
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    values = [max(0, p.get(key, 0)) for p in points]
    max_v = max(values) or 1
    n = len(points)
    gap = 8
    bar_w = max(12, int((plot_w - gap * max(n - 1, 0)) / max(n, 1)))
    total_w = n * bar_w + max(n - 1, 0) * gap
    start_x = margin_left + max(0, (plot_w - total_w) / 2)

    grid_steps = 4
    grid = []
    for step in range(grid_steps + 1):
        y = margin_top + plot_h - (plot_h * step / grid_steps)
        grid.append((y, _format_compact(max_v * step / grid_steps)))

    bars = []
    for idx, point in enumerate(points):
        val = max(0, point.get(key, 0))
        label = str(point.get(label_key, ""))
        short = label[5:] if label_key == "date" and len(label) == 10 else label
        x = start_x + idx * (bar_w + gap)
        bh = 0 if max_v == 0 else (val / max_v) * plot_h
        y = margin_top + plot_h - bh
        value_txt = _format_compact(val)
        inside = bh > 26
        value_y = (y + 14) if inside else max(margin_top + 10, y - 4)
        value_cls = "chart-value inside" if inside else "chart-value"
        bars.append(
            f'<g><rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{bh:.1f}" rx="6" fill="{color}">'
            f'<title>{html.escape(label)}: {value_txt} {html.escape(value_label)}</title></rect>'
            f'<text x="{x + bar_w/2:.1f}" y="{value_y:.1f}" text-anchor="middle" class="{value_cls}">{html.escape(value_txt)}</text>'
            f'<text x="{x + bar_w/2:.1f}" y="{height - margin_bottom + 14:.1f}" text-anchor="middle" class="chart-label">{html.escape(short)}</text></g>'
        )

    grid_lines = []
    for y, lbl in grid:
        grid_lines.append(
            f'<g><line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" class="chart-grid-line"/>'
            f'<text x="{margin_left - 8}" y="{y + 4:.1f}" text-anchor="end" class="chart-axis-label">{html.escape(lbl)}</text></g>'
        )

    axis = []
    if y_axis_title:
        axis.append(
            f'<text x="{margin_left - 40}" y="{margin_top + plot_h/2:.1f}" text-anchor="middle" class="chart-axis-title" '
            f'transform="rotate(-90 {margin_left - 40} {margin_top + plot_h/2:.1f})">{html.escape(y_axis_title)}</text>'
        )
    if x_axis_title:
        axis.append(
            f'<text x="{margin_left + plot_w/2:.1f}" y="{height - 4}" text-anchor="middle" class="chart-axis-title">{html.escape(x_axis_title)}</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" aria-label="{html.escape(value_label)}" preserveAspectRatio="xMidYMid meet">'
        f'{"".join(grid_lines)}{"".join(bars)}{"".join(axis)}</svg>'
    )


def _surface_label(s: str) -> str:
    return {"cli_terminal": "CLI", "desktop_code_tab": "Desktop Code tab", "cowork": "Cowork"}.get(s, s)


def _origin_slug(origin: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", origin.lower()).strip("-") or "group"


def render_html(snapshot: dict, analysis: dict) -> str:
    tpl = (TEMPLATE_DIR / "report.html.tmpl").read_text(encoding="utf-8")
    # Inline CSS from sibling file so edits don't require touching a
    # quoted string inside the template. Template references {{CSS}}.
    css_path = TEMPLATE_DIR / "report.css"
    css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""
    s = snapshot["stats"]
    meta = snapshot["meta"]

    generated = datetime.fromisoformat(meta["generated_at"])
    window_label = f"last {meta['window_days']} days"

    installed = s["installed_count"]
    active = s["active_count"]
    util_pct = (100 * active / installed) if installed else 0
    sess_total = s["sessions_total"]
    sess_skill_pct = (100 * s["sessions_with_skills"] / sess_total) if sess_total else 0

    standouts_html = "\n".join(f"<li>{html.escape(item)}</li>" for item in analysis["what_stands_out"])

    # Recommendation cards
    rec_cards = []
    for idx, rec in enumerate(analysis["skill_recommendations"], 1):
        triggers_html = " ".join(
            f'<span class="chip chip-soft">&ldquo;{html.escape(t)}&rdquo;</span>' for t in rec.get("triggers", [])
        )
        rec_cards.append(
            f'<article class="recommend-card">'
            f'<div class="recommend-top"><div class="recommend-title">'
            f'<span class="eyebrow">Recommended #{idx}</span>'
            f'<h3><code>{html.escape(rec["name"])}</code></h3>'
            f'<p class="recommend-headline">{html.escape(rec.get("headline",""))}</p></div>'
            f'<span class="pill conf-{html.escape(rec.get("confidence","medium"))}">{html.escape(rec.get("confidence","medium"))} confidence</span>'
            f'</div>'
            f'<div><span class="recommend-section-label">Why this would help</span><p>{html.escape(rec.get("why",""))}</p></div>'
            f'<div><span class="recommend-section-label">Trigger phrases</span><div class="chips">{triggers_html}</div></div>'
            f'<div class="recommend-action-row">'
            f'<button class="action-btn" type="button" disabled>Create this skill →</button>'
            f'<span class="small">Prototype — v0 does not auto-create skills.</span>'
            f'</div></article>'
        )
    if not rec_cards:
        rec_cards.append('<article class="recommend-card"><p class="small">No strong recommendation stood out. Run Tinyhat again after another week of work — patterns usually emerge with more sessions.</p></article>')

    # Dormant cards (origin-grouped)
    dormant_cards = []
    by_origin = snapshot.get("dormant_by_origin", {})
    installed_by_origin = snapshot.get("installed_by_origin", {})
    inventory = snapshot.get("inventory", {})
    for origin, names in sorted(by_origin.items(), key=lambda kv: -len(kv[1])):
        dormant_n = len(names)
        installed_n = installed_by_origin.get(origin, dormant_n)
        pct = 100 * dormant_n / installed_n if installed_n else 0
        slug = _origin_slug(origin)
        rows = []
        for name in names:
            meta_i = inventory.get(name, {})
            summary = (meta_i.get("summary") or "No short description found in the local skill file.").strip()
            rows.append(
                f'<label class="cleanup-row">'
                f'<input type="checkbox" class="cleanup-check" data-skill="{html.escape(name)}" data-origin="{html.escape(slug)}"/>'
                f'<span><span class="cleanup-name"><code>{html.escape(name)}</code></span><br>'
                f'<span class="cleanup-summary">{html.escape(summary)}</span></span></label>'
            )
        dormant_cards.append(
            f'<article class="dormant-card">'
            f'<header class="dormant-head"><div><div class="kicker">Origin</div><h3>{html.escape(origin)}</h3></div>'
            f'<div class="dormant-metric"><span class="n">{dormant_n}</span><span class="label">dormant of {installed_n}</span></div></header>'
            f'<div class="dormant-bar"><div class="dormant-bar-fill" style="width:{pct:.1f}%"></div><span class="dormant-bar-label">{pct:.0f}% dormant</span></div>'
            f'<details class="dormant-skills"><summary>Show {dormant_n} dormant skill{"s" if dormant_n != 1 else ""}</summary>'
            f'<div class="cleanup-rows">{"".join(rows)}</div></details>'
            f'</article>'
        )
    if not dormant_cards:
        dormant_cards.append('<article class="dormant-card"><p class="small">Nothing dormant — every installed skill fired at least once.</p></article>')

    # Top skill cards
    top_cards = []
    counts = snapshot.get("skill_counts", {})
    max_runs = max(counts.values()) if counts else 1
    for row in snapshot.get("top_skills", [])[:8]:
        summary = row["summary"] or "No short description found in the local skill file."
        pack_label = row.get("origin") or "Local skill"
        width = max(10, int((row["runs"] / max_runs) * 100))
        top_cards.append(
            f'<article class="skill-card">'
            f'<div><div class="kicker">{html.escape(pack_label)}</div><h3><code>{html.escape(row["skill"])}</code></h3></div>'
            f'<div class="skill-metric"><span class="n">{row["runs"]}</span><span class="label">runs</span></div>'
            f'<p class="skill-summary">{html.escape(summary)}</p>'
            f'<div class="bar"><span style="width:{width}%"></span></div>'
            f'<p class="skill-foot">Last used {html.escape(row["last_used"] or "—")}</p>'
            f'</article>'
        )
    if not top_cards:
        top_cards.append('<article class="skill-card"><p class="small">No active skills in the window.</p></article>')

    # Session cards
    sessions = snapshot.get("sessions", [])
    session_cards = []
    for row in sessions:
        last_ts = row.get("last_ts") or ""
        title = row.get("title") or row.get("project") or "Untitled session"
        skill_chips = " ".join(
            f'<span class="chip">{html.escape(k)} · {v}</span>'
            for k, v in sorted(row.get("skill_counter", {}).items(), key=lambda kv: -kv[1])[:4]
        ) or '<span class="chip chip-soft">No named skills</span>'
        top_tools = sorted(row.get("tool_uses", {}).items(), key=lambda kv: -kv[1])[:5]
        tool_chips = " ".join(
            f'<span class="chip chip-soft">{html.escape(t)} · {n}</span>' for t, n in top_tools
        ) or '<span class="chip chip-soft">No tool data</span>'
        session_cards.append(
            f'<details class="session-item" data-skill-runs="{row["skill_runs"]}" '
            f'data-surface="{html.escape(row["surface"])}" data-project="{html.escape(row["project"])}" '
            f'data-last-ts="{html.escape(last_ts)}">'
            f'<summary><div><div class="session-title">{html.escape(title)}</div>'
            f'<div class="session-sub">{html.escape(_surface_label(row["surface"]))} · {html.escape(row["project"])}</div></div>'
            f'<div class="session-meta"><span class="meta-chip">{html.escape(row.get("last_used") or "—")}</span>'
            f'<span class="meta-chip">{row["skill_runs"]} runs</span></div></summary>'
            f'<div class="session-body">'
            f'<div class="mini-grid">'
            f'<div class="mini-card"><div class="mini-n">{row["turns"]}</div><div class="mini-label">Turns</div></div>'
            f'<div class="mini-card"><div class="mini-n">{row["total_tool_uses"]}</div><div class="mini-label">Tool calls</div></div>'
            f'<div class="mini-card"><div class="mini-n">{_format_compact(row["tokens_total"])}</div><div class="mini-label">Tokens</div></div>'
            f'<div class="mini-card"><div class="mini-n">{len(row.get("skill_counter", {}))}</div><div class="mini-label">Unique skills</div></div>'
            f'</div>'
            f'<p class="small" style="margin-top:10px;"><strong>Skills:</strong></p><div class="chips">{skill_chips}</div>'
            f'<p class="small" style="margin-top:10px;"><strong>Heaviest tools:</strong></p><div class="chips">{tool_chips}</div>'
            f'</div></details>'
        )
    if not session_cards:
        session_cards.append('<p class="small">No recent sessions in the window.</p>')

    # Filter chips
    surfaces_seen = sorted({r["surface"] for r in sessions})
    projects_seen = sorted({r["project"] for r in sessions if r["project"]})

    sort_chips = (
        '<button type="button" class="chip-btn active" data-sort="skill-desc">Most skills first</button>'
        '<button type="button" class="chip-btn" data-sort="recent">Most recent first</button>'
    )
    surface_chips = '<button type="button" class="chip-btn active" data-surface="all">All</button>' + "".join(
        f'<button type="button" class="chip-btn" data-surface="{html.escape(s)}">{html.escape(_surface_label(s))}</button>'
        for s in surfaces_seen
    )
    project_chips = '<button type="button" class="chip-btn active" data-project="all">All</button>' + "".join(
        f'<button type="button" class="chip-btn" data-project="{html.escape(p)}">{html.escape(p)}</button>'
        for p in projects_seen
    )

    # Tools rows
    aggregate_tools = snapshot.get("aggregate_tools", [])
    max_tool = aggregate_tools[0]["calls"] if aggregate_tools else 1
    tools_rows = []
    for idx, t in enumerate(aggregate_tools):
        pct = int(100 * t["calls"] / max_tool) if max_tool else 0
        tools_rows.append(
            f'<div class="tools-row">'
            f'<span class="small">{idx + 1}</span>'
            f'<span><code>{html.escape(t["tool"])}</code></span>'
            f'<div class="tools-bar"><span style="width:{pct}%"></span></div>'
            f'<span class="small">{t["calls"]} / {t["sessions"]}s</span>'
            f'</div>'
        )
    if not tools_rows:
        tools_rows.append('<p class="small">No tool activity in the window.</p>')

    # Charts
    daily = snapshot.get("daily_rollups", [])
    chart_sessions = _svg_bar_chart(daily, "sessions", "#0f5c63", "sessions", y_axis_title="Sessions", x_axis_title="Day")
    chart_turns = _svg_bar_chart(daily, "turns", "#3f8c8d", "turns", y_axis_title="Turns", x_axis_title="Day")
    chart_tokens = _svg_bar_chart(daily, "tokens", "#b56b45", "tokens", y_axis_title="Tokens", x_axis_title="Day")
    surface_points = [{"date": _surface_label(k), "value": v} for k, v in snapshot.get("surface_rollups", {}).items()]
    chart_surfaces = _svg_bar_chart(surface_points, "value", "#7d8f52", "sessions", y_axis_title="Sessions", x_axis_title="Surface")

    # Coverage items
    c = snapshot["coverage"]
    cov_items = [
        f"Scanned {c['cli_transcripts']} Claude Code and {c['cowork_transcripts']} Cowork transcripts.",
        f"GStack telemetry: {'present' if c['gstack_telemetry_present'] else 'not present'} ({c['gstack_events']} events in window).",
        f"Ignored {c['unknown_event_count']} unresolved events under {c['unknown_name_count']} unknown names.",
        f"Dropped {c['bare_read_skill_md_count']} bare Read SKILL.md events as likely false positives.",
    ]
    coverage_items_html = "\n".join(f"<li>{html.escape(item)}</li>" for item in cov_items)

    unused_count = installed - active
    show_all_sessions_label = f"Show all {len(sessions)} sessions"
    show_all_tools_label = f"Show all {len(aggregate_tools)} tools"

    subs = {
        "CSS": css,
        "GENERATED_AT": generated.strftime("%Y-%m-%d %H:%M UTC"),
        "WINDOW_LABEL": window_label,
        "WINDOW_DAYS": meta["window_days"],
        "HEADLINE": analysis["headline"],
        "HEADLINE_SUB": analysis.get("headline_sub", ""),
        "INSTALLED_COUNT": installed,
        "ACTIVE_COUNT": active,
        "SKILL_RUNS_TOTAL": s["skill_runs_total"],
        "SESSIONS_TOTAL": sess_total,
        "SESSIONS_WITH_SKILLS": s["sessions_with_skills"],
        "TURNS_TOTAL_COMPACT": _format_compact(s["turns_total"]),
        "TOKENS_TOTAL_COMPACT": s["tokens_total_compact"],
        "UTILIZATION_PCT": f"{util_pct:.1f}",
        "UTILIZATION_PCT_INT": f"{util_pct:.0f}",
        "SESSION_SKILL_PCT": f"{sess_skill_pct:.1f}",
        "SESSION_SKILL_PCT_INT": f"{sess_skill_pct:.0f}",
        "UNUSED_COUNT": unused_count,
        "STANDOUTS_HTML": standouts_html,
        "DORMANT_COMMENTARY": analysis["dormant_commentary"],
        "DORMANT_CARDS": "\n".join(dormant_cards),
        "RECOMMENDATION_CARDS": "\n".join(rec_cards),
        "TOP_SKILL_CARDS": "\n".join(top_cards),
        "SESSION_CARDS": "\n".join(session_cards),
        "SORT_CHIPS": sort_chips,
        "SURFACE_CHIPS": surface_chips,
        "PROJECT_CHIPS": project_chips,
        "SHOW_ALL_SESSIONS_LABEL": show_all_sessions_label,
        "SHOW_ALL_TOOLS_LABEL": show_all_tools_label,
        "TOOLS_ROWS": "\n".join(tools_rows),
        "TOOLS_TOTAL": sum(t["calls"] for t in aggregate_tools),
        "TOOLS_COUNT": len(aggregate_tools),
        "CHART_SESSIONS": chart_sessions,
        "CHART_TURNS": chart_turns,
        "CHART_TOKENS": chart_tokens,
        "CHART_SURFACES": chart_surfaces,
        "COVERAGE_NOTE": analysis["coverage_note"],
        "COVERAGE_ITEMS": coverage_items_html,
    }
    out = tpl
    for key, value in subs.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out


# ---------------------------------------------------------------------------
# Archive + retention
# ---------------------------------------------------------------------------

def enforce_retention(archive_dir: Path, keep: int = 31) -> None:
    if not archive_dir.is_dir():
        return
    archives = sorted([p for p in archive_dir.iterdir() if p.is_dir()], key=lambda p: p.name)
    while len(archives) > keep:
        oldest = archives.pop(0)
        try:
            shutil.rmtree(oldest)
        except OSError as exc:
            print(f"retention: failed to remove {oldest}: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Tinyhat report.")
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT_PATH))
    parser.add_argument("--analysis", default=str(DEFAULT_ANALYSIS_PATH))
    parser.add_argument(
        "--home-root",
        default=str(DEFAULT_HOME_ROOT),
        help="Root directory for Tinyhat output (default: ~/.claude/tinyhat)",
    )
    parser.add_argument("--archive", action="store_true", help="Also write archive/YYYY-MM-DD/ snapshot and enforce retention.")
    parser.add_argument("--open", action="store_true", help="Open the rendered HTML in the default browser.")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.is_file():
        print(f"error: snapshot not found at {snapshot_path}. Run gather_snapshot.py first.", file=sys.stderr)
        return 1
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    analysis_path = Path(args.analysis)
    analysis_raw = None
    if analysis_path.is_file():
        try:
            analysis_raw = json.loads(analysis_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"warn: analysis JSON at {analysis_path} is invalid ({exc}); using fallbacks.", file=sys.stderr)
    analysis = analysis_with_fallbacks(snapshot, analysis_raw)

    home_root = Path(args.home_root).expanduser()
    latest_dir = home_root / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)

    md = render_markdown(snapshot, analysis)
    htmlout = render_html(snapshot, analysis)

    (latest_dir / "report.md").write_text(md, encoding="utf-8")
    (latest_dir / "report.html").write_text(htmlout, encoding="utf-8")

    today = datetime.now(timezone.utc).date().isoformat()
    (latest_dir / "run-stamp.txt").write_text(today + "\n", encoding="utf-8")

    if args.archive:
        archive_dir = home_root / "archive" / today
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "report.md").write_text(md, encoding="utf-8")
        (archive_dir / "report.html").write_text(htmlout, encoding="utf-8")
        enforce_retention(home_root / "archive", keep=31)

    print(f"Wrote {latest_dir / 'report.md'} and {latest_dir / 'report.html'}", file=sys.stderr)

    if args.open:
        try:
            webbrowser.open((latest_dir / "report.html").as_uri())
        except Exception as exc:
            print(f"warn: failed to open browser: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
