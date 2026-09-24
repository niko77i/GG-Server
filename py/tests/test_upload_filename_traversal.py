# -*- coding: utf-8 -*-
"""上传文件名的路径穿越 —— 3 个端点 + 对照行。

背景（2026-09-24 加固）：werkzeug 的 `FileStorage.filename` 原样携带客户端给的
字符串，可含 `../` / `..\\`。3 个端点把它直接 join 进路径，于是可以写到目标
目录之外。修复前用 Flask test client 实测的基线：

  /api/fonts/upload        → 200，文件落在 `temp/_travprobe/x.ttf`（fonts/ 之外）
  /api/video/upload-music  → 200，文件落在 `temp/_travprobe/x.mp3`（music/ 之外）
  /api/audio-replace       → ffmpeg argv 里的输出路径归一化后为
                             `temp/_travprobe/x_new.mp4`（audio_replace/ 之外）

统一收口在 `main._safe_upload_name`。**每条越界断言都配了对照行** —— 只断言
「越界失败」的测试，在「端点整个坏掉」时同样是绿的。
"""
import os
import shutil
import tempfile

import pytest

import main


def _escapes(target_dir, tmp_path, name, sep="/"):
    """从 target_dir 绕到 tmp_path 的相对路径。"""
    rel = os.path.relpath(str(tmp_path), target_dir)
    # 非空转守卫：rel 若不含 `..`，说明目标目录就在自己内部，这条"穿越"
    # 用例根本没在测穿越 —— 会静默变成假绿。
    assert rel.startswith(os.pardir), "未构造出穿越路径：%r" % rel
    return rel.replace(os.sep, sep) + sep + name


# ---------------- /api/fonts/upload ----------------

def test_fonts_upload_traversal_blocked(client, auth_headers, tmp_path, monkeypatch):
    """`../` 文件名不得把字体写到 _FONTS_DIR 之外。"""
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    monkeypatch.setattr(main, "_FONTS_DIR", str(fonts_dir))

    evil = tmp_path / "evil.ttf"
    fn = _escapes(str(fonts_dir), tmp_path, "evil.ttf")
    client.post("/api/fonts/upload",
                data={"files": (open(__file__, "rb"), fn)},
                headers=auth_headers, content_type="multipart/form-data")

    assert not evil.is_file(), "❌ 越出 _FONTS_DIR 落盘：%s" % evil


def test_fonts_upload_normal_name_still_works(client, auth_headers, tmp_path, monkeypatch):
    """对照行：合法文件名（含中文、含空格）必须照常落在 _FONTS_DIR 内。

    这条防的是「用 secure_filename 修穿越」——那会把中文名整段滤掉，
    把好功能改坏。故中文名是必测的对照行。
    """
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    monkeypatch.setattr(main, "_FONTS_DIR", str(fonts_dir))

    for fn in ("MyFont.ttf", "中文字体.otf", "with space.ttc"):
        r = client.post("/api/fonts/upload",
                        data={"files": (open(__file__, "rb"), fn)},
                        headers=auth_headers, content_type="multipart/form-data")
        assert r.status_code == 200, r.get_json()
        assert (fonts_dir / fn).is_file(), "对照行应正常落盘：%s" % fn


# ---------------- /api/video/upload-music ----------------

def test_music_upload_traversal_blocked(client, auth_headers, tmp_path, monkeypatch):
    """`../` 文件名不得把音乐写到 _MUSIC_DIR 之外。"""
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    monkeypatch.setattr(main, "_MUSIC_DIR", str(music_dir))

    evil = tmp_path / "evil.mp3"
    fn = _escapes(str(music_dir), tmp_path, "evil.mp3")
    client.post("/api/video/upload-music",
                data={"file": (open(__file__, "rb"), fn)},
                headers=auth_headers, content_type="multipart/form-data")

    assert not evil.is_file(), "❌ 越出 _MUSIC_DIR 落盘：%s" % evil


