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
from urllib.parse import quote
from zoneinfo import ZoneInfo

from tinyhat_paths import resolve_home_root


def _local_tz() -> ZoneInfo | timezone:
    """Return the user's local timezone; fall back to system UTC offset."""
    try:
        # Python 3.9+ stdlib: reads TZ / /etc/localtime
        from time import tzname as _tzname  # noqa: F401

        return datetime.now().astimezone().tzinfo or timezone.utc
    except Exception:
        return timezone.utc


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PLUGIN_ROOT / "skills" / "audit" / "templates"
DEFAULT_SNAPSHOT_PATH = Path(tempfile.gettempdir()) / "tinyhat-snapshot-detail.json"
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


def _pct_int(part: int, total: int) -> int:
    if total <= 0:
        return 0
    return int(round((100 * part) / total))


def _ascii_bar(part: int, total: int, *, width: int = 28) -> str:
    filled = 0 if total <= 0 else int(round(part / total * width))
    filled = max(0, min(width, filled))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def _briefing_strip(snapshot: dict) -> str:
    stats = snapshot["stats"]
    skill_pct = _pct_int(stats["active_count"], stats["installed_count"])
    session_pct = _pct_int(stats["sessions_with_skills"], stats["sessions_total"])
    lines = [
        "Skill utilization:    "
        f"{_ascii_bar(stats['active_count'], stats['installed_count'])} "
        f"{skill_pct:>3}%  {stats['active_count']} / {stats['installed_count']}",
        "Sessions with skills: "
        f"{_ascii_bar(stats['sessions_with_skills'], stats['sessions_total'])} "
        f"{session_pct:>3}%  {stats['sessions_with_skills']} / {stats['sessions_total']}",
    ]
    return "\n".join(lines)


def _load_routine_state(home_root: Path) -> dict:
    routine_path = home_root / "routine.json"
    state = {"enabled": True}
    if routine_path.is_file():
        try:
            data = json.loads(routine_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                state.update(data)
        except (OSError, json.JSONDecodeError):
            pass

    run_stamp = home_root / "latest" / "run-stamp.txt"
    last_run = ""
    if run_stamp.is_file():
        try:
            last_run = run_stamp.read_text(encoding="utf-8").strip()
        except OSError:
            last_run = ""
    return {"enabled": bool(state.get("enabled", True)), "last_run": last_run}


def _confidence_rank(value: str | None) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get((value or "").lower(), 0)


def _first_sentence(text: str, *, limit: int = 140) -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return ""
    if clean.endswith((".", "!", "?")):
        return clean
    match = re.search(r"(?<=[.!?])\s", clean)
    head = clean if not match else clean[: match.start()].strip()
    if match or len(head) <= limit:
        return head
    return head[: limit - 3].rstrip() + "..."


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
        r
        for r in sessions
        if r["tool_uses"].get("Edit", 0) >= 15 and r["tool_uses"].get("Bash", 0) >= 15
    ]
    if len(impl) >= 2:
        te = sum(r["tool_uses"].get("Edit", 0) for r in impl)
        tb = sum(r["tool_uses"].get("Bash", 0) for r in impl)
        recs.append(
            {
                "name": "implement-feature",
                "confidence": "high",
                "headline": "Shape the heavy implementation runs you already do.",
                "why": f"{len(impl)} recent sessions leaned hard on Edit + Bash ({te} edits, {tb} shell calls), which points to a repeatable build-fix-verify workflow worth turning into a skill.",
                "triggers": ["implement", "fix", "add support for", "update the code"],
            }
        )

    explore = [
        r
        for r in sessions
        if r["tool_uses"].get("Read", 0) >= 25 and r["tool_uses"].get("Grep", 0) >= 5
    ]
    if len(explore) >= 2:
        tr = sum(r["tool_uses"].get("Read", 0) for r in explore)
        tg = sum(r["tool_uses"].get("Grep", 0) for r in explore)
        recs.append(
            {
                "name": "explore-codebase",
                "confidence": "high" if len(explore) >= 5 else "medium",
                "headline": "Standardize the understand-before-editing workflow.",
                "why": f"{len(explore)} recent sessions were dominated by Read + Grep ({tr} reads, {tg} searches). A focused exploration skill could make those investigations faster and more consistent.",
                "triggers": ["how does", "where is", "trace", "walk me through"],
            }
        )

    research = [
        r
        for r in sessions
        if r["tool_uses"].get("WebSearch", 0) + r["tool_uses"].get("WebFetch", 0) >= 4
    ]
    if len(research) >= 2:
        tw = sum(
            r["tool_uses"].get("WebSearch", 0) + r["tool_uses"].get("WebFetch", 0) for r in research
        )
        recs.append(
            {
                "name": "research-and-write-brief",
                "confidence": "medium",
                "headline": "Turn repeated research-plus-writing into one polished move.",
                "why": f"{len(research)} recent sessions mixed web lookups with writing ({tw} web calls). That pattern usually benefits from a dedicated research-to-brief skill.",
                "triggers": ["research", "look up", "summarize", "write a brief"],
            }
        )
    return recs[:3]


