# agent-delivery-guard

**Your AI agent said "done". This makes it prove it.**

One file. Zero dependencies. Pure Python 3.8+ standard library.

When Claude Code, Cursor, Codex or any agent hands you a "finished" change, it
routinely reports success on work that never happened: a swallowed stderr, a
redirect that lands on a 502, a "next steps" list sold as a delivery, a test
suite that was never run. This tool turns those claims into checks that actually
execute, and blocks the handoff when they don't hold.

```
$ python guard.py demo

[FAIL   ] exit-code truth          发现 3 处会把失败吞成成功的写法
         - app/handler.py:5 | bare except + pass | except Exception:
[FAIL   ] last-hop reachability    1 个出口不通 / 0 通
         - ./dist/bundle.js | 路径不存在
[FAIL   ] evidence anchors         核了 1 个锚点，1 个落空
         - DELIVERY.md 引用 dist/bundle.js -> 不存在
[FAIL   ] plan-as-result           延后信号 3 处，完成态证据 0 处 -- 这是计划不是交付
[FAIL   ] claim vs reality         2 条声称与实测不符
         - 测试全过 | 实际退出码 1，声称 0 | ... config 根本没读到，size 恒为 0
--------------------------------------------------------------------
BLOCKED -- 不许交付   FAIL 5 / WARN 0 / PASS 0 / UNKNOWN 0
exit code: 1
```

Same repo, after the fixes:

```
CLEARED -- 可以交付   FAIL 0 / WARN 0 / PASS 5 / UNKNOWN 0
exit code: 0
```

Both demos ship with the product. You can run them yourself in 10 seconds.

---

## The five checks

| Check | What it catches | How it decides |
|---|---|---|
| `exit-code truth` | `catch { }`, bare `except: pass`, `\|\| true`, `2>/dev/null`, silent-error flags | literal pattern match, reports file:line |
| `last-hop reachability` | redirect chains that end on 404/502 while the first hop was 200 | follows up to 8 hops, judges the **final** status only |
| `evidence anchors` | a report citing paths that do not exist | every backticked path is stat'ed |
| `plan-as-result` | "next steps", TODOs, "waiting for your confirmation" sold as delivery | deferral markers vs. completion evidence |
| `claim vs reality` | "tests pass", "build ok" with nothing behind it | **actually runs your command**, compares exit code |

## Install

Copy `guard.py` into your repo. That's the whole install.

```bash
python guard.py init          # writes .guard.json
# edit .guard.json: put your real verification commands in "claims"
python guard.py verify        # exit 0 = clear, exit 1 = blocked
```

No pip install. No network call except the URLs you put in `targets`.

## Configure

```json
{
  "targets": ["./dist/bundle.js", "https://your-site.com/health"],
  "reports": ["DELIVERY.md"],
  "claims": [
    {"claim": "tests pass", "run": "python run_tests.py", "expect_exit": 0},
    {"claim": "build ok",   "run": "npm run build",     "expect_exit": 0, "timeout_s": 300}
  ]
}
```

`claims` is the heart of it. Anything you would tell a client must be written
here as a command that proves or disproves it.

## Wire it into your agent

`hooks/claude_settings.json` is a ready-made PreToolUse/Stop hook config for
Claude Code. Drop it into `.claude/settings.json` and the guard runs before your
agent is allowed to declare completion. `AGENTS.md` is the matching instruction
file for the agent itself, so it knows the gate exists and stops guessing.

## What it does NOT do

Stated plainly, because a tool that oversells is worth nothing:

- It does **not** judge whether your code is semantically correct. It judges
  whether your *claims* survive execution.
- It does **not** replace tests. It replaces the habit of reporting tests you
  never ran.
- Network unreachable is reported as `UNKNOWN`, never as `FAIL`. Treating a
  firewall as a bug is the single most common false positive in this category.

## Why trust it

The author runs it on real client delivery. In one session it caught a cleanup
script that printed "deleted 58.8 MB" while the files were still on disk, because
the delete call was wrapped in a silent-error flag. The command returned success.
The files were untouched. That is exactly the failure mode this tool exists for,
and it was found by this tool, not by a human reading logs.

## License

Commercial single-team license. See `LICENSE`. Redistribution of the source as a
competing product is not permitted.