def test_music_upload_normal_name_still_works(client, auth_headers, tmp_path, monkeypatch):
    """对照行：合法中文音乐名必须照常落在 _MUSIC_DIR 内。"""
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    monkeypatch.setattr(main, "_MUSIC_DIR", str(music_dir))

    fn = "背景音乐.mp3"
    r = client.post("/api/video/upload-music",
                    data={"file": (open(__file__, "rb"), fn)},
                    headers=auth_headers, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert (music_dir / fn).is_file(), "对照行应正常落盘"


# ---------------- /api/audio-replace ----------------

def _capture_ffmpeg_output(client, auth_headers, monkeypatch, video_name):
    """拦下 subprocess.run，只取它拿到的 output_path（不真跑 ffmpeg）。"""
    captured = {}

    class _R:
        returncode = 1
        stderr = "(stub)"

    def _fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)
        return _R()

    monkeypatch.setattr(main.subprocess, "run", _fake_run)
    client.post("/api/audio-replace",
                data={"video": (open(__file__, "rb"), video_name),
                      "audio": (open(__file__, "rb"), "a.mp3")},
                headers=auth_headers, content_type="multipart/form-data")
    cmd = captured.get("cmd") or []
    return cmd[-1] if cmd else ""


def _audio_replace_tmp_dir():
    return os.path.abspath(os.path.join(os.path.dirname(main.__file__),
                                        "..", "temp", "audio_replace"))


@pytest.fixture
def same_drive_scratch():
    """与 _audio_replace_tmp_dir 同盘的临时目录。

    不能用 pytest 的 `tmp_path`：它在 C: 盘，而本项目在 D: 盘 ——
    跨盘 `os.path.relpath` 直接抛 ValueError（实测），造不出穿越路径。
    """
    d = tempfile.mkdtemp(dir=os.path.dirname(_audio_replace_tmp_dir()),
                         prefix="_travprobe_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_audio_replace_output_stays_inside_tmp(client, auth_headers, monkeypatch,
                                               same_drive_scratch):
    """`../` 视频名不得让 ffmpeg 的输出落到 temp/audio_replace/ 之外。

    该路径不只进 ffmpeg 的 argv，还进 audio_replace_history 表与签名下载 URL，
    所以越界的影响面比前两个端点大。
    """
    fn = _escapes(_audio_replace_tmp_dir(), same_drive_scratch, "evil.mp4")
    out = _capture_ffmpeg_output(client, auth_headers, monkeypatch, fn)
    assert out, "未捕获到 ffmpeg 调用 —— 断言会退化成假绿"
    normal = os.path.normpath(out.replace("/", os.sep))
    assert os.path.dirname(normal) == os.path.normpath(_audio_replace_tmp_dir()), \
        "❌ 输出路径已越出 temp/audio_replace/：%s" % normal


def test_audio_replace_output_normal_name_still_works(client, auth_headers, monkeypatch):
    """对照行：合法中文视频名必须仍产生 <原名>_new.<ext>，且落在 tmp_dir 内。"""
    out = _capture_ffmpeg_output(client, auth_headers, monkeypatch, "原视频.mp4")
    assert out, "未捕获到 ffmpeg 调用 —— 断言会退化成假绿"
    normal = os.path.normpath(out.replace("/", os.sep))
    assert os.path.dirname(normal) == os.path.normpath(_audio_replace_tmp_dir())
    assert os.path.basename(normal) == "原视频_new.mp4", normal


# ---------------- helper 自身的边界 ----------------

def test_safe_upload_name_edges():
    """`.` / `..` / 空 / 纯目录 都必须收敛成 ""（而非父目录或空串 join）。"""
    assert main._safe_upload_name("") == ""
    assert main._safe_upload_name(None) == ""
    assert main._safe_upload_name(".") == ""
    assert main._safe_upload_name("..") == ""
    assert main._safe_upload_name("../..") == ""
    assert main._safe_upload_name("a/..") == ""
    assert main._safe_upload_name("  ") == ""
    # 正常名保留（含中文与空格）
    assert main._safe_upload_name("背景 音乐.mp3") == "背景 音乐.mp3"
    assert main._safe_upload_name("..\\..\\x\\y.png") == "y.png"
    assert main._safe_upload_name("/abs/path/z.ttf") == "z.ttf"
