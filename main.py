from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import asyncio
import httpx

@register("astrbot_plugin_pixiv_yuki", "NightDust981989 & xueelf", "pixiv第三方图床", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 基础 API 地址（域名从配置读取）
        self.random_api = "https://{proxy}/api/recommend"
        self.illust_api = "https://{proxy}/api/illust"
        self.client: httpx.AsyncClient | None = None
        self.background_task: asyncio.Task | None = None
        
        # 从配置读取参数（默认值兜底）
        self.proxy = self.context.config.get("proxy", "pixiv.yuki.sh")  # 代理域名
        self.default_size = self.context.config.get("default_size", "original")  # 默认图片尺寸

    async def initialize(self):
        """初始化：创建复用的 httpx 异步客户端，使用配置的 proxy"""
        # 替换 API 地址中的 proxy 占位符
        self.random_api = self.random_api.format(proxy=self.proxy)
        self.illust_api = self.illust_api.format(proxy=self.proxy)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"https://{self.proxy}/",  # 适配配置的 proxy
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            headers=headers,
            verify=False,
            follow_redirects=False
        )
        self.background_task = asyncio.create_task(self._heartbeat())
        logger.info(f"Pixiv图床插件已初始化 | 代理域名：{self.proxy} | 默认尺寸：{self.default_size}")

    async def _heartbeat(self):
        """后台心跳任务"""
        while True:
            try:
                await asyncio.sleep(300)
                logger.debug(f"Pixiv插件心跳正常 | 代理：{self.proxy}")
            except asyncio.CancelledError:
                logger.debug("Pixiv插件心跳已终止")
                break

    def _validate_size(self, size: str) -> str:
        """验证图片尺寸参数（优先使用用户输入，否则用配置的默认值）"""
        valid_sizes = ["mini", "thumb", "small", "regular", "original"]
        return size if size in valid_sizes else self.default_size

    @filter.command("pixiv")
    async def pixiv(self, event: AstrMessageEvent):
        message_str = event.message_str.strip()
        args = message_str.split()

        # 帮助信息（纯文本）
        if len(args) < 2:
            yield event.plain_result(
                f"请按格式使用：\n"
                f"/pixiv random [size]（可选size：mini/thumb/small/regular/original*当前默认：{self.default_size}）\n"
                f"/pixiv illust [作品id]"
            )
            return

        command_type = args[1]
        try:
            if command_type == "random":
                # 随机图片逻辑：先返本文本信息，再单独发图片URL
                size = self._validate_size(args[2] if len(args) >= 3 else "")
                params = {"type": "json", "proxy": self.proxy}  # 使用配置的 proxy
                
                resp = await self.client.get(self.random_api, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                if data.get("success") and data.get("data"):
                    image_data = data["data"]
                    image_url = image_data["urls"].get(size, image_data["urls"][self.default_size])
                    
                    # 第一步：发送文本信息（单独的plain消息）
                    text_msg = (
                        f"随机Pixiv图片\n"
                        f"标题：{image_data['title']}\n"
                        f"作者：{image_data['user']['name']} (ID: {image_data['user']['id']})\n"
                        f"标签：{', '.join(image_data['tags'])}\n"
                        f"图片链接：{image_url}"
                    )
                    yield event.plain_result(text_msg)
                    
                    # 第二步：单独发送图片URL（使用image_result）
                    if image_url.startswith(("http://", "https://")):
                        yield event.image_result(image_url)
                    else:
                        yield event.plain_result("图片URL格式错误，无法发送图片")
                else:
                    yield event.plain_result(f"{data.get('message', '获取失败，返回数据异常')}")

            elif command_type == "illust":
                # 作品查询逻辑：先返本文本，再发图片
                if len(args) < 3:
                    yield event.plain_result("请输入作品id：/pixiv illust [id]")
                    return
                    
                tid = args[2]
                if not tid.isdigit():
                    yield event.plain_result("作品ID必须是数字")
                    return
                    
                params = {"tid": tid, "proxy": self.proxy}  # 使用配置的 proxy
                resp = await self.client.get(self.illust_api, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                if data.get("success") and data.get("data"):
                    image_data = data["data"]
                    original_url = image_data["urls"]["original"]
                    regular_url = image_data["urls"]["regular"]
                    
                    # 第一步：发送作品详情文本
                    text_msg = (
                        f"作品详情 (ID: {tid})\n"
                        f"标题：{image_data['title']}\n"
                        f"描述：{image_data['description'] or '无'}\n"
                        f"作者：{image_data['user']['name']} (ID: {image_data['user']['id']})\n"
                        f"创建时间：{image_data['createDate'].replace('T', ' ').replace('.000Z', '')}\n"
                        f"标签：{', '.join(image_data['tags'])}\n\n"
                        f"原图：{original_url}\n"
                        f"常规尺寸：{regular_url}\n"
                        f"缩略图：{image_data['urls']['thumb']}"
                    )
                    yield event.plain_result(text_msg)
                    
                    # 第二步：单独发送常规尺寸图片（优先发这个，加载更快）
                    if regular_url.startswith(("http://", "https://")):
                        yield event.image_result(regular_url)
                    else:
                        yield event.plain_result("图片URL格式错误，无法发送图片")
                else:
                    yield event.plain_result(f"{data.get('message', '作品不存在或包含R-18内容')}")

            else:
                yield event.plain_result("指令类型错误 可选：random/illust")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP请求错误 {e.response.status_code}：{str(e)}")
            error_detail = f"（状态码：{e.response.status_code}）"
            if e.response.status_code == 404:
                error_detail += " - API地址可能已变更或资源不存在"
            elif e.response.status_code == 403:
                error_detail += " - 访问被拒绝，可能是IP限制"
            yield event.plain_result(f"请求失败{error_detail}，请稍后再试")
            
        except httpx.TimeoutException:
            logger.error("API请求超时")
            yield event.plain_result("请求超时，请检查网络或稍后再试")
            
        except httpx.ConnectError:
            logger.error("API连接失败")
            yield event.plain_result("连接失败，请检查网络或API服务是否可用")
            
        except KeyError as e:
            logger.error(f"数据解析错误，缺少字段：{str(e)}")
            yield event.plain_result(f"数据解析错误，缺少字段：{str(e)}")
            
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