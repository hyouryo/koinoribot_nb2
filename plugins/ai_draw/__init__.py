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
import aiohttp
from nonebot import on_command, get_driver
from nonebot.adapters import Event, Bot
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.log import logger
from nonebot.params import CommandArg, Depends
from nonebot.plugin import PluginMetadata

from ...money import money, get_database_path
from ...su_manager import get_su_level, SU_LEVEL_CONTRIBUTOR
from ...tools import get_uid, build_image_msg, is_onebot, is_qqbot
from ...koinori_config import config as koinori_config
from ...utils import FreqLimiter
from ._image_meta import detect_image_upload_meta

__plugin_meta__ = PluginMetadata(
    name="ai_draw",
    description="AI画图 - DeepSeek翻译提示词 + GPT-Image-2生成图像",
    usage=(
        "冰祈画图 <描述>    生成图像\n"
        "冰祈修图 <描述> + 图片  编辑图像\n"
        "全局重置画图次数 / 重置画图次数 <uid>  管理日限\n"
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
reset_all_usage_cmd = on_command("全局重置画图次数", priority=5, block=True)
reset_usage_cmd = on_command("重置画图次数", priority=5, block=True)

# DeepSeek 系统提示词
PROMPT_TRANSLATE_SYSTEM = """You are a professional image prompt engineer. Your task is to convert the user's Chinese description into a concise, high-quality English prompt suitable for AI image generation (DALL-E / GPT-Image-2).

Rules:
1. Output ONLY the English prompt, nothing else — no quotes, no prefixes, no explanations.
2. The prompt should be vivid and descriptive, including style, lighting, composition details.
3. Keep it under 200 characters.
4. Preserve the user's intent faithfully — do not add concepts the user didn't mention."""

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


async def check_daily_limit(uid: int) -> bool:
    """检查日限。跨天视为已清零。返回 True 表示未超限。"""
    loop = __import__("asyncio").get_event_loop()
    today = _today()

    def _do():
        with _get_db() as conn:
            row = conn.execute(
                "SELECT date, count FROM ai_draw_usage WHERE uid=?", (uid,)
            ).fetchone()

            if row is None:
                return True

            if row["date"] != today:
                return True

            return row["count"] < koinori_config.daily_limit

    return await loop.run_in_executor(None, _do)


async def record_draw_success(uid: int) -> None:
    """成功生成图片后递增今日次数。level 0 SU 不计入日限。"""
    if get_su_level(uid) == SU_LEVEL_CONTRIBUTOR:
        return

    loop = __import__("asyncio").get_event_loop()
    today = _today()

    def _do():
        with _get_db() as conn:
            row = conn.execute(
                "SELECT date FROM ai_draw_usage WHERE uid=?", (uid,)
            ).fetchone()

            if row is None:
                conn.execute(
                    "INSERT INTO ai_draw_usage (uid, date, count) VALUES (?, ?, 1)",
                    (uid, today),
                )
            elif row["date"] != today:
                conn.execute(
                    "UPDATE ai_draw_usage SET date=?, count=1 WHERE uid=?",
                    (today, uid),
                )
            else:
                conn.execute(
                    "UPDATE ai_draw_usage SET count=count+1 WHERE uid=? AND date=?",
                    (uid, today),
                )
            conn.commit()

    await loop.run_in_executor(None, _do)


async def reset_draw_usage(target_uid: int | None = None) -> int:
    """重置画图次数。target_uid 为 None 时重置全部。返回影响行数。"""
    loop = __import__("asyncio").get_event_loop()

    def _do():
        with _get_db() as conn:
            if target_uid is None:
                cursor = conn.execute("DELETE FROM ai_draw_usage")
            else:
                cursor = conn.execute("DELETE FROM ai_draw_usage WHERE uid=?", (target_uid,))
            conn.commit()
            return cursor.rowcount

    return await loop.run_in_executor(None, _do)


# ═══════════════ 启动初始化 ═══════════════

@driver.on_startup
async def on_startup():
    """初始化数据库"""
    loop = __import__("asyncio").get_event_loop()
    await loop.run_in_executor(None, init_db)
    logger.info(
        f"ai_draw 初始化完成 "
        f"(deepseek_key={'***' if koinori_config.deepseek_api_key else '未配置'}, "
        f"gpt_image_key={'***' if koinori_config.gpt_image_api_key else '未配置'})"
    )


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
    """从 GPT-Image-2 响应中提取图像，若响应包含业务错误则直接抛出"""
    # 先检查响应体是否包含业务错误（HTTP 200 但实际失败的情况）
    relay_error = data.get("RelayError") or data.get("error")
    if relay_error:
        msg = relay_error if isinstance(relay_error, str) else relay_error.get("message", str(relay_error))
        raise RuntimeError(f"GPT-Image-2 API 返回错误: {msg}")

    image_url = None
    if "data" in data and len(data["data"]) > 0:
        item = data["data"][0]
        image_url = item.get("url") or item.get("image_url")
    if not image_url:
        image_url = data.get("url") or data.get("image_url")

    if image_url:
        try:
            async with session.get(image_url, timeout=300) as img_resp:
                if img_resp.status != 200:
                    raise RuntimeError(f"下载图像失败: {img_resp.status}")
                return await img_resp.read()
        except Exception as e:
            raise RuntimeError(f"下载生成的图片时出错（图片可能已生成，请稍后重试）: {e}")

    b64 = None
    if "data" in data and len(data["data"]) > 0:
        b64 = data["data"][0].get("b64_json")
    if not b64:
        b64 = data.get("b64_json")

    if b64:
        return base64.b64decode(b64)

    raise RuntimeError(f"无法解析图像数据，响应: {json.dumps(data, ensure_ascii=False)[:500]}")


async def generate_image(
    api_key: str, prompt: str, size: str = "auto"
) -> bytes:
    """调用 GPT-Image-2 文本生图"""
    url = f"{koinori_config.gpt_image_api_base_url}/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {"model": koinori_config.gpt_image_model, "prompt": prompt, "size": size}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=300) as resp:
            if resp.status != 200:
                try:
                    text = await resp.text()
                except Exception:
                    text = "(无法读取响应体)"
                logger.error(f"GPT-Image-2 API error: {resp.status} {text}")
                raise RuntimeError(f"GPT-Image-2 API 返回错误: {resp.status}\n{text}")
            try:
                data = await resp.json()
            except Exception as e:
                raise RuntimeError(f"GPT-Image-2 响应解析失败（图片可能已生成）: {e}")
            logger.debug(f"GPT-Image-2 response: {json.dumps(data, ensure_ascii=False)[:500]}")
            return await _download_result(session, data)


async def generate_image_edit(
    api_key: str, prompt: str, image_bytes: bytes, size: str = "auto"
) -> bytes:
    """调用 GPT-Image-2 图片编辑（含参考图）"""
    url = f"{koinori_config.gpt_image_api_base_url}/images/edits"

    form_data = aiohttp.FormData()
    form_data.add_field("model", koinori_config.gpt_image_model)
    form_data.add_field("prompt", prompt)
    form_data.add_field("size", size)
    image_filename, image_content_type = detect_image_upload_meta(image_bytes)
    form_data.add_field(
        "image",
        image_bytes,
        filename=image_filename,
        content_type=image_content_type,
    )
    logger.debug(
        "GPT-Image-2 Edit reference image: "
        f"filename={image_filename}, content_type={image_content_type}, bytes={len(image_bytes)}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=form_data, timeout=300) as resp:
            if resp.status != 200:
                try:
                    text = await resp.text()
                except Exception:
                    text = "(无法读取响应体)"
                logger.error(f"GPT-Image-2 Edit API error: {resp.status} {text}")
                raise RuntimeError(f"GPT-Image-2 图片编辑 API 返回错误: {resp.status}\n{text}")
            try:
                data = await resp.json()
            except Exception as e:
                raise RuntimeError(f"GPT-Image-2 响应解析失败（图片可能已生成）: {e}")
            logger.debug(f"GPT-Image-2 Edit response: {json.dumps(data, ensure_ascii=False)[:500]}")
            return await _download_result(session, data)


# ═══════════════ 费用 & 日限检查 ═══════════════

async def check_quota_and_balance(uid: int, cmd) -> bool:
    """检查日限和余额，任意不满足则发送提示并返回 False。"""
    # level 0 SU 不受日限
    if get_su_level(uid) != SU_LEVEL_CONTRIBUTOR:
        ok = await check_daily_limit(uid)
        if not ok:
            await cmd.finish(f"你一天只能画 {koinori_config.daily_limit} 张图，明天再来吧~", at_sender=True)
            return False

    user_gold = money.get_user_money(uid, "gold") or 0
    if user_gold < koinori_config.draw_cost:
        await cmd.finish(
            f"金币不足！画一张图需要 {koinori_config.draw_cost} 金币，你当前只有 {user_gold} 金币。",
            at_sender=True,
        )
        return False

    return True


def pay_draw_cost(uid: int) -> bool:
    return bool(money.reduce_user_money(uid, "gold", koinori_config.draw_cost))


# ═══════════════ 画图处理 ═══════════════

def _build_text_image_message(text: str, image_msg) -> Message:
    """构建文本和图片合并的一条 OneBot 消息。"""
    msg = Message()
    if text.strip():
        msg.append(MessageSegment.text(f"{text.rstrip()}\n"))
    msg.append(image_msg)
    return msg


async def ensure_draw_available(event: Event, uid: int, cmd) -> None:
    """检查文本生图功能是否可用。"""
    if not koinori_config.gpt_image_api_key:
        await cmd.finish("未配置 GPT-Image-2 API Key，请联系主人配置~", at_sender=True)
    if is_qqbot(event):
        await cmd.finish("AI画图功能暂不支持QQbot~", at_sender=True)
    if not koinori_config.ai_draw_enable and get_su_level(uid) != SU_LEVEL_CONTRIBUTOR:
        await cmd.finish("AI画图功能维护中，暂时不可用~", at_sender=True)


async def do_draw(
    event: Event,
    uid: int,
    user_text: str,
    cmd=None,
    progress_text: str | None = None,
    success_text: str | None = None,
) -> None:
    """执行文本生图"""
    if cmd is None:
        cmd = draw_cmd

    if not await check_quota_and_balance(uid, cmd):
        return

    if not draw_limiter.check(uid):
        left = round(draw_limiter.left_time(uid))
        await cmd.finish(f"画图太频繁啦，请等待 {left}s 后再试~", at_sender=True)
    draw_limiter.start_cd(uid)

    if not pay_draw_cost(uid):
        await cmd.finish("扣除金币失败，请稍后再试。", at_sender=True)

    await cmd.send(progress_text or f"少女画图中…\n已扣除{koinori_config.draw_cost}金币")

    try:
        image_bytes = await generate_image(
            koinori_config.gpt_image_api_key, user_text
        )
        image_msg = build_image_msg(event, image_bytes)
    except RuntimeError as e:
        money.increase_user_money(uid, "gold", koinori_config.draw_cost)
        logger.error(f"画图失败: {e}")
        await cmd.finish(f"画图失败: {e}\n已退还金币。", at_sender=True)
    except Exception as e:
        money.increase_user_money(uid, "gold", koinori_config.draw_cost)
        logger.error(f"画图异常: {type(e).__name__}: {e}")
        await cmd.finish(f"画图出错了: {e}\n已退还金币。", at_sender=True)
    else:
        await record_draw_success(uid)
        try:
            result_msg = _build_text_image_message(
                success_text or f"提示词：\n{user_text}",
                image_msg,
            )
            await cmd.send(result_msg, at_sender=True)
        except ActionFailed:
            logger.warning("发送图片超时，但图片可能已送达")
        await cmd.finish()


async def do_edit(event: Event, uid: int, user_text: str) -> None:
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

    if not await check_quota_and_balance(uid, edit_cmd):
        return

    if not draw_limiter.check(uid):
        left = round(draw_limiter.left_time(uid))
        await edit_cmd.finish(f"修图太频繁啦，请等待 {left}s 后再试~", at_sender=True)
    draw_limiter.start_cd(uid)

    prompt = user_text.strip()
    if not pay_draw_cost(uid):
        await edit_cmd.finish("扣除金币失败，请稍后再试。", at_sender=True)

    user_gold_after = money.get_user_money(uid, "gold") or 0
    await edit_cmd.send(f"少女修图中…\n已扣除 {koinori_config.draw_cost} 金币 (剩余 {user_gold_after})")

    try:
        image_bytes = await generate_image_edit(
            koinori_config.gpt_image_api_key, prompt, ref_image
        )
        image_msg = build_image_msg(event, image_bytes)
    except RuntimeError as e:
        money.increase_user_money(uid, "gold", koinori_config.draw_cost)
        logger.error(f"修图失败: {e}")
        await edit_cmd.finish(f"修图失败: {e}\n已退还金币。", at_sender=True)
    except Exception as e:
        money.increase_user_money(uid, "gold", koinori_config.draw_cost)
        logger.error(f"修图异常: {type(e).__name__}: {e}")
        await edit_cmd.finish(f"修图出错了: {e}\n已退还金币。", at_sender=True)
    else:
        await record_draw_success(uid)
        try:
            result_msg = _build_text_image_message(
                f"提示词：\n{prompt}",
                image_msg,
            )
            await edit_cmd.send(result_msg, at_sender=True)
        except ActionFailed:
            logger.warning("修图发送图片超时，但图片可能已送达")
        await edit_cmd.finish()


# ═══════════════ 命令入口 ═══════════════


def _is_level0_su(uid: int) -> bool:
    return get_su_level(uid) == SU_LEVEL_CONTRIBUTOR


@reset_all_usage_cmd.handle()
async def handle_reset_all_usage(uid: int = Depends(get_uid)):
    if not _is_level0_su(uid):
        await reset_all_usage_cmd.finish("权限不足，仅限权限等级为 0 的 SU 使用。", at_sender=True)

    affected = await reset_draw_usage()
    await reset_all_usage_cmd.finish(f"已重置全部用户今日画图次数（清理 {affected} 条记录）。", at_sender=True)


@reset_usage_cmd.handle()
async def handle_reset_usage(
    args: Message = CommandArg(),
    uid: int = Depends(get_uid),
):
    if not _is_level0_su(uid):
        await reset_usage_cmd.finish("权限不足，仅限权限等级为 0 的 SU 使用。", at_sender=True)

    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await reset_usage_cmd.finish("格式：重置画图次数 uid", at_sender=True)

    try:
        target_uid = int(arg_text.split()[0])
    except ValueError:
        await reset_usage_cmd.finish("UID 必须是整数。", at_sender=True)

    affected = await reset_draw_usage(target_uid)
    if affected:
        await reset_usage_cmd.finish(f"已重置 UID:{target_uid} 今日画图次数。", at_sender=True)
    await reset_usage_cmd.finish(f"UID:{target_uid} 今日画图次数已经是 0。", at_sender=True)


@draw_cmd.handle()
async def handle_draw(
    event: Event,
    bot: Bot,
    args: Message = CommandArg(),
    uid: int = Depends(get_uid),
):
#    if not koinori_config.deepseek_api_key:
#        await draw_cmd.finish("未配置 DeepSeek API Key，请联系主人配置~", at_sender=True)
    await ensure_draw_available(event, uid, draw_cmd)

    user_text = args.extract_plain_text().strip()
    if not user_text:
        await draw_cmd.finish("请输入画图描述，例如: 冰祈画图 一只可爱的猫", at_sender=True)

    await do_draw(event, uid, user_text)


@edit_cmd.handle()
async def handle_edit(
    event: Event,
    bot: Bot,
    args: Message = CommandArg(),
    uid: int = Depends(get_uid),
):
#    if not koinori_config.deepseek_api_key:
#        await edit_cmd.finish("未配置 DeepSeek API Key，请联系主人配置~", at_sender=True)
    if not koinori_config.gpt_image_api_key:
        await edit_cmd.finish("未配置 GPT-Image-2 API Key，请联系主人配置~", at_sender=True)
    if is_qqbot(event):
        await edit_cmd.finish("AI修图功能暂不支持QQbot~", at_sender=True)
    if not koinori_config.ai_draw_enable and get_su_level(uid) != SU_LEVEL_CONTRIBUTOR:
        await edit_cmd.finish("AI修图功能维护中，暂时不可用~", at_sender=True)

    user_text = args.extract_plain_text().strip()
    await do_edit(event, uid, user_text)
