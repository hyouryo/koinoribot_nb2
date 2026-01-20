import nonebot.adapters.onebot.v11 as onebot
from nonebot.adapters import Event, qq
from nonebot.log import logger
from nonebot.params import Depends

from .uid_manager import get_uid as get_unified_uid


def _get_platform_uid(event: Event) -> str:
    uid = event.get_user_id()
    logger.debug(f"获取平台UID：{uid}")
    return uid

def get_uid(event: Event, platform_uid: str = Depends(_get_platform_uid)) -> int:
    uuid = None
    if isinstance(event, onebot.Event):
        uuid = get_unified_uid(platform="onebot", external_id= platform_uid)
    if isinstance(event, qq.Event):
        uuid = get_unified_uid(platform="qqbot", external_id= platform_uid)
    if uuid is None:
        raise ValueError(f"不支持的事件类型：{type(event)}")
    logger.debug(f"获取统一UID：{uuid}")
    return uuid

def get_group_id(event: Event) -> str:
    logger.debug(f"获取群 ID，事件：{event}")
    if isinstance(event, onebot.GroupMessageEvent):
        return str(event.group_id)
    if isinstance(event, qq.GroupMsgReceiveEvent):
        return event.group_openid
    raise ValueError(f"不支持的事件类型：{type(event)}")
