# -*- coding: utf-8 -*-
"""
init_lexicon.py — 按 GB/T 45654—2025 附录 A 分类骨架初始化关键词库词表

用途：
    1. 生成 31 个词表骨架文件（含表头注释、配额说明、种子词）
    2. 生成 lexicon_manifest.json（机读的分类定义 + 配额），供 check_quota.py 使用

依据：
    GB/T 45654—2025 §8.1（关键词库）+ 附录 A（31 种安全风险）
    A.1 每类 >=200，A.2 每类 >=100，总规模 >=10000，每周至少更新一次

用法：
    python init_lexicon.py            # 生成（已存在的文件不覆盖）
    python init_lexicon.py --force    # 强制覆盖
"""

import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # 09-合规资料库
VOCAB_DIR = os.path.join(ROOT, "01-关键词库", "词表")
MANIFEST = os.path.join(ROOT, "01-关键词库", "lexicon_manifest.json")

# ---------------------------------------------------------------- 分类定义
# controlled=True 表示该类词条受严格管控，工程文档不留明文，
# 由外部词库导入 + 内部受控维护（见 04-开源资源索引/SEC-006_开源词库资源.md）
CATEGORIES = [
    # ---- A.1 违反社会主义核心价值观（8 类，每类 >=200）----
    dict(id="A1-01", group="A.1", name="煽动颠覆国家政权、推翻社会主义制度",
         quota=200, project_relevance="低", controlled=True, seeds=[
             "# [受控类] 该类词条不在工程文档明文留痕。",
             "# 构建方式：由 04-开源资源索引 所列开源词库导入，按本类重新归类，",
             "#           导入后须经两人复核，词表以受控方式存储（见 05-台账与制度/SEC-012_资产受控与保密说明.md）。",
         ]),
    dict(id="A1-02", group="A.1", name="危害国家安全和利益、损害国家形象",
         quota=200, project_relevance="低", controlled=True, seeds=[
             "# [受控类] 同上，不在工程文档明文留痕。",
         ]),
    dict(id="A1-03", group="A.1", name="煽动分裂国家、破坏国家统一和社会稳定",
         quota=200, project_relevance="低", controlled=True, seeds=[
             "# [受控类] 同上，不在工程文档明文留痕。",
         ]),
    dict(id="A1-04", group="A.1", name="宣扬恐怖主义、极端主义",
         quota=200, project_relevance="中", controlled=False,
         seeds=[
             "terrorist attack\treview\t泛化类别词，用于识别恐袭话题",
             "爆炸装置制作\treview\t",
             "暴恐音视频\treview\t",
             "极端主义宣传\treview\t",
             "恐怖组织招募\treview\t",
             "自制炸药\treview\t",
             "袭击教程\treview\t",
             "极端思想传播\treview\t",
         ]),
    dict(id="A1-05", group="A.1", name="宣扬民族仇恨",
         quota=200, project_relevance="中", controlled=True, seeds=[
             "# [受控类] 民族仇恨类具体表述不在工程文档明文留痕，避免二次传播。",
             "# 构建方式：开源词库导入 + 本项目题材专项（见 ../SEC-001_专项词表-项目题材.md）。",
             "# 本项目特别关注：「某族落都会下蛊」这类地域+民族影射写法，须在本类中覆盖。",
         ]),
    dict(id="A1-06", group="A.1", name="宣扬暴力、淫秽色情",
         quota=200, project_relevance="★高", controlled=False,
         seeds=[
             "# ===== 暴力类（本项目《蛊》核心风险面）=====",
             "血肉模糊\tblock\t命门级",
             "断肢\tblock\t命门级",
             "割喉\tblock\t命门级",
             "开膛\tblock\t命门级",
             "挖眼\tblock\t命门级",
             "剖腹\tblock\t命门级",
             "剥皮\tblock\t命门级",
             "虐杀\tblock\t",
             "血洗\tblock\t爽感渲染",
             "以暴制暴\tblock\t广电总局点名的整治重点",
             "快意恩仇\tblock\t",
             "杀疯了\tblock\t剧名禁用词",
             "血泊\tblock\t",
             "喷血\tblock\t",
             "内脏特写\tblock\t",
             "折磨过程\treview\t",
             "血腥\treview\t按观感判断",
             "伤口特写\treview\t",
             "刀刃入肉\treview\t",
             "# ===== 色情类 =====",
             "色情\tblock\t",
             "淫秽\tblock\t",
             "床戏\treview\t",
             "性暗示\treview\t",
             "露胸\tblock\t封面禁用",
             "露背\tblock\t封面禁用",
             "情色\treview\t",
             "裸体\treview\t按语境判断",
         ]),
    dict(id="A1-07", group="A.1", name="传播虚假有害信息",
         quota=200, project_relevance="中", controlled=False,
         seeds=[
             "谣言\tblock\t",
             "造谣\tblock\t",
             "虚假新闻\treview\t",
             "编造事实\treview\t",
             "恶意散布\treview\t",
             "不实信息\treview\t",
             "伪造证据\treview\t",
         ]),
    dict(id="A1-08", group="A.1", name="其他法律、行政法规禁止的内容",
         quota=200, project_relevance="中", controlled=False,
         seeds=[
             "赌博\tblock\t",
             "网络赌场\tblock\t",
             "毒品交易\tblock\t",
             "枪支买卖\tblock\t",
             "私彩\tblock\t",
             "代开发票\tblock\t",
             "办假证\tblock\t",
             "违禁品\treview\t",
             "走私\treview\t",
         ]),

    # ---- A.2 歧视性内容（9 类，每类 >=100）----
    dict(id="A2-01", group="A.2", name="民族歧视内容",
         quota=100, project_relevance="★高", controlled=False,
         seeds=[
             "# 本项目特别关注：题材涉山地族裔设定，须防止现实民族影射。",
             "劣等民族\treview\t",
             "野蛮民族\treview\t",
             "未开化\treview\t",
             "民族劣根性\treview\t",
             "某族人天生\treview\t影射写法",
         ]),
    dict(id="A2-02", group="A.2", name="信仰歧视内容",
         quota=100, project_relevance="★高", controlled=False,
         seeds=[
             "# 本项目特别关注：《蛊》涉巫祝、秘法，须防止对信仰群体的贬损。",
             "邪教徒\treview\t",
             "愚昧信仰\treview\t",
             "迷信落后\treview\t",
             "信仰低劣\treview\t",
             "拜鬼\treview\t",
         ]),
    dict(id="A2-03", group="A.2", name="国别歧视内容",
         quota=100, project_relevance="低", controlled=False,
         seeds=[
             "洋垃圾\treview\t",
             "劣等国\treview\t",
             "外国佬\treview\t",
             "崇洋媚外\treview\t按语境判断",
         ]),
    dict(id="A2-04", group="A.2", name="地域歧视内容",
         quota=100, project_relevance="★高", controlled=False,
         seeds=[
             "地域黑\treview\t",
             "乡下人\treview\t",
             "小地方来的\treview\t",
             "某地人都\treview\t句式",
             "穷地方\treview\t",
             "蛮荒之地\treview\t本项目設定相关",
         ]),
    dict(id="A2-05", group="A.2", name="性别歧视内容",
         quota=100, project_relevance="中", controlled=False,
         seeds=[
             "女人就该\treview\t",
             "男人都\treview\t",
             "女司机\treview\t",
             "娘炮\treview\t",
             "妇人之见\treview\t",
             "头发长见识短\treview\t",
         ]),
    dict(id="A2-06", group="A.2", name="年龄歧视内容",
         quota=100, project_relevance="低", controlled=False,
         seeds=[
             "老不死的\treview\t",
             "老废物\treview\t",
             "小屁孩\treview\t",
             "老东西\treview\t",
         ]),
    dict(id="A2-07", group="A.2", name="职业歧视内容",
         quota=100, project_relevance="低", controlled=False,
         seeds=[
             "下贱工作\treview\t",
             "低人一等\treview\t",
             "扫大街的\treview\t",
             "没出息的工作\treview\t",
         ]),
    dict(id="A2-08", group="A.2", name="健康歧视内容",
         quota=100, project_relevance="中", controlled=False,
         seeds=[
             "残废\treview\t",
             "智障\treview\t",
             "精神病\treview\t按语境判断",
             "传染病患者\treview\t",
             "畸形\treview\t按语境判断",
         ]),
    dict(id="A2-09", group="A.2", name="其他方面歧视内容",
         quota=100, project_relevance="中", controlled=False,
         seeds=[
             "群体侮辱\treview\t",
             "身份歧视\treview\t",
             "出身体歧视\treview\t",
             "婚史歧视\treview\t",
         ]),

    # ---- A.3 商业违法违规（5 类）----
    dict(id="A3-01", group="A.3", name="侵犯他人知识产权",
         quota=300, project_relevance="★高", controlled=False,
         seeds=[
             "# 本项目特别关注：《蛊》为改编作品，授权链必须完整（见 08-法律法规依据/L1-法律/LAW-005_中华人民共和国著作权法.md）。",
             "盗版\tblock\t",
             "抄袭\tblock\t",
             "洗稿\treview\t",
             "搬运\treview\t",
             "无授权改编\treview\t",
             "魔改原著\treview\t平台点名",
             "未授权IP\treview\t",
             "盗用素材\treview\t",
         ]),
    dict(id="A3-02", group="A.3", name="违反商业道德",
         quota=300, project_relevance="低", controlled=False,
         seeds=[
             "虚假宣传\tblock\t",
             "刷单\tblock\t",
             "水军\treview\t",
             "恶意差评\treview\t",
             "刷量\treview\t",
         ]),
    dict(id="A3-03", group="A.3", name="泄露他人商业秘密",
         quota=300, project_relevance="低", controlled=False,
         seeds=[
             "商业机密外泄\treview\t",
             "内部资料流出\treview\t",
             "客户名单泄露\treview\t",
             "竞业协议规避\treview\t",
         ]),
    dict(id="A3-04", group="A.3", name="利用算法、数据、平台等优势实施垄断和不正当竞争",
         quota=300, project_relevance="低", controlled=False,
         seeds=[
             "数据垄断\treview\t",
             "二选一\treview\t",
             "排他协议\treview\t",
             "恶意收购\treview\t",
             "算法合谋\treview\t",
         ]),
    dict(id="A3-05", group="A.3", name="其他商业违法违规行为",
         quota=300, project_relevance="低", controlled=False,
         seeds=[
             "偷税漏税\treview\t",
             "无照经营\treview\t",
             "非法集资\treview\t",
         ]),

    # ---- A.4 侵犯他人合法权益（7 类）----
    dict(id="A4-01", group="A.4", name="危害他人身心健康",
         quota=300, project_relevance="★高", controlled=False,
         seeds=[
             "# 同时对应本项目 §2 未成年人、自杀自残相关约束。",
             "教唆自杀\tblock\t",
             "自杀方法\tblock\t",
             "自残教程\tblock\t",
             "诱导自伤\treview\t",
             "极端减肥\treview\t",
             "劝酒致死\treview\t",
         ]),
    dict(id="A4-02", group="A.4", name="侵害他人肖像权",
         quota=300, project_relevance="★高", controlled=False,
         seeds=[
             "# 本项目特别关注：AI 漫剧严禁 AI 换脸、明星脸。",
             "AI换脸\tblock\t平台从重处罚",
             "明星脸\tblock\t",
             "换脸\tblock\t",
             "盗用肖像\treview\t",
             "真人面容复刻\treview\t",
         ]),
    dict(id="A4-03", group="A.4", name="侵害他人名誉权",
         quota=300, project_relevance="中", controlled=False,
         seeds=[
             "诽谤\treview\t",
             "人身攻击\treview\t",
             "恶意中伤\treview\t",
             "抹黑\treview\t",
         ]),
    dict(id="A4-04", group="A.4", name="侵害他人荣誉权",
         quota=300, project_relevance="中", controlled=False,
         seeds=[
             "# 对应本项目 §2.8 英烈保护。",
             "诋毁英烈\treview\t",
             "抹黑英雄\treview\t",
             "戏说英烈\treview\t",
         ]),
    dict(id="A4-05", group="A.4", name="侵害他人隐私权",
         quota=300, project_relevance="中", controlled=False,
         seeds=[
             "人肉搜索\tblock\t",
             "开盒\tblock\t",
             "跟踪偷拍\treview\t",
             "隐私泄露\treview\t",
             "定位他人\treview\t",
         ]),
    dict(id="A4-06", group="A.4", name="侵害他人个人信息权益",
         quota=300, project_relevance="中", controlled=False,
         seeds=[
             "倒卖个人信息\tblock\t",
             "手机号买卖\tblock\t",
             "身份证信息交易\treview\t",
             "数据爬取\treview\t按语境判断",
         ]),
    dict(id="A4-07", group="A.4", name="侵犯他人其他合法权益",
         quota=300, project_relevance="低", controlled=False,
         seeds=[
             "骚扰他人\treview\t",
             "恐吓威胁\treview\t",
             "恶意举报\treview\t",
         ]),

    # ---- A.5 无法满足特定服务类型的安全需求（2 类）----
    dict(id="A5-01", group="A.5", name="内容不准确，严重不符合科学常识或主流认知",
         quota=300, project_relevance="中", controlled=False,
         seeds=[
             "# 该类以分类模型 + 人工判定为主，词表仅作辅助信号。",
             "伪科学\treview\t",
             "包治百病\treview\t",
             "偏方治癌\treview\t",
             "违背常识\treview\t",
         ]),
    dict(id="A5-02", group="A.5", name="内容不可靠，无法对使用者形成帮助",
         quota=300, project_relevance="低", controlled=False,
         seeds=[
             "# 该类以分类模型 + 人工判定为主，词表仅作辅助信号。",
             "来源不明\treview\t",
             "无法验证\treview\t",
         ]),
]

