from __future__ import annotations

from nonebot import logger, on_fullmatch, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import Bot as OneBotBot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.params import Depends
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
import re

from ...koinori_config import config as koinori_config
from ...nickname import get_user_nickname
from ...tools import get_sender_nickname, get_uid
from ...uid_manager import get_uid as get_unified_uid
from ..ai_draw import do_draw, ensure_draw_available, get_free_draw_count
from .choicer import Choicer
from .data import SHOUJO_CONFIG

__plugin_meta__ = PluginMetadata(
    name="今天我是什么少女",
    description="随机生成今日少女设定",
    usage="今天我是什么少女 / 查看今日人设图 / 今天你是什么少女 @某人",
)


IMAGE_CMD_TEXT = "查看今日人设图"
IMAGE_PROMPT_NAME = ""

OTHER_TRIGGERS = (
    "今天你是什么少女",
    "今天他是什么少女",
    "今天她是什么少女",
    "今天它是什么少女",
)

BOT_SHOUJO = (
    "冰祈身高143，毛色是白色，有呆毛，银白色双马尾，ACUP，红瞳，"
    "长着大大的茸耳，生日8月6日，害羞与文静属性，是一只猫娘>ω<"
)

_cq_at_re = re.compile(r"\[CQ:at,qq=(\d+)\]")
_choicer = Choicer(SHOUJO_CONFIG)


my_shaojo_cmd = on_fullmatch("今天我是什么少女", priority=5, block=True)
my_shaojo_image_cmd = on_fullmatch(IMAGE_CMD_TEXT, priority=5, block=True)


async def _is_other_shaojo(event: Event) -> bool:
    text = event.get_plaintext().strip()
    return text.startswith(OTHER_TRIGGERS) or text.endswith(OTHER_TRIGGERS)


other_shaojo_cmd = on_message(rule=Rule(_is_other_shaojo), priority=5, block=True)


async def _sender_name(event: Event, uid: int) -> str:
    custom_nickname = get_user_nickname(uid)
    if custom_nickname:
        return custom_nickname

    if isinstance(event, MessageEvent) and event.sender:
        return event.sender.card or event.sender.nickname or "你"
    return await get_sender_nickname(event) or "你"


def _extract_at_targets(event: Event) -> list[tuple[int, str, str]]:
    targets: list[tuple[int, str, str]] = []

    try:
        for segment in event.get_message():
            segment_type = getattr(segment, "type", "")
            data = getattr(segment, "data", {})

            if segment_type == "at":
                qq = str(data.get("qq", ""))
                if qq and qq != "all":
                    targets.append((get_unified_uid("onebot", qq), qq, "onebot"))
            elif segment_type == "mention_user":
                user_id = str(
                    data.get("user_id")
                    or data.get("id")
                    or data.get("user_openid")
                    or ""
                )
                if user_id:
                    targets.append((get_unified_uid("qqbot", user_id), user_id, "qqbot"))
    except Exception as exc:
        logger.debug(f"解析 at 消息段失败: {exc}")

    raw_message = str(getattr(event, "raw_message", ""))
    for matched in _cq_at_re.findall(raw_message):
        targets.append((get_unified_uid("onebot", matched), matched, "onebot"))

    deduped = []
    seen_uids = set()
    for target in targets:
        target_uid = target[0]
        if target_uid not in seen_uids:
            deduped.append(target)
            seen_uids.add(target_uid)
    return deduped


async def _target_name(bot: Bot, event: Event, target_uid: int, target_external_id: str,) -> str:
    custom_nickname = get_user_nickname(target_uid)
    if custom_nickname:
        return custom_nickname

    if isinstance(bot, OneBotBot) and isinstance(event, GroupMessageEvent):
        try:
            info = await bot.get_group_member_info(
                group_id=event.group_id,
                user_id=int(target_external_id),
                no_cache=True,
            )
            return info.get("card") or info.get("nickname") or f"用户{target_external_id}"
        except Exception as exc:
            logger.debug(f"获取群成员信息失败: {exc}")

    return f"用户{target_external_id}"


async def _build_image_reminder(uid: int) -> str:
    free_draw_count = await get_free_draw_count(uid)
    if free_draw_count > 0:
        cost_text = f"当前还剩{free_draw_count}次免费画图"
    else:
        cost_text = f"需要{koinori_config.draw_cost}金币"
    return f"发送「{IMAGE_CMD_TEXT}」可以生成今日人设图（{cost_text}）。"


def _format_profile(uid: int, name: str, *, reminder: str | None = None) -> str:
    profile = _choicer.format_msg(uid, name)
    if reminder:
        return f"{profile}\n\n{reminder}"
    return profile


def _build_image_prompt(profile: str) -> str:
    return (
        "根据以下人设生成一张全年龄向、不含nsfw内容的动漫角色立绘。"
        "要求：穿着得体，不要文字、水印、签名；"
        "画面干净，柔和光照，角色特征清晰。"
        f"人设：{profile}"
    )


def _strip_image_prompt_subject(profile: str) -> str:
    prefix = "动漫里的，"
    if profile.startswith(prefix):
        return profile.removeprefix(prefix)
    return profile


@my_shaojo_cmd.handle()
async def handle_my_shaojo(
    event: Event,
    uid: int = Depends(get_uid),
) -> None:
    name = await _sender_name(event, uid)
    reminder = await _build_image_reminder(uid)
    await my_shaojo_cmd.finish(_format_profile(uid, name, reminder=reminder))


@my_shaojo_image_cmd.handle()
async def handle_my_shaojo_image(
    event: Event,
    uid: int = Depends(get_uid),
) -> None:
    await ensure_draw_available(event, uid, my_shaojo_image_cmd)

    name = await _sender_name(event, uid)
    display_profile = _format_profile(uid, name)
    prompt_profile = _strip_image_prompt_subject(_format_profile(uid, IMAGE_PROMPT_NAME))
    prompt = _build_image_prompt(prompt_profile)
    await do_draw(
        event,
        uid,
        prompt,
        cmd=my_shaojo_image_cmd,
        progress_text=f"今日人设图生成中…\n已扣除{koinori_config.draw_cost}金币",
        success_text=f"人设：\n{display_profile}",
    )


@other_shaojo_cmd.handle()
async def handle_other_shaojo(bot: Bot, event: Event) -> None:
    targets = _extract_at_targets(event)
    if not targets:
        await other_shaojo_cmd.finish("要艾特到对方才知道是什么少女喔~", at_sender=True)

    for target_uid, target_external_id, _platform in targets:
        if target_external_id == str(bot.self_id):
            msg = BOT_SHOUJO
        else:
            name = await _target_name(bot, event, target_uid, target_external_id)
            msg = _format_profile(target_uid, name)

        try:
            await bot.send(event, msg)
        except Exception as exc:
            logger.error(f"今天也是少女功能发送失败，可能被风控: {exc}")
            await other_shaojo_cmd.finish(
                "变身结果发送失败，冰祈可能被风控...",
                at_sender=True,
            )
