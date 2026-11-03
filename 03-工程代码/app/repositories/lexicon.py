"""关键词库加载与匹配 —— **SW-009 / SW-010** 的检测依据。

依据：需求条目 `SW-009`「检测依据见 `09-合规资料库` 关键词库（`SEC-013` §一）」。
数据源：`09-合规资料库/01-关键词库/词表/*.txt` ＋ `lexicon_manifest.json`。

三条纪律（与工程既有「不静默降级」同口径）：

1. **词表为空即如实登记** —— 空类别进 `empty_categories`，**不得当作「无风险」**；
2. **词条内容不入日志、不入响应** —— 只回类别编号与命中数（`SW-019` 数据最小化）；
3. **加载失败不静默** —— 由 `SafetyService` 决定熔断，不在本层兜底放行。

⚠️ **受控类词表当前为空壳**：`A1-01`／`A1-02`／`A1-03`／`A1-05` 四类由项目方手工编写
（任务 `T-020`），盘上文件仅有注释头、**词条数为 0**。本模块据实登记为 `empty_categories`，
**不得因「查不到词」而输出「内容安全」的结论**。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: 注释行前缀（词表文件头部说明块）
_COMMENT = "#"


@dataclass(frozen=True)
class LexiconEntry:
    """单个类别的词表。`words` 为空表示**该类别尚未编写**，不是「无风险」。"""

    category_id: str
    name: str
    group: str
    quota: int
    controlled: bool
    words: tuple[str, ...] = ()
    #: **词条 → 等级**映射（`("血肉模糊", "block")` 形态），来自词表**第 2 段**。
    #: ⚠️ 运行时**必须据此分级处置**：`block` 级命中 → 按 `guard_output_action`；
    #:   仅 `review`/`warn` 级命中 → `flag`（**记录待人工复核、不阻断**）。
    #: ⚠️ **2026-11-03 抽检实测发现**：本字段此前**不存在** ⇒ 运行时丢弃等级 ⇒ 全库
    #:   **12,035 条 `review` 级（96%）被当 `block` 处置** ⇒ 正常剧本段
    #:   **12/12 = 100% 误拒**（命中「第一」「最好」等高频普通词），误拒率 6.7%
    #:   **超国标 ≤5%**。落实 `SEC-007` §4.3「拿不准默认降 warn 而不是 block」。
    levels: tuple[tuple[str, str], ...] = ()
    #: 词条来源：`("main",)` 合规资料库 · `("controlled",)` 受控区 ·
    #: `("main", "controlled")` 两处均有（**去重合并**）。
    #: ⚠️ **受控区的具体路径不外泄**，只以布尔暴露是否已加载（见 `Lexicon.controlled_loaded`）。
    sources: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.words


@dataclass
class Lexicon:
    """一次加载的词库快照（不可变语义：加载后只读）。"""

    standard: str = ""
    entries: tuple[LexiconEntry, ...] = ()
    #: 加载失败的类别（文件缺失 / 不可读）——与「词条为空」区分
    unreadable: tuple[str, ...] = ()
    source_root: str = ""
    #: **受控词库是否已加载**（布尔，**不含路径**——受控区路径属敏感信息，
    #: 按项目方 2026-10-15 决策「不入库、运行时读受控区」，路径不外泄）
    controlled_loaded: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    # ---- 派生视图 ----
    @property
    def total_words(self) -> int:
        return sum(len(e.words) for e in self.entries)

    @property
    def category_count(self) -> int:
        return len(self.entries)

    @property
    def empty_categories(self) -> tuple[str, ...]:
        """**词条数为 0** 的类别编号（待编写，不等于无风险）。"""
        return tuple(e.category_id for e in self.entries if e.is_empty)

    @property
    def quota_covered(self) -> int:
        """达到单类配额（`quota`）的类别数——对照 `SEC-013` §一规模门槛。"""
        return sum(1 for e in self.entries if len(e.words) >= e.quota)

    @property
    def usable(self) -> bool:
        """是否存在**任一**可用词条。全空 ⇒ 调用方必须熔断或显式降级。"""
        return self.total_words > 0

    def scan(self, text: str, *, limit: int = 20) -> list[tuple[str, str, str, str]]:
        """在 `text` 中匹配词条。

        返回 `[(category_id, category_name, matched_word, level), …]`，**按类别编号升序**、
        每类只记首个命中词、总数截断至 `limit`。

        ⚠️ **第 4 项 `level` 是词表第 2 段的等级标注**（`block`/`review`/`warn`），
        调用方**必须据此分级处置** —— 全库 96% 是 `review` 级，一律当 `block` 处置
        会造成 100% 误拒（2026-11-03 抽检实测）。

        匹配规则：字面包含（`in`）。⚠️ 当前规模（数十万词条量级）下字面扫描足够；
        若词表增长到十万级，应换 AC 自动机（`HW-003` 已为该实现预留内存余量）。
        """
        if not text or not self.usable:
            return []
        hits: list[tuple[str, str, str, str]] = []
        for entry in self.entries:
            if entry.is_empty:
                continue
            lv_map = dict(entry.levels)
            # ⚠️ **按类别聚合**（2026-11-03 抽检实测修复，ISSUE-052）：
            #    原实现「首个命中即 `break`」⇒ 同类内先命中的低等级词会**遮蔽**
            #    后续高等级词 ⇒ `block` 级漏放（如 `A3-02` 既有 17 条 block
            #    又有 warn 词时，先命中 warn 词则该类 block 级永不参与判定）。
            #    ⇒ 收集该类**全部**命中词，取**最高等级**（block > review > warn）。
            best_lv = ""
            best_word = ""
            best_rank = -1          # ⚠️ 哨兵初值 **-1**（低于 `warn` 的 0）
            for word in entry.words:
                if word in text:
                    lv = lv_map.get(word, "review")
                    rank = _LEVEL_RANK.get(lv, 1)
                    # ⚠️ 严格 `>`：只在秩**更高**时替换 ⇒ 低等级词**不会**覆盖高等级词
                    #    （`A3-02` 中 warn 词排在 block 词之前时仍须取 block）。
                    #    ⚠️ 初值须为 -1 而非 0：`_LEVEL_RANK["warn"] == 0`，
                    #    若初值为 0 则 `0 > 0` 为假 ⇒ **warn 级永远选不中**。
                    if rank > best_rank:
                        best_rank, best_lv, best_word = rank, lv, word
            if best_word:
                hits.append((entry.category_id, entry.name, best_word, best_lv))
            if len(hits) >= limit:
                break
        return hits


def _category_id_of(filename: str) -> str:
    """从词表文件名提取类别编号。

    两种**实测存在**的文件名格式都要支持：

    | 来源 | 样例 | 提取结果 |
    | --- | --- | --- |
    | 合规资料库 | `A1-07-传播虚假有害信息.txt` | `A1-07`（**前两段**） |
    | 受控区（`E:\\_受控区\\lexicon_controlled`） | `A1-01.txt` | `A1-01`（**先去后缀再取前两段**） |

    ⚠️ **两个已踩过的坑**：
    ① 只按第一个 `-` 切会把 `A1-07` 塌缩成 `A1`，导致所有类别编号相同、**词库整体失效**
       （`T-005` 首轮测试实测发现）；
    ② 不先去 `.txt` 后缀会把 `01.txt` 当成第二段，产出 `A1-01.txt`（带后缀，**匹配不上
       `lexicon_manifest.json` 的 `categories[].id`**）。
    """
    stem = filename.split(".")[0]  # 先去扩展名
    parts = stem.split("-")
    if len(parts) >= 2 and parts[0] and parts[1]:
        return f"{parts[0]}-{parts[1]}"
    return stem


#: **等级序**（用于按类别取最高等级）—— `block` > `review` > `warn`。
#: ⚠️ 与 `SEC-007` §4.3 的三级判据一致：`block` 命中即阻断／`review` 转人工复核／
#: `warn` 仅提示。⚠️ 缺省等级为 `review`（与 `_read_words` 的缺省一致）。
_LEVEL_RANK: dict[str, int] = {"warn": 0, "review": 1, "block": 2}


def _read_words(path: Path) -> tuple[tuple[str, str], ...]:
    """读取单个词表文件：跳过注释行与空行，其余每行一词。

    ⚠️ **词表行是 TAB 分隔的多字段记录**，不是「一整行就是一个词」——
    实际形态（`SEC-007` §五 与 `sign_off.py` 的 `iter_lex` 同口径）：

    | 形态 | 含义 | 实测字段数分布 |
    | --- | --- | --- |
    | `词条` | 纯词条 | 少见 |
    | `词条<TAB>等级` | 无备注 | **821 行**（工程内非受控） |
    | `词条<TAB>等级<TAB>备注` | 完整 | **11,757 行**（工程内）＋ **800 行**（受控区，全部 3 字段） |

    ⇒ **必须按 TAB 切分取第 1 段作词条**；整行入表会使 `word in text`
    **永远为假** ⇒ 双闸**形同虚设**（2026-11-03 抽检实测发现，见 `PM-001` §8）。
    """
    words: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith(_COMMENT):
                continue
            # ⚠️ 按 TAB 切分取第 1 段（词条本体）；其余段是等级/备注/签核人，
            #    **运行时按类别统一策略处置、不逐条读等级**（等级语义见 `SEC-007` §4.3）。
            parts = line.split("\t")
            term = parts[0].strip()
            if term:
                # ⚠️ 第 2 段是**等级**（`block`/`review`/`warn`），缺省按 `review` 处置
                #    （`SEC-007` §4.3「拿不准默认降 warn 而不是 block」）。
                level = parts[1].strip().lower() if len(parts) > 1 else ""
                if level not in ("block", "review", "warn"):
                    level = "review"
                words.append((term, level))
    return tuple(words)


def load_lexicon(root: Path, controlled_root: Path | None = None) -> Lexicon:
    """从 `09-合规资料库/01-关键词库` 加载词库快照，并**可选叠加受控区词条**。

    双源设计（依项目方 **2026-10-15 决策**：「受控内容**不入库**，双闸**运行时读受控区**」）：

    | 源 | 位置 | 文件名格式 | 受控性 |
    | --- | --- | --- | --- |
    | 主源 | `09-合规资料库/01-关键词库/词表/` | `A1-07-传播虚假有害信息.txt` | 受版本控制 |
    | 受控源 | `E:\\_受控区/lexicon_controlled/`（路径可配置） | `A1-01.txt` | **不入库** |

    合并规则：按**类别编号**对齐，**词条去重追加**；受控源可为空（未编写）。
    ⚠️ **受控区的具体路径不出现在返回值里**——只以 `controlled_loaded` 布尔暴露，
    避免路径随 `/safety/policy` 响应外泄。

    纪律：**任何异常都不上抛为崩溃**——统一降级为「该类别不可读」并记入
    `unreadable`，由调用方决定熔断；**绝不返回空快照假装正常**。
    """
    root = Path(root)
    manifest_path = root / "lexicon_manifest.json"
    table_dir = root / "词表"

    standard = ""
    meta_by_id: dict[str, dict] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            standard = str(manifest.get("standard", ""))
            for cat in manifest.get("categories", []) or []:
                cid = str(cat.get("id", "")).strip()
                if cid:
                    meta_by_id[cid] = cat
        except (OSError, ValueError) as exc:  # 清单损坏 → 退化为按文件名发现
            standard = ""
            meta_by_id = {}
    else:
        standard = ""

    warnings: list[str] = []
    if not manifest_path.is_file():
        warnings.append(f"词库清单缺失：{manifest_path}")
    if not table_dir.is_dir():
        warnings.append(f"词表目录缺失：{table_dir}")

    entries: list[LexiconEntry] = []
    unreadable: list[str] = []

    if table_dir.is_dir():
        for f in sorted(table_dir.glob("*.txt")):
            cid = _category_id_of(f.name)
            meta = meta_by_id.get(cid, {})
            try:
                pairs = _read_words(f)
            except OSError:
                unreadable.append(cid)
                continue
            entries.append(
                LexiconEntry(
                    category_id=cid,
                    name=str(meta.get("name", cid)),
                    group=str(meta.get("group", "")),
                    quota=int(meta.get("quota", 0) or 0),
                    controlled=bool(meta.get("controlled", False)),
                    words=tuple(w for w, _ in pairs),
                    levels=pairs,
                    sources=("main",),
                )
            )

    # ---- 受控源叠加（`controlled_root` 可为 None / 目录不存在 / 全空）----
    controlled_loaded = False
    if controlled_root is not None:
        cdir = Path(controlled_root)
        if cdir.is_dir():
            by_id = {e.category_id: i for i, e in enumerate(entries)}
            for f in sorted(cdir.glob("*.txt")):
                cid = _category_id_of(f.name)
                try:
                    cpairs = _read_words(f)
                except OSError:
                    unreadable.append(cid)
                    continue
                if not cpairs:
                    continue
                cwords = tuple(w for w, _ in cpairs)
                controlled_loaded = True
                if cid in by_id:
                    idx = by_id[cid]
                    old = entries[idx]
                    merged = tuple(dict.fromkeys(old.words + cwords))  # 去重且保序
                    # ⚠️ 等级随词条走：**主源优先**（保序去重的首见者为准），
                    #    受控源补齐主源没有的词条及其等级。
                    lv_old = dict(old.levels)
                    lv_ctrl = dict(cpairs)
                    merged_levels = tuple(
                        (w, lv_old.get(w) or lv_ctrl.get(w) or "review")
                        for w in merged)
                    entries[idx] = LexiconEntry(
                        category_id=old.category_id,
                        name=old.name,
                        group=old.group,
                        quota=old.quota,
                        controlled=old.controlled,
                        words=merged,
                        levels=merged_levels,
                        sources=tuple(dict.fromkeys(old.sources + ("controlled",))),
                    )
                else:
                    meta = meta_by_id.get(cid, {})
                    entries.append(
                        LexiconEntry(
                            category_id=cid,
                            name=str(meta.get("name", cid)),
                            group=str(meta.get("group", "")),
                            quota=int(meta.get("quota", 0) or 0),
                            controlled=True,
                            words=cwords,
                            sources=("controlled",),
                        )
                    )
        else:
            warnings.append("受控词库目录不存在：受控类别检测能力不可用")

    # 清单登记了类别但**两源都没有文件** → 登记为不可读
    # （⚠️ 必须在受控源叠加**之后**判定：受控源填充过的类别不再算不可读）
    for cid in meta_by_id:
        if not any(e.category_id == cid for e in entries):
            unreadable.append(cid)

    if not entries:
        warnings.append("未发现任何词表文件：检测能力不可用，调用方必须熔断")

    return Lexicon(
        standard=standard,
        entries=tuple(entries),
        unreadable=tuple(sorted(set(unreadable))),
        source_root=str(root),
        controlled_loaded=controlled_loaded,
        warnings=tuple(warnings),
    )