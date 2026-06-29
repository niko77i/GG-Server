import os
import subprocess
import sys
import webbrowser

# 确保当前目录优先于 site-packages（解决 py 包名冲突）
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from scraper import scrape_images, scrape_logo, ScrapeError
from resizer import process_image, save_logo, ResizeError
from utils import extract_package_name, natural_sort_key
from video_processor import VideoTask, VideoError
from ai_service import get_provider, AIServiceError
import database

from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity, create_access_token, create_refresh_token
import json
import auth
import data_service
import datetime
from functools import wraps
# google_ads_service 按需加载，不打包进 EXE

# 判断是否为 PyInstaller 打包模式
_FROZEN = getattr(sys, "frozen", False)

if _FROZEN:
    # 打包后所有静态文件在 sys._MEIPASS 下的 dist/ 目录
    _dist_dir = os.path.join(sys._MEIPASS, "dist")
    if os.path.isdir(_dist_dir):
        _FRONTEND_DIR = _dist_dir
    else:
        _FRONTEND_DIR = sys._MEIPASS  # 回退
    # 数据目录固定在 EXE 所在目录（而非临时解压目录）
    _DATA_ROOT = os.path.dirname(sys.executable)
else:
    # 开发模式：优先用 frontend/dist/（生产构建），否则回退旧目录
    _dist_dir = os.path.join(os.path.dirname(_current_dir), "frontend", "dist")
    if os.path.isdir(_dist_dir):
        _FRONTEND_DIR = _dist_dir
    else:
        _FRONTEND_DIR = os.path.dirname(_current_dir)  # 回退到旧前端文件
    _DATA_ROOT = os.path.dirname(_current_dir)

app = Flask(__name__, static_folder=_FRONTEND_DIR, static_url_path="")
CORS(app)

# --- 请求日志 ---
import time as _time

@app.before_request
def _log_request():
    """记录请求开始时间。"""
    request._start_time = _time.time()

@app.after_request
def _log_response(response):
    """打印请求日志，格式类似 ImageCrawling。"""
    duration = (_time.time() - getattr(request, '_start_time', _time.time())) * 1000
    qs = request.query_string.decode("utf-8", errors="replace")
    url = request.path + (f"?{qs}" if qs else "")
    method = request.method
    status = response.status_code
    # 日志格式：[时间] 方法 /路径?参数 → 状态码 (耗时ms)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {method} {url} → {status} ({duration:.0f}ms)")
    return response

# --- GG-Server: Config ---
import json
_CONFIG_PATH = os.path.join(os.path.dirname(_current_dir), "config", "config.json")
try:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        APP_CONFIG = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    print("[WARN] config.json not found, using defaults")
    APP_CONFIG = {}

app.config["JWT_SECRET_KEY"] = APP_CONFIG.get("secret_key", "gg-server-default-secret")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = APP_CONFIG.get("jwt_expire_hours", 24) * 3600
jwt = JWTManager(app)

import auth
try:
    auth.init_developer(APP_CONFIG)
except Exception as e:
    print(f"[WARN] Developer init failed: {e}")

# 视频生成任务存储
_video_tasks: dict[str, VideoTask] = {}


