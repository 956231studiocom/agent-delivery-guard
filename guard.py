#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent-delivery-guard -- 在 AI agent 说「做完了」的时候，替你把最后一跳真跑一遍。

单文件、零依赖、纯标准库。Python 3.8+。

用法
    python guard.py verify --path .            检查当前项目
    python guard.py verify --path . --json     机器可读输出
    python guard.py init                       生成 .guard.json 模板
    python guard.py demo                       跑内置坏样例，看它抓什么

退出码
    0  无 FAIL（PASS 或 WARN 混合）
    1  存在 FAIL -- 交付应被拦下
    2  用法错误

设计原则（产品的一部分，不是注释）
    - 只判可复核的事实：退出码、HTTP 终态码、文件存在性、字面命中。不判动机。
    - 环境不可达 -> UNKNOWN，不判 FAIL。把网络故障当代码缺陷是最常见的误报来源。
    - 每个 FAIL 必须带 evidence：文件:行 / URL / 命令 + 原始输出片段。没有证据的判定等于造谣。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

VERSION = "1.1.0"
DEFAULT_CONFIG = ".guard.json"
SC_TOKEN = "SilentlyContinue"


class R:
    PASS, WARN, FAIL, UNKNOWN = "PASS", "WARN", "FAIL", "UNKNOWN"

    def __init__(self, name, status, detail="", evidence=None):
        self.name = name
        self.status = status
        self.detail = detail
        self.evidence = evidence or []


def _read(p):
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _load_ignore(root):
    p = os.path.join(root, ".guardignore")
    if not os.path.exists(p):
        return []
    pats = []
    for line in _read(p).split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            pats.append(line.rstrip("/"))
    return pats