def _cleanup_action(snapshot: dict) -> dict | None:
    dormant_by_origin = snapshot.get("dormant_by_origin", {})
    if not dormant_by_origin:
        return None

    origin = (
        "Plugin"
        if dormant_by_origin.get("Plugin")
        else max(dormant_by_origin.items(), key=lambda kv: len(kv[1]))[0]
    )
    names = dormant_by_origin.get(origin, [])
    if not names:
        return None

    noun = "skill" if len(names) == 1 else "skills"
    origin_label = origin.lower()
    return {
        "verb": "cleanup",
        "label": f"Review the {len(names)} dormant {origin_label} {noun}",
        "context": "They are the cleanest cleanup targets in this snapshot.",
        "impact": "medium",
    }


def _draft_action(analysis: dict) -> dict | None:
    recs = analysis.get("skill_recommendations") or []
    if not recs:
        return None

    top = max(recs, key=lambda rec: _confidence_rank(rec.get("confidence")))
    label = f"Draft `{top['name']}`"
    context = _first_sentence(top.get("why") or top.get("headline") or "")
    return {
        "verb": "draft-skill",
        "label": label,
        "context": context or "It is the strongest candidate from this audit.",
        "impact": top.get("confidence") or "medium",
    }


def _routine_action(home_root: Path, *, report_date: str) -> dict:
    routine = _load_routine_state(home_root)
    last_run = routine["last_run"] or report_date
    if routine["enabled"]:
        context = f"Currently on; last run {last_run}."
    else:
        context = f"Currently off; last successful run {last_run}. Turn it on if you want a daily snapshot."
    return {
        "verb": "routine",
        "label": "Check the daily routine",
        "context": context,
        "impact": "medium",
    }


def _fallback_next_actions(
    snapshot: dict, analysis: dict, *, home_root: Path, report_date: str
) -> list[dict]:
    actions: list[dict] = []

    draft = _draft_action(analysis)
    if draft:
        actions.append(draft)

    cleanup = _cleanup_action(snapshot)
    if cleanup:
        actions.append(cleanup)

    actions.append(_routine_action(home_root, report_date=report_date))
    actions.append(
        {
            "verb": "open-report",
            "label": "Open the full HTML report",
            "context": "The richer charts and session drill-downs live in the sibling `report.html`.",
            "impact": None,
        }
    )
    actions.append(
        {
            "verb": "defer",
            "label": "Do nothing — check back tomorrow",
            "context": "Useful if you only wanted the briefing.",
            "impact": None,
        }
    )

    deduped: list[dict] = []
    seen_verbs: set[str] = set()
    for action in actions:
        verb = action.get("verb")
        if not verb or verb in seen_verbs:
            continue
        seen_verbs.add(verb)
        deduped.append(action)
    return deduped[:5]


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
        parts.append(
            f"Found local GStack telemetry ({c['gstack_events']} recent events) and kept the ranking anchored to transcript-backed inventory matches."
        )
    else:
        parts.append("No local GStack telemetry file was used in this run.")
    if c["unknown_event_count"]:
        parts.append(
            f"Ignored {c['unknown_event_count']} events under {c['unknown_name_count']} unknown names."
        )
    if c["bare_read_skill_md_count"]:
        parts.append(
            f"Dropped {c['bare_read_skill_md_count']} bare Read SKILL.md events as likely false positives."
        )
    parts.append(
        "Counts use only local data and blend direct Skill calls with likely Read SKILL.md matches, so ties and one-off rows are directional."
    )
    return " ".join(parts)


