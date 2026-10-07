"""测试 utils.py 公共函数 — chunk 分块。"""
import os
import sys

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

from utils import chunk, CHUNK_SIZE  # noqa: E402


class TestChunk:
    def test_empty_returns_empty_list(self):
        assert chunk([]) == []

    def test_single_small_sequence_is_one_part(self):
        assert chunk([1, 2, 3]) == [[1, 2, 3]]

    def test_exact_multiple_has_no_trailing_empty_part(self):
        """900 个元素应恰好切成 1 段，不能多出空段。"""
        assert chunk(list(range(900)), size=900) == [list(range(900))]

    def test_boundary_901_splits_into_two(self):
        parts = chunk(list(range(901)), size=900)
        assert [len(p) for p in parts] == [900, 1]

    def test_multiple_parts_preserve_order(self):
        parts = chunk(list(range(1800)), size=900)
        assert [len(p) for p in parts] == [900, 900]
        assert parts[0][0] == 0
        assert parts[1][0] == 900

    def test_default_size_uses_module_constant(self):
        assert CHUNK_SIZE == 900
        assert chunk(list(range(901)))[0] == list(range(900))

    def test_accepts_tuple_and_generator(self):
        assert chunk((1, 2, 3)) == [[1, 2, 3]]
        assert chunk(x for x in range(3)) == [[0, 1, 2]]

    def test_monkeypatchable_size_for_guard_tests(self, monkeypatch):
        """其它任务的守卫测试靠改 CHUNK_SIZE 来证明调用点真的走了 chunk。"""
        import utils
        monkeypatch.setattr(utils, "CHUNK_SIZE", 3)
        assert utils.chunk(list(range(7))) == [[0, 1, 2], [3, 4, 5], [6]]
