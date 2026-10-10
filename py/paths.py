"""temp/ 下的目录布局 —— 只固定「在 data_root 之下怎么摆」。

**刻意不解析根目录**：`main._DATA_ROOT`（分打包/开发模式）、
`database._db_path()`、`logging_setup._data_root()` 各自解析，
`auth._scrape_root()` 更是刻意独立推导（见 auth.py 顶部注释：与
database 同惯例、由一条测试断言钉住一致性，防路径漂移）。

本模块被上述几处共同 import，因此**不得**依赖 main / database / auth
中任何一个 —— 否则引入导入期循环依赖。只允许依赖标准库。

改目录布局时只改这里；根解析仍留在各调用方。
"""
import os

TEMP_DIRNAME = "temp"
DATA_DIRNAME = "data"


def temp_dir(data_root: str) -> str:
    """temp 目录：`<data_root>/temp`。"""
    return os.path.join(data_root, TEMP_DIRNAME)


def data_dir(data_root: str) -> str:
    """运行时数据根：`<data_root>/temp/data`。

    原来的运行时路径直接摆在 `<data_root>/temp` 下，与一次性草稿混在一起；
    2026-10-07 归类后统一收进 `temp/data/`，草稿收进 `temp/scratch/`。
    """
    return os.path.join(temp_dir(data_root), DATA_DIRNAME)
