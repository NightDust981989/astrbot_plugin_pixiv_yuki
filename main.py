from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import asyncio
import httpx
from typing import AsyncGenerator
import tempfile
import os

@register("astrbot_plugin_pixiv_yuki", "NightDust981989 & xueelf", "pixiv第三方图床", "1.2.0","https://github.com/NightDust981989/astrbot_plugin_pixiv_yuki")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # API地址
        self.random_api = "https://pixiv.yuki.sh/api/recommend"
        self.illust_api = "https://pixiv.yuki.sh/api/illust"
        self.client: httpx.AsyncClient | None = None
        self.background_task: asyncio.Task | None = None
        self.heartbeat_url = "https://blog.yuki.sh"

    async def initialize(self):
        """初始化：创建复用的 httpx 异步客户端"""
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
        """后台心跳任务，检测yuki.sh服务可用性"""
        while True:
            try:
                await asyncio.sleep(300)
                # 心跳检测
                try:
                    # 使用HEAD请求减少数据传输
                    resp = await self.client.head(
                        self.heartbeat_url,
                        timeout=httpx.Timeout(10.0)
                    )
                    resp.raise_for_status()
                    logger.debug(f"Pixiv插件心跳正常")
                except httpx.HTTPStatusError as e:
                    logger.warning(f"Pixiv插件心跳检测异常：yuki.sh 返回状态码 {e.response.status_code}")
                except httpx.TimeoutException:
                    logger.warning("Pixiv插件心跳检测超时：连接yuki.sh超时")
                except httpx.ConnectError:
                    logger.warning("Pixiv插件心跳检测失败：无法连接到yuki.sh")
                except Exception as e:
                    logger.warning(f"Pixiv插件心跳检测异常：{str(e)}")
                    
            except asyncio.CancelledError:
                logger.debug("Pixiv插件心跳已终止")
                break

    def _validate_size(self, size: str) -> str:
        """验证图片尺寸参数"""
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
                    error_text = f"{data.get('message', '获取失败，返回数据异常')}"
                    yield event.plain_result(error_text)

            elif command_type == "illust":
                if len(args) < 3:
                    yield event.plain_result("请输入作品id：/pixiv illust [id]")
                    return
                    
                id = args[2]
                if not id.isdigit():
                    yield event.plain_result("作品ID必须是数字")
                    return
                    
                # 修复：删除多余的host参数，仅保留id参数
                params = {"id": id}  
                resp = await self.client.get(self.illust_api, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                if data.get("success") and data.get("data"):
                    image_data = data["data"]
                    
                    # 适配返回数据结构解析字段
                    # 处理URL（兼容null的情况）
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
                        f"描述：{description}\n"
                        f"标签：{', '.join(image_data.get('tags', []))}"
                    )
                    yield event.plain_result(basic_info)
                    
                    # 仅当图片URL存在时发送图片
                    if new_original:
                        async for result in self._send_image(new_original, event):
                            yield result
                    else:
                        yield event.plain_result("该作品为R-18内容，违法平台规则")
                    
                else:
                    yield event.plain_result(f"{data.get('message', '作品不存在')}")

            else:
                yield event.plain_result("指令类型错误 可选：random/illust")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP请求错误 {e.response.status_code}：{str(e)}")
            error_detail = f"（状态码：{e.response.status_code}）"
            if e.response.status_code == 404:
                error_detail += " - API地址可能已变更或资源不存在"
            elif e.response.status_code == 403:
                error_detail += " - 访问被拒绝，可能是IP限制"
            elif e.response.status_code == 401:
                error_detail += " - 找不到指定id的图片"
            yield event.plain_result(f"请求失败{error_detail}，请稍后再试")
            
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
        '''获取一张随机的Pixiv图片。

        Args:
            size(string): 图片尺寸，可选值：mini(迷你缩略图)、thumb(缩略图)、small(小图)、regular(常规图)、original(原图)。留空则使用配置中的默认尺寸
        '''
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
                yield event.plain_result(f"{data.get('message', '获取失败，返回数据异常')}")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP请求错误 {e.response.status_code}：{str(e)}")
            yield event.plain_result(f"请求失败（状态码：{e.response.status_code}），请稍后再试")
        except httpx.TimeoutException:
            yield event.plain_result("请求超时，请稍后再试")
        except httpx.ConnectError:
            yield event.plain_result("连接失败，请检查网络或API服务是否可用")
        except Exception as e:
            logger.error(f"API请求失败：{str(e)}", exc_info=True)
            yield event.plain_result(f"调用API出错：{str(e)[:50]}...")

    @filter.llm_tool(name="pixiv_illust")
    async def pixiv_illust(self, event: AstrMessageEvent, id: str) -> AsyncGenerator[MessageEventResult, None]:
        '''根据作品ID查询Pixiv作品详情并发送图片。

        Args:
            id(string): Pixiv作品ID，纯数字
        '''
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
                    f"描述：{description}\n"
                    f"标签：{', '.join(image_data.get('tags', []))}"
                )
                yield event.plain_result(basic_info)

                if new_original:
                    async for result in self._send_image(new_original, event):
                        yield result
                else:
                    yield event.plain_result("该作品为R-18内容，违法平台规则")
            else:
                yield event.plain_result(f"{data.get('message', '作品不存在')}")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP请求错误 {e.response.status_code}：{str(e)}")
            yield event.plain_result(f"请求失败（状态码：{e.response.status_code}），请稍后再试")
        except httpx.TimeoutException:
            yield event.plain_result("请求超时，请稍后再试")
        except httpx.ConnectError:
            yield event.plain_result("连接失败，请检查网络或API服务是否可用")
        except Exception as e:
            logger.error(f"API请求失败：{str(e)}", exc_info=True)
            yield event.plain_result(f"调用API出错：{str(e)[:50]}...")

    async def terminate(self):
        """销毁方法：优雅清理资源"""
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