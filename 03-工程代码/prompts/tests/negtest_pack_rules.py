#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付包规则负向验证 · negtest_pack_rules.py

定位：`validate_output.py` 只对 examples/ 的**通过样本**跑正向校验——正向全绿仅证明
      「规则不误报」，**不证明规则有效**（把判据写反、条件永不成立、字段名拼错，
      都会让正向照样全绿）。本脚本**逐条构造越界样本**，断言对应规则真的触发（EXIT=1）。

覆盖：交付包层 R26~R36（2026-10-13 随 SW-007 `shot_prompt_v1` 建立；R35 于 v2.0 由「禁入」反转为「道具锚一致性」）
      ＋ **独立台账层 R37**（2026-10-14 随 SW-008 `revise_v1` 建立——`revise` 是链路第二个起点，
      台账必须**另行产出**为独立产物，其形态与交付包不同，故**另有一套基础样本与样本表**）。
      ＋ **对话式修改层 R38／R39**（2026-10-14 随 SW-002 `modify_v1`／`check_consistency_v1` 建立——
      本层与链路阶段**正交**（`modify_v1` 无 `stage`），两种产物各自一套形态，故**再各起一套样本**）。

用法：
    python tests/negtest_pack_rules.py            # 跑全部样本
    python tests/negtest_pack_rules.py --json     # 机器可读结果

退出码：0 = 全部符合预期；1 = 存在不符（规则没触发，或盲区意外触发）

⚠️ 纪律：新增规则时，**必须**在此处补一个越界样本——没有越界样本的新规则
   等于一条未经验证的声明。（与 CFG-007_SCHEMA.md「负向验证纪律」条目配套。）

依赖：仅标准库。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # prompts/
VAL = os.path.join(BASE, "validate_output.py")
EX = os.path.join(BASE, "examples")
JSON_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.S)
UP_CASE = "CASE-002_shot-prompt-case01.md"
UP_SB = "CASE-003_storyboard-case01.md"
LEDGER_CASE = "CASE-005_revise-case01.md"      # revise 层的**独立缺口台账**样本来源
UP_REVISE = "CASE-005_revise-case01.md"        # revise 层的交付包样本来源（可用于 R36 等）
MODIFY_CASE = "CASE-006_modify-case01.md"      # SW-002：变更说明（modify）与漂移报告（drift_report）


# --------------------------------------------------------------------------
# 样本定义
# --------------------------------------------------------------------------
CASES = []          # (名称, 期望命中的规则码, 变异函数, 是否需上游分镜)
BLINDSPOTS = []     # (名称, 变异函数, 为何不触发)
LEDGER_CASES = []   # R37 专用：台账样本（形态与交付包不同，故独立成表）
LEDGER_BLINDSPOTS = []
MODIFY_CASES = []   # R38 专用：变更说明样本（SW-002，与链路阶段正交）
MODIFY_BLINDSPOTS = []
DRIFT_CASES = []    # R39 专用：漂移报告样本
DRIFT_BLINDSPOTS = []
_SB = {}


def _load_base():
    t = open(os.path.join(EX, UP_CASE), encoding="utf-8").read()
    for b in JSON_BLOCK.findall(t):
        j = json.loads(b)
        if "aigc_meta" in j and "schema_version" in j:
            return j
    raise SystemExit(f"[FATAL] {UP_CASE} 中未找到交付包 JSON 块（含 aigc_meta + schema_version）")


def _load_ledger():
    t = open(os.path.join(EX, LEDGER_CASE), encoding="utf-8").read()
    for b in JSON_BLOCK.findall(t):
        j = json.loads(b)
        if set(j.keys()) == {"unspecified"}:
            return j
    raise SystemExit(f"[FATAL] {LEDGER_CASE} 中未找到独立台账 JSON 块（顶层仅 unspecified）")


def _load_view(fname, marker, what):
    """从用例里取出**带指定签名键**的那个 JSON 块（同一 .md 常含多个块，不能取第一个）。"""
    t = open(os.path.join(EX, fname), encoding="utf-8").read()
    for b in JSON_BLOCK.findall(t):
        try:
            j = json.loads(b)
        except Exception:
            continue
        if isinstance(j, dict) and marker(j):
            return j
    raise SystemExit(f"[FATAL] {fname} 中未找到{what}")


