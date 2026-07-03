import os
import subprocess
import sys
import webbrowser

# 确保当前目录优先于 site-packages（解决 py 包名冲突）
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from flask import Flask, request, jsonify, send_file, send_from_directory
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
import requests
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

_SCRAPE_DEFAULT_DIR = os.path.join(_DATA_ROOT, "temp", "scraped_images")
_MUSIC_DIR = os.path.join(_DATA_ROOT, "temp", "music")

app = Flask(__name__, static_folder=_FRONTEND_DIR, static_url_path="")
CORS(app)

# --- 请求日志 ---
import time as _time
import threading

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
@jwt_required()
def scrape():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    url = data.get("url", "").strip()
    save_dir = data.get("save_dir", "").strip()
    if not save_dir:
        user = auth.get_user_by_id(user_id)
        dn = (user.get("display_name") or user.get("username") or f"user_{user_id}").strip()
        save_dir = os.path.join(_SCRAPE_DEFAULT_DIR, dn)
    # 新增参数：是否按 Google Ads 规格放大图片（默认 true，向后兼容）
    include_ads_images = data.get("include_ads_images", True)

    if not url:
        return jsonify({"success": False, "error": "URL 不能为空"}), 400

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


@app.route("/api/scrape/download", methods=["GET"])
def scrape_download():
    """将爬取的图片目录打包为 zip 下载。"""
    path = request.args.get("path", "").strip()
    if not path or not os.path.isdir(path):
        return jsonify({"success": False, "error": "目录不存在"}), 404
    pkg_name = os.path.basename(path)

    import zipfile
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(path):
            for fn in files:
                fp = os.path.join(root, fn)
                arcname = os.path.relpath(fp, path)
                zf.write(fp, arcname)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{pkg_name}.zip")


@app.route("/api/scrape/packages", methods=["GET"])
@jwt_required()
def scrape_packages():
    """列出已爬取包。管理员可传 user_dn 查看其他用户的包。"""
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    is_admin = user and user["role"] in ("developer", "admin")
    user_dn = request.args.get("user_dn", "").strip()
    if user_dn and is_admin:
        dn = user_dn
    else:
        dn = (user.get("display_name") or user.get("username") or f"user_{user_id}").strip()
    user_dir = os.path.join(_SCRAPE_DEFAULT_DIR, dn)
    packages = []
    if os.path.isdir(user_dir):
        for name in sorted(os.listdir(user_dir)):
            p = os.path.join(user_dir, name)
            if os.path.isdir(p) and name != "ai":
                pngs = [f for f in os.listdir(p) if f.lower().endswith('.png') and os.path.isfile(os.path.join(p, f))]
                if pngs:
                    packages.append({"name": name, "path": p, "image_count": len(pngs)})
    return jsonify({"success": True, "packages": packages})


@app.route("/api/scrape/users", methods=["GET"])
@jwt_required()
def scrape_users():
    """列出所有有爬取数据的用户（管理员用）。"""
    users = []
    if os.path.isdir(_SCRAPE_DEFAULT_DIR):
        for dn in sorted(os.listdir(_SCRAPE_DEFAULT_DIR)):
            p = os.path.join(_SCRAPE_DEFAULT_DIR, dn)
            if os.path.isdir(p) and dn != "ai":
                pkg_count = sum(1 for n in os.listdir(p) if os.path.isdir(os.path.join(p, n)) and n != "ai")
                users.append({"display_name": dn, "package_count": pkg_count})
    return jsonify({"success": True, "users": users})


@app.route("/api/scrape/upload-images", methods=["POST"])
@jwt_required()
def scrape_upload_images():
    """上传图片到用户专属目录，用于视频生成。"""
    user_id = int(get_jwt_identity())
    user = auth.get_user_by_id(user_id)
    dn = (user.get("display_name") or user.get("username") or f"user_{user_id}").strip()
    files = request.files.getlist("files")
    if not files or all(not f.filename for f in files):
        return jsonify({"success": False, "error": "未选择文件"}), 400

    import datetime as _dt
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_dir = os.path.join(_SCRAPE_DEFAULT_DIR, dn, f"_upload_{ts}")
    os.makedirs(upload_dir, exist_ok=True)

    images = []
    from PIL import Image as _PILImage
    for f in files:
        if not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp'):
            continue
        # 统一保存为 PNG
        safe_name = f.filename.rsplit('.', 1)[0].replace(' ', '_').replace('\\', '_').replace('/', '_')
        fp = os.path.join(upload_dir, f"{safe_name}.png")
        try:
            img = _PILImage.open(f.stream)
            img = img.convert("RGBA")
            img.save(fp, "PNG")
            images.append({"filename": f"{safe_name}.png", "path": fp.replace("\\", "/"),
                           "width": img.width, "height": img.height})
        except Exception as e:
            print(f"[Upload] 跳过 {f.filename}: {e}")

    return jsonify({"success": True, "saved_path": upload_dir.replace("\\", "/"),
                    "image_count": len(images), "images": images})


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
@jwt_required()
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


@app.route("/api/video/download", methods=["GET"])
def video_download():
    """下载已生成的视频文件。"""
    path = request.args.get("path", "").strip()
    if not path or not os.path.isfile(path):
        return jsonify({"success": False, "error": "文件不存在"}), 404
    return send_file(path, as_attachment=True)


@app.route("/api/video/music-list", methods=["GET"])
def video_music_list():
    """列出服务器上可用的背景音乐。"""
    os.makedirs(_MUSIC_DIR, exist_ok=True)
    files = []
    for fn in sorted(os.listdir(_MUSIC_DIR)):
        if fn.lower().endswith(('.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac')):
            fp = os.path.join(_MUSIC_DIR, fn)
            files.append({"name": fn, "path": fp})
    return jsonify({"success": True, "files": files})


@app.route("/api/video/upload-music", methods=["POST"])
def video_upload_music():
    """上传背景音乐到服务器。"""
    os.makedirs(_MUSIC_DIR, exist_ok=True)
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "error": "未选择文件"}), 400
    filename = f.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac'):
        return jsonify({"success": False, "error": "不支持的音频格式"}), 400
    fp = os.path.join(_MUSIC_DIR, filename)
    f.save(fp)
    return jsonify({"success": True, "name": filename, "path": fp})


@app.route("/api/audio", methods=["GET"])
def serve_audio():
    """音频流服务，供前端预览播放。"""
    path = request.args.get("path", "").strip()
    if not path or not os.path.isfile(path):
        return "", 404
    mt = "audio/mpeg" if path.lower().endswith('.mp3') else "audio/wav"
    return send_file(path, mimetype=mt)


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
            fonts.append({"id": fid, "name": name, "path": path, "source": "system"})

    # 用户导入的字体
    if os.path.isdir(_FONTS_DIR):
        for f in sorted(os.listdir(_FONTS_DIR)):
            if f.lower().endswith((".ttf", ".otf", ".ttc", ".woff", ".woff2")):
                fid = os.path.splitext(f)[0]
                fp = os.path.join(_FONTS_DIR, f)
                fonts.append({
                    "id": fid,
                    "name": fid.replace("_", " ").title(),
                    "path": fp.replace("\\", "/"),
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


@app.route("/api/fonts/upload", methods=["POST"])
def fonts_upload():
    """上传字体文件（不限制本机）。"""
    os.makedirs(_FONTS_DIR, exist_ok=True)
    files = request.files.getlist("files")
    if not files or all(not f.filename for f in files):
        return jsonify({"success": False, "error": "未选择文件"}), 400
    imported = 0
    for f in files:
        if not f.filename: continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ('.ttf', '.otf', '.ttc', '.woff', '.woff2'): continue
        dst = os.path.join(_FONTS_DIR, f.filename)
        if not os.path.isfile(dst):
            f.save(dst)
        imported += 1
    return jsonify({"success": True, "imported": imported, "fonts": _scan_fonts_dir()})


@app.route("/api/font-file", methods=["GET"])
def serve_font_file():
    """提供字体文件，供前端 CSS 预览加载。"""
    path = request.args.get("path", "").strip()
    if not path or not os.path.isfile(path):
        return "", 404
    mt = "font/ttf" if path.lower().endswith('.ttf') else "font/otf"
    return send_file(path, mimetype=mt)


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


def _batch_import_videos(db, urls, region="通用", frame_type="非融帧", effectiveness="",
                         product_name="", review_status="能过审", imported_at="",
                         user_id=0, is_public=0):
    """批量导入 YouTube 视频。先批量查库 → 并行 oEmbed → 批量 INSERT。
    返回 (imported: int, duplicates: list, results: list of (vid, title, is_new))"""
    import datetime as _dt
    import requests as _requests
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not urls:
        return 0, [], []

    # 1. 解析所有 video_id
    parsed = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        vid = _extract_youtube_id(url)
        if vid:
            parsed.append(vid)

    if not parsed:
        return 0, [], []

    # 2. 批量查库：哪些已存在
    placeholders = ",".join(["?"] * len(parsed))
    existing_rows = db.execute(
        f"SELECT id, title FROM videos WHERE id IN ({placeholders})", parsed
    ).fetchall()
    existing_ids = {r["id"] for r in existing_rows}
    existing_titles = {r["id"]: r["title"] for r in existing_rows}

    duplicates = [{"id": vid, "title": existing_titles.get(vid, vid)} for vid in parsed if vid in existing_ids]
    new_vids = [vid for vid in parsed if vid not in existing_ids]

    # 3. 并行 oEmbed 获取标题（只有新视频需要）
    titles = {}
    if new_vids:
        def _fetch_title(vid):
            try:
                r = _requests.get(
                    f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json",
                    timeout=8
                )
                if r.status_code == 200:
                    return vid, r.json().get("title", vid)
            except Exception:
                pass
            return vid, vid

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_title, vid): vid for vid in new_vids}
            for future in as_completed(futures):
                vid, title = future.result()
                titles[vid] = title

    # 4. 批量 INSERT 新视频
    ts = imported_at if imported_at else _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    imported = 0
    results = []
    for vid in parsed:
        if vid in existing_ids:
            results.append((vid, existing_titles.get(vid, vid), False))
        else:
            title = titles.get(vid, vid)
            db.execute(
                "INSERT INTO videos(id,url,title,region,frame_type,effectiveness,"
                "product_name,review_status,imported_at,owner_id,is_public) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (vid, f"https://www.youtube.com/watch?v={vid}", title, region,
                 frame_type, effectiveness, product_name, review_status,
                 ts, user_id, is_public)
            )
            imported += 1
            results.append((vid, title, True))

    return imported, duplicates, results


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
    imported, duplicates, _ = _batch_import_videos(
        db, urls, region=region, frame_type=frame_type, effectiveness=effectiveness,
        product_name=product_name, review_status=review_status, imported_at=imported_at,
        user_id=user_id, is_public=is_public
    )
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


