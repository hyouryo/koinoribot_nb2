"""
签到插件 - icelogin

提供签到、钱包查看等功能
迁移自旧版 koinoribot
"""

from nonebot import on_command
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Event, Bot
from nonebot.params import Depends
from nonebot import logger

# 导入核心模块
from ... import money
from ...utils import FreqLimiter
from ...tools import get_uid, get_sender_nickname, get_user_avatar_url

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
    username = get_sender_nickname(event) or "用户"
    
    # 尝试调用签到卡片生成（如果可用）
    from .aslogin_v3 import as_login_v3
    # 获取用户头像 URL
    avatar_url = get_user_avatar_url(event)
    image_msg = await as_login_v3(
        uid=uid,
        username=username,
        qqname=username,
        nick_flag=1 if username else 0,
        avatar_url=avatar_url
    )
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
    username = get_sender_nickname(event) or "用户"
    
    # 尝试调用钱包卡片生成
    from .aslogin_v3 import get_purse
    # 获取用户头像 URL
    avatar_url = get_user_avatar_url(event)
    image_msg = await get_purse(uid=uid, user_name=username, avatar_url=avatar_url)
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
    
    # 转换为列表并排序
    ranked_list = [(uid_key, gold) for uid_key, gold in all_gold_data.items()]
    ranked_list.sort(key=lambda x: x[1], reverse=True)
    
    if not ranked_list:
        await rank_cmd.finish("排行榜暂无数据。")
    
    # 构建排行榜消息
    msg_parts = ["🏆 金币排行榜-TOP10 🏆"]
    for rank, (user_id, gold) in enumerate(ranked_list[:10], 1):
        gold_in_wan = gold / 10000
        msg_parts.append(f"第{rank}名: UID {user_id}: {gold_in_wan:.2f}万")
    
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
    
    await rank_cmd.finish("\n".join(msg_parts), at_sender=True)


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
    from .aslogin_v3 import dl_save_image
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
    from .aslogin_v3 import del_custom_bg
    del_custom_bg(uid)
    
    await remove_bg_cmd.finish("已恢复默认背景~", at_sender=True)