def _load_modify():
    return _load_view(MODIFY_CASE, lambda j: "change_log" in j,
                      "变更说明 JSON 块（顶层含 change_log）")


def _load_drift():
    return _load_view(MODIFY_CASE, lambda j: "findings" in j and "pair_role" in j,
                      "漂移报告 JSON 块（顶层含 findings + pair_role）")


def _reg(table, name, rule, fn, need_sb=False):
    table.append((name, rule, fn, need_sb))
    return fn


def case(name, rule, need_sb=False):
    def deco(fn):
        return _reg(CASES, name, rule, fn, need_sb)
    return deco


def blindspot(name, fn, why):
    BLINDSPOTS.append((name, fn, why))
    return fn


def setp(obj, path, val):
    """按 a.b.c 路径设置值（末段可为 list 索引）。"""
    put(obj, path, val)


def _resolve(obj, path):
    """返回 (容器, 末段键)；末段若为数字则键为 int。"""
    cur, parts = obj, path.split(".")
    for p in parts[:-1]:
        cur = cur[int(p)] if p.isdigit() else cur[p]
    last = parts[-1]
    return cur, (int(last) if last.isdigit() else last)


def put(obj, path, val):
    cont, key = _resolve(obj, path)
    cont[key] = val


def drop(obj, path):
    cont, key = _resolve(obj, path)
    if isinstance(cont, dict):
        cont.pop(key, None)
    else:
        cont.pop(key)


def add(obj, path, delta):
    cont, key = _resolve(obj, path)
    cont[key] += delta


# ---- R26 运镜幅度／速度的省略规则 ----------------------------------------
@case("R26 幅度用了默认值 medium", "R26")
def _(d):
    put(d, "shots.0.camera.amplitude", "medium")


@case("R26 速度用了默认值 normal", "R26")
def _(d):
    put(d, "shots.1.camera.speed", "normal")


# ---- R27 交付包必备结构 --------------------------------------------------
@case("R27 某镜缺 prompt_en", "R27")
def _(d):
    drop(d, "shots.3.prompt_en")


@case("R27 style_ref 未命中 style_id（§3.8 阻断项）", "R27")
def _(d):
    put(d, "shots.5.style_ref", "STYLE-99")


@case("R27 character_refs 引用未定义角色", "R27")
def _(d):
    put(d, "shots.6.character_refs", ["CHR-99"])


# ---- R28 正文不得复述外观锚 ----------------------------------------------
@case("R28 中文正文复述外观锚", "R28")
def _(d):
    put(d, "shots.0.prompt_zh", d["shots"][0]["prompt_zh"] + "他穿着深蓝色外卖冲锋衣。")


@case("R28 英文正文复述外观锚", "R28")
def _(d):
    put(d, "shots.0.prompt_en",
        d["shots"][0]["prompt_en"] + " A dark blue delivery jacket with reflective strips.")


# ---- R29 提示词正文卫生 --------------------------------------------------
@case("R29 正文含模型参数指令", "R29")
def _(d):
    put(d, "shots.2.prompt_zh", d["shots"][2]["prompt_zh"] + " --ar 16:9 --style raw")


@case("R29 正文含负向残留", "R29")
def _(d):
    put(d, "shots.2.prompt_en", d["shots"][2]["prompt_en"] + " (negative: no rain)")


@case("R29 正文用了锚点清单外的风格词", "R29")
def _(d):
    put(d, "shots.4.prompt_zh", d["shots"][4]["prompt_zh"] + "厚涂质感。")


# ---- R30 AIGC 元数据块 ---------------------------------------------------
@case("R30 Label 不是 \"1\"", "R30")
def _(d):
    put(d, "aigc_meta.AIGC.Label", "0")


@case("R30 ProduceID 与 pack_id 不一致", "R30")
def _(d):
    put(d, "aigc_meta.AIGC.ProduceID", "FR-PK-99999999-XXXXXXXX")


