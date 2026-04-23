#!/usr/bin/env python3
"""Walk local Claude Code / Cowork data and emit a structured snapshot.

The snapshot is facts only — installed-skill inventory, attributed skill
events, per-session metadata, daily rollups, coverage counts. Ranking and
editorial framing are left to the agent, which reads this snapshot and
writes its own analysis JSON before render_report.py runs.

Usage:
    python3 gather_snapshot.py [--window-days 30] [--output path.json]

Default output is /tmp/tinyhat-snapshot.json. Paths and the window are
read from arguments; nothing is read from stdin and nothing is written
outside the output path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator


HOME = Path.home()
CLI_TRANSCRIPT_ROOT = HOME / ".claude" / "projects"

# Desktop-app surfaces (Cowork, Code tab wrappers) are currently macOS-only.
# On Linux/Windows these paths simply won't exist and are skipped silently.
# If Anthropic ships the desktop app on other OSes, add their paths here.
_MAC_APPSUPPORT = HOME / "Library" / "Application Support" / "Claude"
_WIN_APPDATA = Path(os.environ.get("APPDATA", "")) / "Claude" if os.environ.get("APPDATA") else None
_WIN_LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Claude" if os.environ.get("LOCALAPPDATA") else None
_LINUX_CONFIG = HOME / ".config" / "Claude"

_DESKTOP_ROOTS = [p for p in (_MAC_APPSUPPORT, _WIN_APPDATA, _WIN_LOCALAPPDATA, _LINUX_CONFIG) if p]

COWORK_TRANSCRIPT_ROOTS = [r / "local-agent-mode-sessions" for r in _DESKTOP_ROOTS]
DESKTOP_TAB_ROOTS = [r / "claude-code-sessions" for r in _DESKTOP_ROOTS]
GSTACK_USAGE_PATH = HOME / ".gstack" / "analytics" / "skill-usage.jsonl"

DEFAULT_SNAPSHOT_PATH = Path(tempfile.gettempdir()) / "tinyhat-snapshot.json"

SKILL_MD_PATH_RE = re.compile(r"/skills/([^/]+)/SKILL\.md$")
COMMAND_NAME_RE = re.compile(r"<command-name>/?([A-Za-z0-9_:\-]+)</command-name>")
SUMMARY_LIMIT = 140

# Last-resort summaries for skills whose SKILL.md doesn't surface a clean one.
# Covers frequently-used built-in skills so the report stays readable even when
# the skill file leads with operational preamble (e.g. gstack's PROACTIVE gate).
FALLBACK_SKILL_SUMMARIES = {
    "browse": "Open and inspect a live site or app in a browser, then verify what changed.",
    "ship": "Wrap up a finished change and get it ready to land cleanly.",
    "qa": "Run a structured quality pass and look for regressions, bugs, or missing checks.",
    "plan-eng-review": "Prepare an engineering review briefing with progress, risks, and decisions.",
    "plan-ceo-review": "Prepare a CEO review briefing that distills progress, risks, and decisions.",
    "plan-design-review": "Prepare a design-review briefing with the work, open questions, and tradeoffs.",
    "web-research": "Research a topic on the web and return a concise, source-backed summary.",
    "find-company-social-profiles": "Find a company's public and social profile links quickly.",
}

HARNESS_BUILTINS = {
    "model", "clear", "compact", "loop", "init", "help", "exit", "quit",
    "reset", "ide", "mcp", "login", "logout", "config", "terminal-setup",
    "doctor", "theme", "status", "vim", "release-notes", "upgrade", "bug",
    "cost", "review", "pr-comments", "add-dir", "hooks", "permissions",
    "memory",
}


# ---------------------------------------------------------------------------
# Skill inventory
# ---------------------------------------------------------------------------

def _detect_pack(path: Path) -> str | None:
    parent = path.parent.parent
    if parent.name in ("skills", "", None):
        return None
    if parent.parent.name == "skills":
        return parent.name
    return None


def _describe(raw_scope: str, path: Path) -> dict:
    pack = _detect_pack(path)
    if raw_scope == "personal":
        product, origin = "Claude Code", "Personal"
    elif raw_scope == "cowork:skills-plugin":
        product, origin = "Cowork", "Cowork built-in"
    elif raw_scope.startswith("plugin:"):
        plugin = raw_scope.split(":", 1)[1]
        product, origin = "Claude Code", f"Plugin: {plugin}"
    elif raw_scope.startswith("project:"):
        project = raw_scope.split(":", 1)[1]
        product, origin = "Claude Code", f"Project: {project}"
    else:
        product, origin = "Unknown", raw_scope
    if pack:
        origin = f"{origin} ({pack} pack)"
    return {
        "product": product,
        "origin": origin,
        "pack": pack,
        "raw_scope": raw_scope,
        "path": str(path),
    }


def _project_roots_to_scan() -> list[Path]:
    roots: list[Path] = []
    tinyloop_root = HOME / "tinyloop"
    if tinyloop_root.is_dir():
        for entry in tinyloop_root.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                roots.append(entry)
    return roots


def build_inventory() -> dict:
    inventory: dict = {}

    def _add(name: str, raw_scope: str, path: Path):
        if name in inventory:
            return
        inventory[name] = _describe(raw_scope, path)

    personal = HOME / ".claude" / "skills"
    if personal.is_dir():
        for directory in personal.iterdir():
            skill_md = directory / "SKILL.md"
            if skill_md.is_file():
                _add(directory.name, "personal", skill_md)

    plugins_root = HOME / ".claude" / "plugins"
    if plugins_root.is_dir():
        for skill_md in plugins_root.rglob("skills/*/SKILL.md"):
            parts = skill_md.parts
            try:
                idx = parts.index("plugins")
                plugin_name = parts[idx + 2] if len(parts) > idx + 2 else "plugin"
            except ValueError:
                plugin_name = "plugin"
            _add(skill_md.parent.name, f"plugin:{plugin_name}", skill_md)

    for root in _project_roots_to_scan():
        for skill_md in root.rglob("SKILL.md"):
            path_str = str(skill_md)
            if "/node_modules/" in path_str:
                continue
            if "/.cursor/skills/" in path_str:
                continue
            if "/skills/" not in path_str:
                continue
            _add(skill_md.parent.name, f"project:{root.name}", skill_md)

    for cowork_root in COWORK_TRANSCRIPT_ROOTS:
        skills_plugin = cowork_root / "skills-plugin"
        if skills_plugin.is_dir():
            for skill_md in skills_plugin.rglob("skills/*/SKILL.md"):
                _add(skill_md.parent.name, "cowork:skills-plugin", skill_md)

    for name, meta in inventory.items():
        meta["summary"] = _skill_summary(meta["path"], name)
    return inventory


# ---------------------------------------------------------------------------
# SKILL.md summary extraction
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        return "", text
    return parts[0].removeprefix("---").strip("\n"), parts[1].lstrip("\n")


def _clean_inline_text(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().strip('"').strip("'")


def _compact_summary(text: str, limit: int = SUMMARY_LIMIT) -> str:
    text = _clean_inline_text(text)
    if not text or not re.search(r"[A-Za-z0-9]", text):
        return ""
    # Strip wrapper scripts that show up in some bundled skills' bodies.
    if "gstack-update-check" in text or text.startswith("_UPD=") or text.startswith("$("):
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", text)[0]
    if len(sentence) <= limit:
        return sentence
    clipped = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return clipped + "…"


def _extract_description_from_frontmatter(frontmatter: str) -> str:
    if not frontmatter:
        return ""
    lines = frontmatter.splitlines()
    for idx, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value:
            return _compact_summary(value)
        collected: list[str] = []
        for next_line in lines[idx + 1 :]:
            if not next_line.strip():
                if collected:
                    break
                continue
            if re.match(r"^[A-Za-z0-9_-]+:\s", next_line) and not next_line.startswith(" "):
                break
            collected.append(next_line.strip().strip('"'))
        return _compact_summary(" ".join(collected))
    return ""


def _extract_description_from_body(body: str) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    in_code_block = False
    for raw in body.splitlines():
        if raw.strip().startswith("```"):
            in_code_block = not in_code_block
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if in_code_block:
            continue
        line = raw.strip()
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if line.startswith(("#", "|", "- ", "* ", ">")):
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    for paragraph in paragraphs:
        cleaned = _compact_summary(paragraph)
        if cleaned:
            return cleaned
    return ""


def _skill_summary(path_str: str, skill_name: str = "") -> str:
    try:
        text = Path(path_str).read_text(encoding="utf-8")
    except OSError:
        return FALLBACK_SKILL_SUMMARIES.get(skill_name, "")
    frontmatter, body = _parse_frontmatter(text)
    summary = _extract_description_from_frontmatter(frontmatter) or _extract_description_from_body(body)
    # Drop gstack's PROACTIVE preamble if it leaked past the fm parser.
    if summary.lower().startswith("if proactive"):
        summary = ""
    return summary or FALLBACK_SKILL_SUMMARIES.get(skill_name, "")


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------

def _iter_jsonl(path: Path) -> Iterator[dict]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except (OSError, PermissionError):
        return


def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _is_subagent(path: Path) -> bool:
    return "/subagents/" in str(path)


def _parent_session_id(path: Path) -> str:
    try:
        return path.parent.parent.name
    except Exception:
        return ""


def _list_cli_transcripts() -> list[Path]:
    if not CLI_TRANSCRIPT_ROOT.is_dir():
        return []
    return sorted(CLI_TRANSCRIPT_ROOT.rglob("*.jsonl"))


def _list_cowork_transcripts() -> list[Path]:
    paths: list[Path] = []
    for root in COWORK_TRANSCRIPT_ROOTS:
        if root.is_dir():
            paths.extend(root.rglob(".claude/projects/*/*.jsonl"))
    return sorted(paths)


def _desktop_session_ids() -> set[str]:
    ids: set[str] = set()
    for root in DESKTOP_TAB_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("local_*.json"):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            cli_id = data.get("cliSessionId")
            if cli_id:
                ids.add(cli_id)
    return ids


def _cwd_from_transcript(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for _ in range(20):
                line = fh.readline()
                if not line:
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    cwd = data.get("cwd")
                    if cwd:
                        return cwd
    except (OSError, PermissionError):
        pass
    for part in path.parts:
        if part.startswith(("-Users-", "-home-")):
            return "/" + part.lstrip("-").replace("-", "/")
    return ""


def _project_for_cwd(cwd: str) -> str:
    if not cwd:
        return "(unknown project)"
    idx = cwd.find("/.claude/worktrees/")
    if idx != -1:
        cwd = cwd[:idx]
    name = Path(cwd).name
    return name or "(unknown project)"


def _session_metadata(path: Path) -> dict:
    session_id = path.stem
    is_subagent = _is_subagent(path)
    cwd = ""
    title = ""
    first_ts: str | None = None
    last_ts: str | None = None
    model = ""

    user_turns = 0
    assistant_turns = 0
    tool_uses: Counter[str] = Counter()

    tokens_input = 0
    tokens_output = 0
    tokens_cache_read = 0
    tokens_cache_creation = 0

    for data in _iter_jsonl(path):
        if not isinstance(data, dict):
            continue
        if not is_subagent:
            sid = data.get("sessionId") or data.get("session_id")
            if sid and not session_id.startswith(sid[:8]):
                session_id = sid
        if not cwd:
            cwd = data.get("cwd") or cwd
        if data.get("type") == "ai-title":
            title = data.get("aiTitle") or title

        ts = data.get("timestamp")
        if isinstance(ts, str):
            if not first_ts or ts < first_ts:
                first_ts = ts
            if not last_ts or ts > last_ts:
                last_ts = ts

        etype = data.get("type")
        msg = data.get("message") if isinstance(data.get("message"), dict) else None

        if etype == "assistant" and msg:
            assistant_turns += 1
            if not model:
                model = msg.get("model") or ""
            usage = msg.get("usage") or {}
            tokens_input += int(usage.get("input_tokens") or 0)
            tokens_output += int(usage.get("output_tokens") or 0)
            tokens_cache_read += int(usage.get("cache_read_input_tokens") or 0)
            tokens_cache_creation += int(usage.get("cache_creation_input_tokens") or 0)
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name") or ""
                        if name:
                            tool_uses[name] += 1
        elif etype == "user" and msg:
            user_turns += 1

    return {
        "session_id": session_id,
        "cwd": cwd,
        "title": title,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "model": model,
        "turns": user_turns + assistant_turns,
        "tool_uses": dict(tool_uses),
        "tokens_total": tokens_input + tokens_output + tokens_cache_read + tokens_cache_creation,
    }


# ---------------------------------------------------------------------------
# Skill event attribution
# ---------------------------------------------------------------------------

def _extract_events_from_transcript(
    path: Path,
    surface: str,
    desktop_session_ids: set[str],
) -> Iterator[dict]:
    """Yield skill events from a transcript.

    Applies the false-positive mitigation for `Read SKILL.md`: a bare read
    that isn't followed by another assistant tool_use in the same turn or
    an obviously skill-driven follow-up is kept in the audit trail but
    marked `likely_bare=True` so downstream can drop it from the ranking.
    """

    is_subagent = _is_subagent(path)
    parent_id = _parent_session_id(path) if is_subagent else ""
    cwd = _cwd_from_transcript(path)
    project = "(Cowork sandbox)" if surface == "cowork" else _project_for_cwd(cwd)

    for data in _iter_jsonl(path):
        if not isinstance(data, dict):
            continue
        sid_raw = data.get("sessionId") or data.get("session_id") or path.stem
        ts_raw = data.get("timestamp")
        etype = data.get("type")

        attributed_sid = parent_id or sid_raw if is_subagent and parent_id else sid_raw
        if surface == "cli":
            refined_surface = (
                "desktop_code_tab" if attributed_sid in desktop_session_ids else "cli_terminal"
            )
        else:
            refined_surface = surface

        base_event = {
            "ts": ts_raw,
            "session_id": attributed_sid,
            "subagent_session_id": sid_raw if is_subagent else None,
            "surface": refined_surface,
            "project": project,
            "transcript": str(path),
            "source": "transcript",
            "from_subagent": is_subagent,
        }

        if etype == "assistant":
            msg = data.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else []
            if not isinstance(content, list):
                continue
            tool_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            follow_up_tool_count = max(0, len(tool_blocks) - 1)
            for idx, block in enumerate(tool_blocks):
                name = block.get("name")
                inp = block.get("input") or {}
                if name == "Skill":
                    skill = inp.get("skill")
                    if skill:
                        yield {**base_event, "type": "skill_tool", "via": "skill_tool",
                               "skill": skill, "likely_bare": False}
                elif name == "Read":
                    fp = inp.get("file_path") or ""
                    match = SKILL_MD_PATH_RE.search(fp)
                    if match:
                        likely_bare = (len(tool_blocks) == 1)
                        yield {**base_event, "type": "read_skill_md", "via": "read_skill_md",
                               "skill": match.group(1), "likely_bare": likely_bare}
                _ = idx, follow_up_tool_count

        elif etype == "user":
            msg = data.get("message") or {}
            text = ""
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_result":
                            continue
                        value = block.get("text") or block.get("content")
                        if isinstance(value, str):
                            text += value
            if not text:
                raw = data.get("content")
                if isinstance(raw, str):
                    text = raw
            for match in COMMAND_NAME_RE.finditer(text):
                yield {**base_event, "type": "slash_command", "via": "slash_command",
                       "skill": match.group(1), "likely_bare": False}


def _read_gstack_events() -> list[dict]:
    if not GSTACK_USAGE_PATH.is_file():
        return []
    events: list[dict] = []
    try:
        with GSTACK_USAGE_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                skill = record.get("skill")
                ts = record.get("ts")
                if not skill or not ts:
                    continue
                events.append({
                    "type": "gstack_telemetry",
                    "skill": skill,
                    "ts": ts,
                    "session_id": record.get("session_id") or record.get("session") or f"gstack:{skill}:{ts}",
                    "subagent_session_id": None,
                    "surface": "cli_terminal",
                    "via": "gstack_telemetry",
                    "project": record.get("repo") or "(unknown project)",
                    "transcript": str(GSTACK_USAGE_PATH),
                    "from_subagent": False,
                    "source": "gstack",
                    "likely_bare": False,
                })
    except OSError:
        return []
    return events


def _dedupe_same_session(events: list[dict], window_seconds: int = 30) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        grouped[(event["session_id"], event["skill"])].append(event)
    kept: list[dict] = []
    for group in grouped.values():
        group_sorted = sorted(
            group,
            key=lambda e: _parse_ts(e["ts"]) or datetime.max.replace(tzinfo=timezone.utc),
        )
        last: datetime | None = None
        for event in group_sorted:
            ts = _parse_ts(event["ts"])
            if last and ts and (ts - last).total_seconds() < window_seconds:
                continue
            kept.append(event)
            last = ts
    return kept


def _merge_with_gstack(transcript_events: list[dict], gstack_events: list[dict]) -> list[dict]:
    merged: list[dict] = list(gstack_events)
    by_skill: dict[str, list[dict]] = defaultdict(list)
    for event in gstack_events:
        by_skill[event["skill"]].append(event)

    for event in transcript_events:
        ts = _parse_ts(event["ts"])
        duplicate = False
        for candidate in by_skill.get(event["skill"], []):
            cts = _parse_ts(candidate["ts"])
            if ts and cts and abs((ts - cts).total_seconds()) <= 120:
                duplicate = True
                break
        if not duplicate:
            merged.append(event)
    return merged


def _reject_unknown(
    events: Iterable[dict],
    inventory: dict,
) -> tuple[list[dict], list[dict]]:
    known, unknown = [], []
    for event in events:
        name = event["skill"]
        if name in HARNESS_BUILTINS:
            continue
        bare = name.split(":")[-1] if ":" in name else name
        if name in inventory or bare in inventory:
            known.append(event)
        else:
            unknown.append(event)
    return known, unknown


# ---------------------------------------------------------------------------
# Rollups
# ---------------------------------------------------------------------------

def _origin_bucket(raw_scope: str) -> str:
    if raw_scope == "personal":
        return "Personal"
    if raw_scope.startswith("project:"):
        return "Project-local"
    if raw_scope.startswith("plugin:"):
        return "Plugin"
    if raw_scope.startswith("cowork:"):
        return "Cowork"
    return "Other"


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


def _build_daily_rollups(sessions: list[dict]) -> list[dict]:
    daily: dict[str, dict] = defaultdict(lambda: {
        "sessions": 0, "skill_sessions": 0, "turns": 0, "tokens": 0, "skill_runs": 0,
    })
    for row in sessions:
        last_ts = _parse_ts(row.get("last_ts"))
        if not last_ts:
            continue
        day = last_ts.date().isoformat()
        d = daily[day]
        d["sessions"] += 1
        d["turns"] += row["turns"]
        d["tokens"] += row["tokens_total"]
        d["skill_runs"] += row["skill_runs"]
        if row["skill_runs"] > 0:
            d["skill_sessions"] += 1
    return [{"date": day, **daily[day]} for day in sorted(daily)]


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def build_snapshot(window_days: int = 30) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    inventory = build_inventory()
    cli_files = _list_cli_transcripts()
    cowork_files = _list_cowork_transcripts()
    desktop_sids = _desktop_session_ids()

    # Raw events from all transcripts.
    raw_events: list[dict] = []
    for path in cli_files:
        raw_events.extend(_extract_events_from_transcript(path, "cli", desktop_sids))
    for path in cowork_files:
        raw_events.extend(_extract_events_from_transcript(path, "cowork", desktop_sids))

    # Drop bare Read SKILL.md (false-positive mitigation).
    audit_bare = [e for e in raw_events if e["type"] == "read_skill_md" and e.get("likely_bare")]
    ranking_events = [e for e in raw_events if not (e["type"] == "read_skill_md" and e.get("likely_bare"))]

    # Cross-check against inventory — unknown names go to audit only.
    known_transcript, unknown = _reject_unknown(ranking_events, inventory)

    # Window + dedupe.
    in_window = [
        e for e in known_transcript
        if (_parse_ts(e["ts"]) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    in_window_dedup = _dedupe_same_session(in_window)

    # Optional gstack telemetry — merge if present.
    gstack_events = [
        e for e in _read_gstack_events()
        if (_parse_ts(e["ts"]) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    gstack_known, _ = _reject_unknown(gstack_events, inventory)
    merged_events = _merge_with_gstack(in_window_dedup, gstack_known)

    # Per-session metadata. Subagent transcripts are excluded from the
    # session list itself (they roll up to their parent for skill counts).
    top_level_cli = [p for p in cli_files if not _is_subagent(p)]
    events_by_session: dict[str, list[dict]] = defaultdict(list)
    for event in merged_events:
        events_by_session[event["session_id"]].append(event)

    session_rows: list[dict] = []
    for source, files in (("cli", top_level_cli), ("cowork", cowork_files)):
        for path in files:
            meta = _session_metadata(path)
            if meta["turns"] == 0 and not meta["cwd"]:
                continue
            last_ts = _parse_ts(meta["last_ts"])
            if last_ts and last_ts < cutoff:
                continue

            session_id = meta["session_id"] or path.stem
            if source == "cli":
                surface = "desktop_code_tab" if session_id in desktop_sids else "cli_terminal"
                project = _project_for_cwd(meta["cwd"])
            else:
                surface = "cowork"
                project = "(Cowork sandbox)"

            session_events = events_by_session.get(session_id, [])
            skill_counter = Counter(e["skill"] for e in session_events)
            session_rows.append({
                "session_id": session_id,
                "title": meta["title"],
                "surface": surface,
                "project": project,
                "last_ts": meta["last_ts"],
                "last_used": last_ts.strftime("%Y-%m-%d") if last_ts else None,
                "turns": meta["turns"],
                "tokens_total": meta["tokens_total"],
                "tool_uses": meta["tool_uses"],
                "total_tool_uses": sum(meta["tool_uses"].values()),
                "skill_runs": sum(skill_counter.values()),
                "skill_counter": dict(skill_counter),
                "model": meta["model"],
                "transcript": str(path),
            })

    session_rows.sort(
        key=lambda r: _parse_ts(r["last_ts"]) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    # Aggregate skill counts from the dedup'd merged events.
    skill_counts = Counter(e["skill"] for e in merged_events)
    used_skill_names = set(skill_counts)
    unused_names = sorted(n for n in inventory if n not in used_skill_names)
    dormant_by_origin: dict[str, list[str]] = defaultdict(list)
    installed_by_origin: Counter[str] = Counter()
    for name, meta in inventory.items():
        installed_by_origin[_origin_bucket(meta["raw_scope"])] += 1
    for name in unused_names:
        meta = inventory.get(name, {})
        dormant_by_origin[_origin_bucket(meta.get("raw_scope", ""))].append(name)

    last_seen: dict[str, str] = {}
    for event in merged_events:
        cur = last_seen.get(event["skill"])
        if cur is None or (event["ts"] and event["ts"] > cur):
            last_seen[event["skill"]] = event["ts"]

    top_skills: list[dict] = []
    for skill, runs in skill_counts.most_common():
        meta = inventory.get(skill) or inventory.get(skill.split(":")[-1], {})
        ts = _parse_ts(last_seen.get(skill))
        top_skills.append({
            "skill": skill,
            "runs": runs,
            "last_used": ts.strftime("%Y-%m-%d") if ts else None,
            "summary": (meta.get("summary") or "").strip(),
            "origin": meta.get("origin") or "",
            "pack": meta.get("pack") or "",
            "raw_scope": meta.get("raw_scope") or "",
        })

    total_turns = sum(r["turns"] for r in session_rows)
    total_tokens = sum(r["tokens_total"] for r in session_rows)
    sessions_with_skills = sum(1 for r in session_rows if r["skill_runs"] > 0)

    tool_totals: Counter[str] = Counter()
    tool_session_reach: dict[str, set[str]] = defaultdict(set)
    for row in session_rows:
        for tool, n in row["tool_uses"].items():
            tool_totals[tool] += n
            tool_session_reach[tool].add(row["session_id"])
    aggregate_tools = [
        {"tool": tool, "calls": n, "sessions": len(tool_session_reach[tool])}
        for tool, n in tool_totals.most_common()
    ]

    daily_rollups = _build_daily_rollups(session_rows)

    surface_rollups: Counter[str] = Counter(r["surface"] for r in session_rows)

    snapshot = {
        "meta": {
            "generated_at": now.isoformat(),
            "window_days": window_days,
            "window_start": cutoff.date().isoformat(),
            "window_end": now.date().isoformat(),
        },
        "stats": {
            "installed_count": len(inventory),
            "active_count": len(used_skill_names),
            "skill_runs_total": sum(skill_counts.values()),
            "sessions_total": len(session_rows),
            "sessions_with_skills": sessions_with_skills,
            "turns_total": total_turns,
            "tokens_total": total_tokens,
            "tokens_total_compact": _format_compact(total_tokens),
        },
        "inventory": inventory,
        "top_skills": top_skills,
        "skill_counts": dict(skill_counts),
        "last_seen": last_seen,
        "sessions": session_rows,
        "events": merged_events,
        "events_audit": {
            "bare_read_skill_md": audit_bare,
            "unknown_names": sorted({e["skill"] for e in unknown}),
            "unknown_event_count": len(unknown),
        },
        "tool_totals": dict(tool_totals),
        "aggregate_tools": aggregate_tools,
        "daily_rollups": daily_rollups,
        "dormant_by_origin": {k: sorted(v) for k, v in dormant_by_origin.items()},
        "installed_by_origin": dict(installed_by_origin),
        "surface_rollups": dict(surface_rollups),
        "coverage": {
            "cli_transcripts": len(cli_files),
            "cowork_transcripts": len(cowork_files),
            "gstack_events": len(gstack_events),
            "gstack_telemetry_present": GSTACK_USAGE_PATH.is_file(),
            "unknown_event_count": len(unknown),
            "unknown_name_count": len({e["skill"] for e in unknown}),
            "bare_read_skill_md_count": len(audit_bare),
        },
    }
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit a Tinyhat local snapshot as JSON.")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument(
        "--output",
        default=str(DEFAULT_SNAPSHOT_PATH),
        help=f"Path to write the snapshot JSON (default: {DEFAULT_SNAPSHOT_PATH})",
    )
    args = parser.parse_args()

    snapshot = build_snapshot(window_days=args.window_days)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    stats = snapshot["stats"]
    print(
        f"Wrote {output_path} — {stats['installed_count']} installed skills, "
        f"{stats['active_count']} active in last {args.window_days}d, "
        f"{stats['skill_runs_total']} runs, {stats['sessions_total']} sessions.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
