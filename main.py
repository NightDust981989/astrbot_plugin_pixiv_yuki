from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import asyncio
import httpx

@register("astrbot_plugin_pixiv_yuki", "NightDust981989 & xueelf", "pixiv第三方图床", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # API地址
        self.random_api = "https://pixiv.yuki.sh/api/recommend"
        self.illust_api = "https://pixiv.yuki.sh/api/illust"
        self.client: httpx.AsyncClient | None = None
        self.background_task: asyncio.Task | None = None
        # 定义域名替换规则
        self.old_domain = "pixiv.yuki.sh"
        self.new_domain = "i.yuki.sh"

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
        """后台心跳任务"""
        while True:
            try:
                await asyncio.sleep(300)
                logger.debug("Pixiv插件心跳正常")
            except asyncio.CancelledError:
                logger.debug("Pixiv插件心跳已终止")
                break

    def _validate_size(self, size: str) -> str:
        """验证图片尺寸参数"""
        valid_sizes = ["mini", "thumb", "small", "regular", "original"]
        return size if size in valid_sizes else "original"

    def _replace_domain(self, url: str) -> str:
        """统一替换URL中的域名：pixiv.yuki.sh → i.yuki.sh"""
        if self.old_domain in url:
            new_url = url.replace(self.old_domain, self.new_domain)
            logger.debug(f"URL域名替换：{url} → {new_url}")
            return new_url
        return url

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
                size = self._validate_size(args[2] if len(args) >= 3 else "original")
                params = {"type": "json", "proxy": "pixiv.yuki.sh"} 
                
                resp = await self.client.get(self.random_api, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                if data.get("success") and data.get("data"):
                    image_data = data["data"]
                    
                    original_url = image_data["urls"].get(size, image_data["urls"]["original"])
                    new_url = self._replace_domain(original_url)  # 替换域名
                    
                    basic_info = (
                        f"随机Pixiv图片\n"
                        f"标题：{image_data['title']}\n"
                        f"作者：{image_data['user']['name']} (ID: {image_data['user']['id']})\n"
                        f"标签：{', '.join(image_data['tags'])}"
                    )
                    yield event.plain_result(basic_info)
                    
                    yield event.image_result(new_url)
                    
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
                    
                    new_original = self._replace_domain(original_url) if original_url else None
                    
                    
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
                        yield event.image_result(new_original)
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