@case("R30 传播方与生产者取值不同", "R30")
def _(d):
    put(d, "aigc_meta.AIGC.ContentPropagator", "别的主体/OTHER")


# ---- R31 时长守恒与「不改导演决策」不变量 ---------------------------------
@case("R31 只改 meta.total_duration_ms", "R31")
def _(d):
    add(d, "meta.total_duration_ms", 1000)


@case("R31 只改单镜时长、未改总时长", "R31")
def _(d):
    add(d, "shots.9.duration_ms", 1000)


@case("R31 与上游分镜的逐镜时长不一致", "R31", need_sb=True)
def _(d):
    add(d, "shots.11.duration_ms", 1000)
    add(d, "meta.total_duration_ms", 1000)


@case("R31 镜数与上游不一致（少一镜）", "R31", need_sb=True)
def _(d):
    drop_shot = d["shots"].pop()
    add(d, "meta.total_duration_ms", -drop_shot["duration_ms"])


# ---- R32 光照字段的词表纯度 ----------------------------------------------
@case("R32 lighting 写成「词表值——说明」", "R32")
def _(d):
    put(d, "shots.0.lighting", "逐光—侧面硬光打在下半张脸")


@case("R32 lighting_default 非纯词表值", "R32")
def _(d):
    put(d, "style_bible.lighting_default", "实景光（楼道感应灯为主）")


# ---- R33 交付包留空口径：留空须「省略键」、不得写空串（依评审 PR-02 新增）----
@case("R33 camera.amplitude 写空串（应省略键）", "R33")
def _(d):
    put(d, "shots.0.camera.amplitude", "")


@case("R33 camera.speed 写空串", "R33")
def _(d):
    put(d, "shots.0.camera.speed", "")


@case("R33 camera.optics 写空串", "R33")
def _(d):
    put(d, "shots.0.camera.optics", "")


@case("R33 transition_out 写空串（非末镜亦然）", "R33")
def _(d):
    put(d, "shots.0.transition_out", "")


@case("R33 lighting 写空串（vocabRef 不匹配空串）", "R33")
def _(d):
    put(d, "shots.0.lighting", "")


@case("R33 characters[].ref_image = null（schema 为 type:string）", "R33")
def _(d):
    put(d, "characters.0.ref_image", None)


# ---- R34 英文正文须含以 `The camera` 起句的独立句（依评审 PR-04 新增）------
@case("R34 英文运镜句并入前句（`as the camera` 小写）", "R34")
def _(d):
    en = d["shots"][0]["prompt_en"]
    put(d, "shots.0.prompt_en", en.replace(". The camera ", " as the camera "))


@case("R34 英文正文去掉 `The camera` 起句", "R34")
def _(d):
    en = d["shots"][0]["prompt_en"]
    put(d, "shots.0.prompt_en", en.replace("The camera ", "The rig "))


# ---- R35 道具锚一致性（★ v2.0 由「禁入」反转为**正向**；依 T-054 / ISSUE-011 闭环）----
#  旧判据 NO_PROP_REFS 的设立前提是「交付契约无该字段」——v2.0 已补齐（§3.6 增 prop_refs、
#  顶层增 props[]），故前提消失、判据撤销并反转为「必须存在且命中」。**两个失败分支各一样本**：
@case("R35 某镜 prop_refs 引用不存在的 prop_id（道具锚断裂）", "R35")
def _(d):
    put(d, "shots.3.prop_refs", ["PRP-99"])


@case("R35 某镜缺 prop_refs 键（v2.0 契约必备；无道具须为空数组）", "R35")
def _(d):
    drop(d, "shots.4.prop_refs")


# ---- R36 交付包不得含契约字段集之外的键（依评审 PR-14 新增）---------------
@case("R36 顶层出现契约外键 unspecified（上游顶层字段，交付契约无容器）", "R36")
def _(d):
    put(d, "unspecified", [{"field": "shots[].dialogue", "owner": "客户"}])


@case("R36 shots[] 出现契约外键 continuity_note", "R36")
def _(d):
    put(d, "shots.0.continuity_note", "本镜承接上镜视线")


