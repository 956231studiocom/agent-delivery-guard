#!/usr/bin/env python3
"""零依赖测试 runner。任一断言失败即非零退出码。"""
import sys

fails = []

try:
    from app.handler import process
    r = process({"id": 1})
    assert r["ok"] is True, "process 返回 ok=False"
except Exception as e:
    fails.append("test_process_returns_ok: %s" % e)

try:
    from app.handler import process
    r = process({"id": 2})
    assert r["size"] > 0, "config 根本没读到，size 恒为 0"
except Exception as e:
    fails.append("test_size_nonzero: %s" % e)

if fails:
    print("FAILED (%d)" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("OK: 2 passed")
