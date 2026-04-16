"""
签到插件 - icelogin

提供签到、钱包查看等功能
迁移自旧版 koinoribot
"""

import base64

from nonebot import on_command
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Event, Bot
from nonebot.params import Depends
from nonebot import logger
import aiohttp
import os
from io import BytesIO
from PIL import Image
from .aslogin_v3 import get_src_path, del_custom_bg, dl_save_image, get_purse, as_login_v3
# 导入核心模块
from ... import money
from ...utils import FreqLimiter
from ...tools import get_uid, get_sender_nickname, get_user_avatar_url, is_qqbot, is_onebot, build_forward_chain, send_group_forward_msg
import nonebot.adapters.onebot.v11 as onebot_adapter
from ...uid_manager import (
    verify_bind_code, get_external_ids, rebind_external_id,
    delete_uid_mapping
)
from ...nickname import get_user_nickname
from ... import money
from ...su_manager import get_excluded_su_uids
from ..feisheng.data import get_all_feisheng_status

__plugin_meta__ = PluginMetadata(
    name="icelogin",
    description="签到、钱包查看",
    usage="签到 / 我的钱包",
)

# 频率限制器
login_limiter = FreqLimiter(60)
purse_limiter = FreqLimiter(30)


# ===== 签到命令 =====
login_cmd = on_command("签到", priority=5, block=True)


