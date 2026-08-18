from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import asyncio
import httpx
import tempfile
import os
from typing import AsyncGenerator
import tempfile
import os

@register("astrbot_plugin_pixiv_yuki", "NightDust981989 & xueelf", "pixiv第三方图床", "1.2.0","https://github.com/NightDust981989/astrbot_plugin_pixiv_yuki")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.random_api = "https://pixiv.yuki.sh/api/recommend"
        self.illust_api = "https://pixiv.yuki.sh/api/illust"
        self.client: httpx.AsyncClient | None = None
        self.background_task: asyncio.Task | None = None
        self.heartbeat_url = "https://blog.yuki.sh"

    async def initialize(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://pixiv.yuki.sh/",  
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            headers=headers,
            follow_redirects=False
        )
        self.background_task = asyncio.create_task(self._heartbeat())
        logger.info("Pixiv图床插件已初始化")

    async def _heartbeat(self):
        while True:
            try:
                await asyncio.sleep(300)
                try:
                    resp = await self.client.head(self.heartbeat_url, timeout=httpx.Timeout(10.0))
                    resp.raise_for_status()
                    logger.debug("Pixiv插件心跳正常")
                except Exception as e:
                    logger.warning(f"Pixiv插件心跳检测异常：{str(e)}")
            except asyncio.CancelledError:
                logger.debug("Pixiv插件心跳已终止")
                break

    def _validate_size(self, size: str) -> str:
        valid_sizes = ["mini", "thumb", "small", "regular", "original"]
        return size if size in valid_sizes else "original"

    async def _download_image(self, url: str) -> str | None:
        """下载图片到本地临时文件，返回文件路径"""
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name
            logger.debug(f"图片已保存至临时文件：{tmp_path}")
            return tmp_path
        except Exception as e:
            logger.error(f"图片下载失败 [{url}]: {e}")
            return None

    async def _delete_file(self, path: str):
        """延迟删除临时文件"""
        try:
            await asyncio.sleep(2)
            if os.path.exists(path):
                os.unlink(path)
                logger.debug(f"已删除临时文件：{path}")
        except Exception as e:
            logger.warning(f"删除临时文件失败：{e}")

    async def _send_image(self, url: str, event: AstrMessageEvent):
        """下载图片到本地并发送，自动清理临时文件"""
        img_path = await self._download_image(url)
        if img_path:
            yield event.image_result(img_path)
            asyncio.create_task(self._delete_file(img_path))
        else:
            yield event.plain_result("图片下载失败，请稍后重试")

    async def _download_image(self, url: str) -> str | None:
        """下载图片并保存为临时文件，返回文件路径（字符串）"""
        if not url:
            return None
        url = self._fix_url(url)
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name
            logger.debug(f"图片已保存至临时文件：{tmp_path}")
            return tmp_path
        except Exception as e:
            logger.error(f"图片下载失败 [{url}]: {e}")
            return None

    async def _delete_file(self, path: str):
        """延迟删除临时文件"""
        try:
            await asyncio.sleep(2)
            if os.path.exists(path):
                os.unlink(path)
                logger.debug(f"已删除临时文件：{path}")
        except Exception as e:
            logger.warning(f"删除临时文件失败：{e}")

    @filter.command("pixiv")
    async def pixiv(self, event: AstrMessageEvent):
        message_str = event.message_str.strip()
        args = message_str.split()

        if len(args) < 2:
            help_text = (
                "请按格式使用：\n"
                "/pixiv random [size]（可选size：mini/thumb/small/regular/original*默认）\n"
                "/pixiv illust [作品id]"
            )
            yield event.plain_result(help_text)
            return

        command_type = args[1]
        try:
            if command_type == "random":
                size = self._validate_size(args[2] if len(args) >= 3 else self.config.get("default_image_size", "original"))
                params = {"type": "json"} 
                
                resp = await self.client.get(self.random_api, params=params)
                resp.raise_for_status()
                data = resp.json()

                if data.get("success") and data.get("data"):
                    image_data = data["data"]
                    
                    original_url = image_data["urls"].get(size, image_data["urls"]["original"])
                    
                    if self.config.get("show_image_info", True):
                        basic_info = (
                            f"随机Pixiv图片\n"
                            f"标题：{image_data['title']}\n"
                            f"作者：{image_data['user']['name']} (ID: {image_data['user']['id']})\n"
                            f"标签：{', '.join(image_data['tags'])}"
                        )
                        yield event.plain_result(basic_info)

                    async for result in self._send_image(original_url, event):
                        yield result

                else:
                    yield event.plain_result(f"{data.get('message', '获取失败')}")

            elif command_type == "illust":
                if len(args) < 3:
                    yield event.plain_result("请输入作品id：/pixiv illust [id]")
                    return
                pid = args[2]
                if not pid.isdigit():
                    yield event.plain_result("作品ID必须是数字")
                    return

                params = {"id": pid}
                resp = await self.client.get(self.illust_api, params=params)
                resp.raise_for_status()
                data = resp.json()

                if data.get("success") and data.get("data"):
                    image_data = data["data"]
                    urls = image_data.get("urls", {})
                    original_url = urls.get("original")
                    
                    new_original = original_url  # 直接使用 API 返回的 URL
                    
                    
                    # 处理描述字段
                    description = image_data.get("description", "无")
                    
                    # 输出作品基础信息
                    user = image_data.get("user", {})
                    basic_info = (
                        f"作品详情 (ID: {image_data['id']})\n"
                        f"标题：{image_data['title']}\n"
                        f"作者：{user.get('name', '未知')} (ID: {user.get('id', '未知')} | 账号：{user.get('account', '未知')})\n"
                        f"描述：{image_data.get('description', '无')}\n"
                        f"标签：{', '.join(image_data.get('tags', []))}"
                    )
                    yield event.plain_result(basic_info)
                    
                    # 仅当图片URL存在时发送图片
                    if new_original:
                        async for result in self._send_image(new_original, event):
                            yield result
                    else:
                        yield event.plain_result("图片下载失败，请稍后重试")
                else:
                    yield event.plain_result(f"{data.get('message', '作品不存在')}")

            else:
                yield event.plain_result("指令类型错误 可选：random/illust")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP请求错误 {e.response.status_code}：{str(e)}")
            yield event.plain_result(f"请求失败（状态码：{e.response.status_code}），请稍后再试")
        except httpx.TimeoutException:
            yield event.plain_result("请求超时，请检查网络或稍后再试")
        except httpx.ConnectError:
            yield event.plain_result("连接失败，请检查网络或API服务是否可用")
        except KeyError as e:
            yield event.plain_result(f"数据解析错误，缺少字段：{str(e)}")
        except Exception as e:
            logger.error(f"API请求失败：{str(e)}", exc_info=True)
            yield event.plain_result(f"调用API出错：{str(e)[:50]}...")

    @filter.llm_tool(name="pixiv_random")
    async def pixiv_random(self, event: AstrMessageEvent, size: str = "") -> AsyncGenerator[MessageEventResult, None]:
        '''获取一张随机的Pixiv图片。'''
        size = self._validate_size(size) if size else self.config.get("default_image_size", "original")
        try:
            params = {"type": "json"}
            resp = await self.client.get(self.random_api, params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("success") and data.get("data"):
                image_data = data["data"]
                original_url = image_data["urls"].get(size, image_data["urls"]["original"])
                # 直接使用 API 返回的 URL，无需替换域名

                if self.config.get("show_image_info", True):
                    basic_info = (
                        f"随机Pixiv图片\n"
                        f"标题：{image_data['title']}\n"
                        f"作者：{image_data['user']['name']} (ID: {image_data['user']['id']})\n"
                        f"标签：{', '.join(image_data['tags'])}"
                    )
                    yield event.plain_result(basic_info)
                async for result in self._send_image(original_url, event):
                    yield result
            else:
                yield event.plain_result(f"{data.get('message', '获取失败')}")
        except Exception as e:
            logger.error(f"随机图片请求失败：{str(e)}", exc_info=True)
            yield event.plain_result(f"请求出错：{str(e)[:50]}...")

    @filter.llm_tool(name="pixiv_illust")
    async def pixiv_illust(self, event: AstrMessageEvent, id: str) -> AsyncGenerator[MessageEventResult, None]:
        '''根据作品ID查询Pixiv作品详情并发送图片。'''
        if not id.isdigit():
            yield event.plain_result("作品ID必须是数字")
            return
        try:
            params = {"id": id}
            resp = await self.client.get(self.illust_api, params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("success") and data.get("data"):
                image_data = data["data"]
                urls = image_data.get("urls", {})
                original_url = urls.get("original")
                new_original = original_url  # 直接使用 API 返回的 URL

                description = image_data.get("description", "无")
                user = image_data.get("user", {})
                basic_info = (
                    f"作品详情 (ID: {image_data['id']})\n"
                    f"标题：{image_data['title']}\n"
                    f"作者：{user.get('name', '未知')} (ID: {user.get('id', '未知')} | 账号：{user.get('account', '未知')})\n"
                    f"描述：{image_data.get('description', '无')}\n"
                    f"标签：{', '.join(image_data.get('tags', []))}"
                )
                yield event.plain_result(basic_info)

                if new_original:
                    async for result in self._send_image(new_original, event):
                        yield result
                else:
                    yield event.plain_result("图片下载失败，请稍后重试")
            else:
                yield event.plain_result(f"{data.get('message', '作品不存在')}")
        except Exception as e:
            logger.error(f"作品详情请求失败：{str(e)}", exc_info=True)
            yield event.plain_result(f"请求出错：{str(e)[:50]}...")

    async def terminate(self):
        if self.client and not self.client.is_closed:
            try:
                await self.client.aclose()
                logger.info("已关闭 httpx 异步客户端")
            except Exception as e:
                logger.error(f"关闭客户端失败：{str(e)}")
        if self.background_task and not self.background_task.done():
            self.background_task.cancel()
            try:
                await self.background_task
            except asyncio.CancelledError:
                pass
            logger.info("已终止后台心跳任务")
        logger.info("Pixiv图床插件已优雅销毁")
