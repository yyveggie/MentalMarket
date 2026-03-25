#!/usr/bin/env python3
"""Generate config coverage report by scanning code defaults vs config.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"
REPORT_PATH = ROOT / "CONFIG_COVERAGE_REPORT.md"

TARGET_FILES = [
    ROOT / "run.py",
    ROOT / "app" / "domain" / "agent.py",
    ROOT / "app" / "simulation" / "engine.py",
    ROOT / "app" / "infrastructure" / "api_balancer.py",
]

# Map local config dict variables to config.yaml sections.
VAR_SECTION_MAP = {
    "sim_cfg": "simulation",
    "api_cfg": "api",
    "agent_cfg": "agent",
    "evo_cfg": "evolution",
    "social_cfg": "social",
    "ob_cfg": "orderbook",
    "storage_cfg": "storage",
    "infer_cfg": "api.inference",
}

# Map AgentManager bound config objects to config.yaml sections.
SELF_CFG_MAP = {
    "agent_config": "agent",
    "social_config": "social",
    "evolution_config": "evolution",
    "sim_config": "simulation",
}

GET_RE = re.compile(r"(?P<obj>[A-Za-z_][A-Za-z0-9_]*)\.get\(\s*\"(?P<key>[^\"]+)\"\s*,\s*(?P<default>[^\)]*)\)")
SELF_GET_RE = re.compile(r"self\.(?P<obj>[A-Za-z_][A-Za-z0-9_]*)\.get\(\s*\"(?P<key>[^\"]+)\"\s*,\s*(?P<default>[^\)]*)\)")


@dataclass
class Record:
    path: str
    line: int
    section: str
    key: str
    default: str
    configured: bool


def get_nested(data: dict[str, Any], dotted_path: str) -> Any:
    cur: Any = data
    for seg in dotted_path.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def has_nested_key(data: dict[str, Any], dotted_path: str, key: str) -> bool:
    parent = get_nested(data, dotted_path)
    return isinstance(parent, dict) and key in parent


def scan_file(path: Path, config: dict[str, Any]) -> list[Record]:
    records: list[Record] = []
    lines = path.read_text(encoding="utf-8").splitlines()

    for idx, line in enumerate(lines, start=1):
        m = GET_RE.search(line)
        if m:
            obj = m.group("obj")
            if obj in VAR_SECTION_MAP:
                section = VAR_SECTION_MAP[obj]
                key = m.group("key")
                records.append(
                    Record(
                        path=str(path.relative_to(ROOT)),
                        line=idx,
                        section=section,
                        key=key,
                        default=m.group("default").strip(),
                        configured=has_nested_key(config, section, key),
                    )
                )

        m2 = SELF_GET_RE.search(line)
        if m2:
            obj = m2.group("obj")
            if obj in SELF_CFG_MAP:
                section = SELF_CFG_MAP[obj]
                key = m2.group("key")
                records.append(
                    Record(
                        path=str(path.relative_to(ROOT)),
                        line=idx,
                        section=section,
                        key=key,
                        default=m2.group("default").strip(),
                        configured=has_nested_key(config, section, key),
                    )
                )
    return records


def main() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}

    all_records: list[Record] = []
    for f in TARGET_FILES:
        if f.exists():
            all_records.extend(scan_file(f, config))

    # Deduplicate by section+key, keep earliest occurrence
    uniq: dict[tuple[str, str], Record] = {}
    for r in all_records:
        uniq.setdefault((r.section, r.key), r)

    records = sorted(uniq.values(), key=lambda x: (x.section, x.key))
    missing = [r for r in records if not r.configured]

    lines: list[str] = []
    lines.append("# Config Coverage Report")
    lines.append("")
    lines.append(f"- Config file: `{CONFIG_PATH.relative_to(ROOT)}`")
    lines.append(f"- Scanned files: {len([f for f in TARGET_FILES if f.exists()])}")
    lines.append(f"- Parameters with code defaults: {len(records)}")
    lines.append(f"- Parameters currently using default (missing in config): {len(missing)}")
    lines.append("")

    if missing:
        lines.append("## Missing Keys (Default In Effect)")
        lines.append("")
        lines.append("| Section | Key | Code Default | Source |")
        lines.append("|---|---|---:|---|")
        for r in missing:
            lines.append(
                f"| {r.section} | {r.key} | `{r.default}` | `{r.path}:{r.line}` |"
            )
        lines.append("")
    else:
        lines.append("## Missing Keys (Default In Effect)")
        lines.append("")
        lines.append("None. All scanned parameters are present in config.")
        lines.append("")

    lines.append("## All Scanned Parameters")
    lines.append("")
    lines.append("| Section | Key | In Config | Code Default | Source |")
    lines.append("|---|---|---|---:|---|")
    for r in records:
        lines.append(
            f"| {r.section} | {r.key} | {'yes' if r.configured else 'no'} | `{r.default}` | `{r.path}:{r.line}` |"
        )

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