def _can_modify(user_id, table, item_id):
    """检查用户是否有权编辑/删除某项。
    admin/developer 始终有权限；
    普通用户只能操作自己的项或 is_public=1 的项。
    返回 (can: bool, error: str|None)
    """
    user = auth.get_user_by_id(user_id)
    if user and user["role"] in ("developer", "admin"):
        return True, None
    db = _yt_db()
    try:
        row = db.execute(
            f"SELECT owner_id, is_public FROM {table} WHERE id=?", (item_id,)
        ).fetchone()
        if not row:
            return False, "记录不存在"
        if row["owner_id"] == user_id:
            return True, None
        if row["is_public"] == 1:
            return True, None
        return False, "无权限：仅可操作自己的或公开的内容"
    finally:
        db.close()


@app.route("/api/youtube/delete", methods=["POST"])
@jwt_required()
def youtube_delete():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids: return jsonify({"success": False, "error": "未指定视频"}), 400
    db = _yt_db()
    user = auth.get_user_by_id(user_id)
    is_admin = user and user["role"] in ("developer", "admin")
    deleted = 0
    for vid in ids:
        if is_admin:
            cur = db.execute("DELETE FROM videos WHERE id=?", (vid,))
        else:
            cur = db.execute("DELETE FROM videos WHERE id=? AND (owner_id=? OR is_public=1)", (vid, user_id))
        deleted += cur.rowcount
    db.commit(); db.close()
    return jsonify({"success": True, "deleted": deleted})


@app.route("/api/youtube/edit", methods=["POST"])
@jwt_required()
def youtube_edit():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    vid = (data.get("id") or "").strip()
    if not vid: return jsonify({"success": False, "error": "未指定视频ID"}), 400
    db = _yt_db()
    can, err = _can_modify(user_id, "videos", vid)
    if not can:
        db.close()
        return jsonify({"success": False, "error": err}), 403
    for f in ["region", "frame_type", "effectiveness", "product_name", "review_status", "is_public"]:
        if f in data: db.execute(f"UPDATE videos SET {f}=? WHERE id=?", (data[f], vid))
    db.commit()
    row = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    db.close()
    return jsonify({"success": True, "video": dict(row)} if row else {"success": False, "error": "未找到"})


