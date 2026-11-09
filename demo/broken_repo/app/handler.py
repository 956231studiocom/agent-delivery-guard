def load_config(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        pass
    return ""

def process(job):
    data = load_config("config.json")
    return {"ok": True, "size": len(data)}
