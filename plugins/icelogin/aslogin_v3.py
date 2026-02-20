"""
签到卡片生成模块 - aslogin_v3

完整迁移自旧版 koinoribot
功能：签到卡片生成、钱包图片生成
"""

import asyncio
import io
import random
import time
import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
import tempfile
import uuid

import aiohttp

from ... import money
from ...build_image import BuildImage
from .color_convert import lab2rgb

# 调试模式配置
debug_mode = 0
add_watermark = 0
debug_login_flag = 0
save_image_mode = 0
debug_background = 'Background2.jpg'

# 背景图列表
backgroundList = [
    'Background1.jpg', 'Background2.jpg', 'Background3.jpg', 'Background4.jpg', 'Background5.jpg',
    'Background6.jpg', 'Background7.jpg', 'Background8.jpg', 'Background9.jpg', 'Background10.jpg',
    'Background11.jpg', 'Background12.jpg', 'Background13.jpg', 'Background14.jpg'
]

hoshi_bg_list = [
    'Background-hoshi-1.jpg', 'Background-hoshi-2.jpg', 'Background-hoshi-3.jpg',
    'Background-hoshi-4.jpg', 'Background-hoshi-5.jpg'
]

extra_bg_list = ['Background_extra.jpg']

# 宜忌列表
goodluck = [
    '宜 抽卡', '宜 干饭', '宜 摸鱼', '宜 刷副本', '宜 女装', '宜 打游戏',
    '宜 刷b站', '宜 看涩图', '宜 逛街', '宜 好好学习', '宜 搓麻将', '宜 工作',
    '宜 点外卖', '宜 水群', '宜 听音乐', '宜 背单词', '宜 做作业', '宜 刷抖音',
    '宜 睡觉', '宜 刷剧'
]

badluck = [
    '忌 抽卡上头', '忌 躺平', '忌 摸鱼', '忌 刷副本', '忌 女装', '忌 打游戏',
    '忌 刷b站', '忌 看涩图', '忌 逛街', '忌 学习', '忌 搓麻将', '忌 摆烂',
    '忌 点外卖', '忌 水群', '忌 听音乐', '忌 背单词', '忌 做作业', '忌 刷抖音',
    '忌 睡懒觉', '忌 刷剧', '忌 无'
]

# 生日和节日列表
birth_list = [
    "1232", "0422", "0725", "0711", "1126", "1231", "0606", "0520", "0709",
    "0320", "1221", "0614", "0120", "1218", "0221", "1104", "0101", "0504"
]

member_list = [
    "冰祈", "御子柴", "梦馨", "《灵歌少女》", "永远都在的冥蝶～", "盐的砂糖酱",
    "miku丶菈", "叶苏秋和幻心", "让我视视", "桐", "邪恶洛大人", "林克",
    "魔法少女警长", "欢饮明月", "雀", "伊伊姛志", "砂糖的盐酱", "梦月生日"
]

event_list = [
    '0101', '0129', '0212', '0214', '0308', '0401', '0404', '0410', '0501', '0504',
    '0601', '0531', '0701', '0707', '0721', '0801', '0901', '0903', '1001', '1006',
    '1010', '1011', '1101', '1111', '1224', '1225'
]

event_name_list = [
    '元旦节', '春节', '元宵节', '情人节', '妇女节', '愚人节', '清明节', '图书馆纪念日',
    '劳动节', '青年节', '儿童节', '端午节', '建党节', '图书馆纪念日', '0721节', '建军节',
    '开学日', '抗战/反法西斯胜利纪念日', '国庆节', '中秋节', '萌节', '萝莉节',
    '万圣节', '光棍节', '平安夜', '圣诞节'
]

week_list = ["日", "一", "二", "三", "四", "五", "六"]

# 资源路径
_src_path: Optional[str] = None


def set_src_path(path: str):
    """设置资源路径"""
    global _src_path
    _src_path = path


def get_src_path() -> str:
    """获取资源路径"""
    if _src_path is None:
        plugin_dir = Path(__file__).parent.parent.parent
        return str(plugin_dir / "src" / "img" / "icelogin" / "src")
    return _src_path


