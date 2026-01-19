import nonebot.adapters.onebot.v11 as onebot
from nonebot.adapters import Event, qq
from nonebot.params import Depends
from nonebot.log import logger

from .uid_manager import get_uid as get_unified_uid


def _get_platform_uid(event: Event) -> str:
    return event.get_user_id()

def get_uid(event: Event, platform_uid: str = Depends(_get_platform_uid)) -> int:
    logger.debug(f"获取统一 UID，平台 UID：{platform_uid}")
    if isinstance(event, onebot.Event):
        return get_unified_uid(platform="onebot", external_id= platform_uid)
    if isinstance(event, qq.Event):
        return get_unified_uid(platform="qqbot", external_id= platform_uid)
    raise ValueError(f"不支持的事件类型：{type(event)}")

def get_group_id(event: Event) -> str:
    logger.debug(f"获取群 ID，事件：{event}")
    if isinstance(event, onebot.GroupMessageEvent):
        return str(event.group_id)
    if isinstance(event, qq.GroupMsgReceiveEvent):
        return event.group_openid
    raise ValueError(f"不支持的事件类型：{type(event)}")