@login_cmd.handle()
async def handle_login(
    event: Event, 
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理签到命令"""
    # 频率限制检查
    if not login_limiter.check(uid):
        left = round(login_limiter.left_time(uid))
        await login_cmd.finish(
            f"已经领过签到卡片啦，稍微等一下再来领喔~({left}s)",
            at_sender=True
        )
    
    # 获取用户昵称
    username = await get_sender_nickname(event) or "用户"
    # 获取用户头像 URL
    avatar_url = get_user_avatar_url(event, uid=uid)
    image_bytes = await as_login_v3(
        uid=uid,
        username=username,
        qqname=username,
        nick_flag=1 if username else 0,
        avatar_url=avatar_url
    )
    # 根据适配器类型构建图片消息段
    if is_qqbot(event):
        from nonebot.adapters.qq import MessageSegment as QQMsgSeg
        image_msg = QQMsgSeg.file_image(image_bytes)
    else:
        from nonebot.adapters.onebot.v11 import MessageSegment as OBMsgSeg
        image_msg = OBMsgSeg.image(f"base64://{base64.b64encode(image_bytes).decode()}")
    await login_cmd.send(image_msg)

    login_limiter.start_cd(uid)


# ===== 钱包命令 =====
purse_cmd = on_command("我的钱包", priority=5, block=True)


@purse_cmd.handle()
async def handle_purse(
    event: Event, 
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理钱包查看命令"""
    username = await get_sender_nickname(event) or "用户"
    
    # 获取用户头像 URL
    avatar_url = get_user_avatar_url(event, uid=uid)
    image_bytes = await get_purse(uid=uid, user_name=username, avatar_url=avatar_url)
    # 根据适配器类型构建图片消息段
    if is_qqbot(event):
        from nonebot.adapters.qq import MessageSegment as QQMsgSeg
        image_msg = QQMsgSeg.file_image(image_bytes)
    else:
        from nonebot.adapters.onebot.v11 import MessageSegment as OBMsgSeg
        image_msg = OBMsgSeg.image(f"base64://{base64.b64encode(image_bytes).decode()}")
    await purse_cmd.send(image_msg)

    purse_limiter.start_cd(uid)


# ===== 金币排行榜 =====
rank_cmd = on_command("金币排行榜", priority=5, block=True)


@rank_cmd.handle()
async def handle_gold_ranking(
    event: Event, 
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理金币排行榜命令"""
    
    all_gold_data = money.get_all_user_money('gold')
    
    if not all_gold_data:
        await rank_cmd.finish("排行榜暂无数据。")
    
    # 过滤需要排除的 SU 用户（保留 level 1 的 SU）
    excluded_suids = get_excluded_su_uids()
    
    # 获取所有用户飞升状态
    feisheng_status = await get_all_feisheng_status()
    
    # 转换为列表并排序（排除非 level 1 的 SU）
    ranked_list = [(uid_key, gold) for uid_key, gold in all_gold_data.items() if uid_key not in excluded_suids]
    # 已飞升用户置顶，同组内按金币降序
    ranked_list.sort(key=lambda x: (feisheng_status.get(x[0], False), x[1]), reverse=True)
    
    if not ranked_list:
        await rank_cmd.finish("排行榜暂无数据。")
    
    # 构建排行榜消息
    msg_parts = ["🏆 金币排行榜-TOP10 🏆"]
    for rank, (user_id, gold) in enumerate(ranked_list[:10], 1):
        owner_name = get_user_nickname(int(user_id)) or f"UID {user_id}"
        if feisheng_status.get(user_id, False):
            msg_parts.append(f"{rank}. {owner_name}: 超然物外（飞升上界）")
        else:
            gold_in_wan = gold / 10000
            msg_parts.append(f"{rank}. {owner_name}: {gold_in_wan:.2f}万")
    
    # 当前用户排名
    user_rank = -1
    for i, (uid_key, gold) in enumerate(ranked_list):
        if uid_key == uid:
            user_rank = i + 1
            break
    
    if user_rank != -1:
        if user_rank <= 50:
            user_rank_msg = f"您的排名: 第{user_rank}名"
        else:
            percentage = (user_rank / len(ranked_list)) * 100
            user_rank_msg = f"您的排名: 位于前{percentage:.0f}%"
    else:
        user_rank_msg = "您未参与排名"
    
    msg_parts.append(f"\n{user_rank_msg}")

    msg_parts.append(f"\n\n\n使用 冰祈请叫我 可以修改自己的昵称哦~")
    
    msg_str = "\n".join(msg_parts)
    chain = await build_forward_chain(bot, [msg_str])
    await send_group_forward_msg(event, bot, chain)


# ===== 上传签到图片 =====
upload_bg_cmd = on_command("上传签到图片", priority=5, block=True)

# 自定义图片消耗金币数（0表示免费）
UPLOAD_BG_COST = 0

@upload_bg_cmd.handle()
async def handle_upload_bg(
    event: Event, 
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理上传签到图片命令"""
    # 从消息中提取图片URL
    image_url = None
    
    # 尝试从原始消息中提取图片
    try:
        # OneBot v11 格式
        for seg in event.message:
            if seg.type == "image":
                image_url = seg.data.get("url") or seg.data.get("file")
                break
    except:
        pass
    
    if not image_url:
        await upload_bg_cmd.finish("请附带图片~", at_sender=True)
    
    # 检查金币
    user_gold = money.get_user_money(uid, 'gold') or 0
    if user_gold < UPLOAD_BG_COST:
        await upload_bg_cmd.finish("金币不足...", at_sender=True)
    
    # 下载并保存图片（使用uid作为文件名）
    await dl_save_image(image_url, uid)
    
    # 扣除金币（如果需要）
    if UPLOAD_BG_COST > 0:
        money.reduce_user_money(uid, 'gold', UPLOAD_BG_COST)
        msg = f"已上传图片~(将扣除{UPLOAD_BG_COST}金币)"
    else:
        msg = "已上传图片~"
    
    await upload_bg_cmd.finish(msg, at_sender=True)


# ===== 清除签到图片 =====
remove_bg_cmd = on_command("清除签到图片", priority=5, block=True)

@remove_bg_cmd.handle()
async def handle_remove_bg(
    event: Event, 
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理清除签到图片命令"""
    del_custom_bg(uid)
    
    await remove_bg_cmd.finish("已恢复默认背景~", at_sender=True)


# ===== 查看UID =====
view_uid_cmd = on_command("查看uid", aliases={"我的uid", "个人信息"}, priority=5, block=True)

@view_uid_cmd.handle()
async def handle_view_uid(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理查看UID命令"""
    from ...uid_manager import get_external_ids

    external_ids = get_external_ids(uid)
    qq_display = external_ids["onebot_id"] if external_ids["onebot_id"] else "未绑定"
    openid_display = external_ids["qqbot_id"] if external_ids["qqbot_id"] else "未绑定"

    msg = (
        f"\n您的uid：{uid}\n"
        f"--qq：{qq_display}\n"
        f"--openid：{openid_display}"
    )

    await view_uid_cmd.finish(msg, at_sender=True)


# ===== 查找UID =====
find_uid_cmd = on_command("查找uid", aliases={"查询uid"}, priority=5, block=True)

@find_uid_cmd.handle()
async def handle_find_uid(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理查找UID命令"""
    msg = event.get_plaintext().strip().split(maxsplit=1)
    if len(msg) < 2 or not msg[1].isdigit():
        await find_uid_cmd.finish("请输入正确的uid，格式：查找uid [目标uid]", at_sender=True)
    
    target_uid = int(msg[1])
    
    # 检查金币
    user_gold = money.get_user_money(uid, 'gold') or 0
    cost = 10000
    
    if user_gold < cost:
        await find_uid_cmd.finish(f"金币不足...查找uid需要花费 {cost} 金币", at_sender=True)
        
    # 查询信息
    from ...uid_manager import get_external_ids
    target_ids = get_external_ids(target_uid)
    
    qq_display = target_ids["onebot_id"] if target_ids["onebot_id"] else "未绑定"
    openid_display = target_ids["qqbot_id"] if target_ids["qqbot_id"] else "未绑定"
    
    if qq_display == "未绑定" and openid_display == "未绑定":
        await find_uid_cmd.finish("目标uid不存在或未绑定任何平台。", at_sender=True)
        
    # 扣除金币
    money.reduce_user_money(uid, 'gold', cost)
    
    ret_msg = (
        f"消耗 {cost} 金币，为您查询到uid={target_uid}的信息：\n"
        f"--qq：{qq_display}\n"
        f"--openid：{openid_display}"
    )
    
    await find_uid_cmd.finish(ret_msg, at_sender=True)


# ===== 注册验证码（仅私聊） =====
register_code_cmd = on_command("注册验证码", aliases={"注册绑定验证码", "注册绑定码"}, priority=5, block=True)


@register_code_cmd.handle()
async def handle_register_code(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """生成绑定验证码（仅私聊触发）"""
    # 检查是否为私聊
    from nonebot.adapters.qq.event import C2CMessageCreateEvent
    is_private = False
    if is_onebot(event) and isinstance(event, onebot_adapter.PrivateMessageEvent):
        is_private = True
    elif is_qqbot(event) and isinstance(event, C2CMessageCreateEvent):
        is_private = True

    if not is_private:
        await register_code_cmd.finish("该命令仅支持私聊使用哦~", at_sender=True)

    # 检查是否已双平台绑定
    from ...uid_manager import get_external_ids
    external_ids = get_external_ids(uid)
    if external_ids["onebot_id"] and external_ids["qqbot_id"]:
        await register_code_cmd.finish("你已绑定了两个平台，无需再次绑定~", at_sender=True)

    from ...uid_manager import generate_bind_code
    code = generate_bind_code(uid)
    await register_code_cmd.finish(
        f"你的绑定码：{code}\n请在5分钟内于另一个平台发送「绑定账号 {code}」完成绑定。"
    )


# ===== 绑定账号 =====
bind_cmd = on_command("绑定账号", aliases={"账号绑定"}, priority=5, block=True)

# 临时存储绑定上下文: {当前用户uid: {"source_uid": int, "current_uid": int, "current_platform": str, "current_external_id": str}}
_bind_context: dict[int, dict] = {}

# 绑定命令的频率限制器 (30秒)
bind_limiter = FreqLimiter(30)


@bind_cmd.handle()
async def handle_bind(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理绑定账号命令"""
    
    # 频率限制检查
    if not bind_limiter.check(uid):
        left = round(bind_limiter.left_time(uid))
        await bind_cmd.finish(
            f"操作太快啦，请等待 {left} 秒后再尝试绑定~",
            at_sender=True
        )

    # 提取参数（验证码）
    raw_msg = event.get_plaintext().strip()
    parts = raw_msg.split()
    if len(parts) < 2:
        await bind_cmd.finish("请输入验证码，格式：绑定账号 验证码", at_sender=True)

    code = parts[1].strip()

    # 马上开启 CD，防止接下来验证时间差导致同时间的爆破
    bind_limiter.start_cd(uid)

    # 校验验证码
    source_uid = verify_bind_code(code)
    if source_uid is None:
        await bind_cmd.finish("验证码无效或已过期，请通过 注册绑定码 获取~", at_sender=True)

    # 判断当前用户平台
    if is_onebot(event):
        current_platform = "onebot"
    elif is_qqbot(event):
        current_platform = "qqbot"
    else:
        await bind_cmd.finish("不支持的平台类型", at_sender=True)
        return

    current_external_id = event.get_user_id()

    # 检查源uid信息
    source_ids = get_external_ids(source_uid)

    # 不能绑定到自己
    if source_uid == uid:
        await bind_cmd.finish("验证码对应的就是你当前的账号，无需绑定~", at_sender=True)

    # 如果源uid两个槽位都满了，直接拒绝
    if source_ids["onebot_id"] and source_ids["qqbot_id"]:
        await bind_cmd.finish(
            f"验证码对应的uid={source_uid}已绑定了两个平台的账号，不支持绑定~",
            at_sender=True
        )

    # 检查源uid对应的平台槽位是否已被占用（同平台不能绑定）
    source_platform_col = "onebot_id" if current_platform == "onebot" else "qqbot_id"
    if source_ids.get(source_platform_col):
        await bind_cmd.finish(
            f"验证码对应的uid={source_uid}已绑定了{current_platform}平台的账号，不能重复绑定同一平台~",
            at_sender=True
        )

    # 获取两个uid的资产信息用于展示
    source_gold = money.get_user_money(source_uid, 'gold') or 0
    source_gem = money.get_user_money(source_uid, 'kirastone') or 0
    current_gold = money.get_user_money(uid, 'gold') or 0
    current_gem = money.get_user_money(uid, 'kirastone') or 0

    source_qq = source_ids.get("onebot_id", "无")
    source_openid = source_ids.get("qqbot_id", "无")

    # 保存绑定上下文
    _bind_context[uid] = {
        "source_uid": source_uid,
        "current_uid": uid,
        "current_platform": current_platform,
        "current_external_id": current_external_id,
    }

    await bind_cmd.send(
        f"绑定将把你当前平台的账号与验证码对应的账号合并为同一个uid。\n"
        f"你需要选择保留哪个uid，未被保留的uid将被删除。\n\n"
        f"1. 账号一 uid={source_uid}（QQ: {source_qq}, OpenID: {source_openid}）\n"
        f"   金币余额: {source_gold}  宝石余额: {source_gem}\n\n"
        f"2. 账号二 uid={uid}\n"
        f"   金币余额: {current_gold}  宝石余额: {current_gem}\n\n"
        f"请回复 1（保留账号一）或 2（保留账号二）："
    )
    await bind_cmd.pause()


@bind_cmd.handle()
async def handle_bind_choice(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理用户选择保留哪个uid"""
    from ...uid_manager import rebind_external_id, delete_uid_mapping, get_external_ids

    if uid not in _bind_context:
        await bind_cmd.finish("没有待处理的绑定请求~", at_sender=True)

    ctx = _bind_context.pop(uid)
    choice = event.get_plaintext().strip()

    source_uid = ctx["source_uid"]
    current_uid = ctx["current_uid"]
    current_platform = ctx["current_platform"]
    current_external_id = ctx["current_external_id"]

    if choice == "1":
        # 保留老账号（source_uid），将当前平台ID移过去，删除当前uid
        rebind_external_id(source_uid, current_platform, current_external_id)
        delete_uid_mapping(current_uid)
        await bind_cmd.finish(
            f"绑定成功！保留老账号 uid={source_uid}，新账号 uid={current_uid} 已删除。",
            at_sender=True
        )
    elif choice == "2":
        # 保留新账号（current_uid），将源的另一平台ID移过来，删除源uid
        source_other_platform = "qqbot" if current_platform == "onebot" else "onebot"
        source_ids = get_external_ids(source_uid)
        source_other_col = "onebot_id" if source_other_platform == "onebot" else "qqbot_id"
        source_other_id = source_ids.get(source_other_col)
        if source_other_id:
            rebind_external_id(current_uid, source_other_platform, source_other_id)
        delete_uid_mapping(source_uid)
        await bind_cmd.finish(
            f"绑定成功！保留新账号 uid={current_uid}，老账号 uid={source_uid} 已删除。",
            at_sender=True
        )
    else:
        await bind_cmd.finish("无效的选择，绑定已取消。", at_sender=True)


# ===== 解绑账号 =====
unbind_cmd = on_command("解绑账号", priority=5, block=True)


@unbind_cmd.handle()
async def handle_unbind(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """解绑当前平台账号 - 第一步：确认"""
    from ...uid_manager import get_external_ids

    external_ids = get_external_ids(uid)

    if is_onebot(event):
        platform_col = "onebot_id"
    elif is_qqbot(event):
        platform_col = "qqbot_id"
    else:
        await unbind_cmd.finish("不支持的平台类型", at_sender=True)
        return

    # 检查是否已绑定了两个平台
    if not external_ids["onebot_id"] or not external_ids["qqbot_id"]:
        await unbind_cmd.finish("你当前只绑定了一个平台，无需解绑~", at_sender=True)

    await unbind_cmd.send(
        f"解绑后，你在当前平台将获得一个全新的uid，原uid={uid}的数据保留在原账号中。\n"
        f"此操作不可撤销！请回复 确认 继续，或回复其他内容取消："
    )
    await unbind_cmd.pause()


@unbind_cmd.handle()
async def handle_unbind_confirm(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """解绑当前平台账号 - 第二步：执行"""
    from ...uid_manager import get_uid as create_uid, _get_connection

    confirm = event.get_plaintext().strip()
    if confirm != "确认":
        await unbind_cmd.finish("已取消解绑操作。", at_sender=True)

    if is_onebot(event):
        platform = "onebot"
        platform_col = "onebot_id"
    elif is_qqbot(event):
        platform = "qqbot"
        platform_col = "qqbot_id"
    else:
        await unbind_cmd.finish("不支持的平台类型", at_sender=True)
        return

    # 将当前平台ID从uid中移除
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(f'UPDATE user_uid_mapping SET {platform_col} = NULL WHERE uid = ?', (uid,))
    conn.commit()
    conn.close()

    # 为当前平台ID创建新的独立uid
    external_id = event.get_user_id()
    new_uid = create_uid(platform=platform, external_id=external_id)

    await unbind_cmd.finish(
        f"解绑成功！你在当前平台的新uid为 {new_uid}，原uid={uid}的数据保留在原账号中。",
        at_sender=True
    )


# ===== 上传头像 =====
upload_avatar_cmd = on_command("上传头像", priority=5, block=True)


@upload_avatar_cmd.handle()
async def handle_upload_avatar(
    event: Event, 
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """处理上传头像命令"""
    # 从消息中提取图片URL
    image_url = None
    
    # 根据适配器类型尝试提取图片
    from ...tools import is_qqbot, is_onebot
    
    if is_onebot(event):
        for seg in event.message:
            if seg.type == "image":
                image_url = seg.data.get("url") or seg.data.get("file")
                break
    elif is_qqbot(event):
        # 官bot (QQBot): 附件中的图片为 Attachment 形式，或者在 message 当中
        if hasattr(event, "attachments") and event.attachments:
            for attachment in event.attachments:
                # content_type 可能是 'image/jpeg' 等等，或者是根据 type='image' 或者有 url 字段来判断
                if hasattr(attachment, "content_type") and "image" in str(attachment.content_type).lower():
                    image_url = attachment.url
                    # 官bot 返回的 url 可能以 http:// 开头，需要手动转成 https 提供下载，看接口表现，这里先直接取 url
                    break
                elif hasattr(attachment, "url") and attachment.url:
                    image_url = attachment.url
                    break
        else:
            # 如果从 message 下解析 QQBot 的 Attachment Segment
            for seg in event.message:
                if seg.type == "image" or seg.type == "attachment":
                    image_url = seg.data.get("url")
                    break
                    
    if not image_url:
        await upload_avatar_cmd.finish("请加上图片一起发送哦~", at_sender=True)
        return
    
    # 下载并保存裁剪图片
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as r:
                content = await r.read()
                
        img = Image.open(BytesIO(content)).convert("RGBA")
    except (aiohttp.ClientError, OSError, ValueError) as e:
        logger.error(f"上传头像失败: {e}")
        await upload_avatar_cmd.finish("头像上传失败或图片格式不正确...", at_sender=True)
        return

    w, h = img.size
    
    # 居中裁剪为正方形 (1:1 取中间部分)
    length = min(w, h)
    left = (w - length) // 2
    top = (h - length) // 2
    right = left + length
    bottom = top + length
    img = img.crop((left, top, right, bottom))
    
    # 压缩图片以节省空间并统一大小
    if hasattr(Image, 'Resampling'):
        resample_method = Image.Resampling.LANCZOS
    else:
        resample_method = Image.ANTIALIAS
    img = img.resize((256, 256), resample_method)
    
    # 保存为 png
    srcpath = get_src_path()
    save_dir = os.path.join(srcpath, "avatar")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{uid}.png")
    
    img.save(save_path, format="PNG")
    
    await upload_avatar_cmd.finish("头像上传成功并已自动裁剪~", at_sender=True)