async def fetch_avatar(url: str) -> bytes:
    """异步获取用户头像"""
    if not url:
        return b''
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as r:
                return await r.read()
    except:
        return b''


def _hash() -> int:
    """生成随机哈希值"""
    days = random.randint(10000000, 99999999)
    return days >> 8


def check_str_len(string: str) -> int:
    """检查字符串的显示长度"""
    len_txt = len(string)
    len_txt_utf8 = len(string.encode('utf-8'))
    return int((len_txt_utf8 - len_txt) / 2 + len_txt)


def luck_choice(which: int) -> int:
    """获取宜忌索引"""
    if which == 0:
        return random.randint(0, len(goodluck) - 1)
    elif which == 1:
        return random.randint(0, len(badluck) - 1)
    return 0


def feed_back(value: int) -> str:
    """根据人品值返回评语"""
    if value == 0:
        return "QAQ梦灵...梦灵不是故意的..."
    elif value < 20:
        return "运势很差呢,摸摸..."
    elif value < 40:
        return "运势欠佳喔,一定会好起来的！"
    elif value < 60:
        return "运势普普通通,不好也不坏噢~"
    elif value < 80:
        return "运势不错~会有什么好事发生吗?"
    elif value < 90:
        return "运势旺盛！今天是个好日子~"
    elif value <= 99:
        return "好运爆棚！一定有好事发生吧！"
    elif value == 100:
        return "100！！今天说不定能发大财！！"
    else:
        return "999！！是隐藏的999运势！！！"


def save_to_local(img: BuildImage, prefix: str) -> bytes:
    """将图片转为 bytes 返回，由调用方根据适配器类型构建消息段"""
    from io import BytesIO
    buf = BytesIO()
    img.markImg.save(buf, format="PNG")
    return buf.getvalue()