@app.route("/api/youtube/batch-edit", methods=["POST"])
@jwt_required()
def youtube_batch_edit():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    field = (data.get("field") or "").strip()
    value = (data.get("value") or "").strip()
    if not ids:
        return jsonify({"success": False, "error": "未指定视频ID"}), 400
    if field not in ("region", "frame_type", "effectiveness", "product_name", "review_status", "is_public"):
        return jsonify({"success": False, "error": "无效字段"}), 400
    db = _yt_db()
    user = auth.get_user_by_id(user_id)
    is_admin = user and user["role"] in ("developer", "admin")
    updated = 0
    for vid in ids:
        if is_admin:
            cur = db.execute(f"UPDATE videos SET {field}=? WHERE id=?", (value, vid))
        else:
            cur = db.execute(
                f"UPDATE videos SET {field}=? WHERE id=? AND (owner_id=? OR is_public=1)",
                (value, vid, user_id)
            )
        updated += cur.rowcount
    db.commit()
    db.close()
    return jsonify({"success": True, "updated": updated})


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
        try:
            user_id = int(get_jwt_identity())
        except Exception:
            user_id = None
        if user_id:
            uid_s = str(user_id)
            where.append("(p.runner_ids = ? OR p.runner_ids LIKE ? OR p.runner_ids LIKE ? OR p.runner_ids LIKE ?)")
            params += [f"[{uid_s}]", f"[{uid_s},%", f"%, {uid_s},%", f"%, {uid_s}]"]
    elif runner == "all":
        pass
    elif runner.isdigit():
        uid_s = str(runner)
        where.append(
            "(p.runner_ids = ? OR p.runner_ids LIKE ? OR p.runner_ids LIKE ? OR "
            "p.runner_ids LIKE ? OR p.owner_id = ?)"
        )
        params += [f"[{uid_s}]", f"[{uid_s},%", f"%, {uid_s},%", f"%, {uid_s}]", int(runner)]
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
        # 成效素材数
        prod["asset_count"] = db.execute(
            "SELECT COUNT(*) FROM product_assets WHERE product_id=?", (r["id"],)
        ).fetchone()[0]
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
        uid_s = str(uid)
        runner_counts["mine"] = db.execute(
            f"SELECT COUNT(*) FROM products p WHERE (p.runner_ids = ? OR p.runner_ids LIKE ? OR p.runner_ids LIKE ? OR p.runner_ids LIKE ?) AND {stat_clause} AND (is_archived IS NULL OR is_archived = 0)",
            [f"[{uid_s}]", f"[{uid_s},%", f"%, {uid_s},%", f"%, {uid_s}]"] + stat_params_mine
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
    customer = (data.get("customer") or "").strip()
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
        db.execute("INSERT INTO products(product_name,kpi,region,mcc_id,customer,owner_id,runner_ids,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (product_name, kpi, region, mcc_id, customer, user_id, runner_ids, now))
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

    for f in ["product_name", "kpi", "region", "status", "mcc_id", "customer"]:
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
    uid_str = str(user_id)
    mcc_options = [dict(r) for r in db.execute(
        "SELECT id, name, mcc_id FROM mcc WHERE (owner_id=? OR shared_user_ids=? OR "
        "shared_user_ids LIKE ? OR shared_user_ids LIKE ? OR shared_user_ids LIKE ?) ORDER BY name",
        (user_id, f"[{uid_str}]", f"[{uid_str},%", f"%, {uid_str},%", f"%, {uid_str}]")
    ).fetchall()]
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


@app.route("/api/config/ai", methods=["GET"])
@jwt_required()
def config_ai_get():
    """读取 AI 分析配置（按用户隔离）。"""
    user_id = int(get_jwt_identity())
    db = _yt_db()
    row = db.execute(f"SELECT value FROM config WHERE key='ai_analysis_{user_id}'").fetchone()
    db.close()
    if row:
        try:
            cfg = json.loads(row["value"])
        except Exception:
            cfg = {"enabled": False, "provider": "volcano", "model": "deepseek-v4-flash", "api_key": "", "endpoint": "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"}
    else:
        cfg = {"enabled": False, "provider": "volcano", "model": "deepseek-v4-flash", "api_key": "", "endpoint": "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"}
    return jsonify({"success": True, "config": cfg})


@app.route("/api/config/ai", methods=["POST"])
@jwt_required()
def config_ai_save():
    """保存 AI 分析配置（按用户隔离）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    cfg = {
        "enabled": bool(data.get("enabled", False)),
        "provider": data.get("provider", "volcano"),
        "model": data.get("model", "deepseek-v4-flash"),
        "api_key": data.get("api_key", ""),
        "endpoint": data.get("endpoint", "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"),
    }
    db = _yt_db()
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
               (f"ai_analysis_{user_id}", json.dumps(cfg, ensure_ascii=False)))
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



def _can_browse():
    """检查用户是否有权触发文件对话框（本机访问或管理员）。"""
    if _is_local_request():
        return True
    try:
        user_id = int(get_jwt_identity())
    except Exception:
        return False
    user = auth.get_user_by_id(user_id)
    return user and user["role"] in ("developer", "admin")


@app.route("/api/browse-file", methods=["POST"])
@jwt_required(optional=True)
def browse_file():
    """打开本地文件选择对话框，返回选中路径。"""
    if not _can_browse():
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
@jwt_required(optional=True)
def browse_save():
    """打开文件保存对话框。"""
    if not _can_browse():
        return jsonify({"success": False, "error": "仅允许本机访问"}), 403
    data = request.get_json(silent=True) or {}
    initial_dir = data.get("initial_dir") or None
    path = _native_save_dialog(initial_dir=initial_dir)
    if path:
        return jsonify({"success": True, "path": path.replace("\\", "/")})
    return jsonify({"success": True, "path": ""})


@app.route("/api/browse-folder", methods=["POST"])
@jwt_required(optional=True)
def browse_folder():
    """打开文件夹选择对话框。"""
    if not _can_browse():
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
    is_public = data.get("is_public", 0)
    if not text:
        return jsonify({"success": False, "error": "请输入文案内容"}), 400

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return jsonify({"success": False, "error": "未解析到有效文案"}), 400

    db = _yt_db()
    for line in lines:
        db.execute(
            "INSERT INTO copywritings(region, content, owner_id, effectiveness, is_public) VALUES(?,?,?,?,?)",
            (region, line, user_id, effectiveness, is_public)
        )
    db.commit(); db.close()
    return jsonify({"success": True, "imported": len(lines)})


@app.route("/api/copywriting/list", methods=["GET"])
@jwt_required()
def copywriting_list():
    user_id = int(get_jwt_identity())
    region = request.args.get("region", "").strip()
    scope = request.args.get("scope", "private").strip()
    db = _yt_db()

    where = []; params = []
    if scope == "public":
        where.append("cw.is_public = 1")
    elif scope == "private":
        where.append("cw.owner_id = ?"); params.append(user_id)
    else:
        where.append("(cw.is_public = 1 OR cw.owner_id = ?)"); params.append(user_id)

    if region:
        where.append("cw.region = ?"); params.append(region)

    sql = "SELECT cw.* FROM copywritings cw"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE cw.effectiveness WHEN '成效' THEN 0 ELSE 1 END, cw.created_at DESC"

    rows = db.execute(sql, params).fetchall()
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
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    cid = data.get("id")
    if not cid:
        return jsonify({"success": False, "error": "未指定文案ID"}), 400
    db = _yt_db()
    can, err = _can_modify(user_id, "copywritings", cid)
    if not can:
        db.close()
        return jsonify({"success": False, "error": err}), 403
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
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"success": False, "error": "未指定文案"}), 400
    db = _yt_db()
    user = auth.get_user_by_id(user_id)
    is_admin = user and user["role"] in ("developer", "admin")
    deleted = 0
    for cid in ids:
        if is_admin:
            cur = db.execute("DELETE FROM copywritings WHERE id=?", (cid,))
        else:
            cur = db.execute("DELETE FROM copywritings WHERE id=? AND (owner_id=? OR is_public=1)", (cid, user_id))
        deleted += cur.rowcount
    db.commit(); db.close()
    return jsonify({"success": True, "deleted": deleted})


@app.route("/api/copywriting/batch-edit", methods=["POST"])
@jwt_required()
def copywriting_batch_edit():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    region = (data.get("region") or "").strip()
    effectiveness = data.get("effectiveness")
    if not ids:
        return jsonify({"success": False, "error": "未指定文案ID"}), 400
    if not region and effectiveness is None:
        return jsonify({"success": False, "error": "请选择地区或成效标签"}), 400
    db = _yt_db()
    user = auth.get_user_by_id(user_id)
    is_admin = user and user["role"] in ("developer", "admin")
    updated = 0
    for cid in ids:
        if is_admin:
            if region:
                db.execute("UPDATE copywritings SET region=? WHERE id=?", (region, cid))
            if effectiveness is not None:
                db.execute("UPDATE copywritings SET effectiveness=? WHERE id=?", (effectiveness, cid))
            updated += 1
        else:
            cur = None
            if region:
                cur = db.execute(
                    "UPDATE copywritings SET region=? WHERE id=? AND (owner_id=? OR is_public=1)",
                    (region, cid, user_id)
                )
            if effectiveness is not None:
                cur = db.execute(
                    "UPDATE copywritings SET effectiveness=? WHERE id=? AND (owner_id=? OR is_public=1)",
                    (effectiveness, cid, user_id)
                )
            if cur and cur.rowcount > 0:
                updated += 1
    db.commit(); db.close()
    return jsonify({"success": True, "updated": updated})


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
        "SELECT id, username, display_name FROM users WHERE role NOT IN ('hidden','user') ORDER BY id"
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


def _start_weekly_cleanup():
    """每周日 24:00 清理爬取图片和生成视频（音乐库保留）。"""
    import datetime as _dt
    import shutil as _shutil

    def _cleanup():
        while True:
            now = _dt.datetime.now()
            # 计算下个周日 00:00
            days_until_sunday = (6 - now.weekday()) % 7
            if days_until_sunday == 0:
                # 今天是周日，看是否已过 24:00
                pass
            next_sunday = now.replace(hour=0, minute=0, second=0, microsecond=0) + _dt.timedelta(days=(days_until_sunday or 7))
            wait = (next_sunday - now).total_seconds()
            if wait > 0:
                _time.sleep(wait)

            # 清理 scraped_images（含 ai 子目录）
            for d in [_SCRAPE_DEFAULT_DIR]:
                if os.path.isdir(d):
                    _shutil.rmtree(d)
                    os.makedirs(d, exist_ok=True)
            # 恢复 ai 子目录
            ai_dir = os.path.join(_SCRAPE_DEFAULT_DIR, "ai")
            os.makedirs(ai_dir, exist_ok=True)
            print(f"[Cleanup] 已清理爬取图片和视频: {_dt.datetime.now()}")

    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()


# ============================================================
#  产品成效素材 API
# ============================================================

@app.route("/api/products/<int:pid>/assets", methods=["GET"])
@jwt_required()
def product_assets_list(pid):
    """获取产品下所有成效素材（按 added_by 分组顺序）。"""
    db = _yt_db()
    rows = db.execute("""
        SELECT v.*, pa.added_by, pa.added_at, u.display_name AS added_by_name
        FROM product_assets pa
        JOIN videos v ON pa.video_id = v.id
        LEFT JOIN users u ON pa.added_by = u.id
        WHERE pa.product_id = ?
        ORDER BY pa.added_by, pa.added_at DESC
    """, (pid,)).fetchall()
    db.close()
    return jsonify({"success": True, "assets": [dict(r) for r in rows]})


@app.route("/api/products/<int:pid>/assets", methods=["POST"])
@jwt_required()
def product_assets_add(pid):
    """向产品添加成效素材（批量导入 YouTube 视频 + 建立关联）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    urls = data.get("urls") or []
    region = (data.get("region") or "通用").strip()
    frame_type = (data.get("frame_type") or "非融帧").strip()
    effectiveness = (data.get("effectiveness") or "").strip()
    product_name = (data.get("product_name") or "").strip()
    review_status = (data.get("review_status") or "能过审").strip()

    if not urls:
        return jsonify({"success": False, "error": "请输入至少一个链接"}), 400

    # 检查产品是否存在
    db = _yt_db()
    prod = db.execute("SELECT id, product_name, region FROM products WHERE id=?", (pid,)).fetchone()
    if not prod:
        db.close()
        return jsonify({"success": False, "error": "产品不存在"}), 404

    # 使用产品名（如果未指定）
    pname = product_name or prod["product_name"] or ""

    # 批量导入视频到 videos 表
    imported, duplicates, results = _batch_import_videos(
        db, urls, region=region, frame_type=frame_type, effectiveness=effectiveness,
        product_name=pname, review_status=review_status, user_id=user_id, is_public=0
    )

    # 建立 product_assets 关联
    asset_imported = 0
    asset_dupes = []
    for vid, title, _ in results:
        existing = db.execute(
            "SELECT id FROM product_assets WHERE product_id=? AND video_id=?",
            (pid, vid)
        ).fetchone()
        if existing:
            asset_dupes.append({"id": vid, "title": title})
        else:
            db.execute(
                "INSERT INTO product_assets(product_id, video_id, added_by) VALUES(?,?,?)",
                (pid, vid, user_id)
            )
            asset_imported += 1

    db.commit(); db.close()
    return jsonify({
        "success": True,
        "imported": asset_imported,
        "duplicates": asset_dupes
    })


@app.route("/api/products/<int:pid>/assets/<video_id>", methods=["DELETE"])
@jwt_required()
def product_assets_delete(pid, video_id):
    """移除产品的成效素材关联（不删除 videos 表中的视频）。"""
    db = _yt_db()
    db.execute("DELETE FROM product_assets WHERE product_id=? AND video_id=?", (pid, video_id))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/youtube/asset-products", methods=["GET"])
@jwt_required()
def youtube_asset_products():
    """返回有成效素材的产品名列表（用于筛选下拉框）。"""
    db = _yt_db()
    rows = db.execute("""
        SELECT DISTINCT p.product_name
        FROM product_assets pa
        JOIN products p ON pa.product_id = p.id
        ORDER BY p.product_name
    """).fetchall()
    db.close()
    return jsonify({"success": True, "products": [r["product_name"] for r in rows]})


@app.route("/api/youtube/product-assets", methods=["GET"])
@jwt_required()
def youtube_product_assets():
    """批量查询视频关联的产品名（全表扫描，不限用户/可见性）。"""
    ids_str = request.args.get("video_ids", "").strip()
    if not ids_str:
        return jsonify({"success": True, "mapping": {}})
    video_ids = [v.strip() for v in ids_str.split(",") if v.strip()]
    if not video_ids:
        return jsonify({"success": True, "mapping": {}})

    db = _yt_db()
    placeholders = ",".join(["?"] * len(video_ids))
    rows = db.execute(
        f"SELECT pa.video_id, p.product_name FROM product_assets pa "
        f"JOIN products p ON pa.product_id = p.id "
        f"WHERE pa.video_id IN ({placeholders})",
        video_ids
    ).fetchall()
    db.close()

    mapping = {}
    for r in rows:
        vid = r["video_id"]
        pname = r["product_name"]
        if vid not in mapping:
            mapping[vid] = []
        if pname not in mapping[vid]:
            mapping[vid].append(pname)

    return jsonify({"success": True, "mapping": mapping})


# ============================================================
#  做表数据保存 + 分析 API
# ============================================================

@app.route("/api/ad-reports/products", methods=["GET"])
@jwt_required()
def ad_reports_products():
    """返回当前用户有权限的产品（用于保存弹窗下拉）。"""
    user_id = int(get_jwt_identity())
    db = _yt_db()
    rows = db.execute("""
        SELECT DISTINCT p.id, p.product_name, p.region
        FROM products p
        WHERE (p.is_archived IS NULL OR p.is_archived = 0)
          AND (p.status IS NULL OR p.status = '' OR p.status = '0')
          AND (p.owner_id = ? OR p.runner_ids LIKE '%' || ? || '%')
        ORDER BY p.product_name
    """, (user_id, str(user_id))).fetchall()
    db.close()
    return jsonify({"success": True, "products": [dict(r) for r in rows]})


@app.route("/api/ad-reports/check-duplicates", methods=["POST"])
@jwt_required()
def ad_reports_check_duplicates():
    """检查即将保存的数据中哪些行与已有数据重复。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    product_name = (data.get("product_name") or "").strip()
    report_date = (data.get("report_date") or "").strip()
    rows = data.get("rows") or []

    if not product_name or not rows:
        return jsonify({"success": True, "duplicates": []})

    db = _yt_db()
    duplicates = []
    for incoming in rows:
        customer_id = str(incoming.get("customerId", "")).strip()
        campaign = str(incoming.get("campaign", "")).strip()
        if not customer_id or not campaign:
            continue
        existing = db.execute(
            "SELECT * FROM ad_reports WHERE user_id=? AND product_name=? "
            "AND customer_id=? AND campaign=? AND report_date=?",
            (user_id, product_name, customer_id, campaign, report_date)
        ).fetchone()
        if existing:
            duplicates.append({
                "existing": dict(existing),
                "incoming": incoming
            })
    db.close()
    return jsonify({"success": True, "duplicates": duplicates})


def _auto_link_mcc_and_accounts(db, user_id, product_name, region, rows):
    """保存数据时自动关联 MCC、账户、地区时区。"""
    # 1. 查询产品 MCC
    prod = db.execute(
        "SELECT mcc_id, region FROM products WHERE product_name=? LIMIT 1",
        (product_name,)
    ).fetchone()
    mcc_id = prod["mcc_id"] if prod else None
    prod_region = (prod["region"] if prod else "") or region

    # 2. 地区写入 regions（如不存在）
    if prod_region:
        existing_region = db.execute(
            "SELECT id FROM regions WHERE name=?", (prod_region,)
        ).fetchone()
        if not existing_region:
            # 尝试用预设时区
            from database import _DEFAULT_TIMEZONES
            tz = _DEFAULT_TIMEZONES.get(prod_region, "")
            db.execute(
                "INSERT OR IGNORE INTO regions(name, timezone) VALUES(?,?)",
                (prod_region, tz)
            )

    # 3. MCC 关联用户
    if mcc_id:
        mcc = db.execute(
            "SELECT id, owner_id, shared_user_ids, mcc_id FROM mcc WHERE id=?",
            (mcc_id,)
        ).fetchone()
        if mcc:
            try:
                shared = json.loads(mcc["shared_user_ids"] or "[]")
            except Exception:
                shared = []
            if user_id != mcc["owner_id"] and user_id not in shared:
                shared.append(user_id)
                db.execute(
                    "UPDATE mcc SET shared_user_ids=? WHERE id=?",
                    (json.dumps(shared), mcc["id"])
                )

            # 4. 广告账户自动创建（从 rows 提取 account→name, customerId→account_id）
            seen_accounts = set()
            for row in rows:
                account_name = str(row.get("account", "")).strip()
                account_id = str(row.get("customerId", "")).strip()
                if not account_name or not account_id:
                    continue
                key = (account_id, mcc_id)
                if key in seen_accounts:
                    continue
                seen_accounts.add(key)
                existing_acc = db.execute(
                    "SELECT id, mcc_id FROM accounts WHERE account_id=?",
                    (account_id,)
                ).fetchone()
                if not existing_acc:
                    db.execute(
                        "INSERT OR IGNORE INTO accounts(name, account_id, mcc_id, owner_id) "
                        "VALUES(?,?,?,?)",
                        (account_name, account_id, mcc_id, user_id)
                    )
                elif existing_acc["mcc_id"] != mcc_id and mcc_id:
                    # 同 account_id 但不同 mcc_id：更新 mcc
                    db.execute(
                        "UPDATE accounts SET mcc_id=? WHERE account_id=?",
                        (mcc_id, account_id)
                    )


@app.route("/api/ad-reports/save", methods=["POST"])
@jwt_required()
def ad_reports_save():
    """保存做表数据（含自动关联 MCC/账户/时区）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    product_name = (data.get("product_name") or "").strip()
    region = (data.get("region") or "").strip()
    report_date = (data.get("report_date") or "").strip()
    rows = data.get("rows") or []
    override_ids = data.get("override_ids") or []

    if not product_name:
        return jsonify({"success": False, "error": "请选择产品"}), 400
    if not region:
        return jsonify({"success": False, "error": "请填写地区"}), 400
    if not report_date:
        return jsonify({"success": False, "error": "请选择日期"}), 400
    if not rows:
        return jsonify({"success": False, "error": "没有数据"}), 400

    db = _yt_db()

    # 自动关联 MCC / 账户 / 时区
    _auto_link_mcc_and_accounts(db, user_id, product_name, region, rows)
    db.commit()  # 提交自动关联的写入

    # 处理覆盖：删除被选定覆盖的旧行
    override_set = set(override_ids)
    if override_set:
        placeholders = ",".join(["?"] * len(override_set))
        db.execute(
            f"DELETE FROM ad_reports WHERE id IN ({placeholders}) AND user_id=?",
            list(override_set) + [user_id]
        )

    # === 聚合步骤（新增）：按 (report_date, product_name, account, customer_id, campaign) SUM ===
    raw_count = len(rows)
    aggregated = {}
    for row in rows:
        account = str(row.get("account", "")).strip()
        customer_id = str(row.get("customerId", "")).strip()
        campaign = str(row.get("campaign", "")).strip()
        if not customer_id or not campaign:
            continue

        key = (report_date, product_name, account, customer_id, campaign)
        if key not in aggregated:
            aggregated[key] = {
                "account": account,
                "customer_id": customer_id,
                "campaign": campaign,
                "cost": float(row.get("cost", 0) or 0),
                "impressions": int(row.get("impressions", 0) or 0),
                "clicks": int(row.get("clicks", 0) or 0),
                "installs": float(row.get("installs", 0) or 0),
                "in_app_actions": float(row.get("inAppActions", 0) or 0),
                "cost_per_in_app": float(row.get("costPerInApp", 0) or 0),
            }
        else:
            existing = aggregated[key]
            existing["cost"] += float(row.get("cost", 0) or 0)
            existing["impressions"] += int(row.get("impressions", 0) or 0)
            existing["clicks"] += int(row.get("clicks", 0) or 0)
            existing["installs"] += float(row.get("installs", 0) or 0)
            existing["in_app_actions"] += float(row.get("inAppActions", 0) or 0)
            existing["cost_per_in_app"] += float(row.get("costPerInApp", 0) or 0)

    # === upsert 逻辑（替换原有 skip 逻辑）===
    saved = 0
    skipped = 0
    for key, agg_row in aggregated.items():
        _rdate, _pname, account, customer_id, campaign = key

        # 查询是否已有同维度记录
        existing = db.execute(
            "SELECT id, cost, impressions, clicks, installs, in_app_actions, cost_per_in_app "
            "FROM ad_reports WHERE user_id=? AND product_name=? "
            "AND account=? AND customer_id=? AND campaign=? AND report_date=?",
            (user_id, product_name, account, customer_id, campaign, report_date)
        ).fetchone()

        if existing and existing["id"] not in override_set:
            # 已存在 → UPDATE 累加
            db.execute(
                "UPDATE ad_reports SET "
                "cost = cost + ?, impressions = impressions + ?, clicks = clicks + ?, "
                "installs = installs + ?, in_app_actions = in_app_actions + ?, "
                "cost_per_in_app = cost_per_in_app + ?, saved_at = datetime('now','localtime') "
                "WHERE id=?",
                (agg_row["cost"], agg_row["impressions"], agg_row["clicks"],
                 agg_row["installs"], agg_row["in_app_actions"], agg_row["cost_per_in_app"],
                 existing["id"])
            )
            saved += 1
        elif existing and existing["id"] in override_set:
            # 旧记录已被 override 删除 → INSERT 新记录
            db.execute(
                "INSERT INTO ad_reports(user_id, product_name, region, report_date, "
                "account, customer_id, campaign, cost, impressions, clicks, installs, "
                "in_app_actions, cost_per_in_app) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, product_name, region, report_date,
                 account, customer_id, campaign,
                 agg_row["cost"], agg_row["impressions"], agg_row["clicks"],
                 agg_row["installs"], agg_row["in_app_actions"], agg_row["cost_per_in_app"])
            )
            saved += 1
        else:
            # 不存在 → INSERT
            db.execute(
                "INSERT INTO ad_reports(user_id, product_name, region, report_date, "
                "account, customer_id, campaign, cost, impressions, clicks, installs, "
                "in_app_actions, cost_per_in_app) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, product_name, region, report_date,
                 account, customer_id, campaign,
                 agg_row["cost"], agg_row["impressions"], agg_row["clicks"],
                 agg_row["installs"], agg_row["in_app_actions"], agg_row["cost_per_in_app"])
            )
            saved += 1

    db.commit()
    db.close()
    return jsonify({
        "success": True,
        "saved": saved,
        "skipped": skipped,
        "aggregated_from": raw_count
    })