@case("R36 meta 出现契约外键 director_intent", "R36")
def _(d):
    put(d, "meta.director_intent", "全片以冷调压迫感为主")


# ---- R37 独立缺口台账的形态与责任阶段（★ 2026-10-14 随 SW-008 `revise_v1` 新增）----
#  ⚠️ 台账是 `revise` 层的**独有产物**（本层无上游可承载台账，故必须另行产出）。
#     它是本层唯一的新增产物品类，若不识别其形态就会**掉在全部门禁之外**——故须自带越界样本。
def ledger_case(name, rule):
    def deco(fn):
        return _reg(LEDGER_CASES, name, rule, fn)
    return deco


def ledger_blindspot(name, fn, why):
    LEDGER_BLINDSPOTS.append((name, fn, why))
    return fn


@ledger_case("R37 顶层混装契约外键（独立台账只允许 unspecified）", "R37")
def _(d):
    d["pack_id"] = "FR-PK-20261014-XXXX0001"


@ledger_case("R37 某条缺 fill_fallback 字段（7 字段不齐）", "R37")
def _(d):
    d["unspecified"][0].pop("fill_fallback", None)


@ledger_case("R37 某条缺 upstream_field 字段", "R37")
def _(d):
    d["unspecified"][2].pop("upstream_field", None)


@ledger_case('R37 blocking 写成字符串 "false"（字符串非布尔，且 "false" 是真值）', "R37")
def _(d):
    d["unspecified"][1]["blocking"] = "false"


@ledger_case("R37 fill_stage 写成 storyboard（把责任推给本路径上没跑过的层）", "R37")
def _(d):
    d["unspecified"][3]["fill_stage"] = "storyboard"


@ledger_case("R37 某条多出契约外字段 design_source（交付包无此键，台账也不携带）", "R37")
def _(d):
    d["unspecified"][4]["design_source"] = "系统提议待确认"


@ledger_case("R37 unspecified 为空数组（台账必须非空）", "R37")
def _(d):
    d["unspecified"] = []


# ---- R38 变更说明的形态与内在自洽（★ 2026-10-14 随 SW-002 `modify_v1` 新增）----
#  ⚠️ 本产物与链路阶段**正交**（`modify_v1` 无 `stage`），顶层是一组链路判据都不认识的键；
#     不识别其形态，它就会掉进「无法识别产物形态，跳过」——**看起来通过、实则一条都没查**。
def modify_case(name, rule):
    def deco(fn):
        return _reg(MODIFY_CASES, name, rule, fn)
    return deco


def modify_blindspot(name, fn, why):
    MODIFY_BLINDSPOTS.append((name, fn, why))
    return fn


@modify_case("R38 顶层多出契约外键（该形态只允许恰好 6 键）", "R38")
def _(d):
    d["pack_id"] = "FR-PK-20261014-XXXX0001"


@modify_case("R38 顶层缺 clarification 键", "R38")
def _(d):
    d.pop("clarification", None)


@modify_case("R38 target_stage 写成枚举外值（revise 不在本模板 variables 的取值域内）", "R38")
def _(d):
    d["target_stage"] = "revise"


@modify_case("R38 artifact 退化成 diff 片段（不再是完整产物）", "R38")
def _(d):
    d["artifact"] = {"target_path": "shots[0].duration_ms", "after": 6000}


@modify_case("R38 target_stage=pack 但 artifact 是分镜产物（声明与产物不符）", "R38")
def _(d):
    d["target_stage"] = "pack"


@modify_case("R38 change_log 每条缺 upstream_impact（8 键不齐）", "R38")
def _(d):
    d["change_log"][1].pop("upstream_impact", None)


@modify_case("R38 change_log 多出契约外键 note", "R38")
def _(d):
    d["change_log"][0]["note"] = "顺手加了句说明"


@modify_case("R38 op_id 写成 MOD-1（不足两位；契约要求 MOD-\\d{2}）", "R38")
def _(d):
    d["change_log"][0]["op_id"] = "MOD-1"


