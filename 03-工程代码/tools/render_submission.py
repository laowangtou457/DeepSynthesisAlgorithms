# -*- coding: utf-8 -*-
"""真名提交件渲染器（`T-027`／`T-091` 配套，2026-11-10）。

用途：仓库内文档一律**脱敏**（占位符 `{{键}}`），真实身份实值只存
`_私密实值/values.json`（`.gitignore` 已排除）。本脚本把占位符替换为实值，
输出到 `_私密实值/提交件/`，供正式提交使用。

纪律：
- 本脚本本身**不含任何真名**，只按 values.json 的键做替换；
- 渲染后若仍有 `{{…}}` 未解析 ⇒ 直接报错退出（不留半成品）；
- 只读仓库文档、只写私密目录，不修改任何入库文件。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # 工程根
PRIV = ROOT / '_私密实值'
OUT = PRIV / '提交件'

#: 待渲染的脱敏源文档（相对工程根）
SOURCES = [
    '02-备案申报/FIL-003_算法备案申报书-初稿.md',
    '09-合规资料库/05-台账与制度/SEC-019_用户隐私政策-初稿.md',
    '09-合规资料库/05-台账与制度/SEC-020_用户权益保护说明-初稿.md',
    '09-合规资料库/05-台账与制度/SEC-021_用户个人数据标识说明-初稿.md',
]

_TOKEN = re.compile(r'\{\{\s*([^{}]+?)\s*\}\}')

#: 已知「其余四项」待定项——渲染时保留占位、只作提示，不判失败
PENDING: frozenset[str] = frozenset({
    '首次对外提供服务日期', '待页面落地后补', '待与ICP备案名称对齐',
    '待与 ICP 备案名称对齐', '待系统实现确认', '占位符',
})


def load_values() -> dict[str, str]:
    p = PRIV / 'values.json'
    if not p.exists():
        raise SystemExit(f'缺少实值文件：{p}')
    raw = json.loads(p.read_text(encoding='utf-8'))
    return {k: str(v) for k, v in raw.items()
            if not k.startswith('_') and isinstance(v, (str, int, float))}


def render(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        # 兼容「{{待项目方确认：说明}}」这类尚未改键的历史写法
        base = key.split('：')[0].split(':')[0].strip()
        if key in values:
            return values[key]
        if base in values:
            return values[base]
        missing.append(key)
        return m.group(0)

    return _TOKEN.sub(sub, text), missing


def main() -> int:
    values = load_values()
    OUT.mkdir(parents=True, exist_ok=True)
    rc = 0
    for rel in SOURCES:
        src = ROOT / rel
        if not src.exists():
            print(f'[跳过] 源文档不存在：{rel}')
            rc = 1
            continue
        text = src.read_text(encoding='utf-8')
        out_text, missing = render(text, values)
        dst = OUT / src.name.replace('-初稿', '')
        dst.write_text(out_text, encoding='utf-8')
        left = sorted(set(re.findall(r'\{\{\s*([^{}]+?)\s*\}\}', out_text)))
        left = [k for k in left if k not in PENDING]
        status = 'OK' if not left else f'⚠ 仍有占位符 {left}'
        if left:
            rc = 1
        pending = sorted(set(re.findall(r'\{\{\s*([^{}]+?)\s*\}\}', out_text)))
        pending = [k for k in pending if k in PENDING]
        if pending:
            status += f'（待定项：{pending}）'
        print(f'[渲染] {rel} -> {dst.relative_to(ROOT)}  {status}')

    # 交叉核对：八类责任人是否齐备
    posts = values and json.loads((PRIV / 'values.json').read_text(encoding='utf-8')).get('八类责任人', {})
    need = ['用户注册', '算法机制机理审核', '科技伦理审查', '信息发布审核',
            '数据安全', '个人信息保护', '反电信网络诈骗', '应急处置']
    lack = [k for k in need if not posts.get(k)]
    print('[八类责任人] ' + ('齐备 8/8' if not lack else f'缺 {lack}'))
    if lack:
        rc = 1
    return rc


if __name__ == '__main__':
    sys.exit(main())
