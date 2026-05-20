"""
AI 画图插件

使用 DeepSeek V4 Flash 将用户的模糊描述翻译为英文图像提示词，
再调用 GPT-Image-2 生成图像。支持附带参考图进行图片编辑。

费用：100000 金币/次，每日限制 5 次/UID。
"""

import json
import base64
import sqlite3
import time
from pathlib import Path

import aiohttp
from nonebot import on_command, get_driver
from nonebot.adapters import Event, Bot
from nonebot.adapters.onebot.v11 import Message
from nonebot.log import logger
from nonebot.params import CommandArg, Depends
from nonebot.plugin import PluginMetadata

from ...money import UserWallet, wallet_manager, get_database_path
from ...su_manager import get_su_level, SU_LEVEL_CONTRIBUTOR
from ...tools import get_uid, build_image_msg, is_onebot, is_qqbot
from ...utils import FreqLimiter

__plugin_meta__ = PluginMetadata(
    name="ai_draw",
    description="AI画图 - DeepSeek翻译提示词 + GPT-Image-2生成图像",
    usage=(
        "冰祈画图 <描述>    生成图像\n"
        "冰祈修图 <描述> + 图片  编辑图像\n"
        "费用：100000金币/次，每日限5次"
    ),
)

driver = get_driver()

# 频率限制：每用户 30 秒一次
draw_limiter = FreqLimiter(30)

# 注册命令
draw_cmd = on_command(
    "冰祈画图",
    aliases={"冰祈绘图", "冰祈画个图", "冰祈绘个图", "梦灵画图", "梦灵绘图", "梦灵画个图", "梦灵绘个图"},
    priority=5,
    block=True,
)
edit_cmd = on_command(
    "冰祈修图", aliases={"梦灵修图"}, priority=5, block=True
)

# 插件目录
PLUGIN_DIR = Path(__file__).parent
CONFIG_PATH = PLUGIN_DIR / "config.json"

# 运行时配置 (启动时从 config.json 加载)
_config: dict = {}

# 费用与限制
DRAW_COST = 100000
DAILY_LIMIT = 5

# DeepSeek 系统提示词
PROMPT_TRANSLATE_SYSTEM = """You are a professional image prompt engineer. Your task is to convert the user's Chinese description into a concise, high-quality English prompt suitable for AI image generation (DALL-E / GPT-Image-2).

Rules:
1. Output ONLY the English prompt, nothing else — no quotes, no prefixes, no explanations.
2. The prompt should be vivid and descriptive, including style, lighting, composition details.
3. Keep it under 200 characters.
4. Preserve the user's intent faithfully — do not add concepts the user didn't mention."""

DEFAULT_CONFIG = {
    "comment": "AI画图插件配置 — deepseek_api_key 用于翻译提示词，gpt_image_api_key 用于生成图像",
    "deepseek_api_key": "",
    "gpt_image_api_key": ""
}


def get_config() -> dict:
    return _config


