# -*- coding: utf-8 -*-
"""一次性探针（跑完即删，不属套件）：独立复现 MEDIUM-1「改回曾用显示名被自己的旧目录拦住」。

用 pytest + tests/conftest.py 的 client fixture（放 temp/ 下拿不到 fixture）。
运行：python -m pytest tests/_probe_hist_dn.py -q -s
"""
import os
import shutil

import auth
import database
from test_scrape_ownership import _create_user


def test_probe_former_display_name_self_lock(client):
    h, uid = _create_user(client, "hist_a")
    root = auth._scrape_root()
    print("\n_scrape_root =", root)

    made = []
    try:
        # 1) 显示名设为 老王
        r1 = client.put("/api/auth/profile", json={"display_name": "老王"}, headers=h)
        print("[1] 设为 老王 ->", r1.status_code)

        # 2) 造出该目录（判据 3 只对**已存在**的目录生效）
        d = os.path.join(root, "老王")
        os.makedirs(os.path.join(d, "SomePkg"), exist_ok=True)
        made.append(d)
        print("[2] 建目录", d, "->", os.path.isdir(d))

        # 3) 改名 老李（腾出 老王）
        r2 = client.put("/api/auth/profile", json={"display_name": "老李"}, headers=h)
        print("[3] 改名 老李 ->", r2.status_code)

        # 3b) 对照行：目录「老李」存在时，把显示名**再设一次 老李**必须放行
        #     —— 证明判据 3 不是无差别拒绝
        d2 = os.path.join(root, "老李")
        os.makedirs(os.path.join(d2, "P"), exist_ok=True)
        made.append(d2)
        r2b = client.put("/api/auth/profile", json={"display_name": "老李"}, headers=h)
        print("[3b] 对照：重复设 老李（目录已存在，但是自己的） ->", r2b.status_code)
        assert r2b.status_code == 200, "对照行失败：判据 3 变成无差别拒绝了"

        # 4) 改回 老王（自己的旧目录）—— 应当放行
        r3 = client.put("/api/auth/profile", json={"display_name": "老王"}, headers=h)
        print("[4] 改回 老王 ->", r3.status_code, r3.get_json())
        print("\n判据：若 [3b] 200 而 [4] 400，则「曾用显示名自锁」成立"
              "（同一用户的旧目录，别人不占，却永远回不去）。")
        assert r3.status_code == 400, (
            f"未复现：改回曾用名返回 {r3.status_code}，与 MEDIUM-1 的描述不符"
        )
    finally:
        for d in made:
            shutil.rmtree(d, ignore_errors=True)
        db = database.get_db()
        db.execute("DELETE FROM users WHERE username = 'hist_a'")
        db.commit()
        db.close()
