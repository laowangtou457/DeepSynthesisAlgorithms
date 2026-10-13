#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
法规原文抓取与解析工具
用法:
    python fetch_laws.py CFG-009_sources.json

CFG-009_sources.json 格式:
[
  {"file": "L2-行政法规与规章/xxx.md", "title": "...", "url": "...",
   "issuer": "...", "publish": "...", "effect": "...", "level": "L2", "note": "..."},
  ...
]

流程: requests 抓取 -> 编码嗅探 -> HTML 正文提取 -> 清洗 -> 写入 Markdown
"""
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 常见正文容器选择器（按优先级）
CONTENT_SELECTORS = [
    "#Zoom", ".TRS_Editor", "#UCAP-CONTENT", ".article-content", ".content",
    "#content", ".TRS_UEDITOR", "#articleContent", ".detail-content",
    "#mainText", ".main-content", ".text", "article", ".view", "#con",
]


def sniff_encoding(resp):
    """根据响应头/内容嗅探编码"""
    ct = resp.headers.get("Content-Type", "")
    m = re.search(r"charset=([\w-]+)", ct, re.I)
    if m:
        enc = m.group(1).lower()
        if enc in ("gb2312", "gbk", "gb-2312"):
            return "gb18030"
        return enc
    raw = resp.content[:4096]
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            raw.decode(enc)
            return enc
        except Exception:
            continue
    return "utf-8"


def extract_title(soup):
    for sel in ["h1", ".title", "#title", "title"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            t = el.get_text(strip=True)
            t = re.sub(r"[-_|].{0,30}$", "", t).strip()
            if t:
                return t
    return ""


def extract_body(soup):
    """提取正文文本，返回段落列表"""
    node = None
    for sel in CONTENT_SELECTORS:
        try:
            cand = soup.select_one(sel)
        except Exception:
            cand = None
        if cand and len(cand.get_text(strip=True)) > 400:
            node = cand
            break
    if node is None:
        node = soup.body or soup

    # 去掉脚本、样式、导航等
    for bad in node.select("script, style, nav, header, footer, iframe, "
                           ".share, .related, .comment, .print, .editor"):
        bad.decompose()

    # 优先按 <p> 抽段；没有 <p> 则按换行切
    paras = []
    ps = node.find_all(["p", "div"], recursive=True)
    if ps:
        for p in ps:
            txt = p.get_text(" ", strip=True)
            # 跳过纯容器（父节点），只要叶子级文本
            if p.find(["p", "div"]):
                continue
            if txt:
                paras.append(txt)
    if len(paras) < 5:
        raw = node.get_text("\n", strip=True)
        paras = [ln.strip() for ln in raw.split("\n") if ln.strip()]

    # 清理
    cleaned = []
    for p in paras:
        p = re.sub(r"\s+", " ", p).strip()
        p = p.replace("\u3000", " ")
        if not p:
            continue
        if len(p) < 2:
            continue
        cleaned.append(p)
    # 去重复相邻段落
    out = []
    for p in cleaned:
        if not out or out[-1] != p:
            out.append(p)
    return out


def build_md(meta, paras):
    lines = []
    lines.append(f"# {meta.get('title','')}")
    lines.append("")
    lines.append("> **本文件为自动抓取的法规原文存档，用于项目合规依据。**")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("| --- | --- |")
    lines.append(f"| 法规名称 | {meta.get('title','')} |")
    if meta.get("issuer"):
        lines.append(f"| 发布机关 | {meta['issuer']} |")
    if meta.get("publish"):
        lines.append(f"| 发布日期 | {meta['publish']} |")
    if meta.get("effect"):
        lines.append(f"| 施行日期 | {meta['effect']} |")
    if meta.get("doc_no"):
        lines.append(f"| 文号 | {meta['doc_no']} |")
    lines.append(f"| 效力层级 | {meta.get('level','')} |")
    if meta.get("note"):
        lines.append(f"| 备注 | {meta['note']} |")
    lines.append(f"| 来源网址 | {meta.get('url','')} |")
    lines.append(f"| 抓取时间 | {time.strftime('%Y-%m-%d %H:%M:%S')} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 正文")
    lines.append("")
    for p in paras:
        lines.append(p)
        lines.append("")
    return "\n".join(lines)


def fetch_one(meta):
    url = meta["url"]
    resp = requests.get(url, headers=HEADERS, timeout=40, verify=False)
    resp.raise_for_status()
    enc = sniff_encoding(resp)
    html = resp.content.decode(enc, errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    paras = extract_body(soup)
    if not paras:
        raise RuntimeError("正文提取为空")
    return build_md(meta, paras), len(paras)


def main():
    import urllib3
    urllib3.disable_warnings()

    src = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    ok, fail = [], []
    for meta in src:
        out_path = ROOT / meta["file"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            md, n = fetch_one(meta)
            out_path.write_text(md, encoding="utf-8")
            ok.append((meta["file"], n, len(md)))
            print(f"[OK]   {meta['file']}  段数={n}  字符={len(md)}")
        except Exception as e:
            fail.append((meta["file"], str(e)))
            print(f"[FAIL] {meta['file']}  -> {e}")
        time.sleep(0.8)
    print("\n=== 汇总 ===")
    print(f"成功 {len(ok)} / 失败 {len(fail)}")
    for f in fail:
        print("  失败:", f)


if __name__ == "__main__":
    main()
