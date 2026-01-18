"""
事件适配层

将 OneBot 和 QQ-Bot 的事件统一转换为标准格式，
所有业务逻辑使用统一的 UID 和消息接口。
"""

from dataclasses import dataclass, field
from typing import Union, Optional, Any, TYPE_CHECKING
from nonebot import get_bot
from nonebot.adapters import Event, Message, Bot

# 导入各适配器的事件类型
try:
    from nonebot.adapters.onebot.v11 import (
        Event as OneBotV11Event,
        GroupMessageEvent as OneBotGroupMessageEvent,
        PrivateMessageEvent as OneBotPrivateMessageEvent,
        MessageSegment as OneBotMessageSegment,
        Bot as OneBotBot,
    )
    ONEBOT_V11_AVAILABLE = True
except ImportError:
    ONEBOT_V11_AVAILABLE = False
    OneBotV11Event = None
    OneBotGroupMessageEvent = None
    OneBotPrivateMessageEvent = None
    OneBotMessageSegment = None
    OneBotBot = None

try:
    from nonebot.adapters.qq import (
        Event as QQBotEvent,
        GroupAtMessageCreateEvent as QQBotGroupMessageEvent,
        Bot as QQBotBot,
    )
    QQBOT_AVAILABLE = True
except ImportError:
    QQBOT_AVAILABLE = False
    QQBotEvent = None
    QQBotGroupMessageEvent = None
    QQBotBot = None

from . import uid_manager


@dataclass
class UnifiedEvent:
    """统一事件格式"""
    
    uid: int                          # 统一内部 UID
    platform: str                     # "onebot" | "qqbot"
    external_id: str                  # 原始用户 ID（QQ号/OpenID）
    group_id: Optional[str] = None    # 群组 ID（私聊为 None）
    message_text: str = ""            # 纯文本消息内容
    raw_event: Any = None             # 原始事件对象
    raw_bot: Any = None               # 原始 Bot 对象
    
    # 发送者信息
    sender_nickname: str = ""
    
    @property
    def is_group(self) -> bool:
        """是否为群聊消息"""
        return self.group_id is not None
    
    def get_args(self, prefixes: tuple = None) -> str:
        """
        获取去掉命令前缀后的参数文本
        用于 on_startswith 类型的命令，提取命令后面的参数部分。
        """
        if prefixes is None:
            return self.message_text.strip()
        
        text = self.message_text
        for prefix in prefixes:
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        
        # 没有匹配到前缀，返回原文本
        return text.strip()


async def adapt_event(event: Event, bot: Bot) -> UnifiedEvent:
    """
    将各协议事件转换为统一事件
    
    Args:
        event: 原始事件
        bot: Bot 对象
    
    Returns:
        UnifiedEvent 统一事件对象
    """
    # OneBot V11
    if ONEBOT_V11_AVAILABLE and isinstance(event, OneBotV11Event):
        return await _adapt_onebot_v11(event, bot)
    
    # QQ-Bot
    if QQBOT_AVAILABLE and isinstance(event, QQBotEvent):
        return await _adapt_qqbot(event, bot)
    
    raise ValueError(f"不支持的事件类型: {type(event)}")


async def _adapt_onebot_v11(event, bot) -> UnifiedEvent:
    """适配 OneBot V11 事件"""
    external_id = str(event.get_user_id())
    uid = uid_manager.get_uid("onebot", external_id)
    
    # 获取群 ID
    group_id = None
    if hasattr(event, 'group_id') and event.group_id:
        group_id = str(event.group_id)
    
    # 获取消息文本
    message_text = ""
    if hasattr(event, 'get_plaintext'):
        message_text = event.get_plaintext()
    
    # 获取发送者昵称
    nickname = ""
    if hasattr(event, 'sender') and event.sender:
        nickname = getattr(event.sender, 'nickname', '') or getattr(event.sender, 'card', '') or ""
    
    return UnifiedEvent(
        uid=uid,
        platform="onebot",
        external_id=external_id,
        group_id=group_id,
        message_text=message_text,
        raw_event=event,
        raw_bot=bot,
        sender_nickname=nickname,
    )


