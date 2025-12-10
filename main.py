from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import asyncio
import httpx

@register("astrbot_plugin_pixiv_yuki", "NightDust981989 & xueelf", "pixiv第三方图床", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.random_api = "https://pixiv.yuki.sh/api/recommend"
        self.illust_api = "https://pixiv.yuki.sh/api/illust"
        # 定义 httpx 异步客户端
        self.client: httpx.AsyncClient | None = None
        self.background_task: asyncio.Task | None = None

    async def initialize(self):
        """初始化：创建复用的 httpx 异步客户端"""
        # 配置超时、默认头信息
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),  # 全局超时 10 秒
            headers={"User-Agent": "astrbot_plugin_pixiv_yuki/1.0.0"}
        )
        # 示例后台心跳任务
        self.background_task = asyncio.create_task(self._heartbeat())
        logger.info("Pixiv图床插件已初始化")

    async def _heartbeat(self):
        """示例后台心跳任务"""
        while True:
            try:
                await asyncio.sleep(300)
                logger.debug("Pixiv插件心跳正常")
            except asyncio.CancelledError:
                logger.debug("Pixiv插件心跳已终止")
                break

    @filter.command("pixiv")
    async def pixiv(self, event: AstrMessageEvent):
        message_str = event.message_str.strip()
        user_name = event.get_sender_name()
        args = message_str.split()

        if len(args) < 2:
            yield event.plain_result(
                f"Hello {user_name}~ 请按格式使用：\n"
                "/pixiv random [size]（size：mini/thumb/small/regular/original）\n"
                "/pixiv illust [作品id]"
            )
            return

        command_type = args[1]
        try:
            if command_type == "random":
                # 随机图片逻辑
                size = args[2] if len(args) >= 3 else "original"
                params = {"type": "json", "size": size, "proxy": "i.yuki.sh"}
                # httpx 异步请求
                resp = await self.client.get(self.random_api, params=params)
                resp.raise_for_status()  # 主动抛出 HTTP 错误
                data = resp.json()
                yield event.plain_result(f"随机Pixiv图片：\n{data.get('url', '获取失败')}")

            elif command_type == "illust":
                # 作品查询逻辑
                if len(args) < 3:
                    yield event.plain_result("请输入作品id：/pixiv illust [id]")
                    return
                tid = args[2]
                params = {"tid": tid, "proxy": "i.yuki.sh"}
                resp = await self.client.get(self.illust_api, params=params)
                resp.raise_for_status()
                data = resp.json()
                if data.get("urls"):
                    msg = f"作品{tid}链接：\n原图：{data['urls']['original']}\n常规：{data['urls']['regular']}"
                    yield event.plain_result(msg)
                else:
                    yield event.plain_result("作品id无效/含R-18内容")

            else:
                yield event.plain_result("指令类型错误 可选：random/illust")

        except httpx.HTTPStatusError as e:
            # 捕获 HTTP 状态码错误
            logger.error(f"HTTP请求错误 {e.response.status_code}：{str(e)}")
            yield event.plain_result(f"请求失败（{e.response.status_code}），请稍后再试")
        except httpx.TimeoutException:
            logger.error("API请求超时")
            yield event.plain_result("请求超时，请检查网络或稍后再试")
        except Exception as e:
            logger.error(f"API请求失败：{str(e)}")
            yield event.plain_result("调用API出错，请稍后再试")

    async def terminate(self):
        """销毁方法：优雅清理 httpx 客户端和后台任务"""
        # 关闭 httpx 异步客户端
        if self.client and not self.client.is_closed:
            await self.client.aclose()
            logger.info("已关闭 httpx 异步客户端")

        # 取消后台任务
        if self.background_task and not self.background_task.done():
            self.background_task.cancel()
            await self.background_task
            logger.info("已终止后台心跳任务")

        logger.info("Pixiv图床插件已优雅销毁")