@modify_case("R38 op_id 跳号（末条改成 MOD-04）", "R38")
def _(d):
    d["change_log"][2]["op_id"] = "MOD-04"


@modify_case("R38 op_type 越界（写成 modify）", "R38")
def _(d):
    d["change_log"][0]["op_type"] = "modify"


@modify_case("R38 upstream_impact 越界（写成 duration）", "R38")
def _(d):
    d["change_log"][0]["upstream_impact"] = "duration"


@modify_case("R38 target_path 在 artifact 中解析不到（索引越界）", "R38")
def _(d):
    d["change_log"][0]["target_path"] = "shots[9].duration_ms"


@modify_case("R38 target_path 用了通配符 [*]（落点不唯一）", "R38")
def _(d):
    d["change_log"][0]["target_path"] = "shots[*].duration_ms"


@modify_case("R38 unresolved 每条缺 need（4 键不齐）", "R38")
def _(d):
    d["unresolved"][0].pop("need", None)


@modify_case('R38 unresolved.blocking 写成字符串 "false"（字符串非布尔，且 "false" 是真值）', "R38")
def _(d):
    d["unresolved"][1]["blocking"] = "false"


@modify_case("R38 clarification.needed=true 但 change_log 非空（边问边改）", "R38")
def _(d):
    d["clarification"] = {"needed": True, "questions": ["想加强节奏还是运镜强度？"]}


@modify_case("R38 clarification.needed=true 但 questions 为空", "R38")
def _(d):
    d["clarification"] = {"needed": True, "questions": []}


@modify_case("R38 clarification.needed=false 但 questions 非空", "R38")
def _(d):
    d["clarification"] = {"needed": False, "questions": ["要不要一并改总时长？"]}


# ---- R39 漂移报告的形态与三数自洽（★ 2026-10-14 随 SW-002 `check_consistency_v1` 新增）----
def drift_case(name, rule):
    def deco(fn):
        return _reg(DRIFT_CASES, name, rule, fn)
    return deco


def drift_blindspot(name, fn, why):
    DRIFT_BLINDSPOTS.append((name, fn, why))
    return fn


@drift_case("R39 顶层多出契约外键（该形态只允许恰好 4 键）", "R39")
def _(d):
    d["artifact"] = {}


@drift_case("R39 顶层缺 summary 键", "R39")
def _(d):
    d.pop("summary", None)


@drift_case("R39 pair_role 越界（写成 before_after_reverse）", "R39")
def _(d):
    d["pair_role"] = "before_after_reverse"


@drift_case("R39 findings 为空数组（无法区分「查过没问题」与「根本没查」）", "R39")
def _(d):
    d["findings"] = []
    d["summary"] = {"checked_count": 0, "drift_count": 0, "verdict": "clean"}


@drift_case("R39 findings 缺少 anchor 类条目（把锚类汇总的 category 改成 number）", "R39")
def _(d):
    d["findings"][4]["category"] = "number"


@drift_case("R39 findings 每条缺 location_b（8 键不齐）", "R39")
def _(d):
    d["findings"][2].pop("location_b", None)


@drift_case("R39 findings 多出契约外键 severity", "R39")
def _(d):
    d["findings"][0]["severity"] = "high"


@drift_case("R39 category 越界（写成 lighting）", "R39")
def _(d):
    d["findings"][2]["category"] = "lighting"


@drift_case("R39 verdict 越界（写成 changed）", "R39")
def _(d):
    d["findings"][0]["verdict"] = "changed"


@drift_case("R39 finding_id 跳号（改成 DR-05／DR-06）", "R39")
def _(d):
    d["findings"][3]["finding_id"] = "DR-05"
    d["findings"][4]["finding_id"] = "DR-06"


@drift_case("R39 summary.checked_count 与清单条数不符", "R39")
def _(d):
    d["summary"]["checked_count"] = 4


@drift_case("R39 summary.drift_count 与复算不符", "R39")
def _(d):
    d["summary"]["drift_count"] = 1


@drift_case("R39 summary.verdict 与复算不符（有漂移却写 clean）", "R39")
def _(d):
    d["summary"]["verdict"] = "clean"


