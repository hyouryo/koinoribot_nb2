"""
请叫我XXX 插件 - call_me_please

允许用户自定义冰祈对自己的称呼。
数据由于持久化存储到 SQLite 的 koinoribot.db 中。
"""

import os
from nonebot import on_command, get_driver
from nonebot.adapters import Event, Bot, Message
from nonebot.params import CommandArg, Depends
from nonebot.plugin import PluginMetadata
from nonebot.log import logger

from ...koinori_config import config
from ...tools import get_uid, build_image_msg, get_sender_nickname
from ...resources import get as get_res
from ...su_manager import is_su, get_su_level
from ..nickname import set_db_path, get_user_nickname, set_user_nickname

__plugin_meta__ = PluginMetadata(
    name="call_me_please",
    description="自定义称呼插件。允许自己设置称呼，并允许0级SU修改他人称呼。",
    usage="请叫我 [称呼] / 修改名称 [uid] [称呼] / 我是谁"
)

# 屏蔽词
BANNED_WORD = (
    'rbq', 'RBQ', '憨批', '废物', '死妈', '崽种', '傻逼', '傻逼玩意', '贵物', '🐴',
    '没用东西', '傻B', '傻b', 'SB', 'sb', '煞笔', 'cnm', '爬', 'kkp', '你妈死了', '尼玛死了',
    'nmsl', 'D区', '口区', '我是你爹', 'nmbiss', '弱智', '给爷爬', '杂种爬', '爪巴', '冰祈'
)

# 获取资源图片
def get_no_image():
    try:
        return get_res('emotion/no.png')
    except Exception as e:
        logger.warning(f"[call_me_please] 无法加载 no.png 图像: {e}")
        return None

def get_what_image():
    try:
        return get_res('emotion/问号.png')
    except Exception as e:
        logger.warning(f"[call_me_please] 无法加载 问号.png 图像: {e}")
        return None

# ===== 初始化 =====
driver = get_driver()

@driver.on_startup
async def init_call_me_please():
    """初始化数据库"""
    from pathlib import Path
    plugin_dir = Path(__file__).parent.parent.parent
    db_path = plugin_dir / "src" / "database" / "koinoribot.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    set_db_path(str(db_path))
    logger.info("call_me_please 插件初始化完成")


# ===== 核心功能：请叫我 =====
call_me_cmd = on_command("冰祈请叫我", aliases={"请叫我"}, priority=5, block=True)

@call_me_cmd.handle()
async def handle_call_me(bot: Bot, event: Event, uid: int = Depends(get_uid), args: Message = CommandArg()):
    message = args.extract_plain_text().strip()
    
    if not message:
        await call_me_cmd.finish("你要冰祈叫你什么呢？", at_sender=True)
    
    # 获取图片
    no_img_res = get_no_image()
    no_msg = None
    if no_img_res:
        try:
            no_msg = build_image_msg(event, no_img_res.base64)
        except Exception as e:
            logger.warning(f"构建图片失败: {e}")
    
    # 特殊 UUID 拦截 (此处保留原版逻辑中的 80000000，虽然新版使用了唯一 UID)
    if uid == 80000000:
        if no_msg:
            await call_me_cmd.finish(no_msg)
        else:
            await call_me_cmd.finish("no")
    
    # 长度和编码检查
    len_txt = len(message)
    len_txt_utf8 = len(message.encode('utf-8'))
    size = int((len_txt_utf8 - len_txt) / 2 + len_txt)
    
    if size > 20:
        error_msg = f"名字太长，冰祈记不住.."
        if no_msg:
            await call_me_cmd.finish(Message(error_msg) + no_msg, at_sender=True)
        else:
            await call_me_cmd.finish(error_msg, at_sender=True)
        
    # 屏蔽词检查
    for word in BANNED_WORD:
        if word in message:
            error_msg = f"不可以教坏冰祈.."
            if no_msg:
                await call_me_cmd.finish(Message(error_msg) + no_msg, at_sender=True)
            else:
                await call_me_cmd.finish(error_msg, at_sender=True)
            
    # 更新数据库
    if set_user_nickname(uid, message):
        await call_me_cmd.finish("好~", at_sender=True)
    else:
        await call_me_cmd.finish("发生错误，称呼保存失败...", at_sender=True)


# ===== SU 修改他人名称 =====
rename_cmd = on_command("修改名称", priority=2, block=True)

@rename_cmd.handle()
async def handle_rename(bot: Bot, event: Event, uid: int = Depends(get_uid), args: Message = CommandArg()):
    # 鉴权：只有 SU level 0 可以使用
    if not is_su(uid) or get_su_level(uid) != 0:
        await rename_cmd.finish("权限不足，只有最高级管理员才能使用此命令。", at_sender=True)
        
    arg_text = args.extract_plain_text().strip()
    parts = arg_text.split(maxsplit=1)
    
    if len(parts) < 2:
        await rename_cmd.finish("格式错误。正确格式：修改名称 <uid> <新称呼>", at_sender=True)
        
    target_uid_str = parts[0]
    new_nickname = parts[1].strip()
    
    try:
        target_uid = int(target_uid_str)
    except ValueError:
        await rename_cmd.finish("UID 格式错误，必须是数字。", at_sender=True)
        
    if not new_nickname:
        await rename_cmd.finish("新称呼不能为空。", at_sender=True)
        
    # 强制更新，绕过所有限制
    if set_user_nickname(target_uid, new_nickname):
        await rename_cmd.finish(f"已成功强制将 UID {target_uid} 的称呼修改为：{new_nickname}", at_sender=True)
    else:
        await rename_cmd.finish("发生错误，修改失败。", at_sender=True)

# ===== 查询称呼：我是谁 =====
who_am_i_cmd = on_command("冰祈我是谁", aliases={"我是谁"}, priority=5, block=True)

@who_am_i_cmd.handle()
async def handle_who_am_i(bot: Bot, event: Event, uid: int = Depends(get_uid)):
    # 特殊匿名用户检查
    if uid == 80000000:
        await who_am_i_cmd.finish("你是匿名用户捏", at_sender=True)
        
    name = get_user_nickname(uid)
    if not name:
        name = get_sender_nickname(event)
        if not name:
            name = "无名氏"
            
    await who_am_i_cmd.finish(f"是{name}~", at_sender=True)
