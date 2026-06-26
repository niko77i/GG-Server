"""AI 图片转视频服务 — 抽象接口 + Seedance/Veo/Atlas/Doubao Provider。

Provider 选择:
- seedance: 通过 Atlas Cloud 调用 Seedance 2.0（每日 225 免费积分，图转视频最佳）
- doubao: 豆包 Seedance 1.5 Pro（火山方舟 Ark API，效果最新）
- veo: Google Veo 3.1 Lite（完全免费，视频自带音频）
- atlas: Atlas Cloud 统一网关，可切换多个后端
"""
import base64
import os
import sys
import time
import tempfile
import requests


class AIServiceError(Exception):
    """AI 服务调用失败异常。"""
    pass


class AIProvider:
    """AI 图片转视频抽象基类。"""

    def generate_video(self, image_path: str, duration: int, api_key: str) -> str:
        """将图片转为短视频，返回生成的 MP4 本地路径。"""
        raise NotImplementedError

    @staticmethod
    def _encode_image(image_path: str) -> str:
        """将本地图片编码为 base64 data URI（JPEG 压缩，确保 ≤2MB）。"""
        from io import BytesIO
        try:
            from PIL import Image
        except ImportError:
            with open(image_path, "rb") as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"

        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        if w < 300:
            ratio = 300 / w
            img = img.resize((300, int(h * ratio)), Image.LANCZOS)

        quality = 90
        while quality >= 40:
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= 2048 * 1024:
                break
            quality -= 15
        return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"


class AtlasProvider(AIProvider):
    """通过 Atlas Cloud 统一网关调用 AI 视频模型。

    支持模型: seedance-2.0, kling-3.0, vidu-q3, wan-2.2 等
    参考: https://www.atlascloud.ai/
    """

    BASE_URL = "https://api.atlascloud.ai/v1"
    DEFAULT_MODEL = "seedance-2.0"

    def __init__(self, model: str = None):
        self.model = model or self.DEFAULT_MODEL

    def generate_video(self, image_path: str, duration: int, api_key: str) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Step 1: 提交生成请求
        task_id = self._create_task(image_path, duration, headers)

        # Step 2: 轮询直到完成
        video_url = self._poll_task(task_id, headers)

        # Step 3: 下载视频到临时目录
        return self._download_video(video_url)

    def _create_task(self, image_path: str, duration: int, headers: dict) -> str:
        """提交视频生成任务，返回 task_id。"""
        url = f"{self.BASE_URL}/video/generate"
        body = {
            "model": self.model,
            "image_url": f"file://{image_path}",
            "duration": duration,
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            data = resp.json()
            task_id = data.get("task_id") or data.get("id")
            if resp.status_code != 200 or not task_id:
                raise AIServiceError(
                    f"Atlas Cloud 创建任务失败: {data.get('message', resp.text)}"
                )
            return task_id
        except requests.RequestException as e:
            raise AIServiceError(f"Atlas Cloud 网络错误: {e}")

    def _poll_task(self, task_id: str, headers: dict, timeout: int = 600) -> str:
        """轮询任务状态，返回视频下载 URL。"""
        url = f"{self.BASE_URL}/video/status/{task_id}"
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                data = resp.json()
                status = data.get("status", "")
                if status in ("completed", "succeeded", "done"):
                    video_url = data.get("video_url") or data.get("output_url") or data.get("url")
                    if not video_url:
                        raise AIServiceError("任务完成但缺少视频 URL")
                    return video_url
                elif status in ("failed", "cancelled", "error"):
                    raise AIServiceError(f"任务失败: {data.get('message', status)}")
            except requests.RequestException:
                pass  # 网络抖动，继续轮询
            time.sleep(2)
        raise AIServiceError("任务超时")

    def _download_video(self, video_url: str) -> str:
        """下载视频到临时文件，返回本地路径。"""
        try:
            resp = requests.get(video_url, timeout=120, stream=True)
            resp.raise_for_status()
            fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="ai_video_")
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return tmp_path
        except requests.RequestException as e:
            raise AIServiceError(f"下载视频失败: {e}")