def _get_ffmpeg_path() -> str:
    """获取 FFmpeg 可执行文件路径。打包模式从 MEIPASS 加载，开发模式查 PATH。"""
    if _FROZEN:
        bundled = os.path.join(sys._MEIPASS, "ffmpeg.exe")
        if os.path.isfile(bundled):
            return bundled
    import shutil
    path = shutil.which("ffmpeg")
    if path:
        return path
    # 开发模式常见位置
    for p in [
        os.path.join(os.path.dirname(_current_dir), "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return "ffmpeg"


# ---------- 前端页面 ----------

@app.route("/")
def index():
    """返回前端页面。"""
    return send_from_directory(_FRONTEND_DIR, "index.html")


@app.errorhandler(404)
def spa_fallback(e):
    """API 404 返回 JSON，其余返回 index.html（SPA 路由）。"""
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Not found"}), 404
    # 如果请求的静态文件确实不存在，返回 404
    full_path = os.path.join(_FRONTEND_DIR, request.path.lstrip("/"))
    if os.path.isfile(full_path):
        return send_from_directory(_FRONTEND_DIR, request.path.lstrip("/"))
    # SPA 回退
    return send_from_directory(_FRONTEND_DIR, "index.html")


# ---------- API ----------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/scrape", methods=["POST"])
def scrape():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    url = data.get("url", "").strip()
    save_dir = data.get("save_dir", "").strip()
    # 新增参数：是否按 Google Ads 规格放大图片（默认 true，向后兼容）
    include_ads_images = data.get("include_ads_images", True)

    if not url:
        return jsonify({"success": False, "error": "URL 不能为空"}), 400
    if not save_dir:
        return jsonify({"success": False, "error": "保存路径不能为空"}), 400

    # 1. 提取包名
    try:
        pkg_name = extract_package_name(url)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    # 2. 创建保存目录
    pkg_dir = os.path.join(save_dir, pkg_name)

    # 检查是否已有本地文件，有则直接返回（跳过爬取）
    if os.path.isdir(pkg_dir):
        local_pngs = [f for f in os.listdir(pkg_dir)
                      if f.lower().endswith(".png") and os.path.isfile(os.path.join(pkg_dir, f))]
        if local_pngs:
            results = []
            for f in sorted(local_pngs):
                fp = os.path.join(pkg_dir, f)
                try:
                    from PIL import Image
                    with Image.open(fp) as img:
                        w, h = img.size
                    results.append({"filename": f, "width": w, "height": h, "local": True})
                except Exception:
                    results.append({"filename": f, "width": 0, "height": 0, "local": True})
            # 检查本地 logo
            logo = None
            logo_dir = os.path.join(pkg_dir, "包logo")
            if os.path.isdir(logo_dir):
                for lf in sorted(os.listdir(logo_dir)):
                    if lf.lower().endswith(".png") and "_logo" in lf.lower():
                        fp = os.path.join(logo_dir, lf)
                        try:
                            with Image.open(fp) as img:
                                logo = {"filename": lf, "width": img.width, "height": img.height}
                        except Exception:
                            logo = {"filename": lf, "width": 0, "height": 0}
                        break
            return jsonify({
                "success": True,
                "package_name": pkg_name,
                "saved_path": pkg_dir,
                "image_count": len(results),
                "images": results,
                "logo": logo,
                "from_cache": True,
            })

    try:
        os.makedirs(pkg_dir, exist_ok=True)
    except OSError as e:
        return jsonify({"success": False, "error": f"无法创建目录: {e}"}), 500

    response = {
        "success": True,
        "package_name": pkg_name,
        "saved_path": pkg_dir,
    }

    # ---- 3a. Logo 爬取（始终执行） ----
    try:
        logo_url = scrape_logo(url)
        if logo_url:
            logo_dir = os.path.join(pkg_dir, "包logo")
            try:
                os.makedirs(logo_dir, exist_ok=True)
                logo_result = save_logo(logo_url, logo_dir, f"{pkg_name}_logo")
                response["logo"] = logo_result
            except (ResizeError, OSError):
                response["logo"] = None
        else:
            response["logo"] = None
    except Exception:
        response["logo"] = None

    # ---- 3b. 广告图片爬取（始终执行） ----
    try:
        img_urls = scrape_images(url)
    except ScrapeError as e:
        response["image_count"] = 0
        response["images"] = []
        if response["logo"] is None:
            return jsonify({"success": False, "error": str(e)}), 500
        # 有 logo 但广告图爬取失败 — 部分成功
        response["success"] = True
        return jsonify(response)

    if not img_urls:
        response["image_count"] = 0
        response["images"] = []
        if response["logo"] is None:
            return jsonify({"success": False, "error": "该页面未找到图片"}), 404
    else:
        results = []
        # 不勾选时跳过 Google Ads 规格缩放，保留原图
        skip_scaling = not include_ads_images
        for i, img_url in enumerate(img_urls):
            try:
                result = process_image(img_url, pkg_dir, f"{pkg_name}_{i+1:03d}", skip_scaling=skip_scaling)
                results.append(result)
            except ResizeError:
                continue
        response["image_count"] = len(results)
        response["images"] = results

    return jsonify(response)


# ---------- 视频 API ----------


@app.route("/api/video/scan-dir", methods=["POST"])
def video_scan_dir():
    """扫描目录，返回 PNG 图片列表和 logo 信息。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    dir_path = (data.get("dir") or "").strip()
    if not dir_path or not os.path.isdir(dir_path):
        return jsonify({"success": False, "error": "目录不存在或不可访问"}), 400

    images = []
    from PIL import Image
    for root, dirs, files in os.walk(dir_path):
        for f in sorted(files):
            if not f.lower().endswith(".png"):
                continue
            full = os.path.join(root, f)
            try:
                with Image.open(full) as img:
                    # 相对于扫描目录的路径，含子目录名
                    rel = os.path.relpath(full, dir_path)
                    images.append({
                        "filename": rel,
                        "path": full.replace("\\", "/"),
                        "width": img.width,
                        "height": img.height,
                    })
            except Exception:
                pass

    if not images:
        return jsonify({"success": False, "error": "目录中无有效的 PNG 图片"}), 404

    # 检测 logo（包logo/ 子目录中的 _logo.png 文件）
    logo = None
    logo_dir = os.path.join(dir_path, "包logo")
    if os.path.isdir(logo_dir):
        for f in sorted(os.listdir(logo_dir)):
            if f.lower().endswith(".png") and "_logo" in f.lower():
                full = os.path.join(logo_dir, f)
                try:
                    from PIL import Image
                    with Image.open(full) as img:
                        logo = {
                            "filename": f,
                            "path": full.replace("\\", "/"),
                            "width": img.width,
                            "height": img.height,
                        }
                except Exception:
                    pass
                break

    pkg_name = os.path.basename(dir_path.rstrip("/\\"))

    return jsonify({
        "success": True,
        "package_name": pkg_name,
        "images": images,
        "logo": logo,
    })


@app.route("/api/image", methods=["GET"])
def serve_image():
    """返回本地图片文件流，供前端缩略图加载。"""
    path = request.args.get("path", "")
    if not path:
        return "", 400

    # 安全检查
    normalized = os.path.normpath(path)
    if not os.path.isfile(normalized) or not normalized.lower().endswith(".png"):
        return "", 404

    from flask import send_file
    return send_file(normalized, mimetype="image/png", max_age=3600)


@app.route("/api/video/generate", methods=["POST"])
def video_generate():
    """提交视频生成任务（后台线程执行）。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    images = data.get("images") or []
    if data.get("random_order"):
        import random as _random
        _random.shuffle(images)
    settings = data.get("settings") or {}
    output_path = settings.get("output_path", "").strip()

    if not images:
        return jsonify({"success": False, "error": "请至少选择一张图片"}), 400
    if not output_path:
        return jsonify({"success": False, "error": "请输入输出路径"}), 400

    # 确保输出目录存在
    out_dir = os.path.dirname(output_path)
    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            return jsonify({"success": False, "error": f"无法创建输出目录: {e}"}), 400

    # 创建任务
    task = VideoTask(data)
    _video_tasks[task.task_id] = task

    # 后台线程执行
    import threading

    def _run():
        # 可选：AI 动态化
        ai = data.get("ai") or {}
        if ai.get("enabled") and ai.get("api_key"):
            ai_provider = None
            try:
                ai_provider = get_provider(ai.get("service", "doubao"))
            except AIServiceError as e:
                task.message = f"AI 服务初始化失败: {e}"

            if ai_provider:
                duration = int(ai.get("duration", 4))
                api_key = ai["api_key"]
                custom_prompt = ai.get("prompt") or None
                ai_videos = {}
                ai_temp_dir = os.path.join(_DATA_ROOT, "temp", "ai_videos")
                os.makedirs(ai_temp_dir, exist_ok=True)
                import shutil
                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _gen_one(idx, img_path):
                    try:
                        provider = get_provider(ai.get("service", "doubao"))
                        ai_video = provider.generate_video(img_path, duration, api_key, custom_prompt)
                        basename = os.path.splitext(os.path.basename(img_path))[0]
                        temp_path = os.path.join(ai_temp_dir, f"{basename}_ai.mp4")
                        shutil.move(ai_video, temp_path)
                        return (idx, img_path, temp_path, None)
                    except AIServiceError as e:
                        return (idx, img_path, None, str(e))
                    except Exception as e:
                        return (idx, img_path, None, str(e))

                task.message = f"AI 动态化: 并行生成 {len(images)} 段视频..."
                with ThreadPoolExecutor(max_workers=min(len(images), 3)) as executor:
                    futures = {executor.submit(_gen_one, i, p): i for i, p in enumerate(images)}
                    completed = 0
                    for future in as_completed(futures):
                        idx, img_path, saved_path, err = future.result()
                        completed += 1
                        task.progress = completed / len(images) * 0.5
                        if saved_path:
                            ai_videos[img_path] = saved_path
                            task.message = f"AI 动态化: {completed}/{len(images)} 完成"
                        else:
                            task.message = f"AI 动态化: {completed}/{len(images)} (1 段降级)"

                task.params["_ai_videos"] = ai_videos
            else:
                task.message = "AI 服务未就绪，跳过 AI 动态化"
        else:
            task.message = "未启用 AI，使用静态帧拼接"

        # 执行 FFmpeg
        task.run()

        # 清理 temp 中的 AI 视频（_ai_videos 中的副本保留）
        ai_videos = task.params.get("_ai_videos", {})
        for tmp_path in ai_videos.values():
            try:
                os.remove(tmp_path)
            except OSError:
                pass


    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return jsonify({
        "success": True,
        "task_id": task.task_id,
        "message": "视频生成已开始",
    }), 202


@app.route("/api/video/progress", methods=["GET"])
def video_progress():
    """查询视频生成任务进度。"""
    task_id = request.args.get("task_id", "")
    task = _video_tasks.get(task_id)
    if task is None:
        return jsonify({"success": False, "error": "未知任务 ID"}), 404

    resp = {
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
    }
    if task.status == "completed":
        resp["output"] = task.result()
    elif task.status == "error":
        resp["error"] = task.message
    return jsonify(resp)


# ---------- 音频替换 API ----------


@app.route("/api/audio-replace", methods=["POST"])
def audio_replace():
    """替换视频的音频轨道。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    video_path = (data.get("video_path") or "").strip()
    audio_source = (data.get("audio_source") or "").strip()

    if not video_path or not os.path.isfile(video_path):
        return jsonify({"success": False, "error": "原视频文件不存在"}), 400
    if not audio_source or not os.path.isfile(audio_source):
        return jsonify({"success": False, "error": "音频源文件不存在"}), 400

    # 输出路径：原视频同目录，文件名拼接 Music
    video_dir = os.path.dirname(video_path)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    ext = os.path.splitext(video_path)[1] or ".mp4"
    output_path = os.path.join(video_dir, f"{base_name}Music{ext}")

    # 确保输出目录存在
    try:
        os.makedirs(video_dir, exist_ok=True)
    except OSError as e:
        return jsonify({"success": False, "error": f"无法创建输出目录: {e}"}), 500

    ffmpeg = _get_ffmpeg_path()

    # 构建 FFmpeg 命令：替换音频轨道（FFmpeg 自动从视频提取音频）
    cmd = [
        ffmpeg, "-y",
        "-i", video_path.replace("\\", "/"),
        "-i", audio_source.replace("\\", "/"),
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", f"1:a:0",
        "-shortest",
        output_path.replace("\\", "/"),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            err_tail = result.stderr[-300:] if result.stderr else "(无输出)"
            return jsonify({
                "success": False,
                "error": f"FFmpeg 执行失败: {err_tail}",
            }), 500

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        return jsonify({
            "success": True,
            "output": output_path.replace("\\", "/"),
            "size_mb": round(size_mb, 1),
        })
    except FileNotFoundError:
        return jsonify({"success": False, "error": "未找到 FFmpeg"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "处理超时"}), 500


@app.route("/api/video/next-filename", methods=["POST"])
def video_next_filename():
    """检查输出路径是否存在，返回不冲突的文件名。"""
    data = request.get_json(silent=True) or {}
    output_path = (data.get("output_path") or "").strip()
    if not output_path:
        return jsonify({"success": False, "error": "路径不能为空"}), 400

    if not os.path.isfile(output_path):
        return jsonify({"success": True, "path": output_path.replace("\\", "/")})

    # 文件已存在，追加 _1, _2... 直到不冲突
    base = os.path.splitext(output_path)[0]
    ext = os.path.splitext(output_path)[1] or ".mp4"
    counter = 1
    while True:
        new_path = f"{base}_{counter}{ext}"
        if not os.path.isfile(new_path):
            return jsonify({"success": True, "path": new_path.replace("\\", "/")})
        counter += 1


# ---------- 视频设置历史 API ----------

_VIDEO_HISTORY_DIR = os.path.join(_DATA_ROOT, "temp", "video_set")


def _history_file(pkg: str) -> str:
    safe = pkg.replace("\\", "/").replace("..", "").strip("/")
    return os.path.join(_VIDEO_HISTORY_DIR, f"{safe}.json")


def _load_pkg_history(pkg: str) -> list:
    fp = _history_file(pkg)
    if os.path.isfile(fp):
        try:
            import json
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_pkg_history(pkg: str, entries: list):
    os.makedirs(_VIDEO_HISTORY_DIR, exist_ok=True)
    import json
    with open(_history_file(pkg), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _list_packages() -> list[str]:
    os.makedirs(_VIDEO_HISTORY_DIR, exist_ok=True)
    pkgs = []
    for f in sorted(os.listdir(_VIDEO_HISTORY_DIR)):
        if f.endswith(".json"):
            pkgs.append(f[:-5])  # 去掉 .json
    return pkgs


@app.route("/api/video/history/save", methods=["POST"])
def video_history_save():
    """保存当前视频生成设置到对应包的历史文件。"""
    data = request.get_json(silent=True) or {}
    entry = data.get("entry") or {}
    if not entry:
        return jsonify({"success": False, "error": "无数据"}), 400
    import datetime
    entry["saved_at"] = datetime.datetime.now().strftime("%m-%d %H:%M")
    # 按包名分组
    video_dir = (entry.get("videoDir") or "").strip()
    pkg = os.path.basename(video_dir.rstrip("/\\")) if video_dir else "_uncategorized"
    entries = _load_pkg_history(pkg)
    entries.insert(0, entry)
    if len(entries) > 30:
        entries = entries[:30]
    _save_pkg_history(pkg, entries)
    return jsonify({"success": True, "pkg": pkg, "count": len(entries)})


@app.route("/api/video/history/list", methods=["GET"])
def video_history_list():
    """按包名分组返回所有历史。"""
    result = {}
    for pkg in _list_packages():
        result[pkg] = _load_pkg_history(pkg)
    return jsonify({"success": True, "packages": result})


@app.route("/api/video/history/delete", methods=["POST"])
def video_history_delete():
    """删除指定包或包内指定索引的条目。"""
    data = request.get_json(silent=True) or {}
    pkg = (data.get("pkg") or "").strip()
    indices = data.get("indices")  # None=删整个包, list=删指定条目

    if not pkg:
        return jsonify({"success": False, "error": "未指定包名"}), 400

    if indices is None:
        # 删除整个包文件
        fp = _history_file(pkg)
        if os.path.isfile(fp):
            os.remove(fp)
        return jsonify({"success": True})

    # 删除指定条目
    entries = _load_pkg_history(pkg)
    for i in sorted(indices, reverse=True):
        if 0 <= i < len(entries):
            entries.pop(i)
    if entries:
        _save_pkg_history(pkg, entries)
    else:
        os.remove(_history_file(pkg))
    return jsonify({"success": True})


# ---------- 字体管理 API ----------

# 字体存储目录（项目根目录下 fonts/）
_FONTS_DIR = os.path.join(_DATA_ROOT, "fonts")


def _scan_fonts_dir() -> list[dict]:
    """扫描字体目录，返回所有可用字体列表（最近使用排前）。"""
    fonts = []
    # 系统字体
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    sys_font_dir = os.path.join(system_root, "Fonts")
    sys_fonts = [
        ("simhei", "黑体", os.path.join(sys_font_dir, "simhei.ttf")),
        ("msyh", "微软雅黑", os.path.join(sys_font_dir, "msyh.ttc")),
        ("simsun", "宋体", os.path.join(sys_font_dir, "simsun.ttc")),
        ("arial", "Arial", os.path.join(sys_font_dir, "arial.ttf")),
    ]
    for fid, name, path in sys_fonts:
        if os.path.isfile(path):
            fonts.append({"id": fid, "name": name, "source": "system"})

    # 用户导入的字体
    if os.path.isdir(_FONTS_DIR):
        for f in sorted(os.listdir(_FONTS_DIR)):
            if f.lower().endswith((".ttf", ".otf", ".ttc", ".woff", ".woff2")):
                fid = os.path.splitext(f)[0]
                fonts.append({
                    "id": fid,
                    "name": fid.replace("_", " ").title(),
                    "source": "user",
                })

    # 读取最近使用记录，排在最前面
    recent_file = os.path.join(_FONTS_DIR, ".recent.json")
    recent = []
    try:
        import json
        if os.path.isfile(recent_file):
            with open(recent_file, "r") as rf:
                recent = json.load(rf) or []
    except Exception:
        pass

    # 创建 id→font 映射
    font_map = {f["id"]: f for f in fonts}
    # 最近使用排前面
    result = []
    for fid in recent:
        if fid in font_map:
            result.append(font_map.pop(fid))
    # 其余字体
    result.extend(font_map.values())
    return result


def _mark_font_used(font_id: str):
    """标记字体为最近使用。"""
    recent_file = os.path.join(_FONTS_DIR, ".recent.json")
    recent = []
    try:
        import json
        if os.path.isfile(recent_file):
            with open(recent_file, "r") as f:
                recent = json.load(f) or []
    except Exception:
        pass
    # 移到最前
    if font_id in recent:
        recent.remove(font_id)
    recent.insert(0, font_id)
    recent = recent[:20]
    with open(recent_file, "w") as f:
        json.dump(recent, f)


@app.route("/api/fonts/list", methods=["GET"])
def fonts_list():
    """返回所有可用字体（系统 + 用户导入）。"""
    return jsonify({"success": True, "fonts": _scan_fonts_dir()})

@app.route("/api/fonts/mark-used", methods=["POST"])
def fonts_mark_used():
    """标记字体为最近使用。"""
    data = request.get_json(silent=True) or {}
    font_id = (data.get("font") or "").strip()
    if font_id:
        _mark_font_used(font_id)
    return jsonify({"success": True})




@app.route("/api/fonts/preview", methods=["GET"])
def fonts_preview():
    """生成字体预览图片 — 排版精美的字体标本卡。"""
    font_id = request.args.get("font", "simhei")
    from io import BytesIO
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return "", 500

    # 加载字体
    font_path = _find_font_path(font_id)
    if not font_path:
        return "", 404
    try:
        display_font = ImageFont.truetype(font_path, 64)
        body_font = ImageFont.truetype(font_path, 26)
        caption_font = ImageFont.truetype(font_path, 16)
    except Exception:
        return "", 500

    # 画布 — 暖白底匹配浅色主题，留足呼吸空间
    W, H = 560, 210
    img = Image.new("RGB", (W, H), (254, 252, 249))
    draw = ImageDraw.Draw(img)

    # ---- 顶部强调色条 ----
    draw.rectangle([(0, 0), (W, 3)], fill=(212, 133, 10))

    # ---- 第一行：大字中文展示（标题级） ----
    draw.text((24, 16), "字体样张", font=display_font, fill=(30, 27, 24))

    # ---- 第二行：英文 + 数字 + 符号 —— 检验西文部分 ----
    draw.text((24, 90), "ABCDEFGHIJKLM  abcdefghijklm  0123456789", font=body_font, fill=(92, 86, 79))

    # ---- 分隔线 ----
    draw.line([(24, 128), (W - 24, 128)], fill=(218, 212, 202), width=1)

    # ---- 第三行：常用中文补充 + 字号标注 ----
    draw.text((24, 138), "永和九年岁在癸丑暮春之初会于会稽山阴之兰亭", font=body_font, fill=(60, 55, 48))

    # ---- 底部标签栏 ----
    draw.text((24, 178), f"← {font_id}  ·  64px / 26px / 16px", font=caption_font, fill=(160, 155, 148))

    # ---- 右下角装饰块 ----
    draw.rectangle([(W - 32, H - 32), (W, H)], fill=(250, 245, 237), outline=(212, 133, 10))

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype="image/png", max_age=0)


@app.route("/api/fonts/file/<font_id>", methods=["GET"])
def fonts_file(font_id):
    """将字体文件作为 Web 字体提供（供前端 CSS @font-face 使用）。"""
    font_path = _find_font_path(font_id)
    if not font_path:
        return "", 404
    from flask import send_file
    ext = os.path.splitext(font_path)[1].lower()
    mime_map = {".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2", ".ttc": "font/collection"}
    return send_file(font_path, mimetype=mime_map.get(ext, "application/octet-stream"), max_age=3600)


def _find_font_path(font_id: str) -> str | None:
    """根据字体 ID 查找完整路径。"""
    import platform
    system_root = os.environ.get("SystemRoot", r"C:\Windows")

    # 用户字体
    user_dir = os.path.join(_FONTS_DIR)
    if os.path.isdir(user_dir):
        for ext in (".ttf", ".otf", ".ttc", ".woff", ".woff2"):
            p = os.path.join(user_dir, f"{font_id}{ext}")
            if os.path.isfile(p):
                return p

    # 系统字体
    if platform.system() == "Windows":
        font_map = {"simhei": "simhei.ttf", "msyh": "msyh.ttc", "simsun": "simsun.ttc", "arial": "arial.ttf"}
        fn = font_map.get(font_id, f"{font_id}.ttf")
        p = os.path.join(system_root, "Fonts", fn)
        if os.path.isfile(p):
            return p

    return None


@app.route("/api/fonts/import", methods=["POST"])
def fonts_import():
    """导入字体文件到 fonts/ 目录。"""
    if not _is_local_request():
        return jsonify({"success": False, "error": "仅允许本机访问"}), 403

    data = request.get_json(silent=True) or {}
    source = (data.get("source") or "").strip()
    if not source:
        # 用多文件选择对话框
        sources = _multi_file_dialog("选择字体文件（可多选）")
        if not sources:
            return jsonify({"success": True, "imported": 0, "message": "未选择文件"})
    else:
        sources = [source]

    os.makedirs(_FONTS_DIR, exist_ok=True)
    imported = 0
    import shutil

    for sp in sources:
        sp = sp.replace("\\", "/")
        if os.path.isdir(sp):
            for root, dirs, files in os.walk(sp):
                for f in files:
                    if f.lower().endswith((".ttf", ".otf", ".ttc", ".woff", ".woff2")):
                        dst = os.path.join(_FONTS_DIR, f)
                        if not os.path.isfile(dst):
                            shutil.copy2(os.path.join(root, f), dst)
                        imported += 1
        elif os.path.isfile(sp) and sp.lower().endswith((".ttf", ".otf", ".ttc", ".woff", ".woff2")):
            dst = os.path.join(_FONTS_DIR, os.path.basename(sp))
            if not os.path.isfile(dst):
                shutil.copy2(sp, dst)
            imported += 1

    return jsonify({"success": True, "imported": imported, "fonts": _scan_fonts_dir()})



# ---------- YouTube 视频管理 API (SQLite) ----------

import re as _re
import sqlite3 as _sqlite3
import json as _json

def _yt_db():
    """返回统一数据库连接（temp/app.db），由 database.py 管理建表与迁移。"""
    return database.get_db()


def _extract_youtube_id(url: str):
    import re
    m = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/|m\.youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})', url)
    return m.group(1) if m else None


@app.route("/api/youtube/import", methods=["POST"])
@jwt_required()
def youtube_import():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    urls = data.get("urls") or []
    region = (data.get("region") or "通用").strip()
    frame_type = (data.get("frame_type") or "非融帧").strip()
    effectiveness = (data.get("effectiveness") or "").strip()
    product_name = (data.get("product_name") or "").strip()
    review_status = (data.get("review_status") or "能过审").strip()
    imported_at = (data.get("imported_at") or "").strip()  # 用户指定时间，为空则用当前时间
    is_public = data.get("is_public", 0)  # 0=私有, 1=公开
    if not urls:
        return jsonify({"success": False, "error": "请输入至少一个链接"}), 400

    db = _yt_db()
    imported = 0
    duplicates = []
    import datetime
    import requests as _req

    # 时间：用户指定优先，否则用当前时间
    if imported_at:
        ts = imported_at
    else:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    for url in urls:
        url = url.strip()
        if not url: continue
        vid = _extract_youtube_id(url)
        if not vid: continue
        existing = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
        if existing:
            duplicates.append(dict(existing))
            continue
        title = vid
        try:
            r = _req.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json", timeout=8)
            if r.status_code == 200:
                title = r.json().get("title", vid)
        except Exception: pass

        db.execute("INSERT INTO videos(id,url,title,region,frame_type,effectiveness,product_name,review_status,imported_at,owner_id,is_public) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (vid, f"https://www.youtube.com/watch?v={vid}", title, region, frame_type,
                    effectiveness, product_name, review_status,
                    ts, user_id, is_public))
        imported += 1

    db.commit(); db.close()
    return jsonify({"success": True, "imported": imported, "duplicates": duplicates})


@app.route("/api/youtube/list", methods=["GET"])
@jwt_required()
def youtube_list():
    user_id = int(get_jwt_identity())
    scope = request.args.get("scope", "all").strip()  # "public" | "private" | "all"
    region = request.args.get("region", "").strip()
    frame_type = request.args.get("frame_type", "").strip()
    effectiveness = request.args.get("effectiveness", "").strip()
    product_name = request.args.get("product_name", "").strip()
    review_status = request.args.get("review_status", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    uploader_id = request.args.get("uploader_id", "").strip()
    import datetime

    db = _yt_db()
    where = []; params = []

    # 按 scope 过滤
    if scope == "public":
        where.append("v.is_public = 1")
    elif scope == "private":
        where.append("v.owner_id = ?"); params.append(user_id)
    else:  # all
        where.append("(v.is_public = 1 OR v.owner_id = ?)"); params.append(user_id)

    for f, v in [("region", region), ("frame_type", frame_type), ("effectiveness", effectiveness), ("product_name", product_name)]:
        if v: where.append(f"v.{f}=?"); params.append(v)
    # 审核状态：默认筛选「能过审」，传空或"全部"则不过滤
    if review_status and review_status != "全部":
        where.append("v.review_status=?"); params.append(review_status)
    if from_date:
        where.append("v.imported_at >= ?"); params.append(from_date)
    if to_date:
        # to_date 为结束日期当天，需包含完整当天，故加一天用 < 比较
        try:
            dt = datetime.datetime.strptime(to_date, "%Y-%m-%d") + datetime.timedelta(days=1)
            where.append("v.imported_at < ?"); params.append(dt.strftime("%Y-%m-%d"))
        except ValueError:
            pass
    if uploader_id:
        where.append("v.owner_id = ?"); params.append(int(uploader_id))

    query = "SELECT v.*, u.display_name AS owner_display_name, u.username AS owner_username FROM videos v LEFT JOIN users u ON v.owner_id = u.id"
    if where: query += " WHERE " + " AND ".join(where)
    query += " ORDER BY CASE v.review_status WHEN '不能过审' THEN 1 ELSE 0 END, CASE v.effectiveness WHEN '成效' THEN 0 WHEN '一般' THEN 1 ELSE 2 END, v.imported_at DESC"

    rows = db.execute(query, params).fetchall()
    videos = [dict(r) for r in rows]

    counts = {"region": {}, "frame_type": {}, "effectiveness": {}, "product_name": {}, "review_status": {}, "uploader": {}}
    for v in videos:
        for field in ["region", "frame_type", "effectiveness", "product_name", "review_status"]:
            val = v.get(field, "") or ""
            if val: counts[field][val] = counts[field].get(val, 0) + 1
        # uploader 计数：用 owner_id 作为 key，存 display_name 和 count
        oid = v.get("owner_id")
        if oid:
            if oid not in counts["uploader"]:
                dname = v.get("owner_display_name") or v.get("owner_username") or f"用户{oid}"
                counts["uploader"][oid] = {"display_name": dname, "cnt": 0}
            counts["uploader"][oid]["cnt"] += 1

    db.close()
    return jsonify({"success": True, "videos": videos, "counts": counts})


@app.route("/api/youtube/dates", methods=["GET"])
@jwt_required()
def youtube_dates():
    """返回当前筛选条件下有视频的日期及数量，供日期选择器标记使用。"""
    user_id = int(get_jwt_identity())
    scope = request.args.get("scope", "all").strip()
    region = request.args.get("region", "").strip()
    frame_type = request.args.get("frame_type", "").strip()
    effectiveness = request.args.get("effectiveness", "").strip()
    product_name = request.args.get("product_name", "").strip()
    review_status = request.args.get("review_status", "").strip()
    uploader_id = request.args.get("uploader_id", "").strip()

    db = _yt_db()
    where = []; params = []
    if scope == "public":
        where.append("v.is_public = 1")
    elif scope == "private":
        where.append("v.owner_id = ?"); params.append(user_id)
    else:
        where.append("(v.is_public = 1 OR v.owner_id = ?)"); params.append(user_id)
    for f, v in [("region", region), ("frame_type", frame_type), ("effectiveness", effectiveness), ("product_name", product_name)]:
        if v: where.append(f"v.{f}=?"); params.append(v)
    if review_status and review_status != "全部":
        where.append("v.review_status=?"); params.append(review_status)
    if uploader_id:
        where.append("v.owner_id = ?"); params.append(int(uploader_id))

    query = "SELECT substr(v.imported_at, 1, 10) AS date, COUNT(*) AS cnt FROM videos v"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " GROUP BY date ORDER BY date DESC"

    rows = db.execute(query, params).fetchall()
    dates = {r["date"]: r["cnt"] for r in rows}
    db.close()
    return jsonify({"success": True, "dates": dates})


@app.route("/api/youtube/delete", methods=["POST"])
@jwt_required()
def youtube_delete():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids: return jsonify({"success": False, "error": "未指定视频"}), 400
    db = _yt_db()
    for vid in ids: db.execute("DELETE FROM videos WHERE id=? AND owner_id=?", (vid, user_id))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/youtube/edit", methods=["POST"])
@jwt_required()
def youtube_edit():
    data = request.get_json(silent=True) or {}
    vid = (data.get("id") or "").strip()
    if not vid: return jsonify({"success": False, "error": "未指定视频ID"}), 400
    db = _yt_db()
    for f in ["region", "frame_type", "effectiveness", "product_name", "review_status", "is_public"]:
        if f in data: db.execute(f"UPDATE videos SET {f}=? WHERE id=?", (data[f], vid))
    db.commit()
    row = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    db.close()
    return jsonify({"success": True, "video": dict(row)} if row else {"success": False, "error": "未找到"})


@app.route("/api/youtube/batch-edit", methods=["POST"])
@jwt_required()
def youtube_batch_edit():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    field = (data.get("field") or "").strip()
    value = (data.get("value") or "").strip()
    if not ids:
        return jsonify({"success": False, "error": "未指定视频ID"}), 400
    if field not in ("region", "frame_type", "effectiveness", "product_name", "review_status", "is_public"):
        return jsonify({"success": False, "error": "无效字段"}), 400
    db = _yt_db()
    for vid in ids:
        db.execute(f"UPDATE videos SET {field}=? WHERE id=?", (value, vid))
    db.commit()
    db.close()
    return jsonify({"success": True, "updated": len(ids)})


@app.route("/api/youtube/tags", methods=["GET"])
@jwt_required()
def youtube_tags_get():
    db = _yt_db()
    tags = {}
    for r in db.execute("SELECT key, value FROM tags").fetchall():
        try: tags[r["key"]] = _json.loads(r["value"])
        except: tags[r["key"]] = []
    db.close()
    return jsonify({"success": True, "tags": tags})


@app.route("/api/youtube/tags", methods=["POST"])
@jwt_required()
def youtube_tags_save():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    new_regions = data.get("regions") or []
    new_frames = data.get("frame_types") or []
    new_effs = data.get("effectiveness") or []
    new_prods = data.get("product_names") or []
    new_review_statuses = data.get("review_statuses") or []

    db = _yt_db()
    old_tags = {}
    for r in db.execute("SELECT key, value FROM tags").fetchall():
        try: old_tags[r["key"]] = _json.loads(r["value"])
        except: pass
    old_regions = old_tags.get("regions", [])
    old_frames = old_tags.get("frame_types", [])
    old_effs = [e for e in old_tags.get("effectiveness", []) if e]
    old_prods = old_tags.get("product_names", [])
    old_review_statuses = old_tags.get("review_statuses", [])

    renames = {}; deleted_videos = []

    for old_val, new_list, field_name in [(old_regions, new_regions, "region"), (old_frames, new_frames, "frame_type"), (old_effs, new_effs, "effectiveness"), (old_prods, new_prods, "product_name"), (old_review_statuses, new_review_statuses, "review_status")]:
        for i, old_val in enumerate(old_val):
            if i < len(new_list) and new_list[i] != old_val:
                renames[(field_name, old_val)] = new_list[i]
            elif old_val not in new_list:
                deleted_videos.append((field_name, old_val))

    for (field, old_val), new_val in renames.items():
        db.execute(f"UPDATE videos SET {field}=? WHERE {field}=? AND owner_id=?", (new_val, old_val, user_id))

    affected = []
    if deleted_videos:
        for field, deleted_val in deleted_videos:
            for r in db.execute(f"SELECT id, title FROM videos WHERE {field}=? AND owner_id=?", (deleted_val, user_id)).fetchall():
                affected.append({"id": r["id"], "title": r["title"] or r["id"], "field": field, "old_value": deleted_val})

    for k, v in [("regions", new_regions), ("frame_types", new_frames), ("effectiveness", new_effs), ("product_names", new_prods), ("review_statuses", new_review_statuses)]:
        db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)", (k, _json.dumps(v, ensure_ascii=False)))

    db.commit(); db.close()
    return jsonify({"success": True, "renamed": len(renames), "affected": affected})



# ---------- 产品管理 API ----------

import re as _re_prod

@app.route("/api/products/list", methods=["GET"])
@jwt_required(optional=True)
def products_list():
    search = request.args.get("search", "").strip()
    region = request.args.get("region", "").strip()
    product_id = request.args.get("product_id", "").strip()
    mcc_id = request.args.get("mcc_id", "").strip()
    status_filter = request.args.get("status")  # None=不传, ""=正常, "paused"=暂停
    runner = request.args.get("runner", "mine").strip()  # "mine" | "all" | <user_id>
    page = int(request.args.get("page", 1) or 1)
    size = int(request.args.get("size", 20) or 20)
    db = _yt_db()

    where = []; params = []
    if runner == "mine":
        # 需要用户登录才能筛选"我在跑的"
        try:
            user_id = int(get_jwt_identity())
        except Exception:
            user_id = None
        if user_id:
            where.append("(p.runner_ids LIKE ? OR p.owner_id = ?)")
            params += [f'%{user_id}%', user_id]
    elif runner == "all":
        pass  # 不过滤
    elif runner.isdigit():
        # 按指定用户筛选
        where.append("(p.runner_ids LIKE ? OR p.owner_id = ?)")
        params += [f'%{runner}%', int(runner)]
    if search:
        where.append("(p.product_name LIKE ? OR p.kpi LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if region:
        where.append("p.region = ?"); params.append(region)
    if product_id:
        where.append("p.id = ?"); params.append(product_id)
    if mcc_id:
        where.append("p.mcc_id = ?"); params.append(mcc_id)
    # 暂停筛选（None=不传不过滤, ""=正常产品, "paused"=暂停产品）
    if status_filter is not None:
        status_filter = status_filter.strip()
        if status_filter:
            where.append("p.status = ?"); params.append(status_filter)
        else:
            # 兼容旧数据 INTEGER 0（is_paused 迁移后）和新数据 TEXT ''
            where.append("(p.status IS NULL OR p.status = '' OR p.status = '0' OR p.status = 0)")
    where.append("(p.is_archived IS NULL OR p.is_archived = 0)")
    sql = "SELECT p.*, m.name AS mcc_name, m.mcc_id AS mcc_code FROM products p LEFT JOIN mcc m ON p.mcc_id=m.id"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.created_at DESC LIMIT ? OFFSET ?"
    rows = db.execute(sql, params + [size, (page - 1) * size]).fetchall()
    count_sql = "SELECT COUNT(*) FROM products p"
    if where: count_sql += " WHERE " + " AND ".join(where)
    total = db.execute(count_sql, params).fetchone()[0]
    products = []
    for r in rows:
        prod = dict(r)
        pkgs = db.execute("SELECT * FROM packages WHERE product_id=?", (r["id"],)).fetchall()
        # 先按状态排序（正常→拒登→暂停→掉包），同状态按导入时间升序
        status_order = {"": 0, "0": 0, "rejected": 1, "paused": 2, "dropped": 3}
        pkgs = sorted(pkgs, key=lambda p: (
            status_order.get((str(p["status"] or "")).strip(), 0),
            p["created_at"] or ""
        ))
        prod["packages"] = [dict(p) for p in pkgs]
        # 关联账户数：仅统计直属（递归在详情弹窗按需加载）
        if r["mcc_id"]:
            prod["related_account_count"] = db.execute(
                "SELECT COUNT(*) FROM accounts WHERE mcc_id=?", (r["mcc_id"],)
            ).fetchone()[0]
        else:
            prod["related_account_count"] = 0
        products.append(prod)
    regions = [r["region"] for r in db.execute(
        "SELECT DISTINCT region FROM products WHERE region!='' AND (is_archived IS NULL OR is_archived = 0) ORDER BY region"
    ).fetchall()]
    mcc_options_for_filter = [dict(r) for r in db.execute("SELECT id, name, mcc_id FROM mcc ORDER BY name").fetchall()]

    # runner 统计（跟随 status 过滤）
    stat_clause = "1=1"
    stat_params_all = []
    stat_params_mine = []
    if status_filter is not None:
        status_filter_val = status_filter.strip() if isinstance(status_filter, str) else status_filter
        if status_filter_val:
            stat_clause = "p.status = ?"
            stat_params_all = [status_filter_val]
            stat_params_mine = [status_filter_val]
        else:
            stat_clause = "(p.status IS NULL OR p.status = '' OR p.status = '0' OR p.status = 0)"
            stat_params_all = []
            stat_params_mine = []

    runner_counts = {"all": db.execute(
        f"SELECT COUNT(*) FROM products p WHERE {stat_clause} AND (is_archived IS NULL OR is_archived = 0)",
        stat_params_all
    ).fetchone()[0]}
    try:
        uid = int(get_jwt_identity())
    except Exception:
        uid = None
    if uid:
        runner_counts["mine"] = db.execute(
            f"SELECT COUNT(*) FROM products p WHERE (p.runner_ids LIKE ? OR p.owner_id = ?) AND {stat_clause} AND (is_archived IS NULL OR is_archived = 0)",
            [f'%{uid}%', uid] + stat_params_mine
        ).fetchone()[0]
    else:
        runner_counts["mine"] = runner_counts["all"]

    db.close()
    return jsonify({"success": True, "products": products, "total": total, "regions": regions, "mcc_options": mcc_options_for_filter, "runner_counts": runner_counts})


@app.route("/api/products/create", methods=["POST"])
@jwt_required(optional=True)
def products_create():
    data = request.get_json(silent=True) or {}
    product_name = (data.get("product_name") or "").strip()
    kpi = (data.get("kpi") or "").strip()
    region = (data.get("region") or "").strip()
    mcc_id = data.get("mcc_id") or None
    packages = data.get("packages") or []
    if not product_name:
        return jsonify({"success": False, "error": "产品名不能为空"}), 400
    db = _yt_db()

    import datetime, json as _json
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 获取当前用户
    try:
        user_id = int(get_jwt_identity())
    except Exception:
        user_id = None

    # 已有同名产品则追加包
    existing = db.execute("SELECT id, runner_ids FROM products WHERE product_name=?", (product_name,)).fetchone()
    if existing:
        pid = existing["id"]
        if mcc_id is not None:
            db.execute("UPDATE products SET mcc_id=? WHERE id=?", (mcc_id, pid))
        # 将当前用户加入 runner
        if user_id:
            try:
                runners = _json.loads(existing["runner_ids"] or "[]")
            except Exception:
                runners = []
            if user_id not in runners:
                runners.append(user_id)
                db.execute("UPDATE products SET runner_ids=? WHERE id=?", (_json.dumps(runners), pid))
                # 自动分配产品 MCC 给当前用户
                if mcc_id:
                    _assign_mcc_to_users(db, mcc_id, [user_id])
    else:
        runner_ids = _json.dumps([user_id]) if user_id else "[]"
        db.execute("INSERT INTO products(product_name,kpi,region,mcc_id,owner_id,runner_ids,created_at) VALUES(?,?,?,?,?,?,?)",
                   (product_name, kpi, region, mcc_id, user_id, runner_ids, now))
        pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    for p in packages:
        pkg_name = p.get("package_name","")
        pkg_url = p.get("url","")
        # 同一产品下，包名+链接相同 = 同一个包，只更新系列名
        existing_pkg = db.execute(
            "SELECT id FROM packages WHERE product_id=? AND package_name=? AND url=?",
            (pid, pkg_name, pkg_url)
        ).fetchone()
        if existing_pkg:
            db.execute("UPDATE packages SET series_name=? WHERE id=?",
                       (p.get("series_name",""), existing_pkg["id"]))
        else:
            db.execute("INSERT INTO packages(product_id,series_name,package_name,url,created_at) VALUES(?,?,?,?,?)",
                       (pid, p.get("series_name",""), pkg_name, pkg_url, now))
    db.commit(); db.close()
    return jsonify({"success": True, "id": pid})


@app.route("/api/products/<int:pid>", methods=["PUT"])
def products_update(pid):
    data = request.get_json(silent=True) or {}
    db = _yt_db()

    for f in ["product_name", "kpi", "region", "status", "mcc_id"]:
        if f in data:
            db.execute(f"UPDATE products SET {f}=? WHERE id=?", (data[f], pid))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/products/<int:pid>", methods=["DELETE"])
def products_delete(pid):
    db = _yt_db()

    db.execute("DELETE FROM packages WHERE product_id=?", (pid,))
    db.execute("DELETE FROM products WHERE id=?", (pid,))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/products/merge", methods=["POST"])
@jwt_required()
def products_merge():
    """合并多个产品到主产品。"""
    data = request.get_json(silent=True) or {}
    master_id = data.get("master_id")  # 主产品 ID（保留）
    merge_ids = data.get("merge_ids") or []  # 被合并产品 ID 列表

    if not master_id or not merge_ids:
        return jsonify({"success": False, "error": "请指定主产品和被合并产品"}), 400
    if master_id in merge_ids:
        return jsonify({"success": False, "error": "主产品不能在被合并列表中"}), 400

    db = _yt_db()
    db.execute("PRAGMA foreign_keys=OFF")

    # 获取主产品的 runner_ids
    master = db.execute("SELECT runner_ids FROM products WHERE id=?", (master_id,)).fetchone()
    if not master:
        db.close()
        return jsonify({"success": False, "error": "主产品不存在"}), 404

    try:
        master_runners = _json.loads(master["runner_ids"] or "[]")
    except Exception:
        master_runners = []

    merged_packages = 0
    merged_runners = set()

    for mid in merge_ids:
        sub = db.execute("SELECT * FROM products WHERE id=?", (mid,)).fetchone()
        if not sub:
            continue

        # 合并 runner_ids
        try:
            sub_runners = _json.loads(sub["runner_ids"] or "[]")
        except Exception:
            sub_runners = []
        for r in sub_runners:
            master_runners.append(r)
            merged_runners.update(sub_runners)

        # 迁移 packages
        pkgs = db.execute("SELECT * FROM packages WHERE product_id=?", (mid,)).fetchall()
        for p in pkgs:
            pd = dict(p)
            # 检查主产品中是否已有同名+同链接的包
            existing = db.execute(
                "SELECT id FROM packages WHERE product_id=? AND package_name=? AND url=?",
                (master_id, pd.get("package_name", ""), pd.get("url", ""))
            ).fetchone()
            if not existing:
                pd.pop("id", None)
                pd["product_id"] = master_id
                cols = list(pd.keys())
                placeholders = ", ".join(["?"] * len(cols))
                vals = [pd[c] for c in cols]
                db.execute(
                    f"INSERT INTO packages({', '.join(cols)}) VALUES({placeholders})", vals
                )
                merged_packages += 1

        # 删除副产品
        db.execute("DELETE FROM packages WHERE product_id=?", (mid,))
        db.execute("DELETE FROM products WHERE id=?", (mid,))

    # 去重并更新主产品 runner_ids
    master_runners = list(set(master_runners))
    db.execute("UPDATE products SET runner_ids=? WHERE id=?",
               (_json.dumps(master_runners), master_id))

    db.execute("PRAGMA foreign_keys=ON")
    db.commit()
    db.close()

    return jsonify({
        "success": True,
        "merged_packages": merged_packages,
        "merged_products": len(merge_ids),
        "total_runners": len(master_runners),
    })


def _assign_mcc_to_users(db, mcc_id, user_ids):
    """将 MCC（含上级链）分配给指定用户列表。"""
    for uid in user_ids:
        _link_mcc_chain_to_user(db, mcc_id, uid)


def _link_mcc_chain_to_user(db, mcc_id, uid, visited=None):
    """递归将用户加入 MCC 及其所有上级的 shared_user_ids。"""
    if visited is None:
        visited = set()
    if mcc_id in visited:
        return
    visited.add(mcc_id)
    row = db.execute(
        "SELECT id, owner_id, shared_user_ids, parent_mcc_id FROM mcc WHERE id=?",
        (mcc_id,)
    ).fetchone()
    if not row:
        return
    if row["owner_id"] == uid:
        pass  # 已是 owner，不需要在 shared 中
    else:
        try:
            shared = json.loads(row["shared_user_ids"] or "[]")
        except Exception:
            shared = []
        if uid not in shared:
            shared.append(uid)
            db.execute(
                "UPDATE mcc SET shared_user_ids=? WHERE id=?",
                (json.dumps(shared), row["id"])
            )
    # 递归处理上级
    if row["parent_mcc_id"]:
        _link_mcc_chain_to_user(db, row["parent_mcc_id"], uid, visited)


@app.route("/api/products/<int:pid>/runners", methods=["PUT"])
@jwt_required()
def products_update_runners(pid):
    """更新产品的 runner 列表。新增 runner 时自动分配产品 MCC。"""
    data = request.get_json(silent=True) or {}
    runner_ids = data.get("runner_ids")  # list of user IDs

    if runner_ids is None or not isinstance(runner_ids, list):
        return jsonify({"success": False, "error": "请提供 runner_ids 列表"}), 400

    db = _yt_db()
    existing = db.execute(
        "SELECT id, runner_ids, mcc_id FROM products WHERE id=?", (pid,)
    ).fetchone()
    if not existing:
        db.close()
        return jsonify({"success": False, "error": "产品不存在"}), 404

    # 计算新增的 runner
    try:
        old_runners = json.loads(existing["runner_ids"] or "[]")
    except Exception:
        old_runners = []
    new_runners = [uid for uid in runner_ids if uid not in old_runners]

    # 更新 runner_ids
    db.execute("UPDATE products SET runner_ids=? WHERE id=?",
               (json.dumps(runner_ids), pid))

    # 自动分配产品 MCC 给新增的 runner
    product_mcc_id = existing["mcc_id"]
    if product_mcc_id and new_runners:
        _assign_mcc_to_users(db, product_mcc_id, new_runners)

    db.commit()
    db.close()
    return jsonify({"success": True, "runner_ids": runner_ids})


@app.route("/api/products/<int:pid>/detail", methods=["GET"])
def products_detail(pid):
    db = _yt_db()

    prod = db.execute(
        "SELECT p.*, m.name AS mcc_name, m.mcc_id AS mcc_code FROM products p LEFT JOIN mcc m ON p.mcc_id=m.id WHERE p.id=?", (pid,)
    ).fetchone()
    if not prod:
        db.close()
        return jsonify({"success": False, "error": "产品不存在"}), 404
    prod_data = dict(prod)
    # 包列表
    pkgs = db.execute("SELECT * FROM packages WHERE product_id=?", (pid,)).fetchall()
    status_order = {"": 0, "0": 0, "rejected": 1, "paused": 2, "dropped": 3}
    pkgs = sorted(pkgs, key=lambda p: (
        status_order.get((str(p["status"] or "")).strip(), 0),
        p["created_at"] or ""
    ))
    prod_data["packages"] = [dict(p) for p in pkgs]
    # 通过 MCC 关联的账户
    if prod["mcc_id"]:
        related_ids = _mcc_recursive_account_ids(prod["mcc_id"])
        if related_ids:
            placeholders = ",".join("?" * len(related_ids))
            related_accounts = [dict(r) for r in db.execute(
                f"SELECT id, name, account_id, status FROM accounts WHERE id IN ({placeholders}) ORDER BY name",
                related_ids
            ).fetchall()]
        else:
            related_accounts = []
        prod_data["related_accounts"] = related_accounts
        prod_data["related_account_count"] = len(related_accounts)
        # 状态统计
        status_count = {"存活": 0, "死亡": 0, "验证": 0, "限额": 0}
        for a in related_accounts:
            s = a.get("status", "存活")
            if s in status_count:
                status_count[s] += 1
        prod_data["status_count"] = status_count
    else:
        prod_data["related_accounts"] = []
        prod_data["related_account_count"] = 0
        prod_data["status_count"] = {}
    db.close()
    return jsonify({"success": True, "product": prod_data})


@app.route("/api/products/<int:pid>/packages", methods=["POST"])
def products_add_package(pid):
    data = request.get_json(silent=True) or {}
    series_name = (data.get("series_name") or "").strip()
    package_name = (data.get("package_name") or "").strip()
    url = (data.get("url") or "").strip()
    if not package_name:
        return jsonify({"success": False, "error": "包名不能为空"}), 400
    db = _yt_db()

    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    # 同一产品下，包名+链接相同 = 同一个包，只更新系列名
    existing = db.execute(
        "SELECT id FROM packages WHERE product_id=? AND package_name=? AND url=?",
        (pid, package_name, url)
    ).fetchone()
    if existing:
        db.execute("UPDATE packages SET series_name=? WHERE id=?",
                   (series_name, existing["id"]))
    else:
        db.execute("INSERT INTO packages(product_id,series_name,package_name,url,created_at) VALUES(?,?,?,?,?)",
                   (pid, series_name, package_name, url, now))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/products/packages/<int:pkg_id>", methods=["PUT"])
def products_update_package(pkg_id):
    data = request.get_json(silent=True) or {}
    db = _yt_db()

    for f in ["series_name", "package_name", "url", "status"]:
        if f in data:
            db.execute(f"UPDATE packages SET {f}=? WHERE id=?", (data[f], pkg_id))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/products/packages/<int:pkg_id>", methods=["DELETE"])
def products_delete_package(pkg_id):
    db = _yt_db()

    db.execute("DELETE FROM packages WHERE id=?", (pkg_id,))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/products/import-text", methods=["POST"])
def products_import_text():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    product_name = (data.get("product_name") or "").strip()
    kpi = (data.get("kpi") or "").strip()
    region = (data.get("region") or "").strip()
    prefix = (data.get("prefix") or "").strip()
    suffix = (data.get("suffix") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "未提供文本内容"}), 400
    links = _re_prod.findall(r'https?://play\.google\.com/store/apps/details\?id=[\w.&=/\-?%]+', text)
    results = []
    for link in links:
        pkg = _extract_pkg_from_url(link)
        series = _guess_series(text, link)
        if prefix:
            # 如果系列名已经以完整前缀开头，不再重复添加
            if not series.startswith(prefix):
                prefix_base = prefix.split("-")[0]
                series_base = series.split("-")[0] if "-" in series else series
                if prefix_base == series_base:
                    rest = series[len(series_base):].lstrip("-")
                    sep = "" if prefix.endswith("-") else "-"
                    series = prefix + sep + rest if rest else prefix
                else:
                    sep = "" if prefix.endswith("-") else "-"
                    series = prefix + sep + series
        if suffix:
            # 如果系列名已经以后缀结尾，不再重复添加
            if not series.endswith("-" + suffix) and series != suffix:
                series = series + "-" + suffix
        results.append({"series_name": series, "package_name": pkg, "url": link})
    return jsonify({"success": True, "parsed": results})


def _extract_pkg_from_url(url):
    m = _re_prod.search(r'[?&]id=([\w.]+)', url)
    return m.group(1) if m else ""


def _guess_series(text, link):
    """从文本猜测链接对应的系列名。"""
    lines = text.split("\n")
    link_idx = -1
    for i, line in enumerate(lines):
        if link in line:
            link_idx = i; break
    if link_idx < 0:
        return _extract_pkg_from_url(link)
    # 类型2（优先：更具体的"神包上线"格式，必须在类型1之前）
    for j in range(max(0, link_idx - 8), link_idx):
        l = lines[j].strip()
        if "神包上线" in l:
            name = l.split("神包上线：")[-1].split("神包上线")[-1].strip()
            if name: return name
    # 类型7（新增）：广告命名/渠道命名 前缀行，取整行内容含空格
    for j in range(max(0, link_idx - 2), min(len(lines), link_idx + 5)):
        l = lines[j].strip()
        for prefix in ["广告命名：", "广告命名:", "渠道命名：", "渠道命名:"]:
            if prefix in l:
                name = l.split(prefix)[-1].strip()
                if name: return name
    # 类型1：含APK或包号的行（排除"神包上线"以免误匹配）
    for j in range(link_idx, max(-1, link_idx - 10), -1):
        l = lines[j].strip()
        if "神包上线" in l: continue
        if ("APK" in l or ("包" in l and _re_prod.search(r'包\d+', l))) and "-" in l:
            for token in l.split():
                token = _re_prod.sub(r'^[^\w]*', '', token)
                if '-' in token and len(token) > 2:
                    return token
    # 类型3：应用名在链接之后（只向下搜索，窗口缩小到链接后4行内）
    for j in range(link_idx + 1, min(len(lines), link_idx + 6)):
        l = lines[j].strip()
        if "应用名：" in l or "应用名:" in l:
            name = l.split("应用名：")[-1].split("应用名:")[-1].strip()
            if name: return name
    # 类型4
    for j in range(max(0, link_idx - 3), min(len(lines), link_idx)):
        l = lines[j].strip()
        if "名称：" in l or "名称:" in l:
            name = l.split("名称：")[-1].split("名称:")[-1].strip()
            if name: return name
    # 类型6：第一列包含"-"的就是系列名
    for j in range(link_idx, max(-1, link_idx - 3), -1):
        l = lines[j].strip()
        tokens = l.split()
        if tokens:
            first = _re_prod.sub(r'^[^\w]*', '', tokens[0])
            if '-' in first and len(first) > 2:
                return first

    # 类型5
    return _extract_pkg_from_url(link)


# ---------- 账户管理 API ----------

def _mcc_to_dict(r, db=None, current_user_id=None):
    d = dict(r)
    if db:
        d["direct_count"] = db.execute(
            "SELECT COUNT(*) FROM accounts WHERE mcc_id=?", (r["id"],)
        ).fetchone()[0]
        d["total_accounts"] = len(_mcc_recursive_account_ids(r["id"]))
    else:
        d["direct_count"] = 0
        d["total_accounts"] = 0
    d["is_owner"] = (current_user_id is not None and r["owner_id"] == current_user_id)
    return d

def _mcc_recursive_account_ids(mcc_id):
    """递归获取某 MCC 及其所有子孙 MCC 下的所有账户 ID 列表。"""
    db = _yt_db()
    ids = set()
    stack = [mcc_id]
    while stack:
        cur = stack.pop()
        # 当前 MCC 下的直属账户
        for a in db.execute("SELECT id FROM accounts WHERE mcc_id=?", (cur,)).fetchall():
            ids.add(a["id"])
        # 子 MCC
        for m in db.execute("SELECT id FROM mcc WHERE parent_mcc_id=?", (cur,)).fetchall():
            stack.append(m["id"])
    return list(ids)


def _mcc_get_descendant_ids(mid):
    """递归获取某 MCC 的所有子孙 MCC ID（含自身），用于循环引用检测。"""
    db = _yt_db()
    ids = set()
    stack = [mid]
    while stack:
        cur = stack.pop()
        if cur in ids:
            continue
        ids.add(cur)
        for m in db.execute("SELECT id FROM mcc WHERE parent_mcc_id=?", (cur,)).fetchall():
            stack.append(m["id"])
    return ids


@app.route("/api/accounts/list", methods=["GET"])
@jwt_required()
def accounts_list():
    user_id = int(get_jwt_identity())
    search = request.args.get("search", "").strip()
    mcc_id = request.args.get("mcc_id", "").strip()
    status = request.args.get("status", "").strip()
    agent = request.args.get("agent", "").strip()
    page = int(request.args.get("page", 1) or 1)
    size = int(request.args.get("size", 20) or 20)
    db = _yt_db()
    where = ["a.owner_id = ?"]; params = [user_id]
    if search:
        where.append("(a.name LIKE ? OR a.account_id LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if mcc_id:
        where.append("a.mcc_id = ?"); params.append(mcc_id)
    if status:
        where.append("a.status = ?"); params.append(status)
    if agent:
        where.append("a.agent LIKE ?"); params.append(f"%{agent}%")
    sql = "SELECT a.*, m.name AS mcc_name, m.mcc_id AS mcc_code FROM accounts a LEFT JOIN mcc m ON a.mcc_id=m.id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # 排序
    sort = request.args.get("sort", "mcc_tz")
    sort_map = {
        "mcc_tz": "m.name ASC, a.timezone ASC, a.name ASC",
        "tz": "m.name ASC, a.timezone ASC, a.name ASC",
        "name": "m.name ASC, a.name ASC",
        "agent": "m.name ASC, a.agent ASC, a.name ASC",
        "created": "m.name ASC, a.created_at DESC",
    }
    sql += " ORDER BY " + sort_map.get(sort, sort_map["mcc_tz"]) + " LIMIT ? OFFSET ?"
    rows = db.execute(sql, params + [size, (page - 1) * size]).fetchall()
    count_sql = "SELECT COUNT(*) FROM accounts a"
    if where:
        count_sql += " WHERE " + " AND ".join(where)
    total = db.execute(count_sql, params).fetchone()[0]
    accounts = [dict(r) for r in rows]
    # 各状态的计数
    status_counts = {}
    for r in db.execute("SELECT status, COUNT(*) as cnt FROM accounts WHERE owner_id=? GROUP BY status", (user_id,)).fetchall():
        s = r["status"] or "存活"; status_counts[s] = status_counts.get(s, 0) + r["cnt"]
    # 筛选下拉数据
    mcc_options = [dict(r) for r in db.execute("SELECT id, name, mcc_id FROM mcc WHERE owner_id=? ORDER BY name", (user_id,)).fetchall()]
    agents = [r["agent"] for r in db.execute("SELECT DISTINCT agent FROM accounts WHERE agent!='' AND owner_id=? ORDER BY agent", (user_id,)).fetchall()]
    db.close()
    return jsonify({"success": True, "accounts": accounts, "total": total, "mcc_options": mcc_options, "agents": agents, "status_counts": status_counts})


@app.route("/api/accounts/create", methods=["POST"])
@jwt_required()
def accounts_create():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    account_id = (data.get("account_id") or "").strip()
    if not name or not account_id:
        return jsonify({"success": False, "error": "账户名称和ID不能为空"}), 400
    db = _yt_db()
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        db.execute(
            "INSERT INTO accounts(name,account_id,mcc_id,timezone,agent,status,acquired_date,death_date,created_at,updated_at,owner_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (name, account_id,
             data.get("mcc_id") or None,
             (data.get("timezone") or "").strip(),
             (data.get("agent") or "").strip(),
             (data.get("status") or "存活").strip(),
             (data.get("acquired_date") or datetime.date.today().isoformat()),
             (data.get("death_date") or "").strip(),
             now, now, user_id))
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()
        return jsonify({"success": True, "id": new_id})
    except _sqlite3.IntegrityError as e:
        err_msg = str(e).lower()
        db.close()
        if "foreign key" in err_msg:
            return jsonify({"success": False, "error": f"所属 MCC 不存在，请先创建 MCC"}), 409
        if "account_id" in err_msg or "unique" in err_msg:
            return jsonify({"success": False, "error": f"账户 ID '{account_id}' 已存在"}), 409
        return jsonify({"success": False, "error": f"数据完整性错误: {e}"}), 409


@app.route("/api/accounts/<int:aid>", methods=["PUT"])
@jwt_required()
def accounts_update(aid):
    data = request.get_json(silent=True) or {}
    db = _yt_db()
    try:
        for f in ["name", "mcc_id", "timezone", "agent", "status", "acquired_date", "death_date"]:
            if f in data:
                val = data[f]
                # mcc_id 空字符串/0 转 None，避免 FK 约束失败
                if f == "mcc_id":
                    if val is None or val == 0 or val == "0" or (isinstance(val, str) and not val.strip()):
                        val = None
                db.execute(f"UPDATE accounts SET {f}=?, updated_at=datetime('now','localtime') WHERE id=?",
                           (val, aid))
        db.commit()
        return jsonify({"success": True})
    except _sqlite3.IntegrityError as e:
        err_msg = str(e).lower()
        if "foreign key" in err_msg:
            return jsonify({"success": False, "error": "所属 MCC 不存在，请先选择有效的 MCC"}), 409
        return jsonify({"success": False, "error": f"数据完整性错误: {e}"}), 409
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/accounts/<int:aid>", methods=["DELETE"])
@jwt_required()
def accounts_delete(aid):
    user_id = int(get_jwt_identity())
    db = _yt_db()
    try:
        db.execute("DELETE FROM accounts WHERE id=? AND owner_id=?", (aid, user_id))
        db.commit()
        return jsonify({"success": True})
    finally:
        db.close()


@app.route("/api/accounts/batch-delete", methods=["POST"])
@jwt_required()
def accounts_batch_delete():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"success": False, "error": "未选择账户"}), 400
    db = _yt_db()
    try:
        for aid in ids:
            db.execute("DELETE FROM accounts WHERE id=? AND owner_id=?", (aid, user_id))
        db.commit()
        return jsonify({"success": True, "deleted": len(ids)})
    finally:
        db.close()


@app.route("/api/accounts/batch-update", methods=["POST"])
@jwt_required()
def accounts_batch_update():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    field = data.get("field", "").strip()
    value = data.get("value")
    if not ids or not field:
        return jsonify({"success": False, "error": "缺少参数"}), 400
    allowed = ["status", "agent", "mcc_id", "timezone"]
    if field not in allowed:
        return jsonify({"success": False, "error": f"不允许修改字段: {field}"}), 400
    db = _yt_db()
    try:
        # mcc_id 空值/0 转 None，避免 FK 约束失败
        if field == "mcc_id" and (value is None or value == 0 or value == "0" or (isinstance(value, str) and not value.strip())):
            value = None
        for aid in ids:
            db.execute(f"UPDATE accounts SET {field}=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (value, aid))
        db.commit()
        return jsonify({"success": True, "updated": len(ids)})
    finally:
        db.close()


# ---------- MCC API ----------

@app.route("/api/mcc/list", methods=["GET"])
@jwt_required()
def mcc_list():
    user_id = int(get_jwt_identity())
    search = request.args.get("search", "").strip()
    level = request.args.get("level", "").strip()
    parent_filter = request.args.get("parent_filter", "")  # "has_parent", "top", ""
    page = int(request.args.get("page", 1) or 1)
    size = int(request.args.get("size", 20) or 20)
    db = _yt_db()
    uid_str = str(user_id)
    where = ["(m.owner_id = ? OR m.shared_user_ids = ? OR m.shared_user_ids LIKE ? OR m.shared_user_ids LIKE ? OR m.shared_user_ids LIKE ?)"]
    params = [user_id, f"[{uid_str}]", f"[{uid_str},%", f"%, {uid_str},%", f"%, {uid_str}]"]
    if search:
        where.append("(m.name LIKE ? OR m.mcc_id LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if level:
        where.append("m.level LIKE ?"); params.append(f"%{level}%")
    if parent_filter == "has_parent":
        where.append("m.parent_mcc_id IS NOT NULL")
    elif parent_filter == "top":
        where.append("m.parent_mcc_id IS NULL")
    sql = "SELECT m.* FROM mcc m"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.created_at DESC LIMIT ? OFFSET ?"
    rows = db.execute(sql, params + [size, (page - 1) * size]).fetchall()
    count_sql = "SELECT COUNT(*) FROM mcc m"
    if where:
        count_sql += " WHERE " + " AND ".join(where)
    total = db.execute(count_sql, params).fetchone()[0]
    mcc_list_data = [_mcc_to_dict(r, db, user_id) for r in rows]
    db.close()
    return jsonify({"success": True, "mcc_list": mcc_list_data, "total": total})


@app.route("/api/mcc/options", methods=["GET"])
@jwt_required()
def mcc_options():
    user_id = int(get_jwt_identity())
    db = _yt_db()
    uid_str = str(user_id)
    rows = db.execute(
        "SELECT id, name, mcc_id FROM mcc WHERE (owner_id=? OR shared_user_ids=? OR "
        "shared_user_ids LIKE ? OR shared_user_ids LIKE ? OR shared_user_ids LIKE ?) ORDER BY name",
        (user_id, f"[{uid_str}]", f"[{uid_str},%", f"%, {uid_str},%", f"%, {uid_str}]")
    ).fetchall()
    db.close()
    return jsonify({"success": True, "options": [dict(r) for r in rows]})


@app.route("/api/mcc/create", methods=["POST"])
@jwt_required()
def mcc_create():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    mcc_id = (data.get("mcc_id") or "").strip()
    if not name or not mcc_id:
        return jsonify({"success": False, "error": "MCC 名称和 ID 不能为空"}), 400

    db = _yt_db()

    # 检查 mcc_id 是否已存在（按 Google Ads manager ID 字符串）
    existing = db.execute(
        "SELECT m.*, u.display_name, u.username FROM mcc m "
        "LEFT JOIN users u ON m.owner_id = u.id "
        "WHERE m.mcc_id=?", (mcc_id,)
    ).fetchone()

    if existing:
        ed = dict(existing)
        owner_name = ed.get("display_name") or ed.get("username") or "未知"
        # 检查当前用户是否已经在 shared 中或为 owner
        try:
            shared = json.loads(ed.get("shared_user_ids") or "[]")
        except Exception:
            shared = []
        if ed["owner_id"] == user_id or user_id in shared:
            db.close()
            return jsonify({"success": False, "error": "该 MCC 已关联到您的账户"}), 409
        # 存在但用户不在 shared 中 — 返回现有 MCC 信息等前端确认
        db.close()
        return jsonify({
            "success": True,
            "exists": True,
            "existing_mcc": {
                "id": ed["id"],
                "name": ed["name"],
                "mcc_id": ed["mcc_id"]
            },
            "owner_name": owner_name
        })

    # 验证上级 MCC 存在
    parent_mcc_id = data.get("parent_mcc_id") or None
    if parent_mcc_id:
        parent_row = db.execute("SELECT id FROM mcc WHERE id=?", (int(parent_mcc_id),)).fetchone()
        if not parent_row:
            db.close()
            return jsonify({"success": False, "error": "上级 MCC 不存在"}), 400

    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        db.execute(
            "INSERT INTO mcc(name,mcc_id,level,parent_mcc_id,shared_user_ids,created_at,updated_at,owner_id) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (name, mcc_id,
             (data.get("level") or "").strip(),
             parent_mcc_id,
             json.dumps([user_id]),
             now, now, user_id))
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()
        return jsonify({"success": True, "id": new_id})
    except _sqlite3.IntegrityError:
        db.close()
        return jsonify({"success": False, "error": f"MCC ID '{mcc_id}' 已存在"}), 409


@app.route("/api/mcc/<int:mid>", methods=["PUT"])
@jwt_required()
def mcc_update(mid):
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    db = _yt_db()
    mcc_row = db.execute("SELECT owner_id FROM mcc WHERE id=?", (mid,)).fetchone()
    if not mcc_row:
        db.close()
        return jsonify({"success": False, "error": "MCC 不存在"}), 404
    if mcc_row["owner_id"] != user_id:
        db.close()
        return jsonify({"success": False, "error": "只有创建者才能编辑此 MCC"}), 403
    # 循环引用检测：新 parent_mcc_id 不能是当前 MCC 的子孙
    if "parent_mcc_id" in data and data["parent_mcc_id"]:
        new_parent = int(data["parent_mcc_id"])
        if new_parent == mid:
            db.close()
            return jsonify({"success": False, "error": "上级 MCC 不能设为自己"}), 400
        descendants = _mcc_get_descendant_ids(mid)
        if new_parent in descendants:
            db.close()
            return jsonify({"success": False, "error": "不能设置为下属 MCC，这会造成循环引用"}), 400
        # 验证父级存在
        parent_row = db.execute("SELECT id FROM mcc WHERE id=?", (new_parent,)).fetchone()
        if not parent_row:
            db.close()
            return jsonify({"success": False, "error": "上级 MCC 不存在"}), 400
    for f in ["name", "level", "parent_mcc_id"]:
        if f in data:
            db.execute(f"UPDATE mcc SET {f}=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (data[f], mid))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/mcc/<int:mid>", methods=["DELETE"])
@jwt_required()
def mcc_delete(mid):
    user_id = int(get_jwt_identity())
    db = _yt_db()
    # 检查 ownership
    mcc_row = db.execute("SELECT owner_id FROM mcc WHERE id=?", (mid,)).fetchone()
    if not mcc_row:
        db.close()
        return jsonify({"success": False, "error": "MCC 不存在"}), 404
    if mcc_row["owner_id"] != user_id:
        db.close()
        return jsonify({"success": False, "error": "只有创建者才能删除此 MCC"}), 403
    # 检查是否有子 MCC
    children = db.execute("SELECT COUNT(*) FROM mcc WHERE parent_mcc_id=?", (mid,)).fetchone()[0]
    if children > 0:
        db.close()
        return jsonify({"success": False, "error": f"该 MCC 下有 {children} 个子 MCC，请先删除子 MCC"}), 400
    # 检查是否有直接关联的账户
    acct_count = db.execute("SELECT COUNT(*) FROM accounts WHERE mcc_id=?", (mid,)).fetchone()[0]
    if acct_count > 0:
        db.close()
        return jsonify({"success": False, "error": f"该 MCC 下有 {acct_count} 个直接关联账户，请先解除关联"}), 400
    db.execute("DELETE FROM mcc WHERE id=?", (mid,))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/mcc/batch-delete", methods=["POST"])
@jwt_required()
def mcc_batch_delete():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"success": False, "error": "未选择 MCC"}), 400
    db = _yt_db()
    skipped = []
    deleted = 0
    for mid in ids:
        # Owner 检查
        mcc_row = db.execute("SELECT owner_id FROM mcc WHERE id=?", (mid,)).fetchone()
        if not mcc_row:
            skipped.append({"id": mid, "reason": "MCC 不存在"})
            continue
        if mcc_row["owner_id"] != user_id:
            skipped.append({"id": mid, "reason": "非创建者，无法删除"})
            continue
        children = db.execute("SELECT COUNT(*) FROM mcc WHERE parent_mcc_id=?", (mid,)).fetchone()[0]
        if children > 0:
            skipped.append({"id": mid, "reason": f"有 {children} 个子 MCC"})
            continue
        acct_count = db.execute("SELECT COUNT(*) FROM accounts WHERE mcc_id=?", (mid,)).fetchone()[0]
        if acct_count > 0:
            skipped.append({"id": mid, "reason": f"有 {acct_count} 个关联账户"})
            continue
        db.execute("DELETE FROM mcc WHERE id=?", (mid,))
        deleted += 1
    db.commit(); db.close()
    return jsonify({"success": True, "deleted": deleted, "skipped": skipped})


@app.route("/api/mcc/<int:mid>/link", methods=["POST"])
@jwt_required()
def mcc_link(mid):
    """将当前用户关联到已有 MCC（含上级链）。"""
    user_id = int(get_jwt_identity())
    db = _yt_db()

    mcc = db.execute("SELECT * FROM mcc WHERE id=?", (mid,)).fetchone()
    if not mcc:
        db.close()
        return jsonify({"success": False, "error": "MCC 不存在"}), 404

    _link_mcc_chain_to_user(db, mid, user_id)
    db.commit()
    db.close()
    return jsonify({"success": True, "message": "MCC 已关联到您的账户"})


@app.route("/api/mcc/<int:mid>/detail", methods=["GET"])
@jwt_required()
def mcc_detail(mid):
    db = _yt_db()
    mcc = db.execute("SELECT * FROM mcc WHERE id=?", (mid,)).fetchone()
    if not mcc:
        db.close()
        return jsonify({"success": False, "error": "MCC 不存在"}), 404
    mcc_data = dict(mcc)
    # 上级 MCC
    if mcc["parent_mcc_id"]:
        parent = db.execute("SELECT id, name, mcc_id FROM mcc WHERE id=?", (mcc["parent_mcc_id"],)).fetchone()
        mcc_data["parent_mcc"] = dict(parent) if parent else None
    else:
        mcc_data["parent_mcc"] = None
    # 直属账户
    direct_accounts = [dict(r) for r in db.execute(
        "SELECT id, name, account_id, status FROM accounts WHERE mcc_id=? ORDER BY name", (mid,)
    ).fetchall()]
    mcc_data["direct_count"] = len(direct_accounts)
    mcc_data["direct_accounts"] = direct_accounts
    # 子 MCC + 间接账户
    child_mccs = []
    indirect_accounts = []
    for c in db.execute("SELECT id, name, mcc_id FROM mcc WHERE parent_mcc_id=?", (mid,)).fetchall():
        cdict = dict(c)
        c_direct = [dict(r) for r in db.execute(
            "SELECT id, name, account_id, status FROM accounts WHERE mcc_id=? ORDER BY name", (c["id"],)
        ).fetchall()]
        for sc in db.execute("SELECT id FROM mcc WHERE parent_mcc_id=?", (c["id"],)).fetchall():
            c_direct += [dict(r) for r in db.execute(
                "SELECT id, name, account_id, status FROM accounts WHERE mcc_id=? ORDER BY name", (sc["id"],)
            ).fetchall()]
        cdict["account_count"] = len(c_direct)
        child_mccs.append(cdict)
        indirect_accounts += c_direct
    mcc_data["child_mccs"] = child_mccs
    mcc_data["indirect_accounts"] = indirect_accounts
    mcc_data["total_count"] = mcc_data["direct_count"] + len(indirect_accounts)
    # 关联产品（确保 products 表存在）

    mcc_data["products"] = [dict(r) for r in db.execute(
        "SELECT id, product_name FROM products WHERE mcc_id=? ORDER BY product_name", (mid,)
    ).fetchall()]
    db.close()
    return jsonify({"success": True, "mcc": mcc_data})


# ---------- 账户设置 API ----------

@app.route("/api/settings/account", methods=["GET"])
def account_settings_get():
    """返回账户管理相关的可配置项（状态、代理、MCC 等级等）。"""
    db = _yt_db()
    keys = ["account_statuses", "account_agents", "mcc_levels"]
    result = {}
    for k in keys:
        row = db.execute("SELECT value FROM tags WHERE key=?", (k,)).fetchone()
        if row:
            try:
                result[k] = _json.loads(row["value"])
            except Exception:
                result[k] = []
        else:
            # 默认值
            defaults = {
                "account_statuses": ["存活", "死亡", "验证", "限额"],
                "account_agents": [],
                "mcc_levels": [],
            }
            result[k] = defaults.get(k, [])
    db.close()
    return jsonify({"success": True, "settings": result})


@app.route("/api/settings/account", methods=["POST"])
def account_settings_save():
    """保存账户管理相关的可配置项。"""
    data = request.get_json(silent=True) or {}
    db = _yt_db()
    for key in ["account_statuses", "account_agents", "mcc_levels"]:
        if key in data:
            db.execute("INSERT OR REPLACE INTO tags(key,value) VALUES(?,?)",
                       (key, _json.dumps(data[key], ensure_ascii=False)))
    db.commit()
    db.close()
    return jsonify({"success": True})


# ---------- 文件浏览 API ----------


def _is_local_request() -> bool:
    """检查请求是否来自本机（防止远程触发文件对话框）。"""
    remote_addr = request.remote_addr or ""
    return remote_addr in ("127.0.0.1", "::1", "localhost")


def _resolve_initial_dir(path: str) -> str | None:
    """解析初始目录：路径不存在则逐级向上查找存在的目录。"""
    p = path.strip().replace("\\", "/")
    while p:
        if os.path.isdir(p):
            return p
        parent = os.path.dirname(p)
        if parent == p:  # 根目录
            return p if os.path.isdir(p) else None
        p = parent
    return None



def _ps_file_dialog_fast(filter_str, title="选择文件", start_dir=None):
    init = f"$d.InitialDirectory = '{start_dir.replace('/', '\\')}';" if start_dir else ""
    ps = f'''
Add-Type -AssemblyName System.Windows.Forms
$d=New-Object System.Windows.Forms.OpenFileDialog
$d.Title="{title}";$d.Filter="{filter_str}";{init}
if($d.ShowDialog()-eq[System.Windows.Forms.DialogResult]::OK){{$d.FileName}}
'''
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=120)
        return out.stdout.strip() or None
    except: return None

def _ps_save_dialog_fast(title="保存文件", start_dir=None):
    init = f"$d.InitialDirectory = '{start_dir.replace('/', '\\')}';" if start_dir else ""
    ps = f'''
Add-Type -AssemblyName System.Windows.Forms
$d=New-Object System.Windows.Forms.SaveFileDialog
$d.Title="{title}";$d.Filter="MP4文件|*.mp4|所有文件|*.*";$d.DefaultExt=".mp4";{init}
if($d.ShowDialog()-eq[System.Windows.Forms.DialogResult]::OK){{$d.FileName}}
'''
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=120)
        return out.stdout.strip() or None
    except: return None

def _ps_folder_dialog_fast(title="选择文件夹", start_dir=None):
    init = f"$d.SelectedPath = '{start_dir.replace('/', '\\')}';" if start_dir else ""
    ps = f'''
Add-Type -AssemblyName System.Windows.Forms
$d=New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description="{title}";{init}
if($d.ShowDialog()-eq[System.Windows.Forms.DialogResult]::OK){{$d.SelectedPath}}
'''
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=120)
        return out.stdout.strip() or None
    except: return None

def _win32_file_dialog(filter_tuples, title="选择文件", initial_dir=None, multi=False):
    """Windows API 原生文件对话框 — ctypes 秒开零依赖。"""
    import ctypes as ct
    from ctypes import wintypes as w

    start_dir = _resolve_initial_dir(initial_dir) if initial_dir else None
    null = chr(0)

    # 构建过滤字符串
    filter_parts = []
    for name, ext in filter_tuples:
        filter_parts.append(name)
        filter_parts.append(ext)
    filter_str = null.join(filter_parts) + null + null

    buf_size = 260 if not multi else 26000
    buf = ct.create_unicode_buffer(buf_size)

    class OFN(ct.Structure):
        _fields_ = [
            ("lStructSize", w.DWORD), ("hwndOwner", w.HWND), ("hInstance", w.HINSTANCE),
            ("lpstrFilter", w.LPCWSTR), ("lpstrCustomFilter", w.LPWSTR),
            ("nMaxCustFilter", w.DWORD), ("nFilterIndex", w.DWORD),
            ("lpstrFile", w.LPWSTR), ("nMaxFile", w.DWORD),
            ("lpstrFileTitle", w.LPWSTR), ("nMaxFileTitle", w.DWORD),
            ("lpstrInitialDir", w.LPCWSTR), ("lpstrTitle", w.LPCWSTR),
            ("Flags", w.DWORD), ("nFileOffset", w.WORD), ("nFileExtension", w.WORD),
            ("lpstrDefExt", w.LPCWSTR), ("lCustData", w.LPARAM),
            ("lpfnHook", w.LPVOID), ("lpTemplateName", w.LPCWSTR),
        ]

    ofn = OFN()
    ofn.lStructSize = ct.sizeof(OFN)
    ofn.hwndOwner = ct.windll.user32.GetForegroundWindow()
    ofn.lpstrFilter = filter_str
    ofn.lpstrFile = ct.cast(buf, w.LPWSTR)
    ofn.nMaxFile = ct.sizeof(buf) // ct.sizeof(w.WCHAR)
    ofn.lpstrTitle = title
    if start_dir: ofn.lpstrInitialDir = start_dir
    ofn.Flags = 0x80000 | 0x1000 | 0x800 | 0x4  # explorer + filemustexist + pathmustexist + hidereadonly
    if multi: ofn.Flags |= 0x200 | 0x20000  # allowmultiselect

    try:
        ok = ct.windll.comdlg32.GetOpenFileNameW(ct.byref(ofn))
        if ok:
            if multi:
                raw = buf.value
                parts = raw.split(null)
                if len(parts) > 2:
                    return [os.path.join(parts[0], p) for p in parts[1:] if p]
                return [raw] if raw else []
            return buf.value or None
    except Exception:
        pass
    return None if not multi else []


def _win32_save_dialog(title="保存文件", initial_dir=None):
    """Windows API 原生保存文件对话框。"""
    import ctypes as ct
    from ctypes import wintypes as w

    start_dir = _resolve_initial_dir(initial_dir) if initial_dir else None
    null = chr(0)
    filter_str = "MP4 文件" + null + "*.mp4" + null + "所有文件" + null + "*.*" + null + null

    buf = ct.create_unicode_buffer(260)

    class OFN(ct.Structure):
        _fields_ = [
            ("lStructSize", w.DWORD), ("hwndOwner", w.HWND), ("hInstance", w.HINSTANCE),
            ("lpstrFilter", w.LPCWSTR), ("lpstrCustomFilter", w.LPWSTR),
            ("nMaxCustFilter", w.DWORD), ("nFilterIndex", w.DWORD),
            ("lpstrFile", w.LPWSTR), ("nMaxFile", w.DWORD),
            ("lpstrFileTitle", w.LPWSTR), ("nMaxFileTitle", w.DWORD),
            ("lpstrInitialDir", w.LPCWSTR), ("lpstrTitle", w.LPCWSTR),
            ("Flags", w.DWORD), ("nFileOffset", w.WORD), ("nFileExtension", w.WORD),
            ("lpstrDefExt", w.LPCWSTR), ("lCustData", w.LPARAM),
            ("lpfnHook", w.LPVOID), ("lpTemplateName", w.LPCWSTR),
        ]

    ofn = OFN()
    ofn.lStructSize = ct.sizeof(OFN)
    ofn.hwndOwner = ct.windll.user32.GetForegroundWindow()
    ofn.lpstrFilter = filter_str
    ofn.lpstrFile = ct.cast(buf, w.LPWSTR)
    ofn.nMaxFile = ct.sizeof(buf) // ct.sizeof(w.WCHAR)
    ofn.lpstrTitle = title
    if start_dir: ofn.lpstrInitialDir = start_dir
    ofn.Flags = 0x80000 | 0x2 | 0x4
    ofn.lpstrDefExt = "mp4"

    try:
        ok = ct.windll.comdlg32.GetSaveFileNameW(ct.byref(ofn))
        if ok: return buf.value or None
    except Exception:
        pass
    return None


def _win32_folder_dialog(title="选择文件夹", initial_dir=None):
    """Windows API 原生文件夹选择对话框。"""
    import ctypes as ct
    from ctypes import wintypes as w

    start_dir = _resolve_initial_dir(initial_dir) if initial_dir else None

    CB = ct.WINFUNCTYPE(ct.c_int, w.HWND, w.UINT, w.LPARAM, w.LPARAM)

    @CB
    def _cb(hwnd, msg, lp, data):
        if msg == 1 and start_dir:
            ct.windll.user32.SendMessageW(hwnd, 0x467, 1, lp)
        return 0

    class BI(ct.Structure):
        _fields_ = [
            ("hwndOwner", w.HWND), ("pidlRoot", w.LPVOID),
            ("pszDisplayName", w.LPWSTR), ("lpszTitle", w.LPCWSTR),
            ("ulFlags", w.UINT), ("lpfn", CB), ("lParam", w.LPARAM), ("iImage", ct.c_int),
        ]

    dbuf = ct.create_unicode_buffer(260)
    bi = BI()
    bi.hwndOwner = ct.windll.user32.GetForegroundWindow()
    bi.pszDisplayName = ct.cast(dbuf, w.LPWSTR)
    bi.lpszTitle = title
    bi.ulFlags = 0x1 | 0x40 | 0x10  # BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX
    if start_dir:
        bi.lpfn = _cb
        bi.lParam = ct.addressof(ct.create_unicode_buffer(start_dir))

    try:
        pidl = ct.windll.shell32.SHBrowseForFolderW(ct.byref(bi))
        if pidl:
            pbuf = ct.create_unicode_buffer(260)
            ct.windll.shell32.SHGetPathFromIDListW(pidl, pbuf)
            ct.windll.ole32.CoTaskMemFree(pidl)
            return pbuf.value or None
    except Exception:
        pass
    return None


# 统一入口：PowerShell 稳定置顶 + 填路径
def _native_file_dialog(filter_tuples, title="选择文件", initial_dir=None):
    start_dir = _resolve_initial_dir(initial_dir) if initial_dir else None
    filter_str = "|".join(f"{n}|{e}" for n, e in filter_tuples)
    return _ps_file_dialog_fast(filter_str, title, start_dir)

def _native_save_dialog(title="保存文件", initial_dir=None):
    start_dir = _resolve_initial_dir(initial_dir) if initial_dir else None
    return _ps_save_dialog_fast(title, start_dir)

def _native_folder_dialog(title="选择文件夹", initial_dir=None):
    start_dir = _resolve_initial_dir(initial_dir) if initial_dir else None
    return _ps_folder_dialog_fast(title, start_dir)


def _multi_file_dialog(title="选择文件"):
    """多文件选择对话框。"""
    return _win32_file_dialog(
        [("字体文件", "*.ttf;*.otf;*.ttc;*.woff;*.woff2"), ("所有文件", "*.*")],
        title, multi=True
    ) or []



@app.route("/api/browse-file", methods=["POST"])
def browse_file():
    """打开本地文件选择对话框，返回选中路径。"""
    if not _is_local_request():
        return jsonify({"success": False, "error": "仅允许本机访问"}), 403
    data = request.get_json(silent=True) or {}
    file_type = data.get("type", "all")
    initial_dir = data.get("initial_dir") or None

    filters_tk = {
        "mp3": [("MP3 文件", "*.mp3"), ("所有文件", "*.*")],
        "audio": [("音频文件", "*.mp3;*.wav;*.aac;*.m4a;*.flac;*.ogg"), ("视频文件", "*.mp4;*.avi;*.mkv;*.mov"), ("所有文件", "*.*")],
        "video": [("视频文件", "*.mp4;*.avi;*.mkv;*.mov;*.wmv;*.flv"), ("所有文件", "*.*")],
        "image": [("图片文件", "*.png;*.jpg;*.jpeg;*.bmp"), ("所有文件", "*.*")],
        "all": [("所有文件", "*.*")],
    }
    path = _native_file_dialog(filters_tk.get(file_type, filters_tk["all"]), initial_dir=initial_dir)
    if path:
        return jsonify({"success": True, "path": path.replace("\\", "/")})
    return jsonify({"success": True, "path": ""})


@app.route("/api/browse-save", methods=["POST"])
def browse_save():
    """打开文件保存对话框。"""
    if not _is_local_request():
        return jsonify({"success": False, "error": "仅允许本机访问"}), 403
    data = request.get_json(silent=True) or {}
    initial_dir = data.get("initial_dir") or None
    path = _native_save_dialog(initial_dir=initial_dir)
    if path:
        return jsonify({"success": True, "path": path.replace("\\", "/")})
    return jsonify({"success": True, "path": ""})


@app.route("/api/browse-folder", methods=["POST"])
def browse_folder():
    """打开文件夹选择对话框。"""
    if not _is_local_request():
        return jsonify({"success": False, "error": "仅允许本机访问"}), 403
    data = request.get_json(silent=True) or {}
    initial_dir = data.get("initial_dir") or None
    path = _native_folder_dialog(initial_dir=initial_dir)
    if path:
        return jsonify({"success": True, "path": path.replace("\\", "/")})
    return jsonify({"success": True, "path": ""})


# ---------- 启动 ----------

# ---------- Google Ads API ----------

# Google Ads 凭据（在页面中填写，或设置环境变量 GOOGLE_ADS_*）
_GOOGLE_ADS_CONFIG = {
    "client_id": os.environ.get("GOOGLE_ADS_CLIENT_ID", ""),
    "client_secret": os.environ.get("GOOGLE_ADS_CLIENT_SECRET", ""),
    "refresh_token": os.environ.get("GOOGLE_ADS_REFRESH_TOKEN", ""),
    "developer_token": os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", ""),
    "manager_id": os.environ.get("GOOGLE_ADS_MANAGER_ID", ""),
}


@app.route("/api/google-ads/accounts", methods=["POST"])
def google_ads_accounts():
    """获取可访问的子账户列表。"""
    try:
        from google_ads_service import list_accounts, GoogleAdsServiceError  # noqa: F811
    except ImportError:
        return jsonify({"success": False, "error": "Google Ads 功能仅在开发模式可用"}), 500
    data = request.get_json(silent=True) or {}
    cfg = {**_GOOGLE_ADS_CONFIG, **data}
    try:
        accounts = list_accounts(
            cfg["client_id"], cfg["client_secret"], cfg["refresh_token"],
            cfg["developer_token"], cfg["manager_id"],
        )
        return jsonify({"success": True, "accounts": accounts})
    except GoogleAdsServiceError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": f"未知错误: {e}"}), 500


@app.route("/api/google-ads/report", methods=["POST"])
def google_ads_report():
    """拉取广告系列报告。"""
    try:
        from google_ads_service import fetch_campaign_report, GoogleAdsServiceError  # noqa: F811
    except ImportError:
        return jsonify({"success": False, "error": "Google Ads 功能仅在开发模式可用"}), 500
    data = request.get_json(silent=True) or {}
    cfg = {**_GOOGLE_ADS_CONFIG, **data}
    account_id = data.get("account_id", "").strip()
    start_date = data.get("start_date", "").strip()
    end_date = data.get("end_date", "").strip()
    if not account_id:
        return jsonify({"success": False, "error": "请选择账号"}), 400
    if not start_date or not end_date:
        return jsonify({"success": False, "error": "请选择日期范围"}), 400
    try:
        results = fetch_campaign_report(
            cfg["client_id"], cfg["client_secret"], cfg["refresh_token"],
            cfg["developer_token"], cfg["manager_id"],
            account_id, start_date, end_date,
        )
        return jsonify({"success": True, "rows": results, "count": len(results)})
    except GoogleAdsServiceError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": f"未知错误: {e}"}), 500


# ---------- 文案管理 API ----------

@app.route("/api/copywriting/import", methods=["POST"])
@jwt_required()
def copywriting_import():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    region = (data.get("region") or "通用").strip()
    effectiveness = (data.get("effectiveness") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "请输入文案内容"}), 400

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return jsonify({"success": False, "error": "未解析到有效文案"}), 400

    db = _yt_db()
    for line in lines:
        db.execute(
            "INSERT INTO copywritings(region, content, owner_id, effectiveness) VALUES(?,?,?,?)",
            (region, line, user_id, effectiveness)
        )
    db.commit(); db.close()
    return jsonify({"success": True, "imported": len(lines)})


@app.route("/api/copywriting/list", methods=["GET"])
@jwt_required()
def copywriting_list():
    user_id = int(get_jwt_identity())
    region = request.args.get("region", "").strip()
    db = _yt_db()

    if region:
        rows = db.execute(
            "SELECT * FROM copywritings WHERE owner_id=? AND region=? "
            "ORDER BY CASE effectiveness WHEN '成效' THEN 0 ELSE 1 END, created_at DESC",
            (user_id, region)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM copywritings WHERE owner_id=? "
            "ORDER BY CASE effectiveness WHEN '成效' THEN 0 ELSE 1 END, created_at DESC",
            (user_id,)
        ).fetchall()

    items = [dict(r) for r in rows]
    counts = {}
    for item in items:
        r = item.get("region", "")
        counts[r] = counts.get(r, 0) + 1

    db.close()
    return jsonify({"success": True, "items": items, "counts": counts})


@app.route("/api/copywriting/edit", methods=["POST"])
@jwt_required()
def copywriting_edit():
    data = request.get_json(silent=True) or {}
    cid = data.get("id")
    if not cid:
        return jsonify({"success": False, "error": "未指定文案ID"}), 400
    db = _yt_db()
    for f in ["region", "content", "effectiveness"]:
        if f in data:
            db.execute(f"UPDATE copywritings SET {f}=? WHERE id=?", (data[f], cid))
    db.commit()
    row = db.execute("SELECT * FROM copywritings WHERE id=?", (cid,)).fetchone()
    db.close()
    return jsonify({"success": True, "item": dict(row)} if row else {"success": False, "error": "未找到"})


@app.route("/api/copywriting/delete", methods=["POST"])
@jwt_required()
def copywriting_delete():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"success": False, "error": "未指定文案"}), 400
    db = _yt_db()
    for cid in ids:
        db.execute("DELETE FROM copywritings WHERE id=?", (cid,))
    db.commit(); db.close()
    return jsonify({"success": True, "deleted": len(ids)})


@app.route("/api/copywriting/batch-edit", methods=["POST"])
@jwt_required()
def copywriting_batch_edit():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    region = (data.get("region") or "").strip()
    effectiveness = data.get("effectiveness")
    if not ids:
        return jsonify({"success": False, "error": "未指定文案ID"}), 400
    if not region and effectiveness is None:
        return jsonify({"success": False, "error": "请选择地区或成效标签"}), 400
    db = _yt_db()
    for cid in ids:
        if region:
            db.execute("UPDATE copywritings SET region=? WHERE id=?", (region, cid))
        if effectiveness is not None:
            db.execute("UPDATE copywritings SET effectiveness=? WHERE id=?", (effectiveness, cid))
    db.commit(); db.close()
    return jsonify({"success": True, "updated": len(ids)})


# ---------- 翻译 API ----------

@app.route("/api/translate", methods=["POST"])
def translate_text():
    """Google 翻译，基于 deep-translator。"""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    target = (data.get("target") or "zh-CN").strip()
    if not text:
        return jsonify({"success": False, "error": "请输入要翻译的文本"}), 400
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source='auto', target=target).translate(text)
        return jsonify({"success": True, "translated": result})
    except Exception as e:
        return jsonify({"success": False, "error": f"翻译失败: {str(e)}"}), 500


# ---------- 启动 ----------


# ---------- Auth Routes ----------

@jwt.invalid_token_loader
def invalid_token_callback(reason):
    return jsonify(success=False, error="Invalid token"), 401

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify(success=False, error="Token expired"), 401

@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json()
    if not data:
        return jsonify(success=False, error="Missing request body"), 400
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify(success=False, error="Username and password required"), 400
    result = auth.login_user(username, password)
    if not result:
        return jsonify(success=False, error="Invalid credentials or account disabled"), 401
    return jsonify(success=True, **result)

@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    data = request.get_json()
    if not data:
        return jsonify(success=False, error="Missing request body"), 400
    username = data.get("username", "").strip()
    password = data.get("password", "")
    display_name = data.get("display_name", "").strip()
    if not username or len(username) < 4 or len(username) > 20:
        return jsonify(success=False, error="Username must be 4-20 characters"), 400
    if not password or len(password) < 6:
        return jsonify(success=False, error="Password must be at least 6 characters"), 400
    existing = auth.get_user_by_username(username)
    if existing:
        return jsonify(success=False, error="Username already exists"), 409
    user = auth.register_user(username, password, display_name)
    if not user:
        return jsonify(success=False, error="Registration failed"), 500
    return jsonify(success=True, user=user)

@app.route("/api/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def auth_refresh():
    user_id = get_jwt_identity()
    new_token = create_access_token(identity=user_id)
    return jsonify(success=True, access_token=new_token)

@app.route("/api/auth/me", methods=["GET"])
@jwt_required()
def auth_me():
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user:
        return jsonify(success=False, error="User not found"), 404
    return jsonify(success=True, user=user)


@app.route("/api/auth/custom-name", methods=["GET"])
@jwt_required()
def auth_custom_name_get():
    user_id = int(get_jwt_identity())
    db = database.get_db()
    row = db.execute("SELECT custom_name FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    return jsonify({"success": True, "custom_name": row["custom_name"] if row else ""})


@app.route("/api/auth/custom-name", methods=["PUT"])
@jwt_required()
def auth_custom_name_set():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    custom_name = (data.get("custom_name") or "").strip()
    db = database.get_db()
    db.execute("UPDATE users SET custom_name=? WHERE id=?", (custom_name, user_id))
    db.commit()
    db.close()
    return jsonify({"success": True, "custom_name": custom_name})


@app.route("/api/users/names", methods=["GET"])
@jwt_required(optional=True)
def users_names():
    """返回所有用户的 id/username/display_name，供 runner 选择器使用。"""
    db = database.get_db()
    rows = db.execute(
        "SELECT id, username, display_name FROM users WHERE role != 'hidden' ORDER BY id"
    ).fetchall()
    db.close()
    return jsonify({"success": True, "users": [dict(r) for r in rows]})


@app.route("/api/admin/users/create", methods=["POST"])
@jwt_required()
def admin_create_user():
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user or user["role"] not in ("developer", "admin"):
        return jsonify(success=False, error="Permission denied"), 403
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    display_name = data.get("display_name", "").strip()
    role = data.get("role", "user")
    if not username or len(username) < 4 or len(username) > 20:
        return jsonify(success=False, error="Username must be 4-20 characters"), 400
    if not password or len(password) < 6:
        return jsonify(success=False, error="Password must be at least 6 characters"), 400
    if role not in ("user", "admin"):
        return jsonify(success=False, error="Invalid role"), 400
    existing = auth.get_user_by_username(username)
    if existing:
        return jsonify(success=False, error="Username already exists"), 409
    result = auth.create_user(username, password, role, display_name, created_by=user_id)
    if result:
        return jsonify(success=True, user=result)
    return jsonify(success=False, error="Create failed"), 500

# ---------- Admin: User Management ----------

@app.route("/api/admin/users", methods=["GET"])
@jwt_required()
def admin_list_users():
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user or user["role"] not in ("developer", "admin"):
        return jsonify(success=False, error="Permission denied"), 403
    search = request.args.get("search", "")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    result = auth.list_users(search, page, page_size, current_user_id=user_id)
    return jsonify(success=True, **result)


def _can_modify_user(actor: dict, target: dict) -> bool:
    """admin 只能操作 user/hidden，不能操作其他 admin。developer 不受限。"""
    if actor["role"] == "developer":
        return True
    return target["role"] in ("user", "hidden")


@app.route("/api/admin/users/<int:uid>/role", methods=["POST"])
@jwt_required()
def admin_update_role(uid):
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user or user["role"] not in ("developer", "admin"):
        return jsonify(success=False, error="Permission denied"), 403
    if uid == user_id:
        return jsonify(success=False, error="不能修改自己的角色"), 403
    target = auth.get_user_by_id(uid)
    if not target:
        return jsonify(success=False, error="User not found"), 404
    if not _can_modify_user(user, target):
        return jsonify(success=False, error="不能操作同级管理员"), 403
    data = request.get_json()
    new_role = data.get("role", "")
    if new_role not in ("user", "admin", "hidden"):
        return jsonify(success=False, error="Invalid role"), 400
    if auth.update_user_role(uid, new_role):
        return jsonify(success=True)
    return jsonify(success=False, error="Cannot modify developer account"), 400

@app.route("/api/admin/users/<int:uid>/toggle", methods=["POST"])
@jwt_required()
def admin_toggle_user(uid):
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user or user["role"] not in ("developer", "admin"):
        return jsonify(success=False, error="Permission denied"), 403
    if uid == user_id:
        return jsonify(success=False, error="不能禁用自己"), 403
    target = auth.get_user_by_id(uid)
    if not target:
        return jsonify(success=False, error="User not found"), 404
    if not _can_modify_user(user, target):
        return jsonify(success=False, error="不能操作同级管理员"), 403
    result = auth.toggle_user_status(uid)
    if result:
        return jsonify(success=True, user=result)
    return jsonify(success=False, error="Cannot toggle developer account"), 400

@app.route("/api/admin/users/<int:uid>", methods=["DELETE"])
@jwt_required()
def admin_delete_user(uid):
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user or user["role"] not in ("developer", "admin"):
        return jsonify(success=False, error="Permission denied"), 403
    if uid == user_id:
        return jsonify(success=False, error="Cannot delete yourself"), 400
    target = auth.get_user_by_id(uid)
    if not target:
        return jsonify(success=False, error="User not found"), 404
    if not _can_modify_user(user, target):
        return jsonify(success=False, error="不能操作同级管理员"), 403
    if target["role"] == "developer":
        return jsonify(success=False, error="Cannot delete developer account"), 400
    conn = database.get_db()
    try:
        # 先解除外键关联：将其他表中引用此用户的字段置空
        conn.execute("UPDATE users SET created_by = NULL WHERE created_by = ?", (uid,))
        conn.execute("UPDATE products SET owner_id = NULL WHERE owner_id = ?", (uid,))
        conn.execute("UPDATE accounts SET owner_id = NULL WHERE owner_id = ?", (uid,))
        conn.execute("UPDATE mcc SET owner_id = NULL WHERE owner_id = ?", (uid,))
        conn.execute("UPDATE videos SET owner_id = NULL WHERE owner_id = ?", (uid,))
        conn.execute("UPDATE copywritings SET owner_id = NULL WHERE owner_id = ?", (uid,))
        conn.execute("UPDATE scrape_cache SET scraped_by = NULL WHERE scraped_by = ?", (uid,))
        conn.execute("DELETE FROM import_history WHERE user_id = ?", (uid,))
        # 现在可以安全删除用户
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, error=f"删除失败: {str(e)}"), 500
    finally:
        conn.close()


@app.route("/api/admin/users/<int:uid>", methods=["PUT"])
@jwt_required()
def admin_update_user(uid):
    """编辑用户信息（用户名、显示名）。"""
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user or user["role"] not in ("developer", "admin"):
        return jsonify(success=False, error="Permission denied"), 403

    target = auth.get_user_by_id(uid)
    if not target:
        return jsonify(success=False, error="User not found"), 404
    # 非 developer 不能修改 developer 的信息
    if target["role"] == "developer" and user["role"] != "developer":
        return jsonify(success=False, error="Cannot modify developer account"), 400
    if not _can_modify_user(user, target):
        return jsonify(success=False, error="不能操作同级管理员"), 403

    data = request.get_json(silent=True) or {}
    username = data.get("username")
    display_name = data.get("display_name")

    if username is not None:
        username = username.strip()
        if len(username) < 4 or len(username) > 20:
            return jsonify(success=False, error="用户名需 4-20 个字符"), 400

    result = auth.update_user(uid, username=username, display_name=display_name)
    if result:
        return jsonify(success=True, user=result)
    return jsonify(success=False, error="用户名重复或更新失败"), 400


@app.route("/api/admin/users/<int:uid>/password", methods=["PUT"])
@jwt_required()
def admin_reset_password(uid):
    """管理员重置用户密码。"""
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    if not user or user["role"] not in ("developer", "admin"):
        return jsonify(success=False, error="Permission denied"), 403

    target = auth.get_user_by_id(uid)
    if not target:
        return jsonify(success=False, error="User not found"), 404
    # 非 developer 不能修改 developer 的密码
    if target["role"] == "developer" and user["role"] != "developer":
        return jsonify(success=False, error="Cannot modify developer account"), 400
    if not _can_modify_user(user, target):
        return jsonify(success=False, error="不能操作同级管理员"), 403

    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not password or len(password) < 6:
        return jsonify(success=False, error="密码至少 6 位"), 400

    if auth.update_password(uid, password):
        return jsonify(success=True)
    return jsonify(success=False, error="更新失败"), 400


@app.route("/api/auth/password", methods=["PUT"])
@jwt_required()
def auth_change_password():
    """用户自己修改密码。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if not old_password or not new_password:
        return jsonify(success=False, error="请提供旧密码和新密码"), 400
    if len(new_password) < 6:
        return jsonify(success=False, error="新密码至少 6 位"), 400

    current_user = auth.get_user_by_id(user_id)
    if not current_user:
        return jsonify(success=False, error="User not found"), 404
    # get_user_by_id 不含 password，通过 username 获取完整信息验证旧密码
    full_user = auth.get_user_by_username(current_user["username"])
    if not auth.verify_password(old_password, full_user["password"]):
        return jsonify(success=False, error="旧密码不正确"), 400

    if auth.update_password(user_id, new_password):
        return jsonify(success=True)
    return jsonify(success=False, error="更新失败"), 400


@app.route("/api/auth/profile", methods=["PUT"])
@jwt_required()
def auth_update_profile():
    """用户自己更新个人信息（显示名）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    display_name = data.get("display_name", "").strip()

    result = auth.update_user(user_id, username=None, display_name=display_name)
    if result:
        return jsonify(success=True, user=result)
    return jsonify(success=False, error="更新失败"), 400


# ---------- admin_required decorator ----------

def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = int(get_jwt_identity())
        user = auth.get_user_by_id(user_id)
        if not user or user["role"] not in ("developer", "admin"):
            return jsonify({"success": False, "error": "权限不足"}), 403
        return fn(*args, **kwargs)
    return wrapper


# ---------- Data Import/Export ----------

@app.route("/api/data/import", methods=["POST"])
@jwt_required()
def data_import():
    """上传 db 或 json 文件，导入数据到当前用户。"""
    user_id = int(get_jwt_identity())

    if "file" not in request.files:
        return jsonify({"success": False, "error": "请上传文件"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "error": "文件名为空"}), 400

    # 识别文件类型
    fname = file.filename.lower()
    if fname.endswith(".db"):
        file_type = "db"
    elif fname.endswith(".json"):
        file_type = "json"
    else:
        return jsonify({"success": False, "error": "仅支持 .db 或 .json 文件"}), 400

    # 保存临时文件
    import tempfile
    suffix = ".db" if file_type == "db" else ".json"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        report = data_service.execute_import(tmp_path, file_type, user_id)

        # 记录导入历史
        db = database.get_db()
        history_report = report.get("report", {})
        db.execute(
            "INSERT INTO import_history(user_id, file_name, file_type, "
            "products_count, packages_count, accounts_count, mcc_count, videos_count, "
            "copywritings_count, tags_count, skipped_count, status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, file.filename, file_type,
             history_report.get("products", 0),
             history_report.get("packages", 0),
             history_report.get("accounts", 0),
             history_report.get("mcc", 0),
             history_report.get("videos", 0),
             history_report.get("copywritings", {}).get("imported", 0),
             history_report.get("tags", {}).get("imported", 0),
             history_report.get("skipped_count", 0),
             "success")
        )
        db.commit()
        db.close()

        return jsonify(report)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.route("/api/data/export", methods=["GET"])
@jwt_required()
def data_export():
    """导出当前用户的数据为 JSON 文件下载。"""
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    username = user["username"] if user else str(user_id)

    export_data = data_service.export_user_data(user_id)

    from flask import Response
    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    filename = f"gg-server-export-{username}-{date_str}.json"

    return Response(
        json_str,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/api/data/import-history", methods=["GET"])
@jwt_required()
def data_import_history():
    """返回当前用户的导入历史（最近 10 条）。"""
    user_id = int(get_jwt_identity())
    db = database.get_db()
    rows = db.execute(
        "SELECT * FROM import_history WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify({"success": True, "history": [dict(r) for r in rows]})


@app.route("/api/admin/data/import", methods=["POST"])
@admin_required
def admin_data_import():
    """管理员为指定用户导入数据。"""
    user_id = request.form.get("user_id", type=int)
    if not user_id:
        return jsonify({"success": False, "error": "请指定目标用户"}), 400

    if "file" not in request.files:
        return jsonify({"success": False, "error": "请上传文件"}), 400

    file = request.files["file"]
    fname = file.filename.lower()
    file_type = "db" if fname.endswith(".db") else "json"

    import tempfile
    suffix = ".db" if file_type == "db" else ".json"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        report = data_service.execute_import(tmp_path, file_type, user_id)
        return jsonify(report)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.route("/api/admin/data/export/<int:uid>", methods=["GET"])
@admin_required
def admin_data_export(uid):
    """管理员导出指定用户的数据。"""
    user = auth.get_user_by_id(uid)
    if not user:
        return jsonify({"success": False, "error": "用户不存在"}), 404

    export_data = data_service.export_user_data(uid)

    from flask import Response
    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    filename = f"gg-server-export-{user['username']}-{date_str}.json"

    return Response(
        json_str,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5001
    print(f"服务已启动: http://{host}:{port}")
    print("在浏览器中打开上方地址即可使用。")
    # 自动打开浏览器
    # webbrowser.open(f"http://127.0.0.1:{port}")  # 调试时关闭自动打开
    app.run(host=host, port=port, debug=False, threaded=True)


