import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class ScrapeError(Exception):
    """爬取失败异常。"""
    pass


def _upgrade_image_url(img_url: str) -> str:
    """将 Google 图片 URL 升级为高清版本。

    Google Play 图片 URL 包含尺寸参数如 =w526-h296-rw，
    替换为 =w2400-h2400 以请求最大可用分辨率。
    """
    # 匹配 =w数字-h数字 模式，替换为高分辨率
    return re.sub(r"=w\d+-h\d+", "=w2400-h2400", img_url)


def scrape_images(url: str) -> list[str]:
    """从 Google Play 页面爬取 <c-wiz jsrenderer='UZStuc'> 内所有图片 URL。

    参数:
        url: Google Play 应用页面链接

    返回:
        去重后的图片 URL 列表（已补全为绝对路径）

    异常:
        ScrapeError: 页面不可访问、未找到目标标签
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ScrapeError(f"无法访问页面: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")
    c_wiz = soup.find("c-wiz", {"jsrenderer": "UZStuc"})

    if c_wiz is None:
        raise ScrapeError("未找到目标标签 <c-wiz jsrenderer='UZStuc'>")

    img_urls = []
    for img in c_wiz.find_all("img"):
        src = img.get("src")
        if src:
            # 补全相对路径，升级为高清
            full_url = urljoin(url, src)
            full_url = _upgrade_image_url(full_url)
            img_urls.append(full_url)

    # 去重，保持顺序
    seen = set()
    unique = []
    for u in img_urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    return unique


def scrape_logo(url: str) -> str | None:
    """从 Google Play 页面 <div class="Mqg6jb Mhrnjf"> 中提取第一张图片 URL。

    参数:
        url: Google Play 应用页面链接

    返回:
        第一张图片的绝对 URL，未找到返回 None
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    logo_div = soup.find("div", class_="Mqg6jb Mhrnjf")

    if logo_div is None:
        return None

    img = logo_div.find("img")
    if img is None:
        return None

    src = img.get("src")
    if not src:
        return None

    return urljoin(url, src)