class VeoProvider(AIProvider):
    """Google Veo 3.1 Lite — 通过 NexaAPI 免费调用（无需绑卡）。

    特点: 完全免费，视频自带同步音频生成，最长 8 秒。
    限制: 有速率限制，适合少量图片。
    参考: https://dev.to/diwushennian4955/free-veo3-api
    """

    BASE_URL = "https://api.nexaapi.ai/v1"

    def _log(self, msg: str):
        sys.stderr.write(f"  [Veo] {msg}\n")
        sys.stderr.flush()

    def generate_video(self, image_path: str, duration: int, api_key: str) -> str:
        self._log(f"generate_video called: image={image_path}, duration={duration}")
        duration = min(duration, 8)
        data_uri = self._encode_image(image_path)
        self._log(f"Data URI size: {len(data_uri)//1024} KB")
        headers = {
            "Authorization": f"Bearer {api_key or 'free'}",
            "Content-Type": "application/json",
        }

        self._log(f"POST {self.BASE_URL}/video/generate")
        try:
            resp = requests.post(
                f"{self.BASE_URL}/video/generate",
                headers=headers,
                json={
                    "model": "veo-3.1-lite-i2v",
                    "image_url": data_uri,
                    "duration": duration,
                    "aspect_ratio": "16:9",
                },
                timeout=30,
            )
            self._log(f"Status: {resp.status_code}")
            data = resp.json()
            if resp.status_code != 200:
                self._log(f"FAILED: {data.get('message', resp.text)}")
                raise AIServiceError(f"Veo 生成失败: {data.get('message', resp.text)}")

            # 同步返回
            video_url = data.get("video_url") or data.get("url")
            if video_url:
                self._log(f"Sync response, downloading: {video_url[:80]}...")
                return self._download_video(video_url)

            # 异步轮询
            task_id = data.get("task_id") or data.get("id")
            if task_id:
                self._log(f"Async task: {task_id}")
                return self._poll_and_download(task_id, headers)

            self._log(f"Unknown response format: {data}")
            raise AIServiceError("Veo 返回格式未知")
        except requests.RequestException as e:
            self._log(f"Network error: {e}")
            raise AIServiceError(f"Veo 网络错误: {e}")

    def _poll_and_download(self, task_id: str, headers: dict) -> str:
        """轮询 Veo 任务并下载视频。"""
        url = f"{self.BASE_URL}/video/status/{task_id}"
        self._log(f"Polling {task_id}...")
        start = time.time()
        last_status = ""
        while time.time() - start < 600:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                data = resp.json()
                status = data.get("status", "")
                if status != last_status:
                    self._log(f"[{int(time.time()-start)}s] Status: {status}")
                    last_status = status
                if status in ("completed", "done"):
                    video_url = data.get("video_url") or data.get("url")
                    if video_url:
                        self._log(f"Downloading: {video_url[:80]}...")
                        return self._download_video(video_url)
                    self._log("Completed but no video URL!")
                    raise AIServiceError("Veo 完成但无视频 URL")
                elif status in ("failed", "error"):
                    self._log(f"Task failed: {data.get('message')}")
                    raise AIServiceError(f"Veo 任务失败: {data.get('message')}")
            except requests.RequestException:
                pass
            time.sleep(2)
        self._log("Timeout!")
        raise AIServiceError("Veo 任务超时")

    def _download_video(self, video_url: str) -> str:
        """下载 Veo 视频到临时文件。"""
        try:
            resp = requests.get(video_url, timeout=120, stream=True)
            resp.raise_for_status()
            fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="veo_ai_")
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            self._log(f"Downloaded: {tmp_path} ({os.path.getsize(tmp_path)/1024:.0f} KB)")
            return tmp_path
        except requests.RequestException as e:
            self._log(f"Download failed: {e}")
            raise AIServiceError(f"Veo 下载视频失败: {e}")


