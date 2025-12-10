from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import asyncio
import httpx

@register("astrbot_plugin_pixiv_yuki", "NightDust981989 & xueelf", "pixiv第三方图床", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.proxy = self.context.config.get("proxy", "pixiv.yuki.sh")
        self.default_size = self.context.config.get("default_size", "original")
        self.client = httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            verify=False
        )

    @filter.command("pixiv")
    async def pixiv(self, event: AstrMessageEvent):
        # 完全模仿示例的 yield 写法
        args = event.message_str.strip().split()
        
        if len(args) < 2:
            yield event.plain_result(
                f"请按格式使用：\n"
                f"/pixiv random [size]（可选：mini/thumb/small/regular/original，默认：{self.default_size}）\n"
                f"/pixiv illust [作品id]"
            )
            return

        if args[1] == "random":
            size = args[2] if len(args)>=3 and args[2] in ["mini","thumb","small","regular","original"] else self.default_size
            try:
                resp = await self.client.get(f"https://{self.proxy}/api/recommend", params={"type":"json", "proxy":self.proxy})
                data = resp.json()
                if data.get("success") and data.get("data"):
                    img_url = data["data"]["urls"].get(size, data["data"]["urls"]["original"])
                    # 模仿示例：逐个 yield 发送
                    yield event.plain_result(
                        f"随机Pixiv图片\n标题：{data['data']['title']}\n作者：{data['data']['user']['name']}\n链接：{img_url}"
                    )
                    yield event.image_result(img_url)  # 与示例一致的图片发送方式
                else:
                    yield event.plain_result("获取图片失败")
            except Exception as e:
                yield event.plain_result(f"错误：{str(e)[:50]}")
        
        elif args[1] == "illust":
            if len(args)<3 or not args[2].isdigit():
                yield event.plain_result("请输入作品ID：/pixiv illust 123456")
                return
            try:
                resp = await self.client.get(f"https://{self.proxy}/api/illust", params={"tid":args[2], "proxy":self.proxy})
                data = resp.json()
                if data.get("success") and data.get("data"):
                    img_url = data["data"]["urls"]["regular"]
                    # 模仿示例：逐个 yield 发送
                    yield event.plain_result(
                        f"作品详情（ID：{args[2]}）\n标题：{data['data']['title']}\n作者：{data['data']['user']['name']}"
                    )
                    yield event.image_result(img_url)  # 与示例一致的图片发送方式
                else:
                    yield event.plain_result("作品不存在或获取失败")
            except Exception as e:
                yield event.plain_result(f"错误：{str(e)[:50]}")
        
        else:
            yield event.plain_result("指令错误，可选：random/illust")

    async def terminate(self):
        await self.client.aclose()