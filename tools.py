"""
工具函数模块

提供 NoneBot2 依赖注入兼容的工具函数，支持 OneBot V11 和 QQ-Bot 双协议。
"""

from typing import Optional, List, Dict, Any, Union
import base64

import nonebot.adapters.onebot.v11 as onebot
from nonebot.adapters import Event, Bot
from nonebot.adapters import qq
from nonebot.log import logger
from nonebot.params import Depends
import httpx
import io
import textwrap
from .build_image import BuildImage

from .uid_manager import get_uid as get_unified_uid
from .uid_manager import get_uid_by_external_id
from .uid_manager import get_external_ids
from .nickname import get_user_nickname

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
    if isinstance(event, qq.Event) and hasattr(event, 'group_openid') and event.group_openid:
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
    try:
        platform_uid = event.get_user_id()
        uid = get_uid(event, platform_uid)
        custom_nickname = get_user_nickname(uid)
        if custom_nickname:
            return custom_nickname
    except Exception as e:
        logger.debug(f"获取自定义昵称失败: {e}")

    if isinstance(event, onebot.MessageEvent):
        if event.sender:
            return event.sender.nickname or event.sender.card or ""
    if isinstance(event, qq.Event):
        if hasattr(event, 'author') and event.author:
            return getattr(event.author, 'username', '') or ""
    return ""


def get_user_avatar_url(event: Event, uid: Optional[int] = None) -> str:
    """获取用户头像 URL"""
    if isinstance(event, onebot.Event):
        user_id = event.get_user_id()
        return f'https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640'
    if isinstance(event, qq.Event):
        if uid is not None:
            external_ids = get_external_ids(uid)
            if external_ids.get("onebot_id"):
                return f'https://q1.qlogo.cn/g?b=qq&nk={external_ids["onebot_id"]}&s=640'
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
        # 尝试转换为图片发送
        try:
            img_bytes = await _nodes_to_image(messages)
            if img_bytes:
                await bot.send(event, qq.MessageSegment.file_image(img_bytes))
                return
        except Exception as e:
            logger.error(f"合并转发转图片失败: {e}")

        # 图片生成失败，回退到逐条发送
        for node in messages:
            if isinstance(node, dict) and 'data' in node:
                content = node['data'].get('content', [])
                
                msg_to_send = qq.Message()
                if isinstance(content, list):
                    for segment in content:
                        if isinstance(segment, dict):
                            seg_type = segment.get('type')
                            seg_data = segment.get('data', {})
                            
                            if seg_type == 'text':
                                text = seg_data.get('text', '')
                                if text:
                                    msg_to_send.append(qq.MessageSegment.text(text))
                            elif seg_type == 'image':
                                file_uri = seg_data.get('file', '')
                                if file_uri.startswith('base64://'):
                                    try:
                                        b64_data = file_uri.replace('base64://', '')
                                        img_bytes = base64.b64decode(b64_data)
                                        msg_to_send.append(qq.MessageSegment.file_image(img_bytes))
                                    except Exception as e:
                                        logger.error(f"解析合并转发图片失败: {e}")
                                        msg_to_send.append(qq.MessageSegment.text("[图片解析失败]"))
                                elif file_uri.startswith('http'):
                                    msg_to_send.append(qq.MessageSegment.image(file_uri))
                                else:
                                    # 尝试获取 url 字段
                                    url = seg_data.get('url')
                                    if url:
                                        msg_to_send.append(qq.MessageSegment.image(url))
                                    else:
                                        msg_to_send.append(qq.MessageSegment.text("[不支持的图片格式]"))
                                        
                elif isinstance(content, str):
                    msg_to_send.append(qq.MessageSegment.text(content))
                
                if msg_to_send:
                    await bot.send(event, msg_to_send)


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

# ===== 图片生成辅助 =====

