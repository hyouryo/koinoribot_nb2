"""
工具函数模块

提供 NoneBot2 依赖注入兼容的工具函数，支持 OneBot V11 和 QQ-Bot 双协议。
"""

from typing import Optional, List, Dict, Any

import nonebot.adapters.onebot.v11 as onebot
from nonebot.adapters import Event, Bot
from nonebot.adapters import qq
from nonebot.log import logger
from nonebot.params import Depends

from .uid_manager import get_uid as get_unified_uid
from .uid_manager import get_uid_by_external_id


# ===== UID 相关 =====

def _get_platform_uid(event: Event) -> str:
    uid = event.get_user_id()
    logger.debug(f"获取平台UID：{uid}")
    return uid


def get_uid(event: Event, platform_uid: str = Depends(_get_platform_uid)) -> int:
    """获取统一 UID（依赖注入版本）"""
    uuid = None
    if isinstance(event, onebot.Event):
        uuid = get_unified_uid(platform="onebot", external_id=platform_uid)
    if isinstance(event, qq.Event):
        uuid = get_unified_uid(platform="qqbot", external_id=platform_uid)
    if uuid is None:
        raise ValueError(f"不支持的事件类型：{type(event)}")
    logger.debug(f"获取统一UID：{uuid}")
    return uuid


def get_group_id(event: Event) -> str:
    """获取群组 ID""" 
    if isinstance(event, onebot.GroupMessageEvent):
        return str(event.group_id)
    if isinstance(event, qq.GroupMsgReceiveEvent):
        return event.group_openid
    raise ValueError(f"不支持的事件类型：{type(event)}")


def get_group_id_optional(event: Event) -> Optional[str]:
    """获取群组 ID（可选，私聊返回 None）"""
    try:
        return get_group_id(event)
    except ValueError:
        return None


# ===== 用户信息相关 =====

def get_sender_nickname(event: Event) -> str:
    """获取发送者昵称"""
    if isinstance(event, onebot.MessageEvent):
        if event.sender:
            return event.sender.nickname or event.sender.card or ""
    if isinstance(event, qq.Event):
        if hasattr(event, 'author') and event.author:
            return getattr(event.author, 'username', '') or ""
    return ""


def get_user_avatar_url(event: Event) -> str:
    """获取用户头像 URL"""
    if isinstance(event, onebot.Event):
        user_id = event.get_user_id()
        return f'https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640'
    if isinstance(event, qq.Event):
        if hasattr(event, 'author') and event.author:
            avatar = getattr(event.author, 'avatar', None)
            if avatar:
                return avatar
    return ''


def is_onebot(event: Event) -> bool:
    """判断是否为 OneBot 协议"""
    return isinstance(event, onebot.Event)


def is_qqbot(event: Event) -> bool:
    """判断是否为 QQ-Bot 协议"""
    return isinstance(event, qq.Event)


# ===== 消息发送相关 =====

async def send_group_forward_msg(
    event: Event, 
    bot: Bot, 
    messages: List[Dict[str, Any]]
) -> None:
    """
    发送合并转发消息
    
    Args:
        event: 事件对象
        bot: Bot 对象
        messages: 合并转发消息节点列表
    
    Note:
        QQ-Bot 不支持合并转发，会降级为普通消息依次发送
    """
    if isinstance(event, onebot.GroupMessageEvent):
        await bot.send_group_forward_msg(group_id=event.group_id, messages=messages)
    else:
        # QQ-Bot 降级为普通消息
        for msg in messages:
            if isinstance(msg, dict) and 'data' in msg:
                content = msg['data'].get('content', '')
                if content:
                    await bot.send(event, str(content))


async def build_forward_node(
    bot: Bot,
    msg,
    user_id: int = 0
) -> Dict[str, Any]:
    """
    构建合并转发消息节点
    
    Args:
        bot: Bot 对象
        msg: 消息内容（str 或消息段列表）
        user_id: 发送者 ID（0 表示使用 bot 自身）
    
    Returns:
        合并转发消息节点字典
    """
    if not user_id:
        user_id = int(bot.self_id)
    
    try:
        user_info = await bot.get_stranger_info(user_id=user_id)
        user_name = user_info.get('nickname', '用户')
    except Exception:
        user_name = '用户'
    
    if not user_name.strip():
        user_name = '用户'
    
    # 如果 msg 已经是列表（消息段格式），直接使用；否则包装为 text 消息段
    if isinstance(msg, list):
        content = msg
    else:
        content = [{"type": "text", "data": {"text": str(msg)}}]
    
    return {
        "type": "node",
        "data": {
            "name": user_name,
            "user_id": str(user_id),
            "content": content
        }
    }


async def build_forward_chain(
    bot: Bot,
    messages: List[str],
    user_id: int = 0
) -> List[Dict[str, Any]]:
    """
    批量构建合并转发消息链
    
    Args:
        bot: Bot 对象
        messages: 消息内容列表
        user_id: 发送者 ID
    
    Returns:
        合并转发消息节点列表
    """
    chain = []
    for msg in messages:
        node = await build_forward_node(bot, msg, user_id)
        chain.append(node)
    return chain

# ===== 用户at相关 =====
def get_at_uid_onebot(message_segment:onebot.MessageSegment) -> str:
    """
    获取 onebot v11 的 @ 消息中的 uid

    Args:
        message_segment: onebot v11 的 @ 消息

    Returns:
        uid: 消息中的 uid

    Raises:
        ValueError: 消息不是 @ 消息
    """
    if message_segment.type == "at":
        return message_segment.data["qq"]
    raise ValueError("消息不是at消息")


def get_at_uid_qqbot(message_segment:qq.MessageSegment) -> str:
    """
    获取 qqbot 的 @ 消息中的 uid

    Args:
        message_segment: qqbot 的 @ 消息

    Returns:
        uid: 消息中的 uid

    Raises:
        ValueError: 消息不是 @ 消息
    """
    if message_segment.type == "mention_user":
        return message_segment.data["user_id"]
    raise ValueError("消息不是at消息")

def get_at_uid(message_segment:onebot.MessageSegment | qq.MessageSegment) -> Optional[int]:
    """
    获取消息中的 uid

    Args:
        message_segment: 消息

    Returns:
        uid: 消息中的 uid, None时表示没有账户

    Raises:
        ValueError: 消息不是at消息
    """

    uuid = None
    if isinstance(message_segment, onebot.MessageSegment):
        uid = get_at_uid_onebot(message_segment)
        uuid = get_uid_by_external_id(platform="onebot", external_id=uid)
    elif isinstance(message_segment, qq.MessageSegment):
        uid = get_at_uid_qqbot(message_segment)
        uuid = get_uid_by_external_id(platform="qqbot", external_id=uid)
    return uuid
