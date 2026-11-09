def test_process_returns_ok():
    from app.handler import process
    r = process({"id": 1})
    assert r["ok"] is True

def test_size_nonzero():
    from app.handler import process
    r = process({"id": 2})
    assert r["size"] > 0, "config 根本没读到，size 恒为 0"