def _iter_files(root, exts, skip_dirs=(".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build")):
    ignore = _load_ignore(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        dirnames[:] = [d for d in dirnames if d not in skip_dirs
                       and not any((rel_dir + "/" + d).lstrip("./").startswith(ig) for ig in ignore)]
        for fn in filenames:
            if any(fn.endswith(e) for e in exts):
                yield os.path.join(dirpath, fn)


def c1_exit_code_truth(root):
    """逐行文本匹配，不用正则 —— 正则转义在跨平台写入时会被吃掉，曾把 \\b 变成退格符。"""
    hits = []
    seen = set()
    scanned = 0
    EXTS = (".py", ".sh", ".bash", ".ps1", ".js", ".ts", ".mjs")
    SC = SC_TOKEN
    for path in _iter_files(root, EXTS):
        src = _read(path)
        if not src:
            continue
        scanned += 1
        rel = os.path.relpath(path, root)
        lines = src.splitlines()
        for i, raw in enumerate(lines):
            if "guard:ignore" in raw:
                continue
            s = raw.strip()
            if not s:
                continue
            nxt = ""
            for j in range(i + 1, min(i + 3, len(lines))):
                if lines[j].strip():
                    nxt = lines[j].strip()
                    break
            why = None
            if s.startswith("except"):
                tail = s.rsplit(":", 1)[-1].strip() if ":" in s else ""
                if tail == "pass" or nxt == "pass":
                    why = "except 后直接 pass：失败不留痕，调用方以为成功"
            if not why and ("||" in s and "true" in s):  # guard:ignore
                why = "|| true：非零退出码被抹平，脚本继续往下走"  # guard:ignore
            if not why and ("2>" in s and "null" in s):  # guard:ignore
                why = "stderr 丢弃：真实报错信息消失，日志里只剩成功"  # guard:ignore
            if not why and "set +e" in s:  # guard:ignore
                why = "set +e：关闭 errexit，后续失败不再中断"  # guard:ignore
            if not why and ("-ErrorAction" in s or "-EA " in s) and SC in s:  # guard:ignore
                why = "静默错误处理：删除/写入失败不报错，命令仍返回成功"  # guard:ignore
            if not why and "catch" in s and s.replace(" ", "").endswith("{}"):  # guard:ignore
                why = "空 catch 块：异常被吞"
            if why:
                key = "%s:%d" % (rel, i + 1)
                if key in seen:
                    continue
                seen.add(key)
                hits.append("%s:%d | %s | %s" % (rel, i + 1, why, s[:110]))
    if scanned == 0:
        return R("exit-code truth", R.UNKNOWN, "没有可扫描的代码文件（未检查，不算通过）")
    if not hits:
        return R("exit-code truth", R.PASS, "扫了 %d 个文件，未发现吞错误的写法" % scanned)
    return R("exit-code truth", R.FAIL,
             "扫了 %d 个文件，发现 %d 处会把失败吞成成功的写法" % (scanned, len(hits)), hits)


REDIRECT_CODES = {301, 302, 303, 307, 308}


def _probe(url, timeout):
    hops = 0
    cur = url
    seen = set()
    try:
        while hops < 8:
            if cur in seen:
                return None, hops, "redirect loop"
            seen.add(cur)
            req = urllib.request.Request(cur, method="GET",
                                         headers={"User-Agent": "agent-delivery-guard/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.getcode(), hops, cur
            except urllib.error.HTTPError as e:
                if e.code in REDIRECT_CODES and e.headers.get("Location"):
                    nxt = e.headers["Location"]
                    if not nxt.startswith("http"):
                        from urllib.parse import urljoin
                        nxt = urljoin(cur, nxt)
                    cur = nxt
                    hops += 1
                    continue
                return e.code, hops, cur
    except Exception as e:
        return None, hops, "%s: %s" % (type(e).__name__, str(e)[:120])


def c2_last_hop(root, cfg):
    targets = cfg.get("targets", [])
    if not targets:
        return R("last-hop reachability", R.UNKNOWN,
                 "未配置 targets（.guard.json 里的购买出口/健康检查 URL）")
    fails, oks, unknowns = [], [], []
    timeout = float(cfg.get("http_timeout_s", 8))
    for t in targets:
        if t.startswith("http://") or t.startswith("https://"):
            code, hops, note = _probe(t, timeout)
            if code is None:
                unknowns.append("%s | 环境不可达(%s) -- 不判 FAIL" % (t, note))
            elif 200 <= code < 300:
                oks.append("%s | 终态 %d（%d 跳）" % (t, code, hops))
            else:
                fails.append("%s | 终态 %d（%d 跳）| %s" % (t, code, hops, note))
        else:
            p = t if os.path.isabs(t) else os.path.join(root, t)
            if os.path.exists(p):
                oks.append("%s | 文件存在" % t)
            else:
                fails.append("%s | 路径不存在" % t)
    if fails:
        return R("last-hop reachability", R.FAIL,
                 "%d 个出口不通 / %d 通 / %d 不可查" % (len(fails), len(oks), len(unknowns)), fails + unknowns)
    if unknowns:
        return R("last-hop reachability", R.WARN,
                 "%d 通 / %d 环境不可达（未判错）" % (len(oks), len(unknowns)), oks + unknowns)
    return R("last-hop reachability", R.PASS, "全部 %d 个出口终态 2xx" % len(oks), oks)


ANCHOR_RE = re.compile(r"`([^`\n]{3,200})`")


def c3_evidence_anchors(root, cfg):
    reports = cfg.get("reports", [])
    if not reports:
        return R("evidence anchors", R.UNKNOWN, "未配置 reports（要核对的交付文档）")
    checked, missing = 0, []
    for rp in reports:
        p = rp if os.path.isabs(rp) else os.path.join(root, rp)
        src = _read(p)
        if not src:
            missing.append("%s | 报告本身不存在" % rp)
            continue
        for m in ANCHOR_RE.finditer(src):
            tok = m.group(1).strip()
            if any(ch in tok for ch in "<>|$*?"):
                continue
            if any(re.search(p, tok) for p in cfg.get("anchor_allow_regex", [])):
                continue
            looks_path = ("/" in tok or "\\" in tok) and " " not in tok
            looks_url = tok.startswith(("http://", "https://"))
            if not (looks_path or looks_url):
                continue
            checked += 1
            if looks_url:
                continue
            cand = tok if os.path.isabs(tok) else os.path.join(root, tok)
            if not os.path.exists(cand):
                missing.append("%s 引用 %s -> 不存在" % (rp, tok))
    if missing:
        return R("evidence anchors", R.FAIL, "核了 %d 个锚点，%d 个落空" % (checked, len(missing)), missing[:40])
    return R("evidence anchors", R.PASS, "核了 %d 个锚点，全部落地" % checked)


DEFER_PATTERNS = [
    (r"下一步[：:]", "以「下一步」收尾，等于没交付"),
    (r"待办(清单)?", "列了待办清单"),
    (r"后续(再|将|会)", "把动作推到后续"),
    (r"等(你|您)(确认|点头|发话)", "把决策权推给用户，自己没做完"),
    (r"待(你|您)(确认|点头)", "同上"),
    (r"(?<![A-Za-z])TODO(?![A-Za-z])", "留了 TODO"),
    (r"(?<![A-Za-z])TBD(?![A-Za-z])", "留了 TBD"),
    (r"稍后(处理|补)", "推迟处理"),
    (r"如需要我(可以|再)", "用提问代替交付"),
]
DONE_MARKERS = [r"已(完成|落盘|删除|修正|上线|提交|执行)", r"实测", r"退出码", r"=\s*\d+", r"HTTP\s*\d{3}"]


def c4_plan_as_result(root, cfg):
    reports = cfg.get("reports", [])
    if not reports:
        return R("plan-as-result", R.UNKNOWN, "未配置 reports")
    hits, done = [], 0
    for rp in reports:
        p = rp if os.path.isabs(rp) else os.path.join(root, rp)
        src = _read(p)
        if not src:
            continue
        for pat, why in DEFER_PATTERNS:
            for m in re.finditer(pat, src):
                ln = src[: m.start()].count("\n") + 1
                hits.append("%s:%d | %s | ...%s..." % (rp, ln, why, src[max(0, m.start() - 30):m.start() + 40].strip()))
        for pat in DONE_MARKERS:
            done += len(re.findall(pat, src))
    if hits and done == 0:
        return R("plan-as-result", R.FAIL,
                 "延后信号 %d 处，完成态证据 0 处 -- 这是计划不是交付" % len(hits), hits[:30])
    if hits:
        return R("plan-as-result", R.WARN,
                 "延后信号 %d 处，但完成态证据 %d 处（可接受，需人读）" % (len(hits), done), hits[:15])
    return R("plan-as-result", R.PASS, "无延后措辞，完成态证据 %d 处" % done)


def c5_claim_vs_reality(root, cfg):
    claims = cfg.get("claims", [])
    if not claims:
        return R("claim vs reality", R.UNKNOWN,
                 "未配置 claims（.guard.json 里把「我声称做到的」写成可执行的验证）")
    fails, oks, unknowns = [], [], []
    for c in claims:
        claim = c.get("claim", "?")
        cmd = c.get("run", "")
        expect = c.get("expect_exit", 0)
        rx = c.get("expect_stdout")
        if not cmd:
            unknowns.append("%s | 未给 run 命令，无法验" % claim)
            continue
        try:
            p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True,
                               text=True, timeout=int(c.get("timeout_s", 120)))
        except subprocess.TimeoutExpired:
            fails.append("%s | 验证命令超时 | %s" % (claim, cmd))
            continue
        except Exception as e:
            unknowns.append("%s | 命令无法执行 %s | %s" % (claim, type(e).__name__, cmd))
            continue
        if p.returncode != expect:
            tail = (p.stdout + p.stderr).strip().split("\n")[-3:]
            fails.append("%s | 实际退出码 %d，声称 %d | %s | ...%s" %
                         (claim, p.returncode, expect, cmd, " / ".join(tail)[:200]))
            continue
        if rx and not re.search(rx, p.stdout, re.M):
            fails.append("%s | 退出码对但输出不匹配 /%s/ | %s" % (claim, rx, cmd))
            continue
        oks.append("%s | 退出码 %d 与声称一致" % (claim, p.returncode))
    if fails:
        return R("claim vs reality", R.FAIL, "%d 条声称与实测不符" % len(fails), fails)
    if unknowns:
        return R("claim vs reality", R.WARN, "%d 条已验 / %d 条无法验" % (len(oks), len(unknowns)), oks + unknowns)
    return R("claim vs reality", R.PASS, "%d 条声称全部被实测证实" % len(oks), oks)


COLOR = {"PASS": "\033[92m", "WARN": "\033[93m", "FAIL": "\033[91m", "UNKNOWN": "\033[90m", "0": "\033[0m"}


def _c(s, st):
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return s
    return "%s%s%s" % (COLOR.get(st, ""), s, COLOR["0"])


def load_cfg(root):
    p = os.path.join(root, DEFAULT_CONFIG)
    if not os.path.exists(p):
        return {}
    try:
        return json.loads(_read(p))
    except Exception:
        return {}


def verify(root, as_json=False, strict=False):
    cfg = load_cfg(root)
    results = [
        c1_exit_code_truth(root),
        c2_last_hop(root, cfg),
        c3_evidence_anchors(root, cfg),
        c4_plan_as_result(root, cfg),
        c5_claim_vs_reality(root, cfg),
    ]
    n_fail = sum(1 for r in results if r.status == R.FAIL)
    n_warn = sum(1 for r in results if r.status == R.WARN)
    n_pass = sum(1 for r in results if r.status == R.PASS)
    n_unk = sum(1 for r in results if r.status == R.UNKNOWN)
    blocked = n_fail > 0 or (strict and n_unk > 0)

    if as_json:
        print(json.dumps({
            "version": VERSION, "root": os.path.abspath(root),
            "blocked": blocked, "fail": n_fail, "warn": n_warn, "pass": n_pass, "unknown": n_unk,
            "checks": [{"name": r.name, "status": r.status, "detail": r.detail, "evidence": r.evidence}
                       for r in results],
        }, ensure_ascii=False, indent=2))
    else:
        print("agent-delivery-guard v%s  ->  %s" % (VERSION, os.path.abspath(root)))
        print("-" * 68)
        for r in results:
            print("%s %-24s %s" % (_c("[%-7s]" % r.status, r.status), r.name, r.detail))
            for e in r.evidence[:8]:
                print("         - %s" % e)
            if len(r.evidence) > 8:
                print("         - ...另有 %d 条" % (len(r.evidence) - 8))
        print("-" * 68)
        verdict = "BLOCKED -- 不许交付" if blocked else "CLEARED -- 可以交付"
        print("%s   FAIL %d / WARN %d / PASS %d / UNKNOWN %d" %
              (_c(verdict, "FAIL" if blocked else "PASS"), n_fail, n_warn, n_pass, n_unk))
        if n_fail:
            print("\n每条 FAIL 都带证据。修掉证据指向的那一行，再跑一次。")
    return 1 if blocked else 0


INIT_TEMPLATE = {
    "_comment": "把「我声称做到的」写成能跑的验证命令。guard 会真的执行它。",
    "targets": ["https://your-site.com/health", "./dist/bundle.js"],
    "reports": ["DELIVERY.md"],
    "http_timeout_s": 8,
    "claims": [
        {"claim": "测试全过", "run": "python -m pytest -q", "expect_exit": 0, "timeout_s": 180},
        {"claim": "构建成功", "run": "npm run build", "expect_exit": 0, "timeout_s": 300}
    ],
}


def cmd_init(root):
    p = os.path.join(root, DEFAULT_CONFIG)
    if os.path.exists(p):
        print("已存在，未覆盖：%s" % p)
        return 0
    with open(p, "w", encoding="utf-8") as f:
        json.dump(INIT_TEMPLATE, f, ensure_ascii=False, indent=2)
    print("已写入 %s" % p)
    print("下一步：把 claims 换成你自己的验证命令，再跑 python guard.py verify")
    return 0


def cmd_demo():
    here = os.path.dirname(os.path.abspath(__file__))
    demo = os.path.join(here, "demo", "broken_repo")
    if not os.path.isdir(demo):
        print("demo/broken_repo 缺失", file=sys.stderr)
        return 2
    print("演示对象：一个「AI 说全改好了」的项目。它身上有多处真实的假绿。\n")
    return verify(demo)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # guard:ignore
    except Exception:
        pass  # guard:ignore
    ap = argparse.ArgumentParser(prog="guard.py", description="拦住 AI agent 的假绿交付")
    ap.add_argument("cmd", choices=["verify", "init", "demo"])
    ap.add_argument("--path", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="UNKNOWN 也视为阻断")
    a = ap.parse_args()
    if a.cmd == "init":
        return cmd_init(a.path)
    if a.cmd == "demo":
        return cmd_demo()
    return verify(a.path, a.json, a.strict)


if __name__ == "__main__":
    sys.exit(main())
