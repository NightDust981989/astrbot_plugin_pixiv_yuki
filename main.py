from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import asyncio
import httpx

@register("astrbot_plugin_pixiv_yuki", "NightDust981989 & xueelf", "pixiv第三方图床", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.random_api = "https://pixiv.yuki.sh/api/recommend"
        self.illust_api = "https://pixiv.yuki.sh/api/illust"
        self.client: httpx.AsyncClient | None = None
        self.background_task: asyncio.Task | None = None

    async def initialize(self):
        """初始化：创建复用的 httpx 异步客户端，优化请求头"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://pixiv.yuki.sh/",
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

    def _validate_size(self, size: str) -> str:
        """验证并修正图片尺寸参数"""
        valid_sizes = ["mini", "thumb", "small", "regular", "original"]
        return size if size in valid_sizes else "original"

    @filter.command("pixiv")
    async def pixiv(self, event: AstrMessageEvent):
        message_str = event.message_str.strip()
        sender_id = event.get_sender_id()  # 获取发送者ID
        args = message_str.split()

        if len(args) < 2:
            # 构造帮助信息的消息链
            help_chain = [
                Comp.At(qq=sender_id),
                Comp.Plain("\n请按格式使用：\n/pixiv random [size]（可选size：mini/thumb/small/regular/original*默认）\n/pixiv illust [作品id]")
            ]
            yield event.chain_result(help_chain)
            return

        command_type = args[1]
        try:
            if command_type == "random":
                # 随机图片逻辑 - 构造消息链（At + 文本 + 图片）
                size = self._validate_size(args[2] if len(args) >= 3 else "original")
                params = {
                    "type": "json",
                    "proxy": "pixiv.yuki.sh"
                }
                
                resp = await self.client.get(self.random_api, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                if data.get("success") and data.get("data"):
                    image_data = data["data"]
                    image_url = image_data["urls"].get(size, image_data["urls"]["original"])
                    
                    # 构造图片信息文本
                    info_text = (
                        f"\n随机Pixiv图片\n"
                        f"标题：{image_data['title']}\n"
                        f"作者：{image_data['user']['name']} (ID: {image_data['user']['id']})\n"
                        f"标签：{', '.join(image_data['tags'])}\n"
                    )
                    
                    # 构建消息链（At + 文本 + 图片）
                    chain = [
                        Comp.At(qq=sender_id),  # At发送者
                        Comp.Plain(info_text),  # 图片信息文本
                        Comp.Image.fromURL(image_url)  # 从URL加载图片
                    ]
                    yield event.chain_result(chain)

                else:
                    error_chain = [
                        Comp.At(qq=sender_id),
                        Comp.Plain(f"\n{data.get('message', '获取失败，返回数据异常')}")
                    ]
                    yield event.chain_result(error_chain)

            elif command_type == "illust":
                # 作品查询逻辑 - 构造消息链（At + 文本 + 图片）
                if len(args) < 3:
                    empty_id_chain = [
                        Comp.At(qq=sender_id),
                        Comp.Plain("\n请输入作品id：/pixiv illust [id]")
                    ]
                    yield event.chain_result(empty_id_chain)
                    return
                    
                tid = args[2]
                if not tid.isdigit():
                    invalid_id_chain = [
                        Comp.At(qq=sender_id),
                        Comp.Plain("\n作品ID必须是数字")
                    ]
                    yield event.chain_result(invalid_id_chain)
                    return
                    
                params = {
                    "tid": tid,
                    "proxy": "pixiv.yuki.sh"
                }
                
                resp = await self.client.get(self.illust_api, params=params)
                resp.raise_for_status()
                data = resp.json()
                
                if data.get("success") and data.get("data"):
                    image_data = data["data"]
                    original_url = image_data["urls"]["original"]
                    regular_url = image_data["urls"]["regular"]
                    
                    # 构造作品详情文本
                    detail_text = (
                        f"\n作品详情 (ID: {tid})\n"
                        f"标题：{image_data['title']}\n"
                        f"描述：{image_data['description'] or '无'}\n"
                        f"作者：{image_data['user']['name']} (ID: {image_data['user']['id']})\n"
                        f"标签：{', '.join(image_data['tags'])}\n\n"
                        
                    )
                    
                    # 构建消息链（优先显示常规尺寸图片，加载更快）
                    chain = [
                        Comp.At(qq=sender_id),
                        Comp.Plain(detail_text),
                        Comp.Image.fromURL(regular_url)  # 发送常规尺寸图片
                    ]
                    yield event.chain_result(chain)

                else:
                    not_found_chain = [
                        Comp.At(qq=sender_id),
                        Comp.Plain(f"\n{data.get('message', '作品不存在或包含R-18内容')}")
                    ]
                    yield event.chain_result(not_found_chain)

            else:
                error_type_chain = [
                    Comp.At(qq=sender_id),
                    Comp.Plain("\n指令类型错误 可选：random/illust")
                ]
                yield event.chain_result(error_type_chain)

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP请求错误 {e.response.status_code}：{str(e)}")
            error_detail = f"（状态码：{e.response.status_code}）"
            if e.response.status_code == 404:
                error_detail += " - API地址可能已变更或资源不存在"
            elif e.response.status_code == 403:
                error_detail += " - 访问被拒绝，可能是IP限制"
            error_chain = [
                Comp.At(qq=sender_id),
                Comp.Plain(f"\n请求失败{error_detail}，请稍后再试")
            ]
            yield event.chain_result(error_chain)
            
        except httpx.TimeoutException:
            logger.error("API请求超时")
            timeout_chain = [
                Comp.At(qq=sender_id),
                Comp.Plain("\n请求超时，请检查网络或稍后再试")
            ]
            yield event.chain_result(timeout_chain)
            
        except httpx.ConnectError:
            logger.error("API连接失败")
            connect_chain = [
                Comp.At(qq=sender_id),
                Comp.Plain("\n连接失败，请检查网络或API服务是否可用")
            ]
            yield event.chain_result(connect_chain)
            
        except KeyError as e:
            logger.error(f"数据解析错误，缺少字段：{str(e)}")
            key_chain = [
                Comp.At(qq=sender_id),
                Comp.Plain(f"\n数据解析错误，缺少字段：{str(e)}")
            ]
            yield event.chain_result(key_chain)
            
        except Exception as e:
            logger.error(f"API请求失败：{str(e)}", exc_info=True)
            exp_chain = [
                Comp.At(qq=sender_id),
                Comp.Plain(f"\n调用API出错：{str(e)[:50]}...")
            ]
            yield event.chain_result(exp_chain)

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