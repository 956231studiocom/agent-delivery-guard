import json


class ConfigError(Exception):
    """配置读不到时必须显式失败，不许静默返回空。"""


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def process(job):
    try:
        cfg = load_config("config.json")
    except (OSError, ValueError) as e:
        raise ConfigError("config.json 不可读: %s" % e)
    return {"ok": True, "size": len(cfg), "job": job.get("id")}