def analysis_with_fallbacks(
    snapshot: dict, analysis: dict | None, *, home_root: Path, report_date: str
) -> dict:
    analysis = dict(analysis or {})
    analysis.setdefault("headline", _fallback_headline(snapshot))
    analysis.setdefault(
        "headline_sub", "Everything else on this page is supporting evidence for that headline."
    )
    analysis.setdefault("what_stands_out", _fallback_standouts(snapshot))
    analysis.setdefault("dormant_commentary", _fallback_dormant_commentary(snapshot))
    analysis.setdefault("skill_recommendations", _fallback_recommendations(snapshot))
    analysis.setdefault(
        "next_actions",
        _fallback_next_actions(
            snapshot,
            analysis,
            home_root=home_root,
            report_date=report_date,
        ),
    )
    analysis.setdefault("coverage_note", _fallback_coverage_note(snapshot))
    return analysis


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _markdown_action_lines(actions: list[dict]) -> str:
    lines = []
    for idx, action in enumerate(actions, 1):
        context = action.get("context")
        line = f"{idx}. {action['label']}"
        if context:
            line += f": {context}"
        lines.append(line)
    return "\n".join(lines)


def render_markdown(snapshot: dict, analysis: dict) -> str:
    tpl = (TEMPLATE_DIR / "report.md.tmpl").read_text(encoding="utf-8")
    stats = snapshot["stats"]
    meta = snapshot["meta"]

    generated = datetime.fromisoformat(meta["generated_at"].replace("Z", "+00:00"))
    window_label = f"last {meta['window_days']} days"
    briefing_strip = _briefing_strip(snapshot)

    standouts = (
        "\n".join(f"- {line}" for line in analysis["what_stands_out"]) or "- (no observations)"
    )

    next_actions_md = _markdown_action_lines(analysis["next_actions"])

    snapshot_md = "\n".join(
        [
            f"- Installed skills: {stats['installed_count']}",
            f"- Active skills: {stats['active_count']}",
            f"- Skill runs detected: {stats['skill_runs_total']}",
            f"- Recent sessions scanned: {stats['sessions_total']}",
            f"- Sessions with skills: {stats['sessions_with_skills']}",
            f"- Turns scanned: {stats['turns_total']:,}",
            f"- Token activity (incl. cache): {stats['tokens_total_compact']}",
        ]
    )

    top_skill_lines = []
    for idx, row in enumerate(snapshot.get("top_skills", [])[:6], 1):
        summary = row["summary"] or "No short description found in the local skill file."
        top_skill_lines.append(
            f"{idx}. `{row['skill']}` — {row['runs']} runs, last used {row['last_used'] or '—'}. {summary}"
        )
    top_skills_md = "\n".join(top_skill_lines) or "- No active skills in this window."

    unused_count = stats["installed_count"] - stats["active_count"]
    unused_pct = _pct_int(unused_count, stats["installed_count"])
    dormant_origin_lines = []
    for origin, names in sorted(
        snapshot.get("dormant_by_origin", {}).items(), key=lambda kv: -len(kv[1])
    ):
        dormant_origin_lines.append(f"- {origin}: {len(names)}")
    dormant_origins_md = "\n".join(dormant_origin_lines) or "- (none)"

    rec_lines = []
    for rec in analysis["skill_recommendations"]:
        rec_lines.append(f"- `{rec['name']}` — {rec['why']}")
    recommendations_md = (
        "\n".join(rec_lines) or "- No clear recommendation stood out from recent session patterns."
    )

    coverage_md = f"- {analysis['coverage_note']}"

    out = tpl
    substitutions = {
        "BRIEFING_STRIP": briefing_strip,
        "WINDOW_LABEL": window_label,
        "GENERATED_AT": generated.strftime("%Y-%m-%d %H:%M UTC"),
        "HEADLINE": analysis["headline"],
        "HEADLINE_SUB": analysis.get("headline_sub", ""),
        "NEXT_ACTIONS_MD": next_actions_md,
        "SNAPSHOT_MD": snapshot_md,
        "STANDOUTS_MD": standouts,
        "TOP_SKILLS_MD": top_skills_md,
        "INSTALLED_COUNT": stats["installed_count"],
        "UNUSED_COUNT": unused_count,
        "UNUSED_PCT": unused_pct,
        "DORMANT_COMMENTARY": analysis["dormant_commentary"],
        "DORMANT_ORIGINS_MD": dormant_origins_md,
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
    points: list[dict],
    key: str,
    color: str,
    value_label: str,
    *,
    label_key: str = "date",
    width: int = 520,
    height: int = 240,
    y_axis_title: str | None = None,
    x_axis_title: str | None = None,
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
            f"<title>{html.escape(label)}: {value_txt} {html.escape(value_label)}</title></rect>"
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
    return {"cli_terminal": "CLI", "desktop_code_tab": "Desktop Code tab", "cowork": "Cowork"}.get(
        s, s
    )


def _origin_slug(origin: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", origin.lower()).strip("-") or "group"


def _html_next_action_label(action: dict) -> str:
    if action.get("verb") == "open-report":
        return "Switch to data-junkie mode"
    return action["label"]


def _html_next_action_context(action: dict) -> str:
    if action.get("verb") == "open-report":
        return "Charts, filters, and session drill-downs are below."
    return action.get("context") or ""


def _html_inline_code(text: str) -> str:
    parts = re.split(r"`([^`]+)`", text or "")
    out = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            out.append(f"<code>{html.escape(part)}</code>")
        else:
            out.append(html.escape(part))
    return "".join(out)


LATEST_ARCHIVE_INDEX_HREF = "../archive/index.html"
DATED_ARCHIVE_INDEX_HREF = "../index.html"


def render_html(snapshot: dict, analysis: dict, *, archive_index_href: str) -> str:
    tpl = (TEMPLATE_DIR / "report.html.tmpl").read_text(encoding="utf-8")
    # Inline CSS from sibling file so edits don't require touching a
    # quoted string inside the template. Template references {{CSS}}.
    css_path = TEMPLATE_DIR / "report.css"
    css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""
    s = snapshot["stats"]
    meta = snapshot["meta"]

    local_tz = _local_tz()
    generated_utc = datetime.fromisoformat(meta["generated_at"].replace("Z", "+00:00"))
    generated_local = generated_utc.astimezone(local_tz)
    tz_abbr = generated_local.strftime("%Z") or "local"
    window_label = f"last {meta['window_days']} days"

    installed = s["installed_count"]
    active = s["active_count"]
    util_pct = _pct_int(active, installed)
    sess_total = s["sessions_total"]
    sess_skill_pct = _pct_int(s["sessions_with_skills"], sess_total)

    standouts_html = "\n".join(
        f"<li>{html.escape(item)}</li>" for item in analysis["what_stands_out"]
    )

    next_actions_html = []
    for action in analysis["next_actions"]:
        label = _html_next_action_label(action)
        context = _html_next_action_context(action)
        body = f'<span class="next-action-label">{_html_inline_code(label)}</span>'
        if context:
            body += f'<span class="next-action-context">{_html_inline_code(context)}</span>'
        next_actions_html.append(f"<li>{body}</li>")

    # Recommendation cards
    rec_cards = []
    for idx, rec in enumerate(analysis["skill_recommendations"], 1):
        triggers_html = " ".join(
            f'<span class="chip chip-soft">&ldquo;{html.escape(t)}&rdquo;</span>'
            for t in rec.get("triggers", [])
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
            f'<span class="small">Coming soon</span>'
            f'</div></article>'
        )
    if not rec_cards:
        rec_cards.append(
            '<article class="recommend-card"><p class="small">No strong recommendation stood out. Run Tinyhat again after another week of work — patterns usually emerge with more sessions.</p></article>'
        )

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
            summary = (
                meta_i.get("summary") or "No short description found in the local skill file."
            ).strip()
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
        dormant_cards.append(
            '<article class="dormant-card"><p class="small">Nothing dormant — every installed skill fired at least once.</p></article>'
        )

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
        top_cards.append(
            '<article class="skill-card"><p class="small">No active skills in the window.</p></article>'
        )

    # Session cards
    sessions = snapshot.get("sessions", [])
    session_cards = []
    for row in sessions:
        last_ts_raw = row.get("last_ts") or ""
        local_dt_str = "—"
        if last_ts_raw:
            try:
                iso = last_ts_raw.replace("Z", "+00:00")
                last_ts_dt = datetime.fromisoformat(iso).astimezone(local_tz)
                local_dt_str = last_ts_dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                local_dt_str = last_ts_raw[:16].replace("T", " ")
        title = row.get("title") or row.get("project") or "Untitled session"
        skill_chips = (
            " ".join(
                f'<span class="chip">{html.escape(k)} · {v}</span>'
                for k, v in sorted(row.get("skill_counter", {}).items(), key=lambda kv: -kv[1])[:4]
            )
            or '<span class="chip chip-soft">No named skills</span>'
        )
        top_tools = sorted(row.get("tool_uses", {}).items(), key=lambda kv: -kv[1])[:5]
        tool_chips = (
            " ".join(
                f'<span class="chip chip-soft">{html.escape(t)} · {n}</span>' for t, n in top_tools
            )
            or '<span class="chip chip-soft">No tool data</span>'
        )
        session_cards.append(
            f'<details class="session-item" data-skill-runs="{row["skill_runs"]}" '
            f'data-surface="{html.escape(row["surface"])}" data-project="{html.escape(row["project"])}" '
            f'data-last-ts="{html.escape(last_ts_raw)}">'
            f'<summary><div><div class="session-title">{html.escape(title)}</div>'
            f'<div class="session-sub">{html.escape(_surface_label(row["surface"]))} · {html.escape(row["project"])}</div></div>'
            f'<div class="session-meta"><span class="meta-chip">{html.escape(local_dt_str)}</span>'
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
    surface_chips = (
        '<button type="button" class="chip-btn active" data-surface="all">All</button>'
        + "".join(
            f'<button type="button" class="chip-btn" data-surface="{html.escape(s)}">{html.escape(_surface_label(s))}</button>'
            for s in surfaces_seen
        )
    )
    project_chips = (
        '<button type="button" class="chip-btn active" data-project="all">All</button>'
        + "".join(
            f'<button type="button" class="chip-btn" data-project="{html.escape(p)}">{html.escape(p)}</button>'
            for p in projects_seen
        )
    )

    # Tools — ship per-session payload so JS can recompute on filter change.
    aggregate_tools = snapshot.get("aggregate_tools", [])
    tools_session_payload = [
        {
            "session_id": r["session_id"],
            "project": r["project"],
            "surface": r["surface"],
            "tools": r.get("tool_uses", {}),
        }
        for r in sessions
    ]
    tools_payload_json = json.dumps(tools_session_payload)

    tools_surface_chips = (
        '<button type="button" class="chip-btn active" data-surface="all">All</button>'
        + "".join(
            f'<button type="button" class="chip-btn" data-surface="{html.escape(s)}">{html.escape(_surface_label(s))}</button>'
            for s in surfaces_seen
        )
    )
    tools_project_chips = (
        '<button type="button" class="chip-btn active" data-project="all">All</button>'
        + "".join(
            f'<button type="button" class="chip-btn" data-project="{html.escape(p)}">{html.escape(p)}</button>'
            for p in projects_seen
        )
    )

    # Charts — bigger (wider + taller) for the details mode.
    daily = snapshot.get("daily_rollups", [])
    chart_kw = {"width": 820, "height": 320}
    chart_sessions = _svg_bar_chart(
        daily,
        "sessions",
        "#0f5c63",
        "sessions",
        y_axis_title="Sessions",
        x_axis_title="Day",
        **chart_kw,
    )
    chart_turns = _svg_bar_chart(
        daily, "turns", "#3f8c8d", "turns", y_axis_title="Turns", x_axis_title="Day", **chart_kw
    )
    chart_tokens = _svg_bar_chart(
        daily, "tokens", "#b56b45", "tokens", y_axis_title="Tokens", x_axis_title="Day", **chart_kw
    )
    surface_points = [
        {"date": _surface_label(k), "value": v}
        for k, v in snapshot.get("surface_rollups", {}).items()
    ]
    chart_surfaces = _svg_bar_chart(
        surface_points,
        "value",
        "#7d8f52",
        "sessions",
        y_axis_title="Sessions",
        x_axis_title="Surface",
        **chart_kw,
    )

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

    # Mailto feedback subject — URL-encoded so special chars survive.
    feedback_subject_base = quote(
        f"Tinyhat feedback — report {generated_local.strftime('%Y-%m-%d %H:%M')}"
    )

    subs = {
        "CSS": css,
        "ARCHIVE_INDEX_HREF": archive_index_href,
        "GENERATED_AT": generated_local.strftime(f"%Y-%m-%d %H:%M {tz_abbr}".strip()),
        "GENERATED_AT_UTC": generated_utc.strftime("%Y-%m-%d %H:%M UTC"),
        "WINDOW_LABEL": window_label,
        "WINDOW_DAYS": meta["window_days"],
        "FEEDBACK_SUBJECT": feedback_subject_base,
        "HEADLINE": analysis["headline"],
        "HEADLINE_SUB": analysis.get("headline_sub", ""),
        "NEXT_ACTIONS_HTML": "\n".join(next_actions_html),
        "INSTALLED_COUNT": installed,
        "ACTIVE_COUNT": active,
        "SKILL_RUNS_TOTAL": s["skill_runs_total"],
        "SESSIONS_TOTAL": sess_total,
        "SESSIONS_WITH_SKILLS": s["sessions_with_skills"],
        "TURNS_TOTAL_COMPACT": _format_compact(s["turns_total"]),
        "TOKENS_TOTAL_COMPACT": s["tokens_total_compact"],
        "UTILIZATION_PCT": util_pct,
        "SESSION_SKILL_PCT": sess_skill_pct,
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
        "TOOLS_PAYLOAD_JSON": tools_payload_json,
        "TOOLS_SURFACE_CHIPS": tools_surface_chips,
        "TOOLS_PROJECT_CHIPS": tools_project_chips,
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


def render_index(home_root: Path) -> str:
    """Render the reports index page listing every snapshot.

    Lists latest/ first, then every archive/YYYY-MM-DD/ in reverse-
    chronological order. Each entry links to its report.html.
    """
    css = (
        (TEMPLATE_DIR / "report.css").read_text(encoding="utf-8")
        if (TEMPLATE_DIR / "report.css").is_file()
        else ""
    )
    archive_dir = home_root / "archive"
    archives = []
    if archive_dir.is_dir():
        for entry in sorted(archive_dir.iterdir(), reverse=True):
            if entry.is_dir() and (entry / "report.html").is_file():
                archives.append(entry.name)

    local_tz = _local_tz()
    tz_abbr = datetime.now(local_tz).strftime("%Z") or "local"

    latest_stamp_path = home_root / "latest" / "run-stamp.txt"
    latest_date = (
        latest_stamp_path.read_text(encoding="utf-8").strip() if latest_stamp_path.is_file() else ""
    )

    rows = []
    if (home_root / "latest" / "report.html").is_file():
        rows.append(
            f'<a class="index-row index-latest" href="../latest/report.html">'
            f'<div class="index-row-main"><div class="kicker">Latest</div>'
            f'<div class="index-row-title">Most recent report</div>'
            f'<div class="small">Last refreshed {html.escape(latest_date or "—")}</div></div>'
            f'<div class="index-row-arrow">→</div></a>'
        )
    for date in archives:
        rows.append(
            f'<a class="index-row" href="{html.escape(date)}/report.html">'
            f'<div class="index-row-main"><div class="kicker">Archived</div>'
            f'<div class="index-row-title">{html.escape(date)}</div>'
            f'<div class="small">Dated snapshot</div></div>'
            f'<div class="index-row-arrow">→</div></a>'
        )
    if not rows:
        rows.append(
            '<p class="small">No reports yet. Run Tinyhat once to produce the first snapshot.</p>'
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Tinyhat · Reports</title>
<style>
{css}
.index-list {{ display: flex; flex-direction: column; gap: 10px; margin-top: 22px; }}
.index-row {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 22px; border: 1px solid var(--border); border-radius: 16px; background: var(--card); box-shadow: var(--shadow); text-decoration: none; color: var(--ink); transition: transform 0.15s, box-shadow 0.15s; }}
.index-row:hover {{ transform: translateY(-2px); box-shadow: 0 18px 42px rgba(15,92,99,0.14); }}
.index-latest {{ background: linear-gradient(160deg, rgba(255,248,240,0.96), rgba(249,232,215,0.82)); }}
.index-row-title {{ font-family: "Iowan Old Style", Georgia, serif; font-size: 1.2rem; font-weight: 700; margin: 4px 0; }}
.index-row-arrow {{ font-size: 1.4rem; color: var(--accent); }}
</style></head><body class="mode-main"><div class="wrap">
<header class="report-header"><div class="report-header-top"><div>
<div class="kicker">Tinyhat · Reports</div>
<h1 class="report-title">Your Tinyhat snapshots</h1>
<p class="report-sub">Latest, plus every dated archive on this machine. Up to 31 dated copies.</p>
<p class="report-meta">All times shown in {html.escape(tz_abbr)}.</p>
</div></div></header>
<div class="index-list">{''.join(rows)}</div>
</div></body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Tinyhat report.")
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT_PATH))
    parser.add_argument("--analysis", default=str(DEFAULT_ANALYSIS_PATH))
    parser.add_argument(
        "--home-root",
        default=None,
        help="Root directory for Tinyhat output (default: Claude plugin data directory)",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Also write archive/YYYY-MM-DD/ snapshot and enforce retention.",
    )
    parser.add_argument(
        "--open", action="store_true", help="Open the rendered HTML in the default browser."
    )
    parser.add_argument(
        "--index-only", action="store_true", help="Regenerate archive/index.html only (no report)."
    )
    args = parser.parse_args()

    home_root = resolve_home_root(args.home_root)
    report_date = datetime.now(_local_tz()).date().isoformat()

    if args.index_only:
        (home_root / "archive").mkdir(parents=True, exist_ok=True)
        (home_root / "archive" / "index.html").write_text(render_index(home_root), encoding="utf-8")
        print(f"Wrote {home_root / 'archive' / 'index.html'}", file=sys.stderr)
        return 0

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.is_file():
        print(
            f"error: snapshot not found at {snapshot_path}. Run gather_snapshot.py first.",
            file=sys.stderr,
        )
        return 1
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    analysis_path = Path(args.analysis)
    analysis_raw = None
    if analysis_path.is_file():
        try:
            analysis_raw = json.loads(analysis_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(
                f"warn: analysis JSON at {analysis_path} is invalid ({exc}); using fallbacks.",
                file=sys.stderr,
            )
    analysis = analysis_with_fallbacks(
        snapshot,
        analysis_raw,
        home_root=home_root,
        report_date=report_date,
    )

    latest_dir = home_root / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)

    md = render_markdown(snapshot, analysis)
    html_latest = render_html(snapshot, analysis, archive_index_href=LATEST_ARCHIVE_INDEX_HREF)
    snapshot_json = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    analysis_json = json.dumps(analysis, indent=2, ensure_ascii=False) + "\n"

    (latest_dir / "report.md").write_text(md, encoding="utf-8")
    (latest_dir / "report.html").write_text(html_latest, encoding="utf-8")
    (latest_dir / "snapshot.json").write_text(snapshot_json, encoding="utf-8")
    (latest_dir / "analysis.json").write_text(analysis_json, encoding="utf-8")

    today = report_date
    (latest_dir / "run-stamp.txt").write_text(today + "\n", encoding="utf-8")

    if args.archive:
        archive_dir = home_root / "archive" / today
        archive_dir.mkdir(parents=True, exist_ok=True)
        html_archive = render_html(snapshot, analysis, archive_index_href=DATED_ARCHIVE_INDEX_HREF)
        (archive_dir / "report.md").write_text(md, encoding="utf-8")
        (archive_dir / "report.html").write_text(html_archive, encoding="utf-8")
        (archive_dir / "snapshot.json").write_text(snapshot_json, encoding="utf-8")
        (archive_dir / "analysis.json").write_text(analysis_json, encoding="utf-8")
        enforce_retention(home_root / "archive", keep=31)

    # Always regenerate the index so it reflects latest + archives.
    (home_root / "archive").mkdir(parents=True, exist_ok=True)
    index_html = render_index(home_root)
    (home_root / "archive" / "index.html").write_text(index_html, encoding="utf-8")

    print(f"Wrote {latest_dir / 'report.md'} and {latest_dir / 'report.html'}", file=sys.stderr)

    if args.open:
        try:
            webbrowser.open((latest_dir / "report.html").as_uri())
        except Exception as exc:
            print(f"warn: failed to open browser: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
