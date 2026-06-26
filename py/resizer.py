import os
import requests
from PIL import Image
from io import BytesIO
from utils import detect_format


# Google Ads 图片规格配置
# min_short: 该规格短边的最小像素要求
FORMAT_CONFIG = {
    "landscape": {"min_short": 314},   # 横向：高是短边，最小 314
    "square":    {"min_short": 200},   # 方形：两边相等，最小 200
    "portrait":  {"min_short": 320},   # 纵向：宽是短边，最小 320
}

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MiB


class ResizeError(Exception):
    """图片处理失败异常。"""
    pass


def process_image(img_url: str, save_dir: str, filename: str, skip_scaling: bool = False) -> dict:
    """下载、缩放并保存单张图片为 .png。

    参数:
        img_url: 图片远程 URL
        save_dir: 保存目录的绝对路径
        filename: 不含扩展名的文件名
        skip_scaling: 跳过 Google Ads 规格缩放，保留原图尺寸

    返回:
        {"filename": "img_001.png", "width": 1200, "height": 628, "format": "landscape"}

    异常:
        ResizeError: 下载失败或处理失败
    """
    # 1. 下载图片
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(img_url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()
        img_data = BytesIO(resp.content)
    except requests.RequestException as e:
        raise ResizeError(f"下载图片失败: {e}")

    # 2. 打开图片
    try:
        img = Image.open(img_data)
    except Exception as e:
        raise ResizeError(f"无法识别图片格式: {e}")

    # 3. 判断规格
    fmt = detect_format(img.width, img.height)

    if not skip_scaling:
        # 等比放大到短边满足 Google Ads 最小值
        min_short = FORMAT_CONFIG[fmt]["min_short"]
        short_side = min(img.width, img.height)
        if short_side < min_short:
            scale = min_short / short_side
            new_w = int(img.width * scale)
            new_h = int(img.height * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)

    # 4. 保存为 .png，确保 ≤ 5 MiB
    output_path = os.path.join(save_dir, f"{filename}.png")

    # 转换图片模式以减少文件大小（RGBA → RGB 如果无透明通道）
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img.save(output_path, "PNG", optimize=True)
    # 如果文件超过 5 MiB，逐步缩小尺寸
    while os.path.getsize(output_path) > MAX_FILE_SIZE:
        new_w = int(img.width * 0.85)
        new_h = int(img.height * 0.85)
        if skip_scaling:
            if new_w < 1 or new_h < 1:
                break
        else:
            if min(new_w, new_h) < FORMAT_CONFIG[fmt]["min_short"]:
                break  # 不低于最小尺寸
        img = img.resize((new_w, new_h), Image.LANCZOS)
        img.save(output_path, "PNG", optimize=True)

    return {
        "filename": f"{filename}.png",
        "width": img.width,
        "height": img.height,
        "format": fmt,
    }


def save_logo(img_url: str, save_dir: str, filename: str) -> dict:
    """下载 logo 原图并保存为 PNG，不做缩放处理。

    参数:
        img_url: 图片远程 URL
        save_dir: 保存目录的绝对路径
        filename: 不含扩展名的文件名

    返回:
        {"filename": "xxx.png", "width": 120, "height": 120, "format": "logo"}

    异常:
        ResizeError: 下载失败或处理失败
    """
    # 1. 下载图片
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(img_url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()
        img_data = BytesIO(resp.content)
    except requests.RequestException as e:
        raise ResizeError(f"下载 logo 失败: {e}")

    # 2. 打开图片
    try:
        img = Image.open(img_data)
    except Exception as e:
        raise ResizeError(f"无法识别 logo 格式: {e}")

    # 3. 不做缩放，直接保存为 PNG
    output_path = os.path.join(save_dir, f"{filename}.png")

    # RGBA → RGB
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img.save(output_path, "PNG", optimize=True)

    # 如果文件超过 5 MiB，逐步缩小
    while os.path.getsize(output_path) > MAX_FILE_SIZE:
        new_w = int(img.width * 0.85)
        new_h = int(img.height * 0.85)
        if new_w < 1 or new_h < 1:
            break
        img = img.resize((new_w, new_h), Image.LANCZOS)
        img.save(output_path, "PNG", optimize=True)

    return {
        "filename": f"{filename}.png",
        "width": img.width,
        "height": img.height,
        "format": "logo",
    }