@drift_case('R39 summary.checked_count 写成字符串 "5"（非整数）', "R39")
def _(d):
    d["summary"]["checked_count"] = "5"


# ---- 已知盲区（预期**不**触发；登记在案，防止日后误以为规则更强）---------
def _bs_selfconsistent(d):
    add(d, "shots.7.duration_ms", 1000)
    add(d, "meta.total_duration_ms", 1000)      # 逐镜与总量同步改 → 自洽


blindspot("未提供上游时，同时改单镜时长与总时长（自洽）", _bs_selfconsistent,
          "总时长与逐镜仍自洽，无外部真值可比 → 校验交付包须始终带 --storyboard")


def _bs_no_total(d):
    drop(d, "meta.total_duration_ms")


blindspot("meta.total_duration_ms 缺失", _bs_no_total,
          "该字段在 schema 的 meta.required 里是可选的（规范亦未列为必须）→ 本层无从守恒")


def _bs_shot_ref_null(d):
    put(d, "shots.0.ref_image", None)


blindspot("shots[].ref_image = null", _bs_shot_ref_null,
          "该处 schema 为 oneOf[string,null]，null **合法**；R33 刻意只报 characters[].ref_image"
          "（type:string）与枚举／vocabRef 的空串——与门禁**严格对齐**，不写比契约更严的私有口径")


def _lbs_free_text(d):
    d["unspecified"][0]["reason"] = ""
    d["unspecified"][0]["fill_fallback"] = ""


ledger_blindspot("台账条目的 reason／fill_fallback 写成空串", _lbs_free_text,
                 "这两项是**自由文本**，契约未给长度下限——空串在语义上是缺陷、在契约上是合法值。"
                 "R37 只管「形态与责任阶段」（7 字段齐备／blocking 为布尔／fill_stage 为 revise），"
                 "**刻意不判**文本质量；把它判成错误等于自造比契约更严的私有口径（同 R33 的取舍）。"
                 "文本质量由模板 guards 的「台账完整性」自检项与人工复核承担。")


def _mbs_untouched_mutation(d):
    d["artifact"]["units"][0]["soundscape"] = "雨停了，屋檐不再滴水；远处偶有车声"


modify_blindspot("改动一处 change_log 未覆盖的字段（『顺手多改』）", _mbs_untouched_mutation,
                 "判定「未点名处是否逐字保持」需要 `current_artifact` 作**外部基准**"
                 "（同 R31 需 `--storyboard` 的情形）。R38 只判外层形态与内在自洽，"
                 "**刻意不声称覆盖**这一项——要脚本化须为 `validate_output.py` 增设 `--before` 参数。"
                 "该风险在本工程由模板 guards 的「定向性核对」自检项与人工抽检承担。")


def _mbs_empty_before(d):
    d["change_log"][0]["before"] = ""


modify_blindspot("change_log[].before 写成空串（未逐字摘自原件）", _mbs_empty_before,
                 "`before` 是**字符串**，契约刻意未给长度下限（`insert` 时它**就该是**空串）；"
                 "而「是否逐字摘自原件」须与 `current_artifact` 比对才能判——单文件内无从判定。"
                 "同 R33 的取舍：不写比契约更严的私有口径。")


def _dbs_normalized_value(d):
    d["findings"][0]["value_b"] = "6s"


drift_blindspot("findings[].value_b 未逐字摘自原件（写成规范化写法 6s）", _dbs_normalized_value,
                "「两侧取值逐字摘自原件」须与 `artifact_a`／`artifact_b` 比对才能判——"
                "本产物**不含**被检的两份产物本身，单文件内无从判定。R39 只判形态与三数自洽，"
                "**刻意不声称覆盖**这一项；由模板 guards 的「两侧取值逐字核对」自检项与人工抽检承担。")


def _dbs_empty_action(d):
    d["findings"][0]["action"] = ""


drift_blindspot("findings[].action 写成空串", _dbs_empty_action,
                "`action` 是**自由文本**，契约未给长度下限——空串在语义上是缺陷、在契约上是合法值。"
                "同 R37 的取舍：不写比契约更严的私有口径。")


