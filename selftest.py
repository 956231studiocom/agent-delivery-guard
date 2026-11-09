#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""guard.py 纠错体检。每条断言都真跑一次子进程，比对真实退出码与输出。

用法: python selftest.py    退出码 0 = 全过
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "guard.py")
PY = sys.executable
NL = chr(10)
results = []


def run(args, cwd=None, timeout=120):
    return subprocess.run([PY, GUARD] + args, cwd=cwd or HERE,
                          capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def tmpdir():
    return tempfile.mkdtemp(prefix="guardtest_")


# ---------- 1. 两个内置样例的退出码语义 ----------
r = run(["verify", "--path", "demo/broken_repo"])
check("broken_repo 必须退出 1", r.returncode == 1, "got %d" % r.returncode)
check("broken_repo 必须报 5 个 FAIL", r.stdout.count("[FAIL   ]") == 5,
      "got %d" % r.stdout.count("[FAIL   ]"))
check("broken_repo 每条 FAIL 都带证据", "|" in r.stdout and "config 根本没读到" in r.stdout)

r = run(["verify", "--path", "demo/fixed_repo"])
check("fixed_repo 必须退出 0", r.returncode == 0, "got %d" % r.returncode)
check("fixed_repo 必须 5 个 PASS", r.stdout.count("[PASS   ]") == 5,
      "got %d" % r.stdout.count("[PASS   ]"))

# ---------- 2. 产品自检（自指） ----------
r = run(["verify", "--path", "."])
check("产品自检必须 CLEARED", r.returncode == 0, r.stdout.strip().split("\n")[-1][:80])

# ---------- 3. 空目录：不许崩，不许误判 FAIL ----------
d = tmpdir()
r = run(["verify", "--path", d])
check("空目录不崩且不判 FAIL", r.returncode == 0 and "[FAIL" not in r.stdout, r.stdout[:80])
check("空目录应全为 UNKNOWN", r.stdout.count("[UNKNOWN]") == 5,
      "got %d" % r.stdout.count("[UNKNOWN]"))

# ---------- 4. --strict 下 UNKNOWN 必须阻断 ----------
r = run(["verify", "--path", d, "--strict"])
check("strict 模式 UNKNOWN 阻断", r.returncode == 1, "got %d" % r.returncode)
shutil.rmtree(d, ignore_errors=True)

# ---------- 5. JSON 输出必须可解析且结构完整 ----------
r = run(["verify", "--path", "demo/broken_repo", "--json"])
try:
    j = json.loads(r.stdout)
    ok_json = (j["blocked"] is True and j["fail"] == 5 and len(j["checks"]) == 5
               and all(c["evidence"] for c in j["checks"] if c["status"] == "FAIL"))
except Exception as e:
    ok_json = False
    j = {}
check("JSON 可解析且 FAIL 均带 evidence", ok_json, str(j)[:80])

# ---------- 6. .guardignore 生效 ----------
d = tmpdir()
os.makedirs(os.path.join(d, "skipme"))
open(os.path.join(d, "skipme", "bad.py"), "w", encoding="utf-8").write(
    NL.join(["try:", "    x = 1", "except Exception:", "    pass", ""]))
r1 = run(["verify", "--path", d])
open(os.path.join(d, ".guardignore"), "w", encoding="utf-8").write("skipme")
r2 = run(["verify", "--path", d])
check("guardignore 前命中、后不命中",
      "[FAIL" in r1.stdout and "[FAIL" not in r2.stdout,
      "r1=%s r2=%s" % ("[FAIL" in r1.stdout, "[FAIL" in r2.stdout))
shutil.rmtree(d, ignore_errors=True)

# ---------- 7. 行内 guard:ignore 豁免 ----------
d = tmpdir()
open(os.path.join(d, "a.py"), "w", encoding="utf-8").write(
    NL.join(["try:", "    x = 1", "except Exception:  # guard:ignore", "    pass  # guard:ignore", ""]))
open(os.path.join(d, ".guard.json"), "w", encoding="utf-8").write(
    json.dumps({"reports": [], "targets": [], "claims": []}))
r = run(["verify", "--path", d])
check("行内 guard:ignore 豁免生效", "[FAIL" not in r.stdout, r.stdout.split(NL)[2][:80])
shutil.rmtree(d, ignore_errors=True)

# ---------- 8. anchor_allow_regex 生效 ----------
d = tmpdir()
open(os.path.join(d, "DELIVERY.md"), "w", encoding="utf-8").write(
    "见 `somewhere/nonexistent.json`\n")
base_cfg = {"reports": ["DELIVERY.md"], "targets": [], "claims": []}
open(os.path.join(d, ".guard.json"), "w", encoding="utf-8").write(json.dumps(base_cfg))
r1 = run(["verify", "--path", d])
base_cfg["anchor_allow_regex"] = ["nonexistent"]
open(os.path.join(d, ".guard.json"), "w", encoding="utf-8").write(json.dumps(base_cfg))
r2 = run(["verify", "--path", d])
check("anchor_allow_regex 前红后绿",
      "[FAIL" in r1.stdout and "[FAIL" not in r2.stdout,
      "%s -> %s" % ("FAIL" in r1.stdout, "FAIL" in r2.stdout))
shutil.rmtree(d, ignore_errors=True)

# ---------- 9. 二进制/非 UTF8 文件不许崩 ----------
d = tmpdir()
open(os.path.join(d, "blob.py"), "wb").write(bytes(range(256)) * 40)
open(os.path.join(d, "gbk.py"), "wb").write("编码测试 except Exception: pass".encode("gbk", "ignore"))
r = run(["verify", "--path", d])
check("非 UTF8/二进制文件不崩", r.returncode in (0, 1) and "Traceback" not in r.stderr,
      r.stderr[:100])
shutil.rmtree(d, ignore_errors=True)

# ---------- 10. claim 超时不许挂死 ----------
d = tmpdir()
cfg = {"reports": [], "targets": [],
       "claims": [{"claim": "慢命令", "run": "python -c \"import time;time.sleep(30)\"", "timeout_s": 2}]}
open(os.path.join(d, ".guard.json"), "w", encoding="utf-8").write(json.dumps(cfg))
r = run(["verify", "--path", d], timeout=60)
check("claim 超时被判定且不挂死", r.returncode == 1 and "超时" in r.stdout, r.stdout[-120:])
shutil.rmtree(d, ignore_errors=True)

# ---------- 11. 最后一跳：302 -> 404 必须判 FAIL ----------
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", "/dead")
            self.end_headers()
        elif self.path == "/live":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
d = tmpdir()
cfg = {"reports": [], "claims": [],
       "targets": ["http://127.0.0.1:%d/start" % port], "http_timeout_s": 5}
open(os.path.join(d, ".guard.json"), "w", encoding="utf-8").write(json.dumps(cfg))
r = run(["verify", "--path", d])
check("302->404 判 FAIL（不把首跳当通过）",
      r.returncode == 1 and "终态 404" in r.stdout, r.stdout[-160:])
cfg["targets"] = ["http://127.0.0.1:%d/live" % port]
open(os.path.join(d, ".guard.json"), "w", encoding="utf-8").write(json.dumps(cfg))
r = run(["verify", "--path", d])
check("直连 200 判 PASS", "[PASS" in r.stdout and "终态 200" in r.stdout, r.stdout[-120:])
srv.shutdown()
shutil.rmtree(d, ignore_errors=True)

# ---------- 12. init 幂等 ----------
d = tmpdir()
r1 = run(["init", "--path", d])
r2 = run(["init", "--path", d])
check("init 幂等不覆盖", "已存在" in r2.stdout and os.path.exists(os.path.join(d, ".guard.json")),
      r2.stdout[:60])
shutil.rmtree(d, ignore_errors=True)

# ---------- 13. 无关命令退出码 2 ----------
r = subprocess.run([PY, GUARD, "bogus"], capture_output=True, text=True)
check("非法子命令退出码 2", r.returncode == 2, "got %d" % r.returncode)

# ---------- 汇总 ----------
print("=" * 62)
n_pass = sum(1 for _, ok, _ in results if ok)
for name, ok, detail in results:
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "   <<< " + str(detail)))
print("=" * 62)
print("SELFTEST %d/%d %s" % (n_pass, len(results), "GREEN" if n_pass == len(results) else "RED"))
sys.exit(0 if n_pass == len(results) else 1)
