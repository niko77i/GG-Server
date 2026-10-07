"""验证既有 `IN (...)` 调用点真的走了 utils.chunk。

手法：把**消费模块**里的 `chunk` 名字换成一个「强制每段 3 个元素」的记录器，
再用 10 个 id 调端点。10 个 id 在真实 CHUNK_SIZE=900 下只会产生 1 段，
所以**必须**让 spy 强行切成 4 段 —— 否则「调用点压根没分块」和「分块了但只有
一段」这两种情况在断言上无法区分，测试会对真正的失效完全失明。
"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

# 消费 `chunk` 的模块名。必须打**这些模块**的名字，不能打 `utils.chunk` ——
# main.py 用的是 `from utils import chunk`，那是模块级的独立名字绑定，
# 改 utils 里那个对 main.chunk 没有任何影响（这正是本测试要防的
# 「以为分块了其实没有」）。
_CHUNK_CONSUMERS = ("main", "huguan_dashboard")


class _ChunkSpy:
    """记录 chunk 调用，并把每段强制压到 3 个元素。"""

    def __init__(self, monkeypatch):
        self.calls = []
        patched = []

        def spy(seq, size=None):
            items = list(seq)
            self.calls.append(len(items))
            return [items[i:i + 3] for i in range(0, len(items), 3)]

        for name in _CHUNK_CONSUMERS:
            mod = sys.modules.get(name)
            if mod is not None and hasattr(mod, "chunk"):
                monkeypatch.setattr(mod, "chunk", spy, raising=True)
                patched.append(name)
        assert patched, "没有任何消费模块被装上 spy —— 说明导入还没加"

    @property
    def was_used(self):
        """至少有一次分块调用，且输入长度超过了 spy 的段长 3。"""
        return any(n > 3 for n in self.calls)


def test_batch_lookup_uses_chunk(app, client, auth_headers, monkeypatch):
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]
    ids = [f"look{i:04d}" for i in range(10)]
    for aid in ids:
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
                   (aid, aid, uid))
    db.commit()
    db.close()

    spy = _ChunkSpy(monkeypatch)
    resp = client.post("/api/accounts/batch-lookup",
                       json={"account_ids": ids}, headers=auth_headers)
    assert resp.status_code == 200
    # 分块后必须把 4 段结果**合并**，不能只返回最后一段 —— 这是改写时最易犯的错。
    assert len(resp.get_json()["found"]) == 10
    assert spy.was_used, "batch-lookup 没有走 chunk"


def test_batch_lookup_chunk_results_are_merged(app, client, auth_headers, monkeypatch):
    """分块后结果必须合并：断言总数，能抓住「只返回最后一段」的写法。"""
    import database
    db = database.get_db()
    uid = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()["id"]
    ids = [f"m{i:04d}" for i in range(10)]
    for aid in ids:
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)",
                   (aid, aid, uid))
    db.commit()
    db.close()

    _ChunkSpy(monkeypatch)
    body = client.post("/api/accounts/batch-lookup",
                       json={"account_ids": ids}, headers=auth_headers).get_json()
    assert len(body["found"]) == 10
    assert body["not_found"] == []


def test_huguan_collect_rows_uses_chunk(app, monkeypatch):
    """collect_rows_for_push 的 IN（huguan_dashboard.py 约 1331）。"""
    import database
    import huguan_dashboard as hd
    db = database.get_db()
    db.execute("INSERT OR IGNORE INTO users(id, username, password, role) VALUES(1,'dev','x','developer')")
    for i in range(10):
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,1)",
                   (f"acc{i}", f"hd{i:04d}"))
    db.commit()

    spy = _ChunkSpy(monkeypatch)
    rows = hd.collect_rows_for_push(db, "gg", [f"hd{i:04d}" for i in range(10)])
    db.close()

    # 必须回全部 10 行，不是最后一段的 1 行。
    assert len(rows) == 10
    assert spy.was_used, "collect_rows_for_push 没有走 chunk"