async def _create_node_image(node: Dict[str, Any], width: int = 600, font_size: int = 20) -> BuildImage:
    """创建单个消息节点的图片"""
    data = node.get('data', {})
    name = data.get('name', '用户')
    content = data.get('content', [])
    
    # 估算高度
    padding = 10
    name_height = 30
    line_spacing = 5
    
    # 初始高度，后续会裁剪
    temp_height = 5000 
    img = BuildImage(width, temp_height, font_size=font_size, color=(255, 255, 255))
    
    current_y = padding
    
    # 绘制名字 (如果需要显示名字，取消注释并调整颜色)
    # img.text((padding, current_y), f"{name}", fill=(100, 100, 100))
    # current_y += name_height
    
    if isinstance(content, str):
        content = [{'type': 'text', 'data': {'text': content}}]
        
    for segment in content:
        if not isinstance(segment, dict):
            continue
            
        seg_type = segment.get('type')
        seg_data = segment.get('data', {})
        
        if seg_type == 'text':
            text = seg_data.get('text', '')
            if text:
                # 简单自动换行 (0.8 为中英文混合估算系数)，保留原有的换行符
                max_line_chars = int((width - 2 * padding) / (font_size * 0.8))
                
                # 先按换行符分割，再对每一行进行 wrap
                original_lines = text.split('\n')
                for original_line in original_lines:
                    wrapped_lines = textwrap.wrap(original_line, width=max_line_chars)
                    if not wrapped_lines: # 处理空行
                        current_y += font_size + line_spacing
                        continue
                        
                    for line in wrapped_lines:
                        img.text((padding, current_y), line, fill=(0, 0, 0))
                        current_y += font_size + line_spacing
                    
        elif seg_type == 'image':
            image_data = None
            file_uri = seg_data.get('file', '')
            url = seg_data.get('url', '')
            
            if file_uri.startswith('base64://'):
                try:
                    b64_data = file_uri.replace('base64://', '')
                    image_data = base64.b64decode(b64_data)
                except Exception:
                    pass
            elif file_uri.startswith('http'):
                url = file_uri
            elif not url and file_uri:
                 # 尝试直接作为url
                 if file_uri.startswith('http'):
                     url = file_uri

            if not image_data and url:
                async with httpx.AsyncClient() as client:
                    try:
                        resp = await client.get(url, timeout=10)
                        if resp.status_code == 200:
                            image_data = resp.content
                    except Exception:
                        pass
            
            if image_data:
                try:
                    from PIL import Image
                    pic = Image.open(io.BytesIO(image_data))
                    # 调整图片大小以适应宽度
                    pic_w, pic_h = pic.size
                    max_w = width - 2 * padding
                    if pic_w > max_w:
                        ratio = max_w / pic_w
                        new_h = int(pic_h * ratio)
                        pic = pic.resize((max_w, new_h))
                        pic_w, pic_h = max_w, new_h
                        
                    img.paste(pic, (padding, current_y))
                    current_y += pic_h + line_spacing
                except Exception:
                    img.text((padding, current_y), "[图片加载失败]", fill=(255, 0, 0))
                    current_y += font_size + line_spacing
            else:
                if seg_type == 'image':
                     img.text((padding, current_y), "[图片]", fill=(100, 100, 100))
                     current_y += font_size + line_spacing
                     
    # 裁剪多余部分
    if current_y + padding < temp_height:
        img.crop((0, 0, width, current_y + padding))
        
    return img

async def _nodes_to_image(messages: List[Dict[str, Any]]) -> bytes:
    """将消息链转换为长图"""
    images = []
    width = 600
    
    for node in messages:
        try:
            img = await _create_node_image(node, width=width)
            images.append(img)
        except Exception as e:
            logger.warning(f"生成节点图片失败: {e}")
            continue
            
    if not images:
        return b""
        
    total_height = sum(img.h for img in images)
    final_img = BuildImage(width, total_height, color=(255, 255, 255))
    
    current_y = 0
    for img in images:
        final_img.paste(img.markImg, (0, current_y))
        current_y += img.h
        
    output = io.BytesIO()
    final_img.markImg.save(output, format='PNG')
    return output.getvalue()


def build_image_msg(event: Event, image_data: Union[bytes, str]):
    """
    根据适配器类型构建图片消息段

    Args:
        event: 事件对象，用于判断适配器类型
        image_data: 图片数据，可以是 bytes（原始图片）或 str（base64 编码字符串）

    Returns:
        对应适配器的图片消息段
    """
    if isinstance(image_data, str):
        # base64 字符串，先解码为 bytes
        image_bytes = base64.b64decode(image_data)
        b64_str = image_data
    else:
        image_bytes = image_data
        b64_str = base64.b64encode(image_bytes).decode()

    if isinstance(event, qq.Event):
        from nonebot.adapters.qq import MessageSegment as QQMsgSeg
        return QQMsgSeg.file_image(image_bytes)
    else:
        from nonebot.adapters.onebot.v11 import MessageSegment as OBMsgSeg
        return OBMsgSeg.image(f"base64://{b64_str}")