async def as_login_v3(uid: int, username: str, qqname: str, nick_flag: int, avatar_url: str = ''):
    """
    生成签到卡片
    
    Args:
        uid: 用户 UID
        username: 用户昵称
        qqname: QQ 昵称
        nick_flag: 是否显示昵称
        avatar_url: 用户头像 URL
    
    Returns:
        Base64 编码的图片 CQ 码
    """
    srcpath = get_src_path()
    
    # 初始化
    festival_msg = ''
    birthday_msg = ''
    extra_msg = ''
    luckygold_msg = ''
    total_get_msg = ''
    
    current_time = time.localtime(time.time())
    days = int(time.strftime("%d", current_time))
    months = int(time.strftime("%m", current_time))
    week = int(time.strftime("%w", current_time))
    
    last_login = money.get_user_money(uid, "last_login") or 0
    gold = 100
    login_flag = 1 if int(f'{months}0{days}') == last_login else 0
    
    # 节日和生日检查
    flag_day = str(days) if days > 9 else f'0{days}'
    flag_month = str(months) if months > 9 else f'0{months}'
    flag = flag_month + flag_day
    
    birth_flag = 0
    event_flag = 0
    
    for i, birth in enumerate(birth_list):
        if flag == birth:
            birth_flag = 1
            birthday_msg = f'{member_list[i]}的生日'
            if login_flag == 0:
                extra_msg += f'☆ 星星+2400(生日)\n☆ 金币+5000(生日)\n'
            break
    
    for i, event in enumerate(event_list):
        if flag == event:
            event_flag = 1
            festival_msg = f'{event_name_list[i]}'
            if login_flag == 0:
                extra_msg += f'☆ 星星+1600(节日)\n☆ 金币+3600(节日)\n'
            break
    
    if not login_flag:
        money.increase_user_money(uid, "logindays", 1)
    
    # 人品值
    h = money.get_user_money(uid, "rp") if login_flag else _hash()
    rp = h % 101
    info = feed_back(rp)
    
    # 宜忌
    good_todo_index = money.get_user_money(uid, "goodluck") if login_flag else luck_choice(0)
    bad_todo_index = money.get_user_money(uid, "badluck") if login_flag else luck_choice(1)
    if good_todo_index == bad_todo_index:
        bad_todo_index = (bad_todo_index + 1) % len(badluck)
    good_luck_msg = goodluck[good_todo_index % len(goodluck)]
    bad_luck_msg = badluck[bad_todo_index % len(badluck)]
    
    # 幸运币
    if 90 <= rp <= 99 and not login_flag:
        luckygold_num = max(1, min(5, rp - 90))
        extra_msg += f'☆ 幸运币+{luckygold_num} (人品)\n'
        luckygold_msg += f'☆ 幸运币+{luckygold_num}\n'
        money.increase_user_money(uid, "luckygold", luckygold_num)
    elif rp == 100 and not login_flag:
        luckygold_num = 10
        extra_msg += f'☆ 幸运币+{luckygold_num} (人品)\n'
        luckygold_msg += f'☆ 幸运币+{luckygold_num}\n'
        money.increase_user_money(uid, "luckygold", luckygold_num)
    elif rp > 100 and not login_flag:
        luckygold_num = 20
        extra_msg += f'☆ 幸运币+{luckygold_num} (人品)\n'
        luckygold_msg += f'☆ 幸运币+{luckygold_num}\n'
        money.increase_user_money(uid, "luckygold", luckygold_num)
    
    gold += rp
    logindays = money.get_user_money(uid, "logindays") or 0
    star_add = min(random.randint(100 + logindays // 5 * 25, 200 + logindays // 5 * 50), 5000)
    gold_add = min(random.randint(50 + logindays // 2 * 5, 100 + logindays // 1 * 5), 2500)
    
    date_msg = f'{months}月{days}日星期{week_list[week]}   已签到{logindays}天'
    
    # 签到奖励
    if login_flag == 0:
        rdint = random.randint(1, 11)
        user_bg = money.get_user_background(uid)
        if user_bg.get('mode', 0) != 2:
            if rdint >= 8:
                money.set_user_background(uid, random.choice(hoshi_bg_list))
                money.set_user_bg_mode(uid, 1)
            else:
                money.set_user_background(uid, random.choice(backgroundList))
                money.set_user_bg_mode(uid, 0)
        
        num = rp * 5 + birth_flag * 2400 + event_flag * 1600 + star_add
        gold += birth_flag * 5000 + event_flag * 3600 + gold_add
        money.increase_user_money(uid, "starstone", num)
        money.increase_user_money(uid, 'gold', gold)
        money.set_user_money(uid, "last_login", int(f'{months}0{days}'))
        money.set_user_money(uid, "rp", h)
        money.set_user_money(uid, "goodluck", good_todo_index)
        money.set_user_money(uid, "badluck", bad_todo_index)
        
        total_get_msg = f'☆ 星星+{num}\n☆ 金币+{gold}\n{luckygold_msg}'
        if logindays >= 10:
            extra_msg += f'☆ 星星+{star_add} (累签)\n☆ 金币+{gold_add} (累签)\n'
    
    # 匿名用户特殊处理
    if uid == 80000000:
        rp = -1
        info = '  Vanitas vanitatum,Et omnia vanitas.'
        good_luck_msg = '宜 取消匿名'
        bad_luck_msg = '忌 匿名'
        date_msg = f'{months}月{days}日星期{week_list[week]}'
        total_get_msg = f'△ 无'
        extra_msg = ''
        login_flag = 0
    
    # ====== 开始绘图 ======
    user_bg = money.get_user_background(uid)
    
    # 背景
    border = 0
    is_bold = False
    
    if user_bg.get('mode', 0) == 2:
        border = 2
        is_bold = True
        user_bg_choose = f"customize/{user_bg.get('custom', 'default.jpg')}"
        imageFile = os.path.join(srcpath, user_bg_choose)
        if not os.path.exists(imageFile):
            imageFile = os.path.join(srcpath, random.choice(backgroundList))
        bg = BuildImage(0, 0, font_size=30, background=os.path.join(srcpath, 'whiteboard.jpg'), font='HYShiGuangTiW_0.ttf')
        try:
            cstm_bg = BuildImage(0, 0, font_size=30, background=imageFile, font='HYShiGuangTiW_0.ttf')
            if cstm_bg.w > cstm_bg.h * 16 / 9:
                cstm_bg.resize(ratio=540 / cstm_bg.h)
            else:
                cstm_bg.resize(ratio=960 / cstm_bg.w)
            bg.paste(cstm_bg, (int(480 - cstm_bg.w / 2), int(270 - cstm_bg.h / 2)), True)
        except:
            pass
        mask_path = os.path.join(srcpath, 'login_background_custom.png')
        if os.path.exists(mask_path):
            mask = BuildImage(0, 0, font_size=30, background=mask_path, font='HYShiGuangTiW_0.ttf')
            bg.paste(mask, (0, 0), True)
    else:
        if user_bg.get('default'):
            user_bg_choose = user_bg['default']
        else:
            user_bg_choose = random.choice(backgroundList)
            money.set_user_background(uid, user_bg_choose)
            money.set_user_bg_mode(uid, 0)
        
        if uid == 80000000:
            user_bg_choose = extra_bg_list[0]
        
        imageFile = os.path.join(srcpath, user_bg_choose)
        if not os.path.exists(imageFile):
            imageFile = os.path.join(srcpath, backgroundList[0])
        bg = BuildImage(0, 0, font_size=30, background=imageFile, font='HYShiGuangTiW_0.ttf')
    
    # 头像
    icon_pasted = False
    if avatar_url:
        try:
            profile_img = await fetch_avatar(avatar_url)
            if profile_img:
                iconFile = io.BytesIO(profile_img)
                icon = BuildImage(0, 0, background=iconFile)
                w, h = icon.size
                icon.resize(ratio=100 / w)
                icon.circle()
                bg.paste(icon, (23, 23), True)
                icon_pasted = True
        except Exception as e:
            pass  # 头像加载失败，跳过

    if not icon_pasted:
        default_icon_path = os.path.join(srcpath, 'default_avatar.jpg')
        if os.path.exists(default_icon_path):
            try:
                icon = BuildImage(0, 0, background=default_icon_path)
                w, h = icon.size
                icon.resize(ratio=100 / w)
                icon.circle()
                bg.paste(icon, (23, 23), True)
            except Exception:
                pass
    
    # 日期+累计签到（上移至y=473以腾出UID显示空间）
    date_text = BuildImage(0, 0, plain_text=date_msg, font_size=30, font='nyan.ttf',
                           font_color=(77, 83, 149), stroke_width=border, stroke_fill=(255, 255, 255))
    bg.paste(date_text, (23, 473), True)
    
    # 左下角显示UID
    uid_text = BuildImage(0, 0, plain_text=f'UID：{uid}', font_size=18, font='yz.ttf',
                          font_color=(77, 83, 149), stroke_width=border, stroke_fill=(255, 255, 255))
    bg.paste(uid_text, (23, 510), True)
    
    # 用户名
    size = check_str_len(qqname)
    if size >= 20:
        final_txt = ''
        for i in qqname:
            final_txt += i
            if check_str_len(final_txt) >= 20:
                break
    else:
        final_txt = qqname
    
    name_text = BuildImage(0, 0, plain_text=final_txt, font_size=30, font='yz.ttf',
                           font_color=(77, 83, 149), stroke_width=border, stroke_fill=(255, 255, 255))
    
    nick_msg = f"欢迎回来，{username}~" if nick_flag else "欢迎回来~"
    if uid == 80000000:
        nick_msg = "......"
    
    nick_text = BuildImage(0, 0, plain_text=nick_msg, font_size=25, font='yz.ttf',
                           font_color=(77, 83, 149), stroke_width=border, stroke_fill=(255, 255, 255))
    bg.paste(name_text, (190, 30), True)
    bg.paste(nick_text, (190, 75), True)
    
    # 节日提醒
    if festival_msg and birthday_msg:
        jieri_msg = f'今天是{festival_msg}和{birthday_msg}~'
    elif festival_msg:
        jieri_msg = f'今天是{festival_msg}~'
    elif birthday_msg:
        jieri_msg = f'今天是{birthday_msg}~'
    else:
        jieri_msg = ''
    
    if jieri_msg:
        jieri_image = BuildImage(0, 0, plain_text=jieri_msg, font_size=30, font='HYShiGuangTiW_0.ttf',
                                 font_color=(77, 83, 149), stroke_width=border, stroke_fill=(255, 255, 255))
        w, h = jieri_image.size
        bg.paste(jieri_image, (int(215 - w / 2), 157), True)
    
    # 运势
    bg.text((49, 259), good_luck_msg, (77, 83, 149), stroke_width=border, stroke_fill=(255, 255, 255))
    bg.text((261, 259), bad_luck_msg, (77, 83, 149), stroke_width=border, stroke_fill=(255, 255, 255))
    
    # 人品值
    if rp < 0:
        rp_colormap = (244, 93, 129)
    elif rp == 0:
        rp_colormap = (100, 100, 100)
    elif rp <= 100:
        rp_colormap = lab2rgb(86, 80 - rp * 1.6, 4)
    else:
        rp_colormap = (68, 118, 244)
    
    rp_number = BuildImage(0, 0, plain_text=str(rp), font_size=60, font='nyan.ttf',
                           font_color=rp_colormap, stroke_width=border, stroke_fill=(255, 255, 255))
    rp_w, rp_h = rp_number.size
    bg.paste(rp_number, (int(215 - rp_w / 2), 356), True)
    
    infoImage = BuildImage(0, 0, plain_text=info, font_size=25, font='HYShiGuangTiW_0.ttf',
                           font_color=rp_colormap, stroke_width=border, stroke_fill=(255, 255, 255))
    info_w, info_h = infoImage.size
    bg.paste(infoImage, (int(215 - info_w / 2), 424), True)
    
    # 额外奖励 & 总计获得
    if not login_flag:
        bg.text((590, 70), extra_msg, (77, 83, 149), stroke_width=2, stroke_fill=(255, 255, 255, 1))
        if extra_msg:
            bonusIconFile = os.path.join(srcpath, 'extra_bonus.png')
            if os.path.exists(bonusIconFile):
                bonus_icon = BuildImage(0, 0, background=bonusIconFile)
                bg.paste(bonus_icon, (551, 7), True)
        
        totalIconFile = os.path.join(srcpath, 'text_block_new.png')
        if os.path.exists(totalIconFile):
            total_bg = BuildImage(0, 0, background=totalIconFile)
            bg.paste(total_bg, (553, 255), True)
        bg.text((618, 338), total_get_msg, (77, 83, 149), stroke_width=2, stroke_fill=(255, 255, 255, 1))
    else:
        # 已签到标记
        if user_bg.get('mode', 0) == 2:
            loginFlagIconFile = os.path.join(srcpath, 'login_flag_custom.png')
        elif user_bg.get('mode', 0) == 1:
            loginFlagIconFile = os.path.join(srcpath, 'login_flag_hoshi.png')
        else:
            loginFlagIconFile = os.path.join(srcpath, 'login_flag.png')
        
        if os.path.exists(loginFlagIconFile):
            login_flag_img = BuildImage(0, 0, background=loginFlagIconFile)
            bg.paste(login_flag_img, (373, 174), True)
    
    # 返回图片
    return save_to_local(bg, "login")


def get_user_gold_rank_str(current_user_id: int) -> str:
    """获取用户金币排名字符串"""
    all_gold_data = money.get_all_user_money('gold')
    if not all_gold_data:
        return ""
    
    ranked_list = [(uid, gold) for uid, gold in all_gold_data.items()]
    if not ranked_list:
        return ""
    
    ranked_list.sort(key=lambda item: item[1], reverse=True)
    
    user_rank = -1
    total_ranked_users = len(ranked_list)
    for i, (uid, gold) in enumerate(ranked_list):
        if uid == current_user_id:
            user_rank = i + 1
            break
    
    if user_rank == -1:
        return "(未参与排名)"
    
    if user_rank <= 50:
        return f"(位于第{user_rank}名)"
    else:
        percentage = (user_rank / total_ranked_users) * 100
        return f"(位于前{percentage:.0f}%)"


async def get_purse(uid: int, user_name: str, guild_flag: int = 0, avatar_url: str = ''):
    """
    生成钱包图片
    
    Args:
        uid: 用户 UID
        user_name: 用户名
        guild_flag: 是否为频道用户
        avatar_url: 用户头像 URL
    
    Returns:
        Base64 编码的图片 CQ 码
    """
    srcpath = get_src_path()
    
    normal_bg_list = ['purse_01.jpg', 'purse_02.jpg', 'purse_05.jpg', 'purse_09.jpg']
    normal_coin_bg = 'purse_03.jpg'
    normal_star_bg = 'purse_04.jpg'
    many_coin_bonus = 'purse_06.jpg'
    no_coin_bouns = 'purse_07.jpg'
    coin_1w_bonus = 'purse_15.jpg'
    coin_2w_bonus = 'purse_20.jpg'
    coin_3w_bonus = 'purse_21.jpg'
    coin_4w_bonus = 'purse_22.jpg'
    many_lucky_bonus = 'purse_08.jpg'
    lucky_100_bonus = 'purse_19.jpg'
    many_star_bouns = 'purse_10.jpg'
    no_star_bonus = 'purse_13.jpg'
    star_10w_bonus = 'purse_14.jpg'
    night_limit_bonus = 'purse_12.jpg'
    heart_bonus = 'purse_16.jpg'
    fish_nonus = 'purse_17.jpg'
    
    font_color = (116, 88, 86)
    
    user_starstone = money.get_user_money(uid, 'starstone') or 0
    user_gold = money.get_user_money(uid, 'gold') or 0
    user_lucky = money.get_user_money(uid, 'luckygold') or 0
    user_kirastone = money.get_user_money(uid, 'kirastone') or 0
    
    choose_list = normal_bg_list[:]
    
    # 根据资产解锁背景
    if user_gold > 300:
        choose_list.append(normal_coin_bg)
    if user_starstone > 15000:
        choose_list.append(normal_star_bg)
    if 25000 < user_starstone < 100000 and random.randint(1, 101) >= 50:
        choose_list.append(many_star_bouns)
    if user_starstone >= 100000:
        choose_list.append(star_10w_bonus)
    if user_starstone < 4000:
        choose_list.append(no_star_bonus)
    if user_gold >= 40000:
        choose_list.append(coin_4w_bonus)
    elif user_gold >= 30000:
        choose_list.append(coin_3w_bonus)
    elif user_gold >= 20000:
        choose_list.append(coin_2w_bonus)
    elif user_gold >= 10000:
        choose_list.append(coin_1w_bonus)
    if 1000 < user_gold < 10000 and random.randint(1, 101) >= 50:
        choose_list.append(many_coin_bonus)
    if user_gold < 75:
        choose_list.append(no_coin_bouns)
    if 20 < user_lucky < 100 and random.randint(1, 101) >= 50:
        choose_list.append(many_lucky_bonus)
    if user_lucky >= 100:
        choose_list.append(lucky_100_bonus)
    
    bonus_point = random.randint(1, 101)
    if bonus_point > 95:
        choose_list.append(heart_bonus)
    elif bonus_point < 6:
        choose_list.append(fish_nonus)
    elif 47 < bonus_point < 53:
        choose_list.append(fish_nonus)
    
    now = datetime.now()
    hour = int(now.strftime('%H'))
    if 1 < hour < 5:
        choose_list.append(night_limit_bonus)
    
    purse_choose = random.choice(choose_list)
    
    if uid == 80000000:
        purse_choose = 'purse_anony.jpg'
        font_color = (255, 255, 255)
        user_starstone = '???'
        user_gold = '???'
        user_lucky = '???'
        user_kirastone = '???'
    
    imageFile = os.path.join(srcpath, purse_choose)
    if not os.path.exists(imageFile):
        imageFile = os.path.join(srcpath, normal_bg_list[0])
    
    bg = BuildImage(0, 0, font_size=30, background=imageFile, font='yz.ttf')
    
    # 头像
    icon_pasted = False
    if avatar_url:
        try:
            profile_img = await fetch_avatar(avatar_url)
            if profile_img:
                iconFile = io.BytesIO(profile_img)
                icon = BuildImage(0, 0, background=iconFile)
                w, h = icon.size
                icon.resize(ratio=80 / w)
                icon.circle()
                bg.paste(icon, (20, 18), True)
                icon_pasted = True
        except Exception as e:
            pass  # 头像加载失败，跳过

    if not icon_pasted:
        default_icon_path = os.path.join(srcpath, 'default_avatar.jpg')
        if os.path.exists(default_icon_path):
            try:
                icon = BuildImage(0, 0, background=default_icon_path)
                w, h = icon.size
                icon.resize(ratio=80 / w)
                icon.circle()
                bg.paste(icon, (20, 18), True)
            except Exception:
                pass
    
    # 昵称
    display_name = user_name[:9] + '...' if len(user_name) >= 10 else user_name
    name_text = BuildImage(0, 0, plain_text=f'{display_name}的钱包', font_size=35, font='yz.ttf', font_color=font_color)
    bg.paste(img=name_text, pos=(122, 25), alpha=True)
    
    # 排名
    rank_str = get_user_gold_rank_str(uid)
    
    # 资产信息
    star_text = BuildImage(0, 0, plain_text=f'星星 {user_starstone}颗', font_size=30, font='yz.ttf', font_color=font_color)
    bg.paste(img=star_text, pos=(160, 128), alpha=True)
    
    gold_text = BuildImage(0, 0, plain_text=f'金币 {user_gold}枚', font_size=30, font='yz.ttf', font_color=font_color)
    bg.paste(img=gold_text, pos=(280, 187), alpha=True)
    
    if rank_str:
        rank_text = BuildImage(0, 0, plain_text=rank_str, font_size=13, font='yz.ttf', font_color=font_color)
        bg.paste(img=rank_text, pos=(350, 190 + gold_text.h), alpha=True)
    
    lucky_text = BuildImage(0, 0, plain_text=f'幸运币 {user_lucky}枚', font_size=30, font='yz.ttf', font_color=font_color)
    bg.paste(img=lucky_text, pos=(100, 245), alpha=True)
    
    kirastone_text = BuildImage(0, 0, plain_text=f'宝石 {user_kirastone}颗', font_size=30, font='yz.ttf', font_color=font_color)
    bg.paste(img=kirastone_text, pos=(420, 78), alpha=True)
    
    # 左下角显示UID
    uid_text = BuildImage(0, 0, plain_text=f'UID：{uid}', font_size=16, font='yz.ttf', font_color=font_color)
    bg.paste(img=uid_text, pos=(20, 290), alpha=True)
    
    # 使用本地文件保存以避免 NTQQ 超时问题
    return save_to_local(bg, "purse")


async def dl_save_image(url: str, uid: int):
    """下载并保存自定义背景图"""
    srcpath = get_src_path()
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            content = await r.read()
            save_path = os.path.join(srcpath, f'customize/{uid}.jpg')
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(content)
    money.set_user_background(uid, f'{uid}.jpg', 'custom')
    money.set_user_bg_mode(uid, mode=2)


def del_custom_bg(uid: int):
    """删除自定义背景图"""
    srcpath = get_src_path()
    custom_path = os.path.join(srcpath, f'customize/{uid}.jpg')
    if os.path.exists(custom_path):
        os.remove(custom_path)
    money.set_user_background(uid, '', 'custom')
    user_bg = money.get_user_background(uid)
    if 'hoshi' in user_bg.get('default', ''):
        money.set_user_bg_mode(uid, mode=1)
    else:
        money.set_user_bg_mode(uid, mode=0)