class DoubaoProvider(AIProvider):
    """豆包 Seedance 1.5 Pro — 通过火山方舟 Ark SDK 调用。

    模型: doubao-seedance-1-5-pro-251215
    图片通过 data URI (base64) 内嵌传输，无需托管到公网。
    参考: https://www.volcengine.com/docs/82379/1521675
    """

    BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
    MODEL = "doubao-seedance-1-5-pro-251215"

    def _log(self, msg: str):
        sys.stderr.write(f"  [Doubao] {msg}\n")
        sys.stderr.flush()

    def generate_video(self, image_path: str, duration: int, api_key: str, custom_prompt: str = None) -> str:
        self._log(f"generate_video called: image={image_path}, duration={duration}, prompt={custom_prompt and 'custom' or 'default'}")
        try:
            from volcenginesdkarkruntime import Ark
            self._log("Ark SDK imported OK")
        except ImportError as e:
            self._log(f"Ark SDK import FAILED: {e}")
            raise AIServiceError(
                "豆包 Seedance 需要 volcengine SDK，请运行: pip install 'volcengine-python-sdk[ark]'"
            )

        client = Ark(base_url=self.BASE_URL, api_key=api_key)
        self._log(f"Ark client created, base_url={self.BASE_URL}")

        # 将本地图片编码为 data URI
        self._log("Encoding image...")
        data_uri = self._encode_image(image_path)
        self._log(f"Data URI size: {len(data_uri)//1024} KB")

        # 豆包 i2v 只支持 5 秒和 10 秒
        doubao_duration = 5 if duration < 10 else 10
        if custom_prompt:
            prompt = f"{custom_prompt} --duration {doubao_duration} --camerafixed false --watermark true"
        else:
            prompt = (
                f"镜头缓缓推进，画面中的人物和景物自然微动，光影流转，"
                f"营造电影级氛围感 --duration {doubao_duration} --camerafixed false --watermark true"
            )
        self._log(f"Prompt: {prompt}")

        # Step 1: 提交生成任务
        self._log(f"Creating task (model={self.MODEL})...")
        try:
            create_result = client.content_generation.tasks.create(
                model=self.MODEL,
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            )
            task_id = create_result.id
            self._log(f"Task created: {task_id}")
        except Exception as e:
            self._log(f"Create task FAILED: {type(e).__name__}: {e}")
            raise AIServiceError(f"豆包 Seedance 创建任务失败: {e}")

        # Step 2: 轮询直到完成
        self._log(f"Polling task {task_id}...")
        start = time.time()
        timeout = 900
        last_status = ""
        while time.time() - start < timeout:
            try:
                get_result = client.content_generation.tasks.get(task_id=task_id)
            except Exception as e:
                self._log(f"Poll FAILED: {type(e).__name__}: {e}")
                raise AIServiceError(f"豆包 Seedance 查询状态失败: {e}")

            status = get_result.status
            if status != last_status:
                elapsed = int(time.time() - start)
                self._log(f"[{elapsed}s] Status: {status}")
                last_status = status

            if status == "succeeded":
                content = getattr(get_result, "content", None)
                video_url = None
                if content and hasattr(content, "video_url"):
                    video_url = content.video_url
                elif isinstance(content, dict):
                    video_url = content.get("video_url")
                if not video_url:
                    self._log(f"SUCCEEDED but no video_url! content={content}")
                    raise AIServiceError("豆包 Seedance 任务完成但缺少视频 URL")
                self._log(f"Video URL: {video_url[:80]}...")
                self._log("Downloading video...")
                tmp_path = self._download_video(video_url)
                self._log(f"Downloaded: {tmp_path} ({os.path.getsize(tmp_path)/1024:.0f} KB)")
                return tmp_path

            elif status in ("failed", "cancelled", "error"):
                err = getattr(get_result, "error", None)
                err_msg = str(err) if err else status
                self._log(f"Task FAILED: {err_msg}")
                raise AIServiceError(f"豆包 Seedance 任务失败: {err_msg}")

            time.sleep(3)
        self._log(f"Timeout after {timeout}s")
        raise AIServiceError("豆包 Seedance 任务超时（15 分钟）")

    def _download_video(self, video_url: str) -> str:
        """下载视频到临时文件，返回本地路径。"""
        try:
            resp = requests.get(video_url, timeout=180, stream=True)
            resp.raise_for_status()
            fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="doubao_ai_")
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return tmp_path
        except requests.RequestException as e:
            raise AIServiceError(f"豆包 Seedance 下载视频失败: {e}")


# 服务注册表
# 注意: "seedance" 和 "atlas" 共用 AtlasProvider，seedance 使用默认模型 seedance-2.0
class SeedanceProvider(AtlasProvider):
    """Seedance 2.0（字节/即梦）— 图片转视频效果最佳。"""
    def __init__(self):
        super().__init__(model="seedance-2.0")


class DoubaoFastProvider(DoubaoProvider):
    """豆包 Seedance 1.0 Pro Fast — 极速图生视频，适合快速预览。"""

    MODEL = "doubao-seedance-1-0-pro-fast-251015"

    def _log(self, msg: str):
        pass  # 静默，不打印日志


AI_PROVIDERS = {
    "seedance": SeedanceProvider,      # Seedance 2.0（每日 225 免费积分）
    "doubao": DoubaoProvider,         # 🥇 豆包 Seedance 1.5 Pro（效果最佳）
    "doubao-fast": DoubaoFastProvider, # ⚡ 豆包 Seedance 1.0 Pro Fast（极速）
    "veo": VeoProvider,               # Google Veo 3.1 Lite（免费 + 音频）
    "atlas": AtlasProvider,           # Atlas Cloud 多模型网关
}


def get_provider(name: str, **kwargs) -> AIProvider:
    """根据名称获取 AI Provider 实例。

    Args:
        name: Provider 名称 (seedance/veo/atlas)
        **kwargs: 传递给 Provider 构造函数的额外参数 (如 model)

    Returns:
        AIProvider 实例

    Raises:
        AIServiceError: 不支持的 provider
    """
    cls = AI_PROVIDERS.get(name)
    if cls is None:
        raise AIServiceError(
            f"不支持的 AI 服务: {name}。可用: {list(AI_PROVIDERS.keys())}"
        )
    return cls(**kwargs)
