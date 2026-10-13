#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输出契约校验器 · validate_output.py

定位：
  validate_templates.py 校验「模板写了什么」（结构／变量一致性）；
  本脚本校验「产物长什么样」——即模板输出 JSON 是否满足链路已定案的**封闭枚举与接缝约定**。

  ⚠️ 本脚本**不联网、不调用模型**，只对「已产出的 JSON」做静态核对。
     因此它既能用于当前的**人工构造用例**（examples/*.md 内的 JSON 块），
     也能在模型就绪后直接对**真实输出**执行（用法见下）。

首批校验规则（依 2026-10-13 导演视角两轮评审定案）：
  R1 PURPOSE_ENUM          scenes_outline[].purpose / acts[].scenes[].purpose
                           仅限五值：建立／升级／转折／反转／收束
                           —— 本脚本的**首要规则**（对应 R-05：枚举未闭合导致用例越界）
  R2 FILL_STAGE_ENUM       unspecified[].fill_stage 仅限：
                           synopsis／script／storyboard／shot_prompt
  R3 SCENE_NO_CONTINUITY   场号须从 1 起连续、不重复（R-06：区间与档位口径）
  R4 EST_SECONDS_SUM       total_est_seconds 须等于各场 est_seconds 之和
  R5 REQUIRED_KEYS         按产物形态（synopsis／script／storyboard）核对必备顶层字段
  R6 ACT_STRUCTURE         （仅 script）acts 恰为 3 幕，且每场 act_no 与所属幕一致

剧本层补充规则（SW-005 `script_v1` v2.0.0，2026-10-13 依导演视角独立评审 `SR-01`~`SR-11` 新增）：
  R20 DIALOGUE_TYPE_ENUM   dialogue[].type 仅限「对白／旁白／画外音」（SR-09：该枚举此前未登记）
  R21 UNSPECIFIED_OWNER    缺口台账 unspecified[].owner 仅限「算法作者／客户／运维」；
                           且**客户侧缺口不得前移到下游**（SR-02）——下游（分镜／提示词）职责上
                           无法补叙事事实与设计确认，把「待客户确认」推给下游阶段等于把洞换个位置继续走。
                           · 剧本层：`owner=客户` 者 `fill_stage` 必须为 `script`（本层发起追问）；
                           · 分镜层：`owner=客户` 者 `fill_stage` 不得为 `shot_prompt`。
                           本条把该口径从「靠人记着」变成「跑得出来」。
  R22 SCENE_DURATION_FLOOR 每场 est_seconds 须 ≥ 8 秒（＝单镜时长下限 4s × 生成单元最少 2 镜）——
                           SR-08：场时长事实上就是该场的「镜数预算」，低于 8 秒下游切不出任何合规单元。
                           （纵向求和另有 R4；本规则管的是横向「够不够切」。）

分镜层规则（SW-006 `storyboard_v1`，2026-10-13 新增，依规范 §3.5／§3.6／§4.2）：
  R7  SHOT_ID_FORMAT       shot_id 唯一且形如 S<场号两位>-SH<镜号三位>
  R8  SHOT_NO_SEQ          同一场内 shot_no 从 1 起连续、不跳号
  R9  UNIT_LINK            shots[].unit_id 必须命中 units[]；units[].shot_ids 与 shots 双向一致，
                           且成员镜的 scene_no 必须等于其所属单元的 scene_no
  R10 UNIT_SIZE            units[].shot_ids 成员数必须为 2 或 3（规范 §4.3：1 镜单元结构性不合格）
  R11 UNIT_MOVE_UNIQUE     同一单元内 camera.move 取值不得重复
  R12 DURATION_INT_SECONDS duration_ms 必须为整秒（1000 的整数倍）
  R13 DURATION_BOUNDS      单镜时长须落在 [4s, 15s]（MiniMax H3 口径；可用 --duration-bounds 覆盖）
  R14 DURATION_SUM         total_duration_ms 须等于各镜 duration_ms 之和
  R15 DIALOGUE_SPEED       dialogue 字数 ÷ 秒数 ≤ 9（规范 §4.5）
  R16 ENUM_VALUES          shot_size 取景别六值之一；camera.move 取运镜 20 类之一
  R17 STATIC_POV_PARAMS    camera.move 为 static／pov 时不得携带 amplitude／speed（规范 §3.7.2）
  R18 TRANSITION_SIDE      转场单侧表达：单元内非末镜不得填 transition_out
  R19 GATE                 **11 项镜头语言质量门**（整片 + 逐生成单元）——
                           阈值直接引用 audit_shots.py 的 GATE 与其容差算法，不得另立一套（规范 §4.2）

  ⚠️ 口径差异（必须知道）：R19 判定的是**结构化字段是否有值**（SW-006 的产物）；
     audit_shots.py 判定的是**适配投喂文本**（SW-007 的产物）。两者对象不同——
     本层判定通过不等于下游文本判定通过，SW-007 完成后须对文本再跑一次（规范 §4.8）。

用法：
  python validate_output.py                     # 扫描 examples/*.md 内全部 JSON 块
  python validate_output.py --file out.json     # 校验单个 JSON 文件（真实模型输出）
  python validate_output.py --json              # 机器可读结果
  python validate_output.py --duration-bounds 4-15   # 覆盖单镜时长区间（秒）

退出码：
  0 = 全部通过 ｜ 1 = 存在失败项 ｜ 2 = 环境缺失依赖或用法错误

依赖：仅标准库（无 pyyaml 依赖）
"""
import sys
import os
import re
import json
import math
import argparse
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))

# ---------------- 封闭枚举（唯一真值来源，改动须同步模板与 SCHEMA.md） ----------------
PURPOSE_ENUM = ["建立", "升级", "转折", "反转", "收束"]
FILL_STAGE_ENUM = ["synopsis", "script", "storyboard", "shot_prompt"]

# 剧本层封闭枚举（2026-10-13 依 SR-09 / SR-02 新增登记）
DIALOGUE_TYPE_ENUM = ["对白", "旁白", "画外音"]
OWNER_ENUM = ["算法作者", "客户", "运维"]      # 缺口台账的闭合责任人
OWNER_CLIENT = "客户"

# 场时长下限（秒）—— 单镜时长下限 4s × 生成单元最少 2 镜（SR-08：场时长＝该场的镜数预算）
SCENE_MIN_SECONDS = 8

# 分镜层封闭枚举（规范 §3.7.1 / §3.7.2 / §3.7.5）
SHOT_SIZE_ENUM = ["extreme_wide", "wide", "full", "medium", "close_up", "extreme_close_up"]
MOVE_ENUM = [
    "static", "push_in", "pull_out", "zoom_in", "zoom_out",
    "pan_left", "pan_right", "tilt_up", "tilt_down",
    "truck_left", "truck_right", "pedestal_up", "pedestal_down",
    "arc", "tracking", "shake_slight", "shake_strong", "pov", "roll_cw", "roll_ccw",
]
NO_PARAM_MOVES = ("static", "pov")   # 不得携带幅度与速度
TRANSITION_ENUM = ["cut", "fade_in", "fade_out", "dissolve", "wipe"]

# 镜头语言质量门阈值 —— **直接引用 audit_shots.py 的 GATE**，不得另立一套（规范 §4.2）
GATE = {
    "运镜覆盖": 1.00,       # 每镜都要有
    "景别覆盖": 1.00,       # 每镜都要有
    "静止镜占比": 0.40,     # 上限
    "运镜类型数": 5,        # 下限
    "单一运镜占比": 0.35,   # 上限
    "角度覆盖": 0.40,
    "光学覆盖": 0.30,
    "构图覆盖": 0.50,
    "轴线覆盖": 0.30,
    "光线覆盖": 0.40,
    "画面结果覆盖": 0.60,
}

# 单镜时长区间（毫秒）—— 默认取 MiniMax H3 口径（唯一 verified 的目标模型）
DURATION_MIN_MS, DURATION_MAX_MS = 4000, 15000

JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)
SHOT_ID_RE = re.compile(r"^S\d{2}-SH\d{3}$")

RESULT = {"checks": 0, "errors": [], "warnings": []}
QUIET = False


def out(msg=""):
    if not QUIET:
        print(msg)


def ok(msg):
    RESULT["checks"] += 1
    out(f"  [OK]   {msg}")


def err(msg):
    RESULT["errors"].append(msg)
    out(f"  [FAIL] {msg}")


def warn(msg):
    RESULT["warnings"].append(msg)
    out(f"  [WARN] {msg}")


# ---------------- 形态识别与字段抽取 ----------------
def detect_shape(doc):
    """按产物顶层字段识别形态。"""
    if not isinstance(doc, dict):
        return None
    if "acts" in doc:
        return "script"
    if "shots" in doc and "units" in doc:
        return "storyboard"
    if "scenes_outline" in doc:
        return "synopsis"
    return None


def iter_scenes(doc, shape):
    """产出 (场号, purpose, est_seconds, 定位串) 四元组，屏蔽两种形态差异。"""
    if shape == "script":
        for ai, act in enumerate(doc.get("acts") or []):
            for si, sc in enumerate(act.get("scenes") or []):
                yield (sc, f"acts[{ai}].scenes[{si}]")
    else:
        for si, sc in enumerate(doc.get("scenes_outline") or []):
            yield (sc, f"scenes_outline[{si}]")


# ---------------- 规则实现 ----------------
def rule_purpose_enum(doc, shape, where):
    """R1：purpose 封闭枚举（本脚本首要规则）。"""
    seen = 0
    bad = []
    for sc, loc in iter_scenes(doc, shape):
        if not isinstance(sc, dict):
            continue
        seen += 1
        val = sc.get("purpose")
        if val is None:
            bad.append(f"{loc}.purpose 缺失")
        elif val not in PURPOSE_ENUM:
            bad.append(f"{loc}.purpose = 『{val}』")
    if bad:
        err(f"{where} · R1 PURPOSE_ENUM：越界/缺失 {len(bad)} 处 → " + "；".join(bad[:6]))
    elif seen:
        ok(f"{where} · R1 PURPOSE_ENUM：{seen} 处 purpose 全部落在五值枚举内")
    else:
        warn(f"{where} · R1 PURPOSE_ENUM：未找到任何场次（跳过）")


def rule_fill_stage_enum(doc, where):
    """R2：unspecified[].fill_stage 封闭枚举。"""
    items = doc.get("unspecified") or []
    if not isinstance(items, list) or not items:
        warn(f"{where} · R2 FILL_STAGE_ENUM：无 unspecified 条目（跳过）")
        return
    bad = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            bad.append(f"unspecified[{i}] 非对象")
            continue
        val = it.get("fill_stage")
        if val not in FILL_STAGE_ENUM:
            bad.append(f"unspecified[{i}].fill_stage = 『{val}』")
    if bad:
        err(f"{where} · R2 FILL_STAGE_ENUM：越界/缺失 {len(bad)} 处 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R2 FILL_STAGE_ENUM：{len(items)} 条 fill_stage 全部落在四值枚举内")


def rule_scene_no_continuity(doc, shape, where):
    """R3：场号从 1 起连续、不重复。"""
    nos = []
    for sc, loc in iter_scenes(doc, shape):
        if isinstance(sc, dict):
            nos.append(sc.get("no"))
    if not nos:
        warn(f"{where} · R3 SCENE_NO_CONTINUITY：无场号可校（跳过）")
        return
    if any(not isinstance(n, int) for n in nos):
        err(f"{where} · R3 SCENE_NO_CONTINUITY：存在非整数场号 → {nos}")
        return
    if sorted(nos) != list(range(1, len(nos) + 1)):
        err(f"{where} · R3 SCENE_NO_CONTINUITY：场号应为 1..{len(nos)}，实际 {nos}")
    else:
        ok(f"{where} · R3 SCENE_NO_CONTINUITY：场号 1..{len(nos)} 连续且唯一")


def rule_est_seconds_sum(doc, shape, where):
    """R4：total_est_seconds == Σ est_seconds。"""
    total = doc.get("total_est_seconds")
    vals = []
    for sc, loc in iter_scenes(doc, shape):
        if isinstance(sc, dict):
            vals.append(sc.get("est_seconds"))
    if total is None:
        err(f"{where} · R4 EST_SECONDS_SUM：缺 total_est_seconds")
        return
    if any(not isinstance(v, (int, float)) for v in vals):
        err(f"{where} · R4 EST_SECONDS_SUM：存在非数值 est_seconds → {vals}")
        return
    s = sum(vals)
    if s != total:
        err(f"{where} · R4 EST_SECONDS_SUM：Σest_seconds={s} ≠ total_est_seconds={total}")
    else:
        ok(f"{where} · R4 EST_SECONDS_SUM：Σ{len(vals)} 场 = {s} = total_est_seconds")


def rule_required_keys(doc, shape, where):
    """R5：按形态核对必备顶层字段。"""
    need = {
        "synopsis": ["title", "logline", "protagonist", "supporting", "world",
                     "conflict", "scenes_outline", "ending", "forbidden_items",
                     "total_est_seconds", "unspecified"],
        "script": ["title", "logline", "genre", "style_bible", "characters", "props", "acts",
                   "forbidden_items", "total_est_seconds", "unspecified"],
        "storyboard": ["title", "genre", "style_ref", "aspect_ratio_default",
                       "total_duration_ms", "units", "shots", "forbidden_items",
                       "unspecified", "quality_gate"],
    }[shape]
    miss = [k for k in need if k not in doc]
    if miss:
        err(f"{where} · R5 REQUIRED_KEYS（{shape}）：缺 {miss}")
    else:
        ok(f"{where} · R5 REQUIRED_KEYS（{shape}）：{len(need)} 个必备顶层字段齐备")


def rule_act_structure(doc, where):
    """R6（仅 script）：恰为 3 幕，且每场 act_no 与所属幕一致。"""
    acts = doc.get("acts")
    if not isinstance(acts, list) or not acts:
        err(f"{where} · R6 ACT_STRUCTURE：acts 缺失或为空")
        return
    if len(acts) != 3:
        err(f"{where} · R6 ACT_STRUCTURE：幕数应为 3，实际 {len(acts)}")
        return
    bad = []
    for ai, act in enumerate(acts):
        if not isinstance(act, dict):
            bad.append(f"acts[{ai}] 非对象")
            continue
        expect = act.get("act_no")
        for si, sc in enumerate(act.get("scenes") or []):
            if isinstance(sc, dict) and sc.get("act_no") != expect:
                bad.append(f"acts[{ai}].scenes[{si}].act_no={sc.get('act_no')} 与幕 act_no={expect} 不一致")
    if bad:
        err(f"{where} · R6 ACT_STRUCTURE：{len(bad)} 处不一致 → " + "；".join(bad[:5]))
    else:
        ok(f"{where} · R6 ACT_STRUCTURE：3 幕齐备，各场 act_no 归属一致")


# ---------------- 剧本层补充规则（SW-005 · script_v1 v2.0.0 · 依 SR-02 / SR-08 / SR-09） ----------------
def rule_dialogue_type(doc, where):
    """R20：dialogue[].type 仅限「对白／旁白／画外音」（SR-09）。"""
    entries = []
    for ai, act in enumerate(doc.get("acts") or []):
        if not isinstance(act, dict):
            continue
        for si, sc in enumerate(act.get("scenes") or []):
            if not isinstance(sc, dict):
                continue
            for di, d in enumerate(sc.get("dialogue") or []):
                if isinstance(d, dict):
                    entries.append((f"acts[{ai}].scenes[{si}].dialogue[{di}]", d.get("type")))
    if not entries:
        warn(f"{where} · R20 DIALOGUE_TYPE_ENUM：无对白条目（跳过）")
        return
    bad = [f"{loc}.type = 『{v}』" for loc, v in entries if v not in DIALOGUE_TYPE_ENUM]
    if bad:
        err(f"{where} · R20 DIALOGUE_TYPE_ENUM：越界/缺失 {len(bad)} 处 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R20 DIALOGUE_TYPE_ENUM：{len(entries)} 条 dialogue.type 全部落在三值枚举内")


def rule_unspecified_owner(doc, shape, where):
    """R21：缺口台账 owner 枚举；且「客户侧缺口不得前移」（SR-02）。

    shape == script     → owner=客户 者 fill_stage 必须为 script（本层，发起追问的阶段）
    shape == storyboard → owner=客户 者 fill_stage 不得为 shot_prompt（下游同样无权补）
    """
    items = doc.get("unspecified") or []
    if not isinstance(items, list) or not items:
        warn(f"{where} · R21 UNSPECIFIED_OWNER：无 unspecified 条目（跳过）")
        return
    objs = [it for it in items if isinstance(it, dict)]
    if not any("owner" in it for it in objs):
        warn(f"{where} · R21 UNSPECIFIED_OWNER：条目均未含 owner（跳过；synopsis 层未定义该字段）")
        return
    bad = []
    for i, it in enumerate(objs):
        o = it.get("owner")
        fs = it.get("fill_stage")
        if o not in OWNER_ENUM:
            bad.append(f"unspecified[{i}].owner = 『{o}』")
        elif o == OWNER_CLIENT:
            if shape == "script" and fs != "script":
                bad.append(f"unspecified[{i}] owner=客户 但 fill_stage=『{fs}』"
                           f"（须为 script——本层发起追问，下游无人能补）")
            elif shape == "storyboard" and fs == "shot_prompt":
                bad.append(f"unspecified[{i}] owner=客户 但 fill_stage=『shot_prompt』"
                           f"（不得前移至下游——下游同样无权补）")
    if bad:
        err(f"{where} · R21 UNSPECIFIED_OWNER：{len(bad)} 处不合规 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R21 UNSPECIFIED_OWNER：{len(objs)} 条 owner 合规，"
           f"客户侧缺口均未前移至下游")


def rule_scene_duration_floor(doc, shape, where):
    """R22：每场 est_seconds ≥ SCENE_MIN_SECONDS（场时长＝该场镜数预算，SR-08）。"""
    bad, seen = [], 0
    for sc, loc in iter_scenes(doc, shape):
        if not isinstance(sc, dict):
            continue
        v = sc.get("est_seconds")
        if not isinstance(v, (int, float)):
            bad.append(f"{loc}.est_seconds 非数值（{v}）")
            continue
        seen += 1
        if v < SCENE_MIN_SECONDS:
            bad.append(f"{loc}.est_seconds={v} < {SCENE_MIN_SECONDS}")
    if not seen:
        warn(f"{where} · R22 SCENE_DURATION_FLOOR：无场次可校（跳过）")
        return
    if bad:
        err(f"{where} · R22 SCENE_DURATION_FLOOR：{len(bad)} 处低于下限 → " + "；".join(bad[:6]))
    else:
        ok(f"{where} · R22 SCENE_DURATION_FLOOR：{seen} 场 est_seconds 均 ≥ {SCENE_MIN_SECONDS}s"
           f"（下游单镜下限 4s × 单元最少 2 镜）")


# ---------------- 分镜层规则（SW-006 · storyboard_v1） ----------------
def _shots(doc):
    return [r for r in (doc.get("shots") or []) if isinstance(r, dict)]


def _units(doc):
    return [u for u in (doc.get("units") or []) if isinstance(u, dict)]


def _cam(r):
    c = r.get("camera")
    return c if isinstance(c, dict) else {}


def _sl(r):
    s = r.get("shot_language")
    return s if isinstance(s, dict) else {}


def rule_shot_id_format(doc, where):
    """R7：shot_id 唯一且形如 S<场号两位>-SH<镜号三位>。"""
    shots = _shots(doc)
    if not shots:
        err(f"{where} · R7 SHOT_ID_FORMAT：shots 缺失或为空")
        return
    ids = [r.get("shot_id") for r in shots]
    bad = [i for i in ids if not (isinstance(i, str) and SHOT_ID_RE.match(i))]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if bad:
        err(f"{where} · R7 SHOT_ID_FORMAT：格式不合规 → {bad[:6]}")
    if dup:
        err(f"{where} · R7 SHOT_ID_FORMAT：编号重复 → {dup}")
    if not bad and not dup:
        ok(f"{where} · R7 SHOT_ID_FORMAT：{len(ids)} 个 shot_id 格式合规且唯一")


def rule_shot_no_seq(doc, where):
    """R8：同一场内 shot_no 从 1 起连续、不跳号。"""
    shots = _shots(doc)
    if not shots:
        return
    groups = {}
    for r in shots:
        groups.setdefault(r.get("scene_no"), []).append(r.get("shot_no"))
    bad = []
    for sc, nos in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if any(not isinstance(n, int) for n in nos):
            bad.append(f"场 {sc} 存在非整数镜号 {nos}")
        elif sorted(nos) != list(range(1, len(nos) + 1)):
            bad.append(f"场 {sc} 镜号应为 1..{len(nos)}，实际 {sorted(nos)}")
    if bad:
        err(f"{where} · R8 SHOT_NO_SEQ：" + "；".join(bad[:5]))
    else:
        ok(f"{where} · R8 SHOT_NO_SEQ：{len(groups)} 个场内镜号均连续")


def rule_unit_link(doc, where):
    """R9：units 与 shots 双向一致，且成员镜的 scene_no 等于所属单元的 scene_no。"""
    units, shots = _units(doc), _shots(doc)
    by_id = {r.get("shot_id"): r for r in shots}
    uids = [u.get("unit_id") for u in units]
    bad = []
    if len(set(uids)) != len(uids):
        bad.append(f"unit_id 重复：{uids}")
    listed = []
    for u in units:
        for sid in (u.get("shot_ids") or []):
            listed.append(sid)
            sh = by_id.get(sid)
            if sh is None:
                bad.append(f"{u.get('unit_id')}.shot_ids 引用了不存在的镜头 {sid}")
                continue
            if sh.get("unit_id") != u.get("unit_id"):
                bad.append(f"{sid}.unit_id='{sh.get('unit_id')}' 与所属单元 '{u.get('unit_id')}' 不一致")
            if sh.get("scene_no") != u.get("scene_no"):
                bad.append(f"{sid}.scene_no={sh.get('scene_no')} 与单元场号 {u.get('scene_no')} 不一致")
    orphan = [sid for sid, sh in by_id.items() if sh.get("unit_id") not in uids]
    if orphan:
        bad.append(f"未归入任何单元的镜头：{orphan[:6]}")
    extra = sorted(set(listed) - set(by_id.keys()))
    missing = sorted(set(by_id.keys()) - set(listed))
    if extra:
        bad.append(f"shot_ids 中的多余镜头：{extra[:6]}")
    if missing:
        bad.append(f"未被任何单元收录的镜头：{missing[:6]}")
    if bad:
        err(f"{where} · R9 UNIT_LINK：" + "；".join(bad[:5]))
    else:
        ok(f"{where} · R9 UNIT_LINK：{len(units)} 个单元与 {len(shots)} 个镜头双向一致，场号归属一致")


def rule_unit_size(doc, where):
    """R10：单元成员数必须为 2 或 3（1 镜单元结构性不合格，规范 §4.3）。"""
    units = _units(doc)
    if not units:
        return
    bad = [f"{u.get('unit_id')} 成员 {len(u.get('shot_ids') or [])} 个（须为 2 或 3）"
           for u in units if len(u.get("shot_ids") or []) not in (2, 3)]
    if bad:
        err(f"{where} · R10 UNIT_SIZE：" + "；".join(bad[:6]))
    else:
        ok(f"{where} · R10 UNIT_SIZE：{len(units)} 个单元成员数均在 [2,3]")


def rule_unit_move_unique(doc, where):
    """R11：同一单元内 camera.move 取值不得重复。"""
    units = _units(doc)
    by_id = {r.get("shot_id"): r for r in _shots(doc)}
    bad = []
    for u in units:
        moves = [_cam(by_id.get(sid) or {}).get("move") for sid in (u.get("shot_ids") or [])]
        if len(set(moves)) != len(moves):
            bad.append(f"{u.get('unit_id')} 运镜重复 {moves}")
    if bad:
        err(f"{where} · R11 UNIT_MOVE_UNIQUE：" + "；".join(bad[:6]))
    else:
        ok(f"{where} · R11 UNIT_MOVE_UNIQUE：{len(units)} 个单元内运镜类型均不重复")


def rule_duration(doc, where):
    """R12/R13/R14：整秒 / 区间 / 求和。"""
    shots = _shots(doc)
    if not shots:
        err(f"{where} · R12/13/14 DURATION：shots 为空")
        return
    non_int, out_range, vals = [], [], []
    for r in shots:
        ms = r.get("duration_ms")
        if not isinstance(ms, (int, float)):
            non_int.append(f"{r.get('shot_id')} 非数值")
            continue
        vals.append(ms)
        if ms % 1000 != 0:
            non_int.append(f"{r.get('shot_id')}={ms}")
        if not (DURATION_MIN_MS <= ms <= DURATION_MAX_MS):
            out_range.append(f"{r.get('shot_id')}={ms}")
    if non_int:
        err(f"{where} · R12 DURATION_INT_SECONDS：非整秒 → " + "；".join(non_int[:6]))
    else:
        ok(f"{where} · R12 DURATION_INT_SECONDS：{len(vals)} 镜均为整秒")
    if out_range:
        err(f"{where} · R13 DURATION_BOUNDS：越界（{DURATION_MIN_MS}~{DURATION_MAX_MS}ms）→ "
            + "；".join(out_range[:6]))
    else:
        ok(f"{where} · R13 DURATION_BOUNDS：{len(vals)} 镜均落在 "
           f"{DURATION_MIN_MS // 1000}–{DURATION_MAX_MS // 1000}s")
    total, s = doc.get("total_duration_ms"), sum(vals)
    if total is None:
        err(f"{where} · R14 DURATION_SUM：缺 total_duration_ms")
    elif total != s:
        err(f"{where} · R14 DURATION_SUM：Σduration_ms={s} ≠ total_duration_ms={total}")
    else:
        ok(f"{where} · R14 DURATION_SUM：Σ{len(vals)} 镜 = {s} = total_duration_ms")


def rule_dialogue_speed(doc, where):
    """R15：台词字数 ÷ 秒数 ≤ 9（规范 §4.5）。"""
    over, checked = [], 0
    for r in _shots(doc):
        d = (r.get("dialogue") or "").strip()
        ms = r.get("duration_ms")
        if not d or not isinstance(ms, (int, float)) or ms <= 0:
            continue
        checked += 1
        rate = len(d) / (ms / 1000.0)
        if rate > 9:
            over.append(f"{r.get('shot_id')} {len(d)}字/{ms / 1000:.0f}s≈{rate:.1f}字/秒")
    if over:
        err(f"{where} · R15 DIALOGUE_SPEED：超 9 字/秒 → " + "；".join(over[:6]))
    elif checked:
        ok(f"{where} · R15 DIALOGUE_SPEED：{checked} 处台词语速均 ≤ 9 字/秒")
    else:
        warn(f"{where} · R15 DIALOGUE_SPEED：无台词可校（跳过）")


def rule_enum_values(doc, where):
    """R16：景别取六值之一、运镜取 20 类之一。"""
    shots = _shots(doc)
    bad_size = [f"{r.get('shot_id')}='{r.get('shot_size')}'"
                for r in shots if r.get("shot_size") not in SHOT_SIZE_ENUM]
    bad_move = [f"{r.get('shot_id')}='{_cam(r).get('move')}'"
                for r in shots if _cam(r).get("move") not in MOVE_ENUM]
    if bad_size:
        err(f"{where} · R16 ENUM_VALUES：景别越界 → " + "；".join(bad_size[:6]))
    if bad_move:
        err(f"{where} · R16 ENUM_VALUES：运镜越界 → " + "；".join(bad_move[:6]))
    if not bad_size and not bad_move:
        ok(f"{where} · R16 ENUM_VALUES：{len(shots)} 镜的景别与运镜取值全部合规")


def rule_static_pov_params(doc, where):
    """R17：static／pov 不得携带 amplitude／speed（规范 §3.7.2）。"""
    bad = []
    for r in _shots(doc):
        cam = _cam(r)
        if cam.get("move") in NO_PARAM_MOVES:
            for k in ("amplitude", "speed"):
                if cam.get(k) not in (None, ""):
                    bad.append(f"{r.get('shot_id')}.{k}='{cam.get(k)}'（{cam.get('move')} 不得携带）")
    if bad:
        err(f"{where} · R17 STATIC_POV_PARAMS：" + "；".join(bad[:6]))
    else:
        ok(f"{where} · R17 STATIC_POV_PARAMS：static／pov 均未携带幅度与速度")


def rule_transition_side(doc, where):
    """R18：转场单侧表达——单元内非末镜不得填 transition_out。"""
    units = _units(doc)
    by_id = {r.get("shot_id"): r for r in _shots(doc)}
    bad = []
    for u in units:
        for sid in (u.get("shot_ids") or [])[:-1]:
            sh = by_id.get(sid) or {}
            if (sh.get("transition_out") or "").strip():
                bad.append(f"{sid}（{u.get('unit_id')} 非末镜）填了 transition_out='{sh.get('transition_out')}'")
    if bad:
        err(f"{where} · R18 TRANSITION_SIDE：" + "；".join(bad[:6]))
    else:
        ok(f"{where} · R18 TRANSITION_SIDE：{len(units)} 个单元内非末镜均未填 transition_out")


def _allow(ratio, n):
    """占比门槛 → 绝对个数。与 audit_shots.py 同实现：max(1, ceil(ratio*n))。"""
    return max(1, math.ceil(ratio * n))


def _coverage(rows, getter):
    if not rows:
        return 0.0
    hit = 0
    for r in rows:
        v = getter(r)
        if isinstance(v, str) and v.strip():
            hit += 1
    return hit / len(rows)


def _gate_check(rows):
    """对一组镜头跑 11 项质量门，返回未达标项列表（阈值引用 GATE，算法同 audit_shots.py）。"""
    n = len(rows)
    bad = []
    cov_checks = [
        ("运镜覆盖", lambda r: _cam(r).get("move"), GATE["运镜覆盖"]),
        ("景别覆盖", lambda r: r.get("shot_size"), GATE["景别覆盖"]),
        ("角度覆盖", lambda r: _cam(r).get("height"), GATE["角度覆盖"]),
        ("光学覆盖", lambda r: _cam(r).get("optics"), GATE["光学覆盖"]),
        ("构图覆盖", lambda r: _sl(r).get("composition"), GATE["构图覆盖"]),
        ("轴线覆盖", lambda r: _sl(r).get("axis"), GATE["轴线覆盖"]),
        ("光线覆盖", lambda r: r.get("lighting"), GATE["光线覆盖"]),
        ("画面结果覆盖", lambda r: _sl(r).get("result"), GATE["画面结果覆盖"]),
    ]
    for name, getter, limit in cov_checks:
        v = _coverage(rows, getter)
        if v < limit:
            bad.append(f"{name} {v:.0%} < 门槛 {limit:.0%}")

    st_cnt = sum(1 for r in rows if _cam(r).get("move") == "static")
    st_allow = _allow(GATE["静止镜占比"], n)
    if st_cnt > st_allow:
        bad.append(f"静止镜 {st_cnt}/{n} > 允许 {st_allow}（上限 {GATE['静止镜占比']:.0%}）")

    moves = [m for m in (_cam(r).get("move") for r in rows) if m]
    if moves:
        cnt = Counter(moves)
        top_type, top_cnt = cnt.most_common(1)[0]
        top_allow = _allow(GATE["单一运镜占比"], n)
        if top_cnt > top_allow:
            bad.append(f"单一运镜（{top_type}）{top_cnt}/{n} > 允许 {top_allow}"
                       f"（上限 {GATE['单一运镜占比']:.0%}）")
        need = min(GATE["运镜类型数"], max(2, -(-n // 4)))
        if len(cnt) < need:
            bad.append(f"运镜类型数 {len(cnt)} < 门槛 {need}（{n} 镜，动作贫乏）")
    return bad


def rule_gate(doc, where):
    """R19：11 项镜头语言质量门（整片 + 逐生成单元），阈值引用 audit_shots.py 的 GATE。"""
    shots = _shots(doc)
    if not shots:
        return
    bad_all = _gate_check(shots)
    if bad_all:
        err(f"{where} · R19 GATE（整片 {len(shots)} 镜）：" + "；".join(bad_all[:8]))
    else:
        ok(f"{where} · R19 GATE（整片 {len(shots)} 镜）：11 项全通过")

    units = _units(doc)
    by_id = {r.get("shot_id"): r for r in shots}
    bad_units = []
    for u in units:
        rows = [by_id[s] for s in (u.get("shot_ids") or []) if s in by_id]
        if not rows:
            continue
        b = _gate_check(rows)
        if b:
            bad_units.append(f"{u.get('unit_id')}：" + "；".join(b[:3]))
    if bad_units:
        err(f"{where} · R19 GATE（逐单元）：" + " ‖ ".join(bad_units[:5]))
    else:
        ok(f"{where} · R19 GATE（逐单元）：{len(units)} 个单元 11 项全通过（含 2–3 镜短单元的容差算法）")


# ---------------- 调度 ----------------
def validate_doc(doc, where):
    shape = detect_shape(doc)
    if shape is None:
        warn(f"{where}：无法识别产物形态（既无 acts／shots 也无 scenes_outline），跳过")
        return
    out(f"\n--- {where}（形态：{shape}）---")
    rule_required_keys(doc, shape, where)
    rule_fill_stage_enum(doc, where)
    if shape == "storyboard":
        rule_shot_id_format(doc, where)
        rule_shot_no_seq(doc, where)
        rule_unit_link(doc, where)
        rule_unit_size(doc, where)
        rule_unit_move_unique(doc, where)
        rule_duration(doc, where)
        rule_dialogue_speed(doc, where)
        rule_enum_values(doc, where)
        rule_static_pov_params(doc, where)
        rule_transition_side(doc, where)
        rule_gate(doc, where)
        rule_unspecified_owner(doc, shape, where)
        return
    rule_purpose_enum(doc, shape, where)
    rule_scene_no_continuity(doc, shape, where)
    rule_est_seconds_sum(doc, shape, where)
    rule_scene_duration_floor(doc, shape, where)
    if shape == "script":
        rule_act_structure(doc, where)
        rule_dialogue_type(doc, where)
        rule_unspecified_owner(doc, shape, where)


def scan_examples():
    exp_dir = os.path.join(BASE, "examples")
    if not os.path.isdir(exp_dir):
        warn("examples/ 目录不存在，跳过")
        return
    files = [f for f in sorted(os.listdir(exp_dir)) if f.endswith(".md") and f != "README.md"]
    if not files:
        warn("examples/ 下无可校验样例")
        return
    for fn in files:
        with open(os.path.join(exp_dir, fn), encoding="utf-8") as f:
            text = f.read()
        blocks = JSON_BLOCK_RE.findall(text)
        if not blocks:
            warn(f"{fn}：未找到 ```json 代码块")
            continue
        for i, b in enumerate(blocks, 1):
            try:
                doc = json.loads(b)
            except Exception as e:
                err(f"{fn}（第 {i} 个 JSON 块）：解析失败 {e}")
                continue
            validate_doc(doc, f"{fn}#{i}")


def validate_file(path):
    if not os.path.exists(path):
        err(f"文件不存在：{path}")
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 允许传入「裸 JSON」或「含 ```json 块的 md」
    blocks = JSON_BLOCK_RE.findall(text)
    if not blocks:
        blocks = [text]
    for i, b in enumerate(blocks, 1):
        try:
            doc = json.loads(b)
        except Exception as e:
            err(f"{os.path.basename(path)}（第 {i} 个 JSON）：解析失败 {e}")
            continue
        validate_doc(doc, f"{os.path.basename(path)}#{i}")


def main():
    global QUIET, DURATION_MIN_MS, DURATION_MAX_MS
    ap = argparse.ArgumentParser(description="输出契约校验器（purpose/dialogue.type 封闭枚举、缺口台账 owner 责任归属、场时长下限、分镜层质量门）")
    ap.add_argument("--file", help="校验单个 JSON（或含 ```json 块的 .md）文件")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    ap.add_argument("--duration-bounds", metavar="MIN-MAX",
                    help="单镜时长区间（秒），如 4-15；默认 4-15（MiniMax H3 口径）")
    args = ap.parse_args()
    QUIET = args.json

    if args.duration_bounds:
        try:
            lo, hi = (int(x) for x in args.duration_bounds.split("-"))
            DURATION_MIN_MS, DURATION_MAX_MS = lo * 1000, hi * 1000
        except Exception:
            print(f"[FATAL] --duration-bounds 格式应为 MIN-MAX（秒），收到：{args.duration_bounds}",
                  file=sys.stderr)
            return 2

    if not QUIET:
        print("输出契约校验 · validate_output.py")
        print(f"根目录：{BASE}")
        print(f"purpose 枚举：{'／'.join(PURPOSE_ENUM)}")
        print(f"fill_stage 枚举：{'／'.join(FILL_STAGE_ENUM)}")
        print(f"dialogue.type 枚举：{'／'.join(DIALOGUE_TYPE_ENUM)} ｜ "
              f"owner 枚举：{'／'.join(OWNER_ENUM)}（owner=客户 者 fill_stage 须为 script）")
        print(f"场时长下限：{SCENE_MIN_SECONDS}s（单镜 4s × 单元最少 2 镜）")
        print(f"分镜单镜时长区间：{DURATION_MIN_MS // 1000}–{DURATION_MAX_MS // 1000}s"
              f"（质量门阈值引用 audit_shots.py 的 GATE）")

    if args.file:
        validate_file(args.file)
    else:
        scan_examples()

    passed = not RESULT["errors"]
    if args.json:
        print(json.dumps({
            "passed": passed,
            "checks": RESULT["checks"],
            "errors": RESULT["errors"],
            "warnings": RESULT["warnings"],
            "purpose_enum": PURPOSE_ENUM,
            "fill_stage_enum": FILL_STAGE_ENUM,
            "dialogue_type_enum": DIALOGUE_TYPE_ENUM,
            "owner_enum": OWNER_ENUM,
            "scene_min_seconds": SCENE_MIN_SECONDS,
            "shot_size_enum": SHOT_SIZE_ENUM,
            "move_enum": MOVE_ENUM,
            "duration_bounds_ms": [DURATION_MIN_MS, DURATION_MAX_MS],
            "gate": GATE,
            "exit_code": 0 if passed else 1,
        }, ensure_ascii=False, indent=2))
    else:
        print("\n" + "=" * 52)
        print(f"通过检查项：{RESULT['checks']}")
        print(f"失败：{len(RESULT['errors'])} ｜ 警告：{len(RESULT['warnings'])}")
        print("结论：" + ("✅ 全部通过" if passed else "❌ 存在失败项"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