@app.route("/api/ad-reports/list", methods=["GET"])
@jwt_required()
def ad_reports_list():
    """列出当前用户的做表数据。"""
    user_id = int(get_jwt_identity())
    product_name = request.args.get("product_name", "").strip()
    report_date = request.args.get("report_date", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 50))

    db = _yt_db()
    where = ["user_id=?"]; params = [user_id]
    if product_name:
        where.append("product_name=?"); params.append(product_name)
    if report_date:
        where.append("report_date=?"); params.append(report_date)
    if from_date:
        where.append("report_date >= ?"); params.append(from_date)
    if to_date:
        where.append("report_date <= ?"); params.append(to_date)

    total = db.execute(
        f"SELECT COUNT(*) FROM ad_reports WHERE {' AND '.join(where)}", params
    ).fetchone()[0]

    offset = (page - 1) * size
    rows = db.execute(
        f"SELECT * FROM ad_reports WHERE {' AND '.join(where)} "
        f"ORDER BY saved_at DESC LIMIT ? OFFSET ?",
        params + [size, offset]
    ).fetchall()

    # 聚合的产品和地区列表
    products = [r[0] for r in db.execute(
        "SELECT DISTINCT product_name FROM ad_reports WHERE user_id=? ORDER BY product_name",
        (user_id,)
    ).fetchall()]
    regions = [r[0] for r in db.execute(
        "SELECT DISTINCT region FROM ad_reports WHERE user_id=? AND region!='' ORDER BY region",
        (user_id,)
    ).fetchall()]

    db.close()
    return jsonify({
        "success": True,
        "reports": [dict(r) for r in rows],
        "total": total,
        "products": products,
        "regions": regions
    })


