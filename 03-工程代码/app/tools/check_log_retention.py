#!/usr/bin/env python
"""溯源日志留存自检 —— 官方第 9 项「生成内容溯源留存 ≥6 个月」的**可复跑**证据（`T-090`）。

## 干什么

1. 报出生效配置（落盘目录、留存天数）——**配置错了先于数据错**；
2. 逐通道（应用日志 `app.log*` / 溯源审计 `audit.log*`）统计：
   覆盖区间、天数、文件数、条目数、**日期缺口**、最新一条的时点；
3. 判定（退出码可进 CI）：

| 判定 | 条件 | 退出码 |
| --- | --- | --- |
| FAIL | 留存天数 < 180（官方下限）／今日无日志（服务没在写）／覆盖区间有缺口 | 1 |
| WARN | 历史不足 180 天（新部署常态：**还验不了「6 个月前还在」**） | 0 |
| PASS | 覆盖区间 ≥ 留存天数且无缺口 | 0 |

⚠️ **不造假**：本脚本只读实际落盘文件，不生成、不补写任何「历史」。
新部署时输出 WARN 是**如实**的——「6 个月留存」只能由时间证明，不能由脚本声称。

## 怎么用

```bash
cd 03-工程代码/app
python tools/check_log_retention.py                 # 按配置的 log_dir
python tools/check_log_retention.py --json          # 机读（贴进报告/CI）
python tools/check_log_retention.py --dir E:/logs   # 指定目录（部署机大盘）
```

截图举证建议：跑一次上面的命令，截「配置 ＋ 覆盖区间 ＋ 判定」三行即可
（与 `06-测试评估/` 的报告同批留档）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# 允许 `python tools/check_log_retention.py` 直接跑（工程根 = app 的上一级）
_APP_DIR = Path(__file__).resolve().parents[1]
_CODE_DIR = _APP_DIR.parent
for p in (str(_CODE_DIR),):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.core.config import get_settings  # noqa: E402
from app.core.logging import _PROJECT_ROOT  # noqa: E402

#: 官方下限（月按 30 天折算 → 180）
MIN_RETENTION_DAYS = 180

#: 通道 → 文件前缀
CHANNELS = {"app": "app.log", "audit": "audit.log"}

_TS_RE = re.compile(r'"ts"\s*:\s*"([0-9T:\-+\.]+)"')


def _resolve_dir(raw: str) -> Path:
    return Path(raw) if raw else _PROJECT_ROOT / ".wb-e2e" / "logs"


def _iter_channel_files(log_dir: Path, prefix: str) -> list[Path]:
    """活跃文件 ＋ 轮转件（`app.log.2026-11-03` 形态）。"""
    files = []
    active = log_dir / prefix
    if active.exists():
        files.append(active)
    files.extend(sorted(log_dir.glob(f"{prefix}.[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]")))
    return files


def _read_stats(path: Path) -> dict:
    """读文件的条目数、最早/最新时点（按行内 `ts` 字段，比文件名可靠）。"""
    count = 0
    first_ts: str | None = None
    last_ts: str | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                count += 1
                m = _TS_RE.search(line)
                if m:
                    ts = m.group(1)
                    first_ts = first_ts or ts
                    last_ts = ts
    except OSError as exc:  # noqa: BLE001 - 自检脚本如实报，不抛栈
        return {"file": path.name, "error": type(exc).__name__, "count": 0,
                "first_ts": None, "last_ts": None, "day": None}
    day = None
    if first_ts:
        try:
            day = datetime.fromisoformat(first_ts.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            day = None
    return {"file": path.name, "count": count, "first_ts": first_ts,
            "last_ts": last_ts, "day": day}


def check(log_dir: Path, retention_days: int, channels: tuple[str, ...]) -> dict:
    result: dict = {
        "log_dir": str(log_dir),
        "retention_days": retention_days,
        "min_retention_days": MIN_RETENTION_DAYS,
        "today": date.today().isoformat(),
        "channels": {},
        "verdict": "PASS",
        "reasons": [],
    }
    if retention_days < MIN_RETENTION_DAYS:
        result["verdict"] = "FAIL"
        result["reasons"].append(
            f"留存天数 {retention_days} < 官方下限 {MIN_RETENTION_DAYS} 天（6 个月）"
        )

    for ch in channels:
        prefix = CHANNELS[ch]
        files = _iter_channel_files(log_dir, prefix)
        stats = [_read_stats(f) for f in files]
        days = sorted({s["day"] for s in stats if s.get("day")})
        total = sum(s["count"] for s in stats)
        # 缺口：覆盖区间内应有而没有的日期（只对「已有连续观测」的区间判）
        gaps: list[str] = []
        if days:
            d0 = date.fromisoformat(days[0])
            d1 = date.fromisoformat(days[-1])
            have = {date.fromisoformat(d) for d in days}
            cur = d0
            while cur <= d1:
                if cur not in have:
                    gaps.append(cur.isoformat())
                cur += timedelta(days=1)
        channel = {
            "files": len(files),
            "entries": total,
            "days_covered": len(days),
            "first_day": days[0] if days else None,
            "last_day": days[-1] if days else None,
            "latest_ts": next((s["last_ts"] for s in reversed(stats) if s.get("last_ts")), None),
            "gaps": gaps,
            "today_written": date.today().isoformat() in set(days),
        }
        result["channels"][ch] = channel

        if not files:
            result["verdict"] = "FAIL"
            result["reasons"].append(f"[{ch}] 目录内无 {prefix} 文件：日志**从未落盘**")
            continue
        if not channel["today_written"]:
            result["verdict"] = "FAIL"
            result["reasons"].append(f"[{ch}] 今日无日志：服务未在写该通道（或今天尚未产生事件）")
        if gaps:
            result["verdict"] = "FAIL"
            result["reasons"].append(f"[{ch}] 覆盖区间存在 {len(gaps)} 个缺口日（首 {gaps[0]}）")
        if channel["days_covered"] < retention_days and result["verdict"] == "PASS":
            result["verdict"] = "WARN"
            result["reasons"].append(
                f"[{ch}] 历史覆盖 {channel['days_covered']} 天 < 留存要求 {retention_days} 天"
                "（新部署常态：**尚不能证明** 6 个月前的日志仍在，须随运行时间自然满足）"
            )
    return result


def _render(result: dict) -> str:
    lines = [
        "=" * 78,
        "溯源日志留存自检（官方第 9 项 · ≥6 个月）",
        "=" * 78,
        f"日志目录      : {result['log_dir']}",
        f"留存天数(配置): {result['retention_days']} 天（官方下限 {result['min_retention_days']}）",
        f"自检日期      : {result['today']}",
        "-" * 78,
    ]
    for ch, c in result["channels"].items():
        lines += [
            f"[{ch}] 文件 {c['files']} 个 ｜ 条目 {c['entries']} 条 ｜ 覆盖 {c['days_covered']} 天",
            f"      区间 {c['first_day']} ~ {c['last_day']} ｜ 最新条目 {c['latest_ts']}",
            f"      今日已写: {'是' if c['today_written'] else '否'} ｜ 缺口 {len(c['gaps'])} 个",
        ]
    lines.append("-" * 78)
    lines.append(f"判定: {result['verdict']}")
    for r in result["reasons"]:
        lines.append(f"  · {r}")
    lines.append("=" * 78)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="溯源日志留存自检（官方第 9 项）")
    ap.add_argument("--dir", default="", help="日志目录（留空用配置 APP_LOG_DIR）")
    ap.add_argument("--days", type=int, default=0, help="留存天数（留空用配置）")
    ap.add_argument("--channel", default="app,audit", help="通道：app,audit（默认两者）")
    ap.add_argument("--json", action="store_true", help="机读输出")
    args = ap.parse_args(argv)

    settings = get_settings()
    log_dir = _resolve_dir(args.dir or str(getattr(settings, "log_dir", "") or ""))
    days = args.days or int(getattr(settings, "log_retention_days", 180) or 180)
    channels = tuple(c.strip() for c in args.channel.split(",") if c.strip() in CHANNELS)
    if not channels:
        print("通道参数非法：只接受 app / audit", file=sys.stderr)
        return 2

    result = check(log_dir, days, channels)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _render(result))
    return 0 if result["verdict"] in ("PASS", "WARN") else 1


if __name__ == "__main__":
    raise SystemExit(main())