HEADER_TMPL = """# =============================================================================
# 关键词库词表：{cid} {name}
# 组别：{group}   单类配额：>= {quota} 个
# 本项目相关度：{relevance}
# 依据：GB/T 45654—2025 §8.1 + 附录 A
# 格式：一行一个词条；支持 `词条` / `词条<TAB>等级<TAB>备注`；`#` 开头为注释
# 等级：block（阻断）/ review（复核）/ warn（提示）
# 状态：骨架 + 种子词，待扩充至配额线。运行 ../06-构建工具/check_quota.py 查看进度。
# =============================================================================

"""


def build_file(cat):
    """生成单个词表文件内容。"""
    lines = [HEADER_TMPL.format(
        cid=cat["id"], name=cat["name"], group=cat["group"],
        quota=cat["quota"], relevance=cat["project_relevance"],
    )]
    lines.append("# ---------------------------- 词条 ----------------------------\n")
    for s in cat["seeds"]:
        lines.append(s + "\n")
    lines.append("\n# 词条数（不含注释）：%d / %d\n" % (count_words(cat["seeds"]), cat["quota"]))
    return "".join(lines)


def count_words(seeds):
    return sum(1 for s in seeds if s.strip() and not s.strip().startswith("#"))


def main():
    force = "--force" in sys.argv
    os.makedirs(VOCAB_DIR, exist_ok=True)

    manifest = dict(
        standard="GB/T 45654—2025",
        clauses=dict(
            lexicon_total_min=10000,
            a1_per_class_min=200,
            a2_per_class_min=100,
            covered_groups=["A.1", "A.2"],
            covered_class_count=17,
            update_cycle="每周至少一次",
        ),
        categories=[],
    )

    created, skipped = 0, 0
    for cat in CATEGORIES:
        fname = "%s-%s.txt" % (cat["id"], cat["name"].replace("、", "").replace("，", ""))
        fname = fname[:60] + ".txt" if not fname.endswith(".txt") else fname
        path = os.path.join(VOCAB_DIR, fname)
        manifest["categories"].append(dict(
            id=cat["id"], group=cat["group"], name=cat["name"],
            quota=cat["quota"], project_relevance=cat["project_relevance"],
            controlled=cat["controlled"], file=fname,
            seed_count=count_words(cat["seeds"]),
        ))
        if os.path.exists(path) and not force:
            skipped += 1
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(build_file(cat))
        created += 1

    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("[init_lexicon] 词表目录：%s" % VOCAB_DIR)
    print("[init_lexicon] 新建 %d 个，跳过（已存在）%d 个" % (created, skipped))
    print("[init_lexicon] 分类清单：%s" % MANIFEST)


if __name__ == "__main__":
    main()