# ═══════════════ SQLite 日限 ═══════════════

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(get_database_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _get_db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ai_draw_usage (
                uid INTEGER PRIMARY KEY,
                date TEXT NOT NULL DEFAULT '',
                count INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.commit()


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


async def check_and_increment_daily_limit(uid: int) -> bool:
    """检查日限并递增。跨天自动清零。返回 True 表示未超限（已递增），False 表示超限。"""
    loop = __import__("asyncio").get_event_loop()
    today = _today()

    def _do():
        with _get_db() as conn:
            row = conn.execute(
                "SELECT date, count FROM ai_draw_usage WHERE uid=?", (uid,)
            ).fetchone()

            if row is None:
                conn.execute(
                    "INSERT INTO ai_draw_usage (uid, date, count) VALUES (?, ?, 1)",
                    (uid, today),
                )
                conn.commit()
                return True

            if row["date"] != today:
                conn.execute(
                    "UPDATE ai_draw_usage SET date=?, count=1 WHERE uid=?",
                    (today, uid),
                )
                conn.commit()
                return True

            if row["count"] >= DAILY_LIMIT:
                return False

            conn.execute(
                "UPDATE ai_draw_usage SET count=count+1 WHERE uid=? AND date=?",
                (uid, today),
            )
            conn.commit()
            return True

    return await loop.run_in_executor(None, _do)


# ═══════════════ 启动初始化 ═══════════════

@driver.on_startup
async def on_startup():
    """异步加载 config.json 并初始化数据库"""
    # config.json
    try:
        text = await _async_read_file(CONFIG_PATH)
        _config.update(json.loads(text))
        logger.info(
            "ai_draw config.json 加载成功 "
            f"(deepseek_key={'***' if _config.get('deepseek_api_key') else '未配置'}, "
            f"gpt_image_key={'***' if _config.get('gpt_image_api_key') else '未配置'})"
        )
    except FileNotFoundError:
        await _async_write_file(CONFIG_PATH, json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False))
        _config.update(DEFAULT_CONFIG)
        logger.info("ai_draw config.json 已自动创建，请填写 API Key")
    except Exception as e:
        logger.error(f"ai_draw config.json 加载失败: {e}")
        _config.update(DEFAULT_CONFIG)

    # SQLite
    loop = __import__("asyncio").get_event_loop()
    await loop.run_in_executor(None, init_db)
    logger.info("ai_draw 数据库初始化完成")


async def _async_read_file(path: Path) -> str:
    loop = __import__("asyncio").get_event_loop()
    return await loop.run_in_executor(None, lambda: path.read_text(encoding="utf-8"))


async def _async_write_file(path: Path, content: str) -> None:
    loop = __import__("asyncio").get_event_loop()
    await loop.run_in_executor(None, lambda: path.write_text(content, encoding="utf-8"))


# ═══════════════ 图片提取 ═══════════════

async def extract_image(event: Event) -> bytes | None:
    """从消息中提取第一张图片并下载，返回 bytes；无图片则返回 None"""
    image_url = None

    if is_onebot(event):
        for seg in event.message:
            if seg.type == "image":
                image_url = seg.data.get("url") or seg.data.get("file")
                break
    elif is_qqbot(event):
        if hasattr(event, "attachments") and event.attachments:
            for attachment in event.attachments:
                if hasattr(attachment, "content_type") and "image" in str(attachment.content_type).lower():
                    image_url = attachment.url
                    break
                if hasattr(attachment, "url") and attachment.url:
                    image_url = attachment.url
                    break
        if not image_url:
            for seg in event.message:
                if seg.type == "image" or seg.type == "attachment":
                    image_url = seg.data.get("url")
                    break

    if not image_url:
        return None

    async with aiohttp.ClientSession() as session:
        async with session.get(image_url, timeout=30) as resp:
            if resp.status != 200:
                logger.error(f"下载参考图失败: HTTP {resp.status}, url={image_url[:80]}")
                raise RuntimeError(f"下载参考图失败: {resp.status}")
            return await resp.read()


# ═══════════════ DeepSeek 翻译 ═══════════════

async def translate_prompt(api_key: str, user_text: str) -> str:
    """调用 DeepSeek V4 Flash 翻译提示词"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": PROMPT_TRANSLATE_SYSTEM},
            {"role": "user", "content": user_text},
        ],
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "stream": False,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"DeepSeek API error: {resp.status} {text}")
                raise RuntimeError(f"DeepSeek API 返回错误: {resp.status}")

            data = await resp.json()
            english_prompt = data["choices"][0]["message"]["content"].strip()
            logger.info(f"DeepSeek translated prompt: {english_prompt}")
            return english_prompt


# ═══════════════ GPT-Image-2 ═══════════════

async def _download_result(session: aiohttp.ClientSession, data: dict) -> bytes:
    """从 GPT-Image-2 响应中提取图像"""
    image_url = None
    if "data" in data and len(data["data"]) > 0:
        item = data["data"][0]
        image_url = item.get("url") or item.get("image_url")
    if not image_url:
        image_url = data.get("url") or data.get("image_url")

    if image_url:
        async with session.get(image_url, timeout=60) as img_resp:
            if img_resp.status != 200:
                raise RuntimeError(f"下载图像失败: {img_resp.status}")
            return await img_resp.read()

    b64 = None
    if "data" in data and len(data["data"]) > 0:
        b64 = data["data"][0].get("b64_json")
    if not b64:
        b64 = data.get("b64_json")

    if b64:
        return base64.b64decode(b64)

    raise RuntimeError(f"无法解析图像数据，响应: {json.dumps(data, ensure_ascii=False)[:300]}")


async def generate_image(
    api_key: str, prompt: str, size: str = "auto"
) -> bytes:
    """调用 GPT-Image-2 文本生图"""
    url = "https://www.guanxingyun.com/aimodelapi/v1/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {"model": "gpt-image-2-all", "prompt": prompt, "size": size}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=120) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"GPT-Image-2 API error: {resp.status} {text}")
                raise RuntimeError(f"GPT-Image-2 API 返回错误: {resp.status}")
            data = await resp.json()
            logger.debug(f"GPT-Image-2 response: {json.dumps(data, ensure_ascii=False)[:500]}")
            return await _download_result(session, data)


async def generate_image_edit(
    api_key: str, prompt: str, image_bytes: bytes, size: str = "auto"
) -> bytes:
    """调用 GPT-Image-2 图片编辑（含参考图）"""
    url = "https://www.guanxingyun.com/aimodelapi/v1/images/edits"

    form_data = aiohttp.FormData()
    form_data.add_field("model", "gpt-image-2-all")
    form_data.add_field("prompt", prompt)
    form_data.add_field("size", size)
    form_data.add_field("image", image_bytes, filename="reference.png", content_type="image/png")

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=form_data, timeout=120) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"GPT-Image-2 Edit API error: {resp.status} {text}")
                raise RuntimeError(f"GPT-Image-2 图片编辑 API 返回错误: {resp.status}")
            data = await resp.json()
            logger.debug(f"GPT-Image-2 Edit response: {json.dumps(data, ensure_ascii=False)[:500]}")
            return await _download_result(session, data)


# ═══════════════ 费用 & 日限检查 ═══════════════

async def check_quota_and_pay(uid: int, wallet: UserWallet, cmd) -> bool:
    """检查日限和余额，任意不满足则发送提示并返回 False；通过则扣款+递增日限并返回 True"""
    # level 0 SU 不受日限
    if get_su_level(uid) != SU_LEVEL_CONTRIBUTOR:
        ok = await check_and_increment_daily_limit(uid)
        if not ok:
            await cmd.finish(f"你一天只能了 {DAILY_LIMIT} 张图，明天再来吧~", at_sender=True)
            return False

    if wallet.gold < DRAW_COST:
        await cmd.finish(
            f"金币不足！画一张图需要 {DRAW_COST} 金币，你当前只有 {wallet.gold} 金币。",
            at_sender=True,
        )
        return False

    wallet.gold -= DRAW_COST
    return True


# ═══════════════ 画图处理 ═══════════════

async def do_draw(event: Event, uid: int, wallet: UserWallet, user_text: str) -> None:
    """执行文本生图"""
    if not await check_quota_and_pay(uid, wallet, draw_cmd):
        return

    if not draw_limiter.check(uid):
        left = round(draw_limiter.left_time(uid))
        await draw_cmd.finish(f"画图太频繁啦，请等待 {left}s 后再试~", at_sender=True)
    draw_limiter.start_cd(uid)

    await draw_cmd.send(f"少女画图中…\n已扣除100000金币")

    try:
        english_prompt = await translate_prompt(_config["deepseek_api_key"], user_text)
        #await draw_cmd.send(f"提示词: {english_prompt}")

        image_bytes = await generate_image(
            _config["gpt_image_api_key"], english_prompt
        )
        image_msg = build_image_msg(event, image_bytes)
        await draw_cmd.finish(image_msg)

    except RuntimeError as e:
        wallet.gold += DRAW_COST
        logger.error(f"画图失败: {e}")
        await draw_cmd.finish(f"画图失败: {e}\n已退还金币。", at_sender=True)
    except Exception as e:
        wallet.gold += DRAW_COST
        logger.error(f"画图异常: {type(e).__name__}: {e}")
        await draw_cmd.finish(f"画图出错了: {type(e).__name__}\n已退还 10万 金币。", at_sender=True)


async def do_edit(event: Event, uid: int, wallet: UserWallet, user_text: str) -> None:
    """执行图片编辑"""
    try:
        ref_image = await extract_image(event)
    except RuntimeError as e:
        await edit_cmd.finish(f"获取参考图失败: {e}", at_sender=True)
        return

    if not ref_image:
        await edit_cmd.finish(
            "请附带一张参考图再使用修图命令哦~\n例: 发送冰祈修图[附带图片] 把背景换成赛博朋克风格",
            at_sender=True,
        )
        return

    if not user_text.strip():
        await edit_cmd.finish("请输入修图描述，例如: 冰祈修图[附带图片] 把猫变成金色的", at_sender=True)
        return

    if not await check_quota_and_pay(uid, wallet, edit_cmd):
        return

    if not draw_limiter.check(uid):
        left = round(draw_limiter.left_time(uid))
        await edit_cmd.finish(f"修图太频繁啦，请等待 {left}s 后再试~", at_sender=True)
    draw_limiter.start_cd(uid)

    prompt = user_text.strip()
    await edit_cmd.send(f"少女修图中…\n已扣除 10万 金币 (剩余 {wallet.gold})")

    try:
        english_prompt = await translate_prompt(_config["deepseek_api_key"], prompt)
        #await edit_cmd.send(f"提示词: {english_prompt}")

        image_bytes = await generate_image_edit(
            _config["gpt_image_api_key"], english_prompt, ref_image
        )
        image_msg = build_image_msg(event, image_bytes)
        await edit_cmd.finish(image_msg)

    except RuntimeError as e:
        wallet.gold += DRAW_COST
        logger.error(f"修图失败: {e}")
        await edit_cmd.finish(f"修图失败: {e}\n已退还 10万 金币。", at_sender=True)
    except Exception as e:
        wallet.gold += DRAW_COST
        logger.error(f"修图异常: {type(e).__name__}: {e}")
        await edit_cmd.finish(f"修图出错了: {type(e).__name__}\n已退还 10万 金币。", at_sender=True)


# ═══════════════ 命令入口 ═══════════════

@draw_cmd.handle()
async def handle_draw(
    event: Event,
    bot: Bot,
    args: Message = CommandArg(),
    uid: int = Depends(get_uid),
    wallet: UserWallet = Depends(wallet_manager),
):
    cfg = get_config()
    if not cfg.get("deepseek_api_key"):
        await draw_cmd.finish("未配置 DeepSeek API Key，请联系主人配置~", at_sender=True)
    if not cfg.get("gpt_image_api_key"):
        await draw_cmd.finish("未配置 GPT-Image-2 API Key，请联系主人配置~", at_sender=True)
    if is_qqbot(event):
        await draw_cmd.finish("AI画图功能暂不支持QQbot~", at_sender=True)

    user_text = args.extract_plain_text().strip()
    if not user_text:
        await draw_cmd.finish("请输入画图描述，例如: ml冰祈画图 一只可爱的猫", at_sender=True)

    await do_draw(event, uid, wallet, user_text)


@edit_cmd.handle()
async def handle_edit(
    event: Event,
    bot: Bot,
    args: Message = CommandArg(),
    uid: int = Depends(get_uid),
    wallet: UserWallet = Depends(wallet_manager),
):
    cfg = get_config()
    if not cfg.get("deepseek_api_key"):
        await edit_cmd.finish("未配置 DeepSeek API Key，请联系主人配置~", at_sender=True)
    if not cfg.get("gpt_image_api_key"):
        await edit_cmd.finish("未配置 GPT-Image-2 API Key，请联系主人配置~", at_sender=True)
    if is_qqbot(event):
        await edit_cmd.finish("AI修图功能暂不支持QQbot~", at_sender=True)

    user_text = args.extract_plain_text().strip()
    await do_edit(event, uid, wallet, user_text)