async def _adapt_qqbot(event, bot) -> UnifiedEvent:
    """适配 QQ-Bot 事件"""
    # QQ-Bot 使用 OpenID 作为用户标识
    external_id = event.get_user_id()
    uid = uid_manager.get_uid("qqbot", external_id)
    
    # 获取群 ID
    group_id = None
    if hasattr(event, 'group_openid') and event.group_openid:
        group_id = event.group_openid
    
    # 获取消息文本
    message_text = ""
    if hasattr(event, 'get_plaintext'):
        message_text = event.get_plaintext()
    
    # QQ-Bot 发送者昵称获取方式不同
    nickname = ""
    if hasattr(event, 'author') and event.author:
        nickname = getattr(event.author, 'username', '') or ""
    
    return UnifiedEvent(
        uid=uid,
        platform="qqbot",
        external_id=external_id,
        group_id=group_id,
        message_text=message_text,
        raw_event=event,
        raw_bot=bot,
        sender_nickname=nickname,
    )


async def send_message(uevent: UnifiedEvent, message, at_sender: bool = False):
    """
    统一消息发送接口
    
    Args:
        uevent: 统一事件
        message: 消息内容 (str 或 MessageSegment)
        at_sender: 是否 @ 发送者
    """
    bot = uevent.raw_bot
    event = uevent.raw_event
    
    if uevent.platform == "onebot":
        await _send_onebot_v11(bot, event, message, at_sender)
    elif uevent.platform == "qqbot":
        await _send_qqbot(bot, event, message, at_sender)


async def _send_onebot_v11(bot, event, message, at_sender: bool):
    """OneBot V11 消息发送"""
    if at_sender and hasattr(event, 'user_id'):
        # 构建 @ 消息
        msg = OneBotMessageSegment.at(event.user_id) + " " + message
    else:
        msg = message
    
    await bot.send(event, msg)


async def _send_qqbot(bot, event, message: str, at_sender: bool):
    """QQ-Bot 消息发送"""
    # QQ-Bot 群消息需要通过特定 API 发送
    if hasattr(event, 'group_openid') and event.group_openid:
        # 群消息
        await bot.send(event, message)
    else:
        # 其他消息
        await bot.send(event, message)


async def send_group_forward_msg(uevent: UnifiedEvent, messages: list):
    """
    发送合并转发消息（仅 OneBot 支持）
    
    Args:
        uevent: 统一事件
        messages: 合并转发消息节点列表
    """
    if uevent.platform != "onebot":
        # QQ-Bot 不支持合并转发，降级为普通消息
        for msg in messages:
            if isinstance(msg, dict) and 'data' in msg:
                content = msg['data'].get('content', '')
                if content:
                    await send_message(uevent, str(content))
        return
    
    bot = uevent.raw_bot
    if uevent.group_id:
        await bot.send_group_forward_msg(group_id=int(uevent.group_id), messages=messages)


async def get_user_avatar_url(uevent: UnifiedEvent) -> str:
    """
    获取用户头像 URL
    
    Args:
        uevent: 统一事件
    
    Returns:
        头像 URL
    """
    if uevent.platform == "onebot":
        # QQ 头像 URL
        return f'https://q1.qlogo.cn/g?b=qq&nk={uevent.external_id}&s=640'
    elif uevent.platform == "qqbot":
        # QQ-Bot 从 author.avatar 获取头像
        event = uevent.raw_event
        if hasattr(event, 'author') and event.author:
            avatar = getattr(event.author, 'avatar', None)
            if avatar:
                return avatar
        return ''
    else:
        return ''


async def chain_reply(uevent: UnifiedEvent, chain: list, msg: str, user_id: int = 0):
    """
    构建合并转发消息节点（兼容旧版 API）
    
    Args:
        uevent: 统一事件
        chain: 消息链列表（会被修改）
        msg: 消息内容
        user_id: 发送者 ID（0 表示使用 bot 自身）
    """
    if uevent.platform != "onebot":
        # 非 OneBot 不支持合并转发，直接添加文本
        chain.append({"content": msg})
        return chain
    
    bot = uevent.raw_bot
    if not user_id:
        user_id = int(uevent.raw_bot.self_id)
    
    try:
        user_info = await bot.get_stranger_info(user_id=user_id)
        user_name = user_info.get('nickname', '用户')
    except:
        user_name = '用户'
    
    if not user_name.strip():
        user_name = '用户'
    
    data = {
        "type": "node",
        "data": {
            "name": user_name,
            "user_id": str(user_id),
            "content": msg
        }
    }
    chain.append(data)
    return chain
