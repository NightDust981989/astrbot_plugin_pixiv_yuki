from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger
import asyncio
import httpx

# 全局配置（模拟配置面板，如需可视化配置可后续适配）
# 对应 _conf_schema.json 的配置项，手动修改此处或后续对接配置面板
CONFIG = {
    "proxy": "pixiv.yuki.sh",  # 可在配置面板修改
    "default_size": "original" # 可在配置面板修改
}

# 全局异步客户端
client = httpx.AsyncClient(
    timeout=httpx.Timeout(15.0),
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://{CONFIG['proxy']}/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    },
    verify=False,
    follow_redirects=False
)

def _validate_size(size: str) -> str:
    """验证图片尺寸参数"""
    valid_sizes = ["mini", "thumb", "small", "regular", "original"]
    return size if size in valid_sizes else CONFIG["default_size"]

# 完全匹配示例的装饰器+方法写法（无self，仅event参数）
@filter.command("pixiv")
async def pixiv(event: AstrMessageEvent):
    message_str = event.message_str.strip()
    args = message_str.split()

    # 帮助信息（纯文本）
    if len(args) < 2:
        yield event.plain_result(
            f"请按格式使用：\n"
            f"/pixiv random [size]（可选size：mini/thumb/small/regular/original*当前默认：{CONFIG['default_size']}）\n"
            f"/pixiv illust [作品id]"
        )
        return

    command_type = args[1]
    try:
        if command_type == "random":
            # 随机图片逻辑：逐个yield发送
            size = _validate_size(args[2] if len(args) >= 3 else "")
            params = {"type": "json", "proxy": CONFIG["proxy"]}
            random_api = f"https://{CONFIG['proxy']}/api/recommend"
            
            resp = await client.get(random_api, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("success") and data.get("data"):
                image_data = data["data"]
                image_url = image_data["urls"].get(size, image_data["urls"][CONFIG["default_size"]])
                
                # 示例同款：yield 纯文本
                yield event.plain_result(
                    f"随机Pixiv图片\n"
                    f"标题：{image_data['title']}\n"
                    f"作者：{image_data['user']['name']} (ID: {image_data['user']['id']})\n"
                    f"标签：{', '.join(image_data['tags'])}\n"
                    f"图片链接：{image_url}"
                )
                # 示例同款：yield 图片URL
                if image_url.startswith(("http://", "https://")):
                    yield event.image_result(image_url)
                else:
                    yield event.plain_result("图片URL格式错误，无法发送图片")
            else:
                yield event.plain_result(f"{data.get('message', '获取失败，返回数据异常')}")

        elif command_type == "illust":
            # 作品查询逻辑：逐个yield发送
            if len(args) < 3:
                yield event.plain_result("请输入作品id：/pixiv illust [id]")
                return
                
            tid = args[2]
            if not tid.isdigit():
                yield event.plain_result("作品ID必须是数字")
                return
                
            params = {"tid": tid, "proxy": CONFIG["proxy"]}
            illust_api = f"https://{CONFIG['proxy']}/api/illust"
            
            resp = await client.get(illust_api, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("success") and data.get("data"):
                image_data = data["data"]
                original_url = image_data["urls"]["original"]
                regular_url = image_data["urls"]["regular"]
                
                # 示例同款：yield 纯文本
                yield event.plain_result(
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
                # 示例同款：yield 图片URL
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

# 插件停止时清理资源
@atexit.register
async def cleanup():
    await client.aclose()
    logger.info("Pixiv图床插件已清理资源并关闭")