# --------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------
#   四种形态**各自一套基础样本**：形态不同则「越界」的含义不同，混用一张表会让样本
#   落在错误的产物上（例如把台账样本套到交付包上，触发的是别条规则、看起来却像"通过了"）。
FORMS = [
    ("交付包（pack）", _load_base, CASES, BLINDSPOTS),
    ("独立台账（ledger）", _load_ledger, LEDGER_CASES, LEDGER_BLINDSPOTS),
    ("变更说明（modify）", _load_modify, MODIFY_CASES, MODIFY_BLINDSPOTS),
    ("漂移报告（drift_report）", _load_drift, DRIFT_CASES, DRIFT_BLINDSPOTS),
]


def _run(doc, need_sb, tmpdir):
    fp = os.path.join(tmpdir, "_tmp_pack.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    cmd = [sys.executable, VAL, "--file", fp]
    if need_sb:
        cmd += ["--storyboard", os.path.join(EX, UP_SB)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    ap = argparse.ArgumentParser(description="输出契约规则负向验证：交付包 R26~R36 ＋ 台账 R37 ＋ "
                                             "变更说明 R38 ＋ 漂移报告 R39")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    ap.add_argument("--keep", action="store_true", help="保留临时样本目录（排查用）")
    args = ap.parse_args()

    tmpdir = tempfile.mkdtemp(prefix="negtest-pack-")
    rows, bad = [], 0
    try:
        for label, loader, cases, blinds in FORMS:
            doc = loader()
            for name, rule, mutate, need_sb in cases:
                d = copy.deepcopy(doc)
                mutate(d)
                code, out = _run(d, need_sb, tmpdir)
                fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
                exact = any(rule in ln for ln in fails)
                good = (code == 1 and exact)
                bad += 0 if good else 1
                rows.append({"form": label, "case": name, "rule": rule,
                             "expect": "EXIT=1 命中 " + rule,
                             "exit": code, "hit": exact, "ok": good, "fails": fails[:3]})
            for name, mutate, why in blinds:
                d = copy.deepcopy(doc)
                mutate(d)
                code, out = _run(d, False, tmpdir)
                good = (code == 0)
                bad += 0 if good else 1
                rows.append({"form": label, "case": name, "rule": "（已知盲区）",
                             "expect": "EXIT=0", "exit": code, "hit": None,
                             "ok": good, "why": why})
    finally:
        shutil.rmtree(tmpdir, ignore_errors=not args.keep)

    n_cases = len(CASES) + len(LEDGER_CASES) + len(MODIFY_CASES) + len(DRIFT_CASES)
    n_blind = len(BLINDSPOTS) + len(LEDGER_BLINDSPOTS) + len(MODIFY_BLINDSPOTS) + len(DRIFT_BLINDSPOTS)
    if args.json:
        print(json.dumps({"passed": bad == 0, "total": len(rows), "failed": bad,
                          "cases": n_cases, "blindspots": n_blind,
                          "rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"输出契约规则负向验证 · 交付包 R26~R36 ＋ 台账 R37 ＋ 变更说明 R38 ＋ 漂移报告 R39 · ")
        print(f"{n_cases} 个越界样本 + {n_blind} 个已知盲区（四形态各自一套基础样本）")
        print("=" * 66)
        prev = None
        for r in rows:
            if r["form"] != prev:
                print(f"—— {r['form']} ——")
                prev = r["form"]
            print(f"[{'OK ' if r['ok'] else 'BAD'}] exit={r['exit']} {r['expect']} · {r['case']}")
            if not r["ok"]:
                print("      → 实际 FAIL 行：" + (" | ".join(r["fails"]) if r.get("fails") else "（无）"))
            if r.get("why"):
                print(f"      理由：{r['why']}")
        print("=" * 66)
        print(f"合计 {len(rows)} 项：{len(rows) - bad} 项符合预期，{bad} 项不符")
        print("结论：" + ("✅ 规则有效（每条均能被越界样本触发）" if bad == 0 else "❌ 存在未触发/意外触发项"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
