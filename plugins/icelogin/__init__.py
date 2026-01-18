"""
签到插件 - icelogin

提供签到、钱包查看等功能
迁移自旧版 koinoribot
"""

from nonebot import on_fullmatch, on_startswith
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Event, Bot
from nonebot import logger

# 导入事件适配器和核心模块
from ... import event_adapter
from ... import money
from ...utils import FreqLimiter

__plugin_meta__ = PluginMetadata(
    name="icelogin",
    description="签到、钱包查看",
    usage="签到 / 我的钱包",
)

# 频率限制器
login_limiter = FreqLimiter(60)
purse_limiter = FreqLimiter(30)


# ===== 签到命令 =====
login_cmd = on_fullmatch(("签到", "/签到", "#签到"), priority=5, block=True)


@login_cmd.handle()
async def handle_login(event: Event, bot: Bot):
    """处理签到命令"""
    try:
        # 转换为统一事件
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        # 频率限制检查
        if not login_limiter.check(uid):
            left = round(login_limiter.left_time(uid))
            await event_adapter.send_message(
                uevent, 
                f"已经领过签到卡片啦，稍微等一下再来领喔~({left}s)",
                at_sender=True
            )
            return
        
        # 获取用户昵称
        username = uevent.sender_nickname or "用户"
        
        # 尝试调用签到卡片生成（如果可用）
        from .aslogin_v3 import as_login_v3
        # 获取用户头像 URL
        avatar_url = await event_adapter.get_user_avatar_url(uevent)
        image_msg = await as_login_v3(
            uid=uid,
            username=username,
            qqname=username,
            nick_flag=1 if username else 0,
            avatar_url=avatar_url
        )
        await event_adapter.send_message(uevent, image_msg)

        
        login_limiter.start_cd(uid)
        
    except Exception as e:
        logger.error(f"签到失败: {e}")
        await bot.send(event, f"签到失败: {e}")

'''
async def simple_login(uid: int, username: str) -> str:
    """简化版签到（不生成图片）"""
    import time
    import random
    
    current_time = time.localtime()
    months = int(time.strftime("%m", current_time))
    days = int(time.strftime("%d", current_time))
    
    # 检查是否已签到
    last_login = money.get_user_money(uid, "last_login") or 0
    today_flag = int(f'{months}0{days}')
    
    if last_login == today_flag:
        # 已签到
        logindays = money.get_user_money(uid, "logindays") or 0
        return f"今天已经签过到了哦~\n已累计签到 {logindays} 天"
    
    # 执行签到
    rp = random.randint(0, 100)
    gold = 100 + rp
    star_add = random.randint(100, 200)
    
    # 更新数据
    money.increase_user_money(uid, "logindays", 1)
    money.increase_user_money(uid, "starstone", rp * 5 + star_add)
    money.increase_user_money(uid, "gold", gold)
    money.set_user_money(uid, "last_login", today_flag)
    money.set_user_money(uid, "rp", rp)
    
    logindays = money.get_user_money(uid, "logindays") or 1
    
    # 生成反馈
    if rp < 20:
        rp_msg = "运势很差呢..."
    elif rp < 40:
        rp_msg = "运势欠佳"
    elif rp < 60:
        rp_msg = "运势普通"
    elif rp < 80:
        rp_msg = "运势不错~"
    elif rp < 100:
        rp_msg = "运势旺盛！"
    else:
        rp_msg = "运势爆棚！！"
    
    return (
        f"签到成功！\n"
        f"今日人品: {rp} ({rp_msg})\n"
        f"获得: ⭐{rp * 5 + star_add} 💰{gold}\n"
        f"已累计签到 {logindays} 天"
    )
'''

# ===== 钱包命令 =====
purse_cmd = on_fullmatch(("我的钱包", "#我的钱包", "/我的钱包"), priority=5, block=True)