@app.route("/api/ad-reports/<int:report_id>", methods=["PUT"])
@jwt_required()
def ad_reports_update(report_id):
    """编辑单条报告（仅 owner）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    db = _yt_db()

    # 确认记录存在且属于当前用户
    existing = db.execute(
        "SELECT id FROM ad_reports WHERE id=? AND user_id=?",
        (report_id, user_id)
    ).fetchone()
    if not existing:
        db.close()
        return jsonify({"success": False, "error": "记录不存在或无权操作"}), 404

    # 允许更新的字段
    updatable = [
        "product_name", "region", "report_date", "account",
        "customer_id", "campaign", "cost", "impressions",
        "clicks", "installs", "in_app_actions"
    ]
    sets = []
    params = []
    for field in updatable:
        if field in data:
            val = data[field]
            if field in ("cost", "installs", "in_app_actions"):
                val = float(val) if val != "" else 0.0
            elif field in ("impressions", "clicks"):
                val = int(val) if val != "" else 0
            else:
                val = str(val).strip() if val else ""
            sets.append(f"{field}=?")
            params.append(val)

    if not sets:
        db.close()
        return jsonify({"success": False, "error": "没有可更新的字段"}), 400

    params.append(report_id)
    db.execute(
        f"UPDATE ad_reports SET {', '.join(sets)}, saved_at=datetime('now','localtime') WHERE id=?",
        params
    )
    db.commit()
    db.close()
    return jsonify({"success": True})


@app.route("/api/ad-reports/<int:report_id>", methods=["DELETE"])
@jwt_required()
def ad_reports_delete(report_id):
    """删除单条报告（仅 owner）。"""
    user_id = int(get_jwt_identity())
    db = _yt_db()
    db.execute("DELETE FROM ad_reports WHERE id=? AND user_id=?", (report_id, user_id))
    db.commit(); db.close()
    return jsonify({"success": True})


@app.route("/api/ad-reports/dashboard", methods=["GET"])
@jwt_required()
def ad_reports_dashboard():
    """仪表盘概览：聚合指标 + 环比 + 异常检测。"""
    user_id = int(get_jwt_identity())
    product_name = request.args.get("product_name", "").strip()
    region = request.args.get("region", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()

    db = _yt_db()
    where = ["user_id=?"]; params = [user_id]
    if product_name:
        where.append("product_name=?"); params.append(product_name)
    if region:
        where.append("region=?"); params.append(region)
    if from_date:
        where.append("report_date >= ?"); params.append(from_date)
    if to_date:
        where.append("report_date <= ?"); params.append(to_date)

    where_clause = " AND ".join(where)

    # 当前周期
    current = db.execute(
        f"SELECT SUM(cost) AS total_cost, SUM(impressions) AS total_impressions, "
        f"SUM(clicks) AS total_clicks, SUM(installs) AS total_installs, "
        f"SUM(in_app_actions) AS total_in_app, "
        f"COUNT(*) AS row_count "
        f"FROM ad_reports WHERE {where_clause}", params
    ).fetchone()

    # 查产品 KPI
    product_kpi = None
    if product_name:
        prod = db.execute(
            "SELECT kpi FROM products WHERE product_name=? LIMIT 1", (product_name,)
        ).fetchone()
        if prod and prod["kpi"]:
            try:
                product_kpi = float(prod["kpi"])
            except (ValueError, TypeError):
                pass

    total_cost = current["total_cost"] or 0
    total_impressions = current["total_impressions"] or 0
    total_clicks = current["total_clicks"] or 0
    total_installs = current["total_installs"] or 0
    total_in_app = current["total_in_app"] or 0
    avg_cpi = round(total_cost / max(total_in_app, 1), 2)
    avg_ctr = round(total_clicks / max(total_impressions, 1), 4)
    avg_cvr = round(total_installs / max(total_clicks, 1), 4)
    summary = {
        "total_cost": round(total_cost, 2),
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "total_installs": total_installs,
        "total_in_app": round(total_in_app, 2),
        "avg_cpi": avg_cpi,
        "avg_ctr": avg_ctr,
        "avg_cvr": avg_cvr,
        "product_kpi": product_kpi,
        "kpi_met": (product_kpi is not None and avg_cpi <= product_kpi),
    }

    # 异常检测：每个系列近3天 vs 前7天均值
    anomalies = []
    all_campaigns = db.execute(
        f"SELECT DISTINCT campaign FROM ad_reports WHERE {where_clause} ORDER BY campaign",
        params
    ).fetchall()

    for c in all_campaigns:
        cname = c["campaign"]
        cparams = params + [cname]
        cwhere = f"{where_clause} AND campaign=?"
        stats = db.execute(
            f"SELECT report_date, SUM(cost) AS day_cost, SUM(installs) AS day_installs, "
            f"SUM(in_app_actions) AS day_in_app "
            f"FROM ad_reports WHERE {cwhere} "
            f"GROUP BY report_date ORDER BY report_date DESC",
            cparams
        ).fetchall()

        if len(stats) < 3:
            continue
        # 最近3天
        recent = stats[:3]
        # 前7天（排除最近3天）
        older = stats[3:10]
        if not older:
            continue

        avg_recent_cost = sum(s["day_cost"] or 0 for s in recent) / len(recent)
        avg_older_cost = sum(s["day_cost"] or 0 for s in older) / len(older)
        avg_recent_installs = sum(s["day_installs"] or 0 for s in recent) / len(recent)
        avg_older_installs = sum(s["day_installs"] or 0 for s in older) / len(older)
        recent_cost_sum = sum(s["day_cost"] or 0 for s in recent)
        recent_in_app_sum = sum(s["day_in_app"] or 0 for s in recent)
        older_cost_sum = sum(s["day_cost"] or 0 for s in older)
        older_in_app_sum = sum(s["day_in_app"] or 0 for s in older)
        avg_recent_cpi = recent_cost_sum / max(recent_in_app_sum, 1)
        avg_older_cpi = older_cost_sum / max(older_in_app_sum, 1)

        # 花费暴涨 > 50% 但安装下降
        if avg_older_cost > 0 and avg_recent_cost > avg_older_cost * 1.5 and avg_recent_installs < avg_older_installs:
            anomalies.append({
                "campaign": cname, "date": recent[0]["report_date"],
                "type": "cost_spike",
                "detail": f"花费暴涨{round((avg_recent_cost/avg_older_cost - 1)*100)}%，安装下降{round((1 - avg_recent_installs/max(avg_older_installs, 1))*100)}%"
            })
        # CPI 飙升 > 30%
        if avg_older_cpi > 0 and avg_recent_cpi > avg_older_cpi * 1.3:
            anomalies.append({
                "campaign": cname, "date": recent[0]["report_date"],
                "type": "cpi_spike",
                "detail": f"CPI 飙升至 ${round(avg_recent_cpi, 2)}（均值 ${round(avg_older_cpi, 2)}）"
            })

    # 环比计算：比较前一个等长周期
    period_compare = {}
    if from_date and to_date:
        try:
            from datetime import datetime as _dt, timedelta as _td
            fd = _dt.strptime(from_date, "%Y-%m-%d")
            td = _dt.strptime(to_date, "%Y-%m-%d")
            days = (td - fd).days + 1
            prev_from = (fd - _td(days=days)).strftime("%Y-%m-%d")
            prev_to = (fd - _td(days=1)).strftime("%Y-%m-%d")

            prev_where = "user_id=?"
            prev_params = [user_id]
            if product_name:
                prev_where += " AND product_name=?"
                prev_params.append(product_name)
            if region:
                prev_where += " AND region=?"
                prev_params.append(region)
            prev_where += " AND report_date >= ? AND report_date <= ?"
            prev_params += [prev_from, prev_to]

            prev = db.execute(
                f"SELECT SUM(cost) AS total_cost, SUM(installs) AS total_installs, "
                f"SUM(in_app_actions) AS total_in_app "
                f"FROM ad_reports WHERE {prev_where}", prev_params
            ).fetchone()

            if prev and prev["total_cost"]:
                period_compare["cost_change_pct"] = round(
                    ((summary["total_cost"] - prev["total_cost"]) / prev["total_cost"]) * 100
                )
                period_compare["installs_change_pct"] = round(
                    ((summary["total_installs"] - prev["total_installs"]) / max(prev["total_installs"], 1)) * 100
                )
                prev_total_in_app = prev["total_in_app"] or 0
                prev_avg_cpi = round((prev["total_cost"] or 0) / max(prev_total_in_app, 1), 2)
                if prev_avg_cpi:
                    period_compare["cpi_change_pct"] = round(
                        ((summary["avg_cpi"] - prev_avg_cpi) / prev_avg_cpi) * 100
                    )
        except Exception:
            pass

    # 按 campaign 分组统计
    campaign_stats = db.execute(
        f"SELECT campaign, "
        f"SUM(cost) AS total_cost, SUM(installs) AS total_installs, "
        f"SUM(impressions) AS total_impressions, SUM(clicks) AS total_clicks, "
        f"SUM(in_app_actions) AS total_in_app "
        f"FROM ad_reports WHERE {where_clause} "
        f"GROUP BY campaign ORDER BY total_cost DESC",
        params
    ).fetchall()
    campaigns = [{
        "campaign": r["campaign"] or "未命名",
        "total_cost": round(r["total_cost"] or 0, 2),
        "total_installs": round(r["total_installs"] or 0, 2),
        "total_impressions": r["total_impressions"] or 0,
        "total_clicks": r["total_clicks"] or 0,
        "total_in_app": round(r["total_in_app"] or 0, 2),
        "avg_cpi": round((r["total_cost"] or 0) / max(r["total_in_app"] or 1, 1), 2),
        "ctr": round((r["total_clicks"] or 0) / max(r["total_impressions"] or 1, 1), 4),
        "cvr": round((r["total_installs"] or 0) / max(r["total_clicks"] or 1, 1), 4),
    } for r in campaign_stats]

    # 成效素材关联数
    asset_count = 0
    if product_name:
        asset_count = db.execute("""
            SELECT COUNT(*) FROM product_assets pa
            JOIN products p ON pa.product_id = p.id
            WHERE p.product_name = ?
        """, (product_name,)).fetchone()[0]

    db.close()
    return jsonify({
        "success": True,
        "summary": summary,
        "period_compare": period_compare,
        "anomalies": anomalies,
        "campaigns": campaigns,
        "asset_count": asset_count
    })


@app.route("/api/ad-reports/trends", methods=["GET"])
@jwt_required()
def ad_reports_trends():
    """趋势数据：按日期聚合指定指标。"""
    user_id = int(get_jwt_identity())
    product_name = request.args.get("product_name", "").strip()
    region = request.args.get("region", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    metric = request.args.get("metric", "cpi").strip()
    group_by = request.args.get("group_by", "product_name").strip()  # product_name or campaign

    db = _yt_db()
    where = ["user_id=?"]; params = [user_id]
    if product_name:
        where.append("product_name=?"); params.append(product_name)
    if region:
        where.append("region=?"); params.append(region)
    if from_date:
        where.append("report_date >= ?"); params.append(from_date)
    if to_date:
        where.append("report_date <= ?"); params.append(to_date)

    where_clause = " AND ".join(where)

    group_col = "product_name" if group_by == "product_name" else "campaign"

    rows = db.execute(
        f"SELECT {group_col} AS name, report_date, "
        f"SUM(cost) AS total_cost, SUM(installs) AS total_installs, "
        f"SUM(impressions) AS total_impressions, SUM(clicks) AS total_clicks, "
        f"SUM(in_app_actions) AS total_in_app "
        f"FROM ad_reports WHERE {where_clause} "
        f"GROUP BY {group_col}, report_date ORDER BY report_date",
        params
    ).fetchall()

    # Python 计算指标值
    def _compute_metric(r, m):
        if m == "cost": return r["total_cost"] or 0
        if m == "installs": return r["total_installs"] or 0
        if m == "impressions": return r["total_impressions"] or 0
        if m == "clicks": return r["total_clicks"] or 0
        if m == "cpi":
            return (r["total_cost"] or 0) / max(r["total_in_app"] or 1, 1)
        if m == "ctr":
            return (r["total_clicks"] or 0) / max(r["total_impressions"] or 1, 1)
        if m == "cvr":
            return (r["total_installs"] or 0) / max(r["total_clicks"] or 1, 1)
        return (r["total_cost"] or 0) / max(r["total_in_app"] or 1, 1)  # 默认 CPI

    series_map = {}
    for r in rows:
        name = r["name"]
        if name not in series_map:
            series_map[name] = []
        series_map[name].append({"date": r["report_date"], "value": round(_compute_metric(r, metric), 4)})

    db.close()
    return jsonify({
        "success": True,
        "series": [{"name": k, "data": v} for k, v in series_map.items()]
    })


@app.route("/api/ad-reports/compare", methods=["GET"])
@jwt_required()
def ad_reports_compare():
    """产品/系列聚合对比。"""
    user_id = int(get_jwt_identity())
    group_by = request.args.get("group_by", "product_name").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    sort_by = request.args.get("sort_by", "cpi").strip()

    db = _yt_db()
    where = ["user_id=?"]; params = [user_id]
    if from_date:
        where.append("report_date >= ?"); params.append(from_date)
    if to_date:
        where.append("report_date <= ?"); params.append(to_date)

    where_clause = " AND ".join(where)
    group_col = "product_name" if group_by == "product_name" else "campaign"

    rows = db.execute(
        f"SELECT {group_col} AS name, "
        f"SUM(cost) AS total_cost, SUM(impressions) AS total_impressions, "
        f"SUM(clicks) AS total_clicks, SUM(installs) AS total_installs, "
        f"SUM(in_app_actions) AS total_in_app "
        f"FROM ad_reports WHERE {where_clause} "
        f"GROUP BY {group_col}",
        params
    ).fetchall()

    # Python 计算派生指标
    items = []
    for r in rows:
        cost = r["total_cost"] or 0
        impressions = r["total_impressions"] or 0
        clicks = r["total_clicks"] or 0
        installs = r["total_installs"] or 0
        in_app = r["total_in_app"] or 0
        items.append({
            "name": r["name"],
            "total_cost": round(cost, 2),
            "total_impressions": impressions,
            "total_clicks": clicks,
            "total_installs": installs,
            "total_in_app": in_app,
            "avg_cpi": round(cost / max(in_app, 1), 2),
            "ctr": round(clicks / max(impressions, 1), 4),
            "cvr": round(installs / max(clicks, 1), 4),
        })

    # Python 排序
    sort_key = sort_by if sort_by in ("cost", "installs") else ("cpi" if sort_by == "cpi" else sort_by)
    reverse = sort_by != "cpi"  # cpi 默认升序，其余降序
    if sort_key == "cpi":
        items.sort(key=lambda x: x["avg_cpi"], reverse=False)
    elif sort_key == "cost":
        items.sort(key=lambda x: x["total_cost"], reverse=True)
    elif sort_key == "installs":
        items.sort(key=lambda x: x["total_installs"], reverse=True)
    elif sort_key == "ctr":
        items.sort(key=lambda x: x["ctr"], reverse=True)
    elif sort_key == "cvr":
        items.sort(key=lambda x: x["cvr"], reverse=True)

    db.close()
    return jsonify({
        "success": True,
        "items": items
    })


@app.route("/api/ad-reports/cross-user", methods=["GET"])
@jwt_required()
def ad_reports_cross_user():
    """跨用户对比：同产品不同用户的聚合数据。"""
    user_id = int(get_jwt_identity())
    product_name = request.args.get("product_name", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()

    if not product_name:
        return jsonify({"success": False, "error": "请指定产品"}), 400

    db = _yt_db()
    where = ["product_name=?"]; params = [product_name]
    if from_date:
        where.append("report_date >= ?"); params.append(from_date)
    if to_date:
        where.append("report_date <= ?"); params.append(to_date)

    where_clause = " AND ".join(where)

    rows = db.execute(
        f"SELECT ar.user_id, u.display_name, u.username, "
        f"SUM(ar.cost) AS total_cost, SUM(ar.installs) AS total_installs, "
        f"SUM(ar.in_app_actions) AS total_in_app, "
        f"COUNT(DISTINCT ar.report_date) AS report_days "
        f"FROM ad_reports ar "
        f"LEFT JOIN users u ON ar.user_id = u.id "
        f"WHERE {where_clause} "
        f"GROUP BY ar.user_id",
        params
    ).fetchall()

    users = []
    for r in rows:
        cost = r["total_cost"] or 0
        in_app = r["total_in_app"] or 0
        users.append({
            "user_id": r["user_id"],
            "display_name": r["display_name"],
            "username": r["username"],
            "total_cost": round(cost, 2),
            "total_installs": r["total_installs"] or 0,
            "total_in_app": in_app,
            "avg_cpi": round(cost / max(in_app, 1), 2),
            "report_days": r["report_days"],
        })

    users.sort(key=lambda u: u["avg_cpi"])

    db.close()
    return jsonify({
        "success": True,
        "users": users
    })


@app.route("/api/ad-reports/multi-analysis", methods=["GET"])
@jwt_required()
def ad_reports_multi_analysis():
    """多维自由分析：任意指标 X/Y 轴 + 任意分组维度 + 统计 + 规则引擎结论。"""
    user_id = int(get_jwt_identity())
    x_axis = request.args.get("x_axis", "cost").strip()
    y_axis = request.args.get("y_axis", "cpi").strip()
    size_by = request.args.get("size_by", "").strip()
    group_by = request.args.get("group_by", "account").strip()
    product_name = request.args.get("product_name", "").strip()
    campaign = request.args.get("campaign", "").strip()
    account = request.args.get("account", "").strip()
    region = request.args.get("region", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    split_by_date = request.args.get("split_by_date", "0").strip() == "1"

    # 分组列映射
    group_col_map = {
        "product_name": "product_name",
        "campaign": "campaign",
        "account": "account",
        "customer_id": "customer_id",
    }
    group_col = group_col_map.get(group_by, "account")

    # 指标标签
    metric_labels = {
        "cost": "花费", "cpi": "CPI", "ctr": "CTR", "cvr": "CVR",
        "installs": "安装", "impressions": "展示", "clicks": "点击",
    }

    db = _yt_db()
    where = ["user_id=?"]; params = [user_id]
    if product_name:
        where.append("product_name=?"); params.append(product_name)
    if campaign:
        where.append("campaign=?"); params.append(campaign)
    if account:
        where.append("account=?"); params.append(account)
    if region:
        where.append("region=?"); params.append(region)
    if from_date:
        where.append("report_date >= ?"); params.append(from_date)
    if to_date:
        where.append("report_date <= ?"); params.append(to_date)
    where_clause = " AND ".join(where)

    if split_by_date:
        sql = (
            f"SELECT {group_col} AS name, report_date, "
            f"SUM(cost) AS total_cost, SUM(impressions) AS total_impressions, "
            f"SUM(clicks) AS total_clicks, SUM(installs) AS total_installs, "
            f"SUM(in_app_actions) AS total_in_app "
            f"FROM ad_reports WHERE {where_clause} "
            f"GROUP BY {group_col}, report_date ORDER BY report_date"
        )
    else:
        sql = (
            f"SELECT {group_col} AS name, "
            f"SUM(cost) AS total_cost, SUM(impressions) AS total_impressions, "
            f"SUM(clicks) AS total_clicks, SUM(installs) AS total_installs, "
            f"SUM(in_app_actions) AS total_in_app "
            f"FROM ad_reports WHERE {where_clause} "
            f"GROUP BY {group_col} ORDER BY total_cost DESC"
        )
    rows = db.execute(sql, params).fetchall()
    db.close()

    # 计算派生指标
    def _calc_cpi(cost, in_app):
        return round(cost / max(in_app, 1), 4)
    def _calc_ctr(clicks, impr):
        return round(clicks / max(impr, 1), 4)
    def _calc_cvr(installs, clicks):
        return round(installs / max(clicks, 1), 4)

    def _get_metric_val(d, m):
        m = m.lower()
        if m == "cost": return d["total_cost"] or 0
        if m == "installs": return d["total_installs"] or 0
        if m == "impressions": return d["total_impressions"] or 0
        if m == "clicks": return d["total_clicks"] or 0
        if m == "cpi": return _calc_cpi(d["total_cost"] or 0, d["total_in_app"] or 0)
        if m == "ctr": return _calc_ctr(d["total_clicks"] or 0, d["total_impressions"] or 0)
        if m == "cvr": return _calc_cvr(d["total_installs"] or 0, d["total_clicks"] or 0)
        return d["total_cost"] or 0

    # 构建点数据
    points = []
    for r in rows:
        cost = r["total_cost"] or 0
        impr = r["total_impressions"] or 0
        clicks = r["total_clicks"] or 0
        installs = r["total_installs"] or 0
        in_app = r["total_in_app"] or 0
        cpi = _calc_cpi(cost, in_app)
        ctr = _calc_ctr(clicks, impr)
        cvr = _calc_cvr(installs, clicks)
        detail = {
            "total_cost": round(cost, 2),
            "total_installs": installs,
            "total_in_app": in_app,
            "avg_cpi": cpi,
            "ctr": ctr,
            "cvr": cvr,
            "total_impressions": impr,
            "total_clicks": clicks,
        }
        sz = _get_metric_val({
            "total_cost": cost, "total_installs": installs,
            "total_impressions": impr, "total_clicks": clicks,
            "total_in_app": in_app,
        }, size_by) if size_by else 1.0
        rd = r["report_date"] if split_by_date else ""
        pt_name = r["name"] if not split_by_date else f"{r['name']} ({rd})"
        points.append({
            "name": pt_name,
            "group": group_by,
            "x": _get_metric_val({
                "total_cost": cost, "total_installs": installs,
                "total_impressions": impr, "total_clicks": clicks,
                "total_in_app": in_app,
            }, x_axis),
            "y": _get_metric_val({
                "total_cost": cost, "total_installs": installs,
                "total_impressions": impr, "total_clicks": clicks,
                "total_in_app": in_app,
            }, y_axis),
            "size": round(sz, 6) if sz else 1.0,
            "x_label": metric_labels.get(x_axis, x_axis),
            "y_label": metric_labels.get(y_axis, y_axis),
            "detail": detail,
        })

    # 统计计算
    n = len(points)
    stats = {"sample_count": n, "x_label": metric_labels.get(x_axis, x_axis),
             "y_label": metric_labels.get(y_axis, y_axis)}
    if n > 0:
        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]
        x_avg = round(sum(xs) / n, 4)
        y_avg = round(sum(ys) / n, 4)
        xs_sorted = sorted(xs)
        ys_sorted = sorted(ys)
        x_median = round(xs_sorted[n // 2], 4) if n % 2 else round((xs_sorted[n // 2 - 1] + xs_sorted[n // 2]) / 2, 4)
        y_median = round(ys_sorted[n // 2], 4) if n % 2 else round((ys_sorted[n // 2 - 1] + ys_sorted[n // 2]) / 2, 4)
        stats["x_avg"] = x_avg
        stats["x_median"] = x_median
        stats["y_avg"] = y_avg
        stats["y_median"] = y_median
        # Pearson 相关系数
        if n >= 2:
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
            std_x = (sum((x - mean_x) ** 2 for x in xs) ** 0.5)
            std_y = (sum((y - mean_y) ** 2 for y in ys) ** 0.5)
            if std_x > 0 and std_y > 0:
                stats["correlation"] = round(cov / (std_x * std_y), 4)
            else:
                stats["correlation"] = 0
        else:
            stats["correlation"] = 0
    else:
        stats.update({"x_avg": 0, "x_median": 0, "y_avg": 0, "y_median": 0, "correlation": 0})

    # 规则引擎 insight
    insights = []
    if n > 0:
        x_label = metric_labels.get(x_axis, x_axis)
        y_label = metric_labels.get(y_axis, y_axis)
        total_cost = sum(p["detail"]["total_cost"] for p in points)
        avg_y = stats.get("y_avg", 0)
        r_val = stats.get("correlation", 0)

        for p in points:
            # CPI 异常高：CPI > 均值 * 1.5 且 y_axis 是 cpi
            if y_axis == "cpi" and avg_y > 0 and p["y"] > avg_y * 1.5:
                pct = round((p["y"] - avg_y) / avg_y * 100)
                insights.append(f"{p['name']} 的 CPI(${p['y']}) 高于均值(${avg_y}) {pct}%，位于异常区，建议排查投放策略")
            # 花费集中
            if total_cost > 0 and p["detail"]["total_cost"] > total_cost * 0.6:
                insights.append(f"{p['name']} 消耗了 {round(p['detail']['total_cost']/total_cost*100)}% 的预算，需关注投入产出比")
            # 高花费低 CTR
            if x_axis == "cost" and n > 1:
                avg_cost = stats.get("x_avg", 0)
                avg_ctr_val = sum(pt["detail"]["ctr"] for pt in points) / n
                if p["x"] > avg_cost * 1.5 and p["detail"]["ctr"] < avg_ctr_val:
                    insights.append(f"{p['name']} 花费高(${p['detail']['total_cost']})但 CTR({round(p['detail']['ctr']*100,2)}%)低于均值，可能存在投放效率问题")

        # 相关性结论
        if abs(r_val) > 0.1:
            r_desc = "强" if abs(r_val) > 0.6 else ("中等" if abs(r_val) > 0.3 else "弱")
            direction = "正相关" if r_val > 0 else "负相关"
            insights.append(f"{x_label}与{y_label}呈{r_desc}{direction}(r={r_val})")

    return jsonify({
        "success": True,
        "points": points,
        "stats": stats,
        "insights": insights,
    })


@app.route("/api/ad-reports/multi-analysis", methods=["POST"])
@jwt_required()
def ad_reports_multi_analysis_post():
    """多维分析 POST：支持 extra_rows 临时数据对比。"""
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    params = body.get("params", {})
    extra_rows = body.get("extra_rows", [])

    x_axis = params.get("x_axis", "cost").strip()
    y_axis = params.get("y_axis", "cpi").strip()
    size_by = params.get("size_by", "").strip()
    group_by = params.get("group_by", "account").strip()
    product_name = params.get("product_name", "").strip()
    campaign = params.get("campaign", "").strip()
    account = params.get("account", "").strip()
    region = params.get("region", "").strip()
    from_date = params.get("from_date", "").strip()
    to_date = params.get("to_date", "").strip()
    split_by_date = params.get("split_by_date", "0") == "1"

    group_col_map = {
        "product_name": "product_name", "campaign": "campaign",
        "account": "account", "customer_id": "customer_id",
    }
    group_col = group_col_map.get(group_by, "account")

    metric_labels = {
        "cost": "花费", "cpi": "CPI", "ctr": "CTR", "cvr": "CVR",
        "installs": "安装", "impressions": "展示", "clicks": "点击",
    }

    def _agg_rows(rows, grp_col, split_date):
        """将行列表按 grp_col 聚合（纯 Python），返回聚合计列表。"""
        from collections import defaultdict
        groups = defaultdict(lambda: {"total_cost": 0, "total_impressions": 0, "total_clicks": 0,
                                       "total_installs": 0, "total_in_app": 0})
        for r in rows:
            if isinstance(r, dict):
                name = r.get(grp_col, "")
                rd = r.get("report_date", "")
            else:
                name = r[grp_col] if grp_col in r.keys() else ""
                rd = r["report_date"] if "report_date" in r.keys() else ""
            key = (name, rd) if split_date else name
            groups[key]["name"] = name
            groups[key]["total_cost"] += float(r.get("cost", 0)) if isinstance(r, dict) else (r["cost"] or 0)
            groups[key]["total_impressions"] += int(r.get("impressions", 0)) if isinstance(r, dict) else (r["impressions"] or 0)
            groups[key]["total_clicks"] += int(r.get("clicks", 0)) if isinstance(r, dict) else (r["clicks"] or 0)
            groups[key]["total_installs"] += float(r.get("installs", 0)) if isinstance(r, dict) else (r["installs"] or 0)
            groups[key]["total_in_app"] += float(r.get("inAppActions", 0)) if isinstance(r, dict) else (r["in_app_actions"] or 0)
        result = []
        for k, v in groups.items():
            entry = dict(v)
            if split_date:
                entry["report_date"] = k[1]
            result.append(entry)
        return result

    def _build_points(agg_rows, src_label):
        pts = []
        for r in agg_rows:
            cost = r.get("total_cost", 0) or 0
            impr = r.get("total_impressions", 0) or 0
            clicks = r.get("total_clicks", 0) or 0
            installs = r.get("total_installs", 0) or 0
            in_app = r.get("total_in_app", 0) or 0
            cpi = round(cost / max(in_app, 1), 4)
            ctr = round(clicks / max(impr, 1), 4)
            cvr = round(installs / max(clicks, 1), 4)
            detail = {"total_cost": round(cost, 2), "total_installs": installs, "total_in_app": in_app,
                      "avg_cpi": cpi, "ctr": ctr, "cvr": cvr, "total_impressions": impr, "total_clicks": clicks}
            def _mv(d, m):
                m = m.lower()
                if m == "cost": return d["total_cost"] or 0
                if m == "installs": return d["total_installs"] or 0
                if m == "impressions": return d["total_impressions"] or 0
                if m == "clicks": return d["total_clicks"] or 0
                if m == "cpi": return round(d["total_cost"] / max(d["total_in_app"], 1), 4)
                if m == "ctr": return round(d["total_clicks"] / max(d["total_impressions"], 1), 4)
                if m == "cvr": return round(d["total_installs"] / max(d["total_clicks"], 1), 4)
                return d["total_cost"] or 0
            sz = _mv({"total_cost": cost, "total_installs": installs, "total_impressions": impr,
                       "total_clicks": clicks, "total_in_app": in_app}, size_by) if size_by else 1.0
            rd = r.get("report_date", "")
            pt_name = r.get("name", "") if not split_by_date else f"{r.get('name','')} ({rd})"
            pts.append({"name": pt_name, "group": group_by, "source": src_label,
                        "x": _mv({"total_cost": cost, "total_installs": installs, "total_impressions": impr,
                                   "total_clicks": clicks, "total_in_app": in_app}, x_axis),
                        "y": _mv({"total_cost": cost, "total_installs": installs, "total_impressions": impr,
                                   "total_clicks": clicks, "total_in_app": in_app}, y_axis),
                        "size": round(sz, 6) if sz else 1.0,
                        "x_label": metric_labels.get(x_axis, x_axis),
                        "y_label": metric_labels.get(y_axis, y_axis),
                        "detail": detail})
        return pts

    def _compute_stats(all_pts):
        n = len(all_pts)
        s = {"sample_count": n, "x_label": metric_labels.get(x_axis, x_axis),
             "y_label": metric_labels.get(y_axis, y_axis)}
        if n > 0:
            xs = [p["x"] for p in all_pts]; ys = [p["y"] for p in all_pts]
            s["x_avg"] = round(sum(xs) / n, 4); s["y_avg"] = round(sum(ys) / n, 4)
            sxs = sorted(xs); sys = sorted(ys)
            s["x_median"] = round(sxs[n // 2], 4) if n % 2 else round((sxs[n // 2 - 1] + sxs[n // 2]) / 2, 4)
            s["y_median"] = round(sys[n // 2], 4) if n % 2 else round((sys[n // 2 - 1] + sys[n // 2]) / 2, 4)
            if n >= 2:
                mx = sum(xs) / n; my = sum(ys) / n
                cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
                sx = (sum((x - mx) ** 2 for x in xs) ** 0.5)
                sy = (sum((y - my) ** 2 for y in ys) ** 0.5)
                s["correlation"] = round(cov / (sx * sy), 4) if sx > 0 and sy > 0 else 0
            else:
                s["correlation"] = 0
        else:
            s.update({"x_avg": 0, "x_median": 0, "y_avg": 0, "y_median": 0, "correlation": 0})
        return s

    def _gen_insights(all_pts, stats):
        ins = []
        n = len(all_pts)
        if n > 0:
            x_label = metric_labels.get(x_axis, x_axis)
            y_label = metric_labels.get(y_axis, y_axis)
            total_cost = sum(p["detail"]["total_cost"] for p in all_pts)
            avg_y = stats.get("y_avg", 0)
            r_val = stats.get("correlation", 0)
            for p in all_pts:
                if y_axis == "cpi" and avg_y > 0 and p["y"] > avg_y * 1.5:
                    pct = round((p["y"] - avg_y) / avg_y * 100)
                    ins.append(f"{p['name']} 的 CPI(${p['y']}) 高于均值(${avg_y}) {pct}%，位于异常区")
                if total_cost > 0 and p["detail"]["total_cost"] > total_cost * 0.6:
                    ins.append(f"{p['name']} 消耗了 {round(p['detail']['total_cost']/total_cost*100)}% 的预算")
                if x_axis == "cost" and n > 1:
                    avg_cost = stats.get("x_avg", 0)
                    avg_ctr_v = sum(pt["detail"]["ctr"] for pt in all_pts) / n
                    if p["x"] > avg_cost * 1.5 and p["detail"]["ctr"] < avg_ctr_v:
                        ins.append(f"{p['name']} 花费高但 CTR 低于均值")
            if abs(r_val) > 0.1:
                r_desc = "强" if abs(r_val) > 0.6 else ("中等" if abs(r_val) > 0.3 else "弱")
                direction = "正相关" if r_val > 0 else "负相关"
                ins.append(f"{x_label}与{y_label}呈{r_desc}{direction}(r={r_val})")
        return ins

    # 查询历史数据
    db = _yt_db()
    where = ["user_id=?"]; wparams = [user_id]
    if product_name: where.append("product_name=?"); wparams.append(product_name)
    if campaign: where.append("campaign=?"); wparams.append(campaign)
    if account: where.append("account=?"); wparams.append(account)
    if region: where.append("region=?"); wparams.append(region)
    if from_date: where.append("report_date >= ?"); wparams.append(from_date)
    if to_date: where.append("report_date <= ?"); wparams.append(to_date)
    wc = " AND ".join(where)

    if split_by_date:
        sql = (f"SELECT {group_col} AS name, report_date, SUM(cost) AS total_cost, SUM(impressions) AS total_impressions, "
               f"SUM(clicks) AS total_clicks, SUM(installs) AS total_installs, SUM(in_app_actions) AS total_in_app "
               f"FROM ad_reports WHERE {wc} GROUP BY {group_col}, report_date ORDER BY report_date")
    else:
        sql = (f"SELECT {group_col} AS name, SUM(cost) AS total_cost, SUM(impressions) AS total_impressions, "
               f"SUM(clicks) AS total_clicks, SUM(installs) AS total_installs, SUM(in_app_actions) AS total_in_app "
               f"FROM ad_reports WHERE {wc} GROUP BY {group_col} ORDER BY total_cost DESC")
    hist_rows = db.execute(sql, wparams).fetchall()
    db.close()

    hist_agg = [dict(r) for r in hist_rows]
    hist_points = _build_points(hist_agg, "历史")

    # 聚合 extra_rows
    new_points = []
    if extra_rows:
        new_agg = _agg_rows(extra_rows, group_col, split_by_date)
        new_points = _build_points(new_agg, "新增")

    all_pts = hist_points + new_points
    stats = _compute_stats(all_pts)
    insights = _gen_insights(all_pts, stats)

    return jsonify({
        "success": True,
        "historical": hist_points,
        "new": new_points,
        "points": all_pts,
        "stats": stats,
        "insights": insights,
    })


@app.route("/api/ad-reports/multi-ai-chat", methods=["POST"])
@jwt_required()
def ad_reports_multi_ai_chat():
    """多维分析 AI 对话：带数据上下文的智能问答。"""
    user_id = int(get_jwt_identity())
    db = _yt_db()
    ai_config_row = db.execute(
        f"SELECT value FROM config WHERE key='ai_analysis_{user_id}'"
    ).fetchone()
    db.close()

    ai_enabled = False
    if ai_config_row:
        try:
            ai_config = json.loads(ai_config_row["value"])
            ai_enabled = ai_config.get("enabled", False)
        except Exception:
            pass

    if not ai_enabled:
        return jsonify({"success": True, "enabled": False, "answer": "AI 分析未启用，请联系管理员在系统配置中开启。"})

    question = (request.get_json(silent=True) or {}).get("question", "").strip()
    context = (request.get_json(silent=True) or {}).get("context", {})
    history = (request.get_json(silent=True) or {}).get("history", [])

    if not question:
        return jsonify({"success": True, "enabled": True, "answer": "请输入问题。"})

    # 构建 prompt
    context_summary = ""
    if context:
        pts = context.get("points", [])
        stats = context.get("stats", {})
        if pts:
            context_summary = f"\n当前分析数据（共{len(pts)}个分组）：\n"
            for p in pts:
                d = p.get("detail", {})
                context_summary += f"- {p.get('name','?')}: 花费${d.get('total_cost',0)}, CPI${d.get('avg_cpi',0)}, CTR{round(d.get('ctr',0)*100,2)}%, CVR{round(d.get('cvr',0)*100,2)}%, 安装{d.get('total_installs',0)}\n"
            if stats:
                context_summary += f"\n统计：{stats.get('x_label','X')}均值={stats.get('x_avg','?')}, {stats.get('y_label','Y')}均值={stats.get('y_avg','?')}, 相关系数r={stats.get('correlation','?')}\n"

    try:
        ai_config = json.loads(ai_config_row["value"])
        provider = ai_config.get("provider", "volcano")
        model = ai_config.get("model", "deepseek-v4-flash")
        api_key = ai_config.get("api_key", "")
        endpoint = ai_config.get("endpoint", "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions")

        # 拼完整 endpoint URL
        chat_url = endpoint
        messages = [
            {"role": "system", "content": "你是一个广告投放数据分析师，帮助用户分析广告投放数据，找出优化机会。请用中文回答，简洁明确，给出可执行的建议。"},
        ]
        for h in history[-10:]:  # 最近10轮对话
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": f"以下是我的广告数据：{context_summary}\n问题：{question}"})

        resp = requests.post(
            chat_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 1024},
            timeout=30,
        )
        if resp.status_code == 200:
            body = resp.json()
            answer = body.get("choices", [{}])[0].get("message", {}).get("content", "AI 未返回有效回复")
        else:
            answer = f"AI 服务返回错误({resp.status_code}): {resp.text[:300]}"
    except Exception as e:
        answer = f"AI 服务调用失败: {str(e)[:200]}"

    return jsonify({"success": True, "enabled": True, "answer": answer})


@app.route("/api/ad-reports/dates", methods=["GET"])
@jwt_required()
def ad_reports_dates():
    """返回筛选条件下有数据的日期列表，供日期选择器标记使用。"""
    user_id = int(get_jwt_identity())
    product_name = request.args.get("product_name", "").strip()
    region = request.args.get("region", "").strip()

    db = _yt_db()
    where = ["user_id=?"]; params = [user_id]
    if product_name:
        where.append("product_name=?"); params.append(product_name)
    if region:
        where.append("region=?"); params.append(region)

    rows = db.execute(
        f"SELECT report_date, COUNT(*) AS cnt FROM ad_reports "
        f"WHERE {' AND '.join(where)} GROUP BY report_date ORDER BY report_date",
        params
    ).fetchall()
    db.close()
    dates = {r["report_date"]: r["cnt"] for r in rows}
    return jsonify({"success": True, "dates": dates})


@app.route("/api/ad-reports/analyze", methods=["POST"])
@jwt_required()
def ad_reports_analyze():
    """AI 分析（可配置开关，按用户隔离）。"""
    user_id = int(get_jwt_identity())
    # 检查配置
    db = _yt_db()
    ai_config_row = db.execute(
        f"SELECT value FROM config WHERE key='ai_analysis_{user_id}'"
    ).fetchone()
    db.close()

    ai_enabled = False
    ai_provider = "atlas"
    if ai_config_row:
        try:
            ai_config = json.loads(ai_config_row["value"])
            ai_enabled = ai_config.get("enabled", False)
            ai_provider = ai_config.get("provider", "atlas")
        except Exception:
            pass

    if not ai_enabled:
        return jsonify({"success": True, "enabled": False, "answer": "AI 分析未启用，请联系管理员在系统配置中开启。"})

    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip()
    filters = body.get("filters", {})

    if not question:
        return jsonify({"success": True, "enabled": True, "answer": "请输入问题。"})

    # 收集当前筛选条件下的数据摘要
    db2 = _yt_db()
    where = ["user_id=?"]; params = [user_id]
    if filters.get("product_name"):
        where.append("product_name=?"); params.append(filters["product_name"])
    if filters.get("region"):
        where.append("region=?"); params.append(filters["region"])
    if filters.get("from_date"):
        where.append("report_date >= ?"); params.append(filters["from_date"])
    if filters.get("to_date"):
        where.append("report_date <= ?"); params.append(filters["to_date"])
    where_clause = " AND ".join(where)

    summary_row = db2.execute(
        f"SELECT SUM(cost) AS tc, SUM(impressions) AS ti, SUM(clicks) AS tcl, "
        f"SUM(installs) AS tins, SUM(in_app_actions) AS tia, COUNT(*) AS cnt "
        f"FROM ad_reports WHERE {where_clause}", params
    ).fetchone()
    db2.close()

    context_summary = ""
    if summary_row and summary_row["cnt"]:
        tc = summary_row["tc"] or 0
        tcl = summary_row["tcl"] or 0
        tins = summary_row["tins"] or 0
        tia = summary_row["tia"] or 0
        ti = summary_row["ti"] or 0
        avg_cpi = round(tc / max(tia, 1), 2)
        avg_ctr = round(tcl / max(ti, 1) * 100, 2)
        context_summary = (
            f"数据摘要：总花费${tc}，总展示{ti}，总点击{tcl}，"
            f"总安装{tins}，总应用内操作{tia}，"
            f"平均CPI${avg_cpi}，平均CTR{avg_ctr}%。"
        )

    try:
        model = ai_config.get("model", "deepseek-v4-flash")
        api_key = ai_config.get("api_key", "")
        endpoint = ai_config.get("endpoint", "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions")
        chat_url = endpoint
        messages = [
            {"role": "system", "content": "你是一个广告投放数据分析师，帮助用户分析广告投放数据，找出优化机会。请用中文回答，简洁明确，给出可执行的建议。"},
            {"role": "user", "content": f"{context_summary}\n问题：{question}"},
        ]
        resp = requests.post(
            chat_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 1024},
            timeout=30,
        )
        if resp.status_code == 200:
            body_resp = resp.json()
            answer = body_resp.get("choices", [{}])[0].get("message", {}).get("content", "AI 未返回有效回复")
        else:
            answer = f"AI 服务返回错误({resp.status_code}): {resp.text[:300]}"
    except Exception as e:
        answer = f"AI 服务调用失败: {str(e)[:200]}"

    return jsonify({
        "success": True,
        "enabled": True,
        "answer": answer,
        "provider": ai_provider
    })


# ============================================================
#  地区时区管理 API
# ============================================================

@app.route("/api/regions/list", methods=["GET"])
@jwt_required()
def regions_list_api():
    """获取所有地区+时区。"""
    result = database.regions_list()
    return jsonify({"success": True, "regions": result})


@app.route("/api/regions/<int:region_id>", methods=["PUT"])
@jwt_required()
def regions_update_api(region_id):
    """更新地区时区。"""
    data = request.get_json(silent=True) or {}
    timezone = (data.get("timezone") or "").strip()
    database.regions_update(region_id, timezone)
    return jsonify({"success": True})


@app.route("/api/regions/create", methods=["POST"])
@jwt_required()
def regions_create_api():
    """新增地区。"""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    timezone = (data.get("timezone") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "地区名不能为空"}), 400
    rid = database.regions_create(name, timezone)
    return jsonify({"success": True, "id": rid})


@app.route("/api/regions/<int:region_id>", methods=["DELETE"])
@jwt_required()
def regions_delete_api(region_id):
    """删除地区。"""
    database.regions_delete(region_id)
    return jsonify({"success": True})


if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5001
    _start_weekly_cleanup()
    # 全局 500 处理器，开发时返回详细错误
    @app.errorhandler(500)
    def _internal_error(e):
        import traceback
        tb = traceback.format_exc()
        print(f"[500 ERROR] {tb}", file=sys.stderr)
        return jsonify({"success": False, "error": str(e), "trace": tb[-2000:]}), 500

    print(f"服务已启动: http://{host}:{port}")
    print("在浏览器中打开上方地址即可使用。")
    # 自动打开浏览器
    # webbrowser.open(f"http://127.0.0.1:{port}")  # 调试时关闭自动打开
    app.run(host=host, port=port, debug=False, threaded=True)