@purse_cmd.handle()
async def handle_purse(event: Event, bot: Bot):
    """处理钱包查看命令"""
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        username = uevent.sender_nickname or "用户"
        
        # 尝试调用钱包卡片生成

        from .aslogin_v3 import get_purse
        # 获取用户头像 URL
        avatar_url = await event_adapter.get_user_avatar_url(uevent)
        image_msg = await get_purse(uid=uid, user_name=username, avatar_url=avatar_url)
        await event_adapter.send_message(uevent, image_msg)

        
        purse_limiter.start_cd(uid)
        
    except Exception as e:
        logger.error(f"查看钱包失败: {e}")
        await bot.send(event, f"查看钱包失败: {e}")

'''
async def simple_purse(uid: int, username: str) -> str:
    """简化版钱包查看"""
    gold = money.get_user_money(uid, "gold") or 0
    starstone = money.get_user_money(uid, "starstone") or 0
    luckygold = money.get_user_money(uid, "luckygold") or 0
    kirastone = money.get_user_money(uid, "kirastone") or 0
    
    return (
        f"💼 {username} 的钱包\n"
        f"━━━━━━━━━━\n"
        f"💰 金币: {gold}\n"
        f"⭐ 星星: {starstone}\n"
        f"🍀 幸运币: {luckygold}\n"
        f"💎 宝石: {kirastone}"
    )
'''

# ===== 金币排行榜 =====
rank_cmd = on_fullmatch(("金币排行榜", "#金币排行榜", "/金币排行榜"), priority=5, block=True)


@rank_cmd.handle()
async def handle_gold_ranking(event: Event, bot: Bot):
    """处理金币排行榜命令"""
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        all_gold_data = money.get_all_user_money('gold')
        
        if not all_gold_data:
            await event_adapter.send_message(uevent, "排行榜暂无数据。")
            return
        
        # 转换为列表并排序
        ranked_list = [(uid_key, gold) for uid_key, gold in all_gold_data.items()]
        ranked_list.sort(key=lambda x: x[1], reverse=True)
        
        if not ranked_list:
            await event_adapter.send_message(uevent, "排行榜暂无数据。")
            return
        
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
        
        await event_adapter.send_message(uevent, "\n".join(msg_parts), at_sender=True)
        
    except Exception as e:
        logger.error(f"获取排行榜失败: {e}")
        await bot.send(event, f"获取排行榜失败: {e}")


# ===== 上传签到图片 =====
upload_bg_cmd = on_startswith(("上传签到图片", "#上传签到图片", "/上传签到图片"), priority=5, block=True)

# 自定义图片消耗金币数（0表示免费）
UPLOAD_BG_COST = 0

@upload_bg_cmd.handle()
async def handle_upload_bg(event: Event, bot: Bot):
    """处理上传签到图片命令"""
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
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
            await event_adapter.send_message(uevent, "请附带图片~", at_sender=True)
            return
        
        # 检查金币
        user_gold = money.get_user_money(uid, 'gold') or 0
        if user_gold < UPLOAD_BG_COST:
            await event_adapter.send_message(uevent, "金币不足...", at_sender=True)
            return
        
        # 下载并保存图片（使用uid作为文件名）
        from .aslogin_v3 import dl_save_image
        await dl_save_image(image_url, uid)
        
        # 扣除金币（如果需要）
        if UPLOAD_BG_COST > 0:
            money.reduce_user_money(uid, 'gold', UPLOAD_BG_COST)
            msg = f"已上传图片~(将扣除{UPLOAD_BG_COST}金币)"
        else:
            msg = "已上传图片~"
        
        await event_adapter.send_message(uevent, msg, at_sender=True)
        
    except Exception as e:
        logger.error(f"上传签到图片失败: {e}")


# ===== 清除签到图片 =====
remove_bg_cmd = on_startswith(("清除签到图片", "#清除签到图片", "/清除签到图片"), priority=5, block=True)

@remove_bg_cmd.handle()
async def handle_remove_bg(event: Event, bot: Bot):
    """处理清除签到图片命令"""
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        from .aslogin_v3 import del_custom_bg
        del_custom_bg(uid)
        
        await event_adapter.send_message(uevent, "已恢复默认背景~", at_sender=True)
        
    except Exception as e:
        logger.error(f"清除签到图片失败: {e}")

