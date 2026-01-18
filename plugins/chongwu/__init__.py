"""
宠物插件 - chongwu

完整迁移自旧版 koinoribot
功能：扭蛋、领养、投喂、玩耍、进化、技能、商店
"""

import random
import time
import math
from datetime import datetime
from typing import Optional

from nonebot import on_fullmatch, on_startswith, get_driver
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Event, Bot
from nonebot import logger

from ... import event_adapter
from ... import money
from ...koinori_config import config

from .petconfig import (
    GACHA_REWARDS, GACHA_CONSOLE_PRIZE, GACHA_CONFIG,
    EVOLUTIONS, PET_SHOP_ITEMS, PET_SKILLS,
    GROWTH_STAGE_1, GROWTH_STAGE_2
)
from .pet import (
    set_db_path, init_pet_database,
    get_user_pet, update_user_pet, remove_user_pet, get_user_pets,
    get_user_items, add_user_item, use_user_item,
    get_pet_data, get_status_description, update_pet_status, check_pet_evolution
)

__plugin_meta__ = PluginMetadata(
    name="chongwu",
    description="宠物养成系统 - 完整版",
    usage="宠物帮助 / 开启扭蛋 / 我的宠物 等",
)


# ===== 宠物帮助 =====
pet_help_cmd = on_fullmatch(("宠物帮助", "#宠物帮助", "/宠物帮助"), priority=5, block=True)

# 宠物帮助内容（迁移自old_bot完整版）
pet_help = """
宠物养成系统帮助：
【扭蛋系统】
1. 购买普通/高级/传说扭蛋 [数量] - 购买宠物扭蛋
2. 开启扭蛋 - 开启一个扭蛋(可能获得宠物或安慰奖)
3. 领养宠物 [名字] - 领养扭蛋获得的宠物
4. 放弃宠物 - 放弃扭蛋获得的宠物

【宠物用品】
1. 宠物商店 - 查看可购买的宠物用品
2. 购买 [名称] [数量] - 购买指定宠物用品
3. 退还 [名称] [数量] - 以『50%的价格』退还指定宠物用品
4. 宠物背包 - 查看拥有的宠物用品
5. 投喂 [料理名称] -消耗【对应的料理】
6. 丟玩具球 - 消耗【玩具球】
7. 寻回宠物 - 消耗【最初的契约】
8. 重置进化路线 - 消耗【时之泪】
9. 进化宠物 - 消耗1个 【奶油蛋糕/豪华蛋糕】
10. 补充精力 - 消耗1个 【能量饮料】
11.学习技能 - 消耗1个 【技能药水】（具体请发送 技能帮助）
12.遗忘 [技能名称] - 消耗1个 【遗忘药水】
13.永恒誓约 - 消耗1个 【誓约戒指】

【宠物管理】
1. 我的宠物 - 查看宠物状态
2. 摸摸宠物 - 陪伴宠物（恢复好感）
3. 宠物改名 [新名字] - 为宠物改名
4. 放生宠物 确认 - 放生当前宠物
5. 宠物事件 - 触发宠物的所有技能
6. 技能百科 - 查看可学习的技能列表

【其他】
1. 买宝石 [数量] - 购买宝石
2. 卖宝石 [数量] - 退还宝石
3. 宠物帮助 - 显示本帮助
4. 宠物排行榜 - 查看成长值最高的成年体宠物
5. 宠物排名 - 查看自己宠物的排名

【温馨提醒】
1. 当饱食度或精力值过低时，好感度会迅速下降
2. 当好感度过低时，宠物会离家出走
3. 离家出走期间，宠物将停止长大
4. 排行榜功能需要宠物成长至完全体才能开启


"""

@pet_help_cmd.handle()
async def handle_pet_help(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        
        # 构建转发消息链
        chain = []
        await event_adapter.chain_reply(uevent, chain, pet_help)
        
        # 发送转发消息
        await event_adapter.send_group_forward_msg(uevent, chain)
    except Exception as e:
        logger.error(f"宠物帮助失败: {e}")


# ===== 买宝石 =====
buy_kirastone_cmd = on_startswith(("买宝石", "#买宝石", "/买宝石"), priority=5, block=True)
@buy_kirastone_cmd.handle()
async def handle_buy_kirastone(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        args = uevent.get_args(("买宝石", "#买宝石", "/买宝石")).split()
        if not args or not args[0].isdigit():
            await event_adapter.send_message(uevent, "请指定购买数量，例如：买宝石 1", at_sender=True)
            return
        quantity = int(args[0])
        if quantity <= 0:
            await event_adapter.send_message(uevent, "购买数量必须是正整数！", at_sender=True)
            return
        price_per_gem = 1000
        total_cost = quantity * price_per_gem
        # 检查用户是否有足够的金币
        user_money = money.get_user_money(uid, 'gold')
        if user_money < total_cost:
            await event_adapter.send_message(uevent, f"金币不足！购买{quantity}个宝石需要{total_cost}金币，你只有{user_money}金币。", at_sender=True)
            return

        # 扣除金币并增加宝石
        money.reduce_user_money(uid, 'gold', total_cost)
        money.increase_user_money(uid, 'kirastone', quantity)
        await event_adapter.send_message(uevent, f"你成功购买了{quantity}枚宝石，花费了{total_cost}金币！", at_sender=True)
    except Exception as e:
        logger.error(f"买宝石失败: {e}")

# ===== 卖宝石 =====
sell_kirastone_cmd = on_startswith(("卖宝石", "#卖宝石", "/卖宝石"), priority=5, block=True)
@sell_kirastone_cmd.handle()
async def handle_sell_kirastone(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        args = uevent.get_args(("卖宝石", "#卖宝石", "/卖宝石")).split()
        if not args or not args[0].isdigit():
            await event_adapter.send_message(uevent, "请指定出售数量，例如：卖宝石 1", at_sender=True)
            return
        quantity = int(args[0])
        if quantity <= 0:
            await event_adapter.send_message(uevent, "出售数量必须是正整数！", at_sender=True)
            return
        # 检查用户是否有足够的宝石
        user_gems = money.get_user_money(uid, 'kirastone') or 0
        if user_gems < quantity:
            await event_adapter.send_message(uevent, f"宝石不足！你只有{user_gems}枚宝石，无法出售{quantity}枚。", at_sender=True)
            return

        # 扣除宝石并增加金币
        money.reduce_user_money(uid, 'kirastone', quantity)
        fee = int(quantity * 1000 * config.stone_fee)
        gold_earned = quantity * 1000 - fee
        money.increase_user_money(uid, 'gold', gold_earned)
        await event_adapter.send_message(uevent, f"你成功出售了{quantity}枚宝石，获得了{gold_earned}金币。(已自动扣除{fee}金币手续费)", at_sender=True)
    except Exception as e:
        logger.error(f"卖宝石失败: {e}")

# ===== 开启扭蛋 =====
open_gacha_cmd = on_startswith(("开启", "#开启", "/开启"), priority=5, block=True)

@open_gacha_cmd.handle()
async def handle_open_gacha(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        gacha_name = uevent.get_args(("开启", "#开启", "/开启"))
        if not gacha_name or "扭蛋" not in gacha_name:
            return
        
        if gacha_name not in GACHA_CONFIG:
            await event_adapter.send_message(uevent, f"未知的扭蛋类型，可用: {', '.join(GACHA_CONFIG.keys())}", at_sender=True)
            return
        
        # 检查是否有扭蛋
        if not await use_user_item(uid, gacha_name):
            await event_adapter.send_message(uevent, f"你没有[{gacha_name}]！使用'购买 {gacha_name}'来获取。", at_sender=True)
            return
        
        # 检查用户宠物状态
        pet_data = await get_user_pet(uid)
        if pet_data:
            if "temp_data" in pet_data:
                await add_user_item(uid, gacha_name)
                await event_adapter.send_message(uevent, f"你已有一只宠物({pet_data['type']})等待领养，请先领养或放弃。", at_sender=True)
                return
            else:
                # 已有宠物，只获得安慰奖
                if random.random() < 0.9:
                    money.increase_user_money(uid, 'gold', GACHA_CONSOLE_PRIZE)
                    await event_adapter.send_message(uevent, f"你已经有宠物了，本次扭蛋里没有宠物，获得{GACHA_CONSOLE_PRIZE}金币安慰奖...", at_sender=True)
                else:
                    money.increase_user_money(uid, 'luckygold', 1)
                    await event_adapter.send_message(uevent, "你已经有宠物了，本次扭蛋里没有宠物，但有1枚幸运币...", at_sender=True)
                return
        
        # 抽奖逻辑
        pet_type = None
        pool = None
        
        if gacha_name == "传说扭蛋":
            pool = GACHA_REWARDS["传说"]
        elif gacha_name == "高级扭蛋":
            roll = random.random() * 100
            if roll < 55:
                pool = GACHA_REWARDS["稀有"]
            elif roll < 90:
                pool = GACHA_REWARDS["史诗"]
            else:
                pool = GACHA_REWARDS["传说"]
        else:  # 普通扭蛋
            if random.random() < 0.5:
                if random.random() < 0.8:
                    money.increase_user_money(uid, 'gold', GACHA_CONSOLE_PRIZE)
                    await event_adapter.send_message(uevent, f"扭蛋里没有宠物，获得{GACHA_CONSOLE_PRIZE}金币安慰奖...", at_sender=True)
                else:
                    money.increase_user_money(uid, 'luckygold', 1)
                    await event_adapter.send_message(uevent, "扭蛋里没有宠物，但有1枚幸运币...", at_sender=True)
                return
            
            roll = random.random() * 100
            if roll < 55:
                pool = GACHA_REWARDS["普通"]
            elif roll < 80:
                pool = GACHA_REWARDS["稀有"]
            elif roll < 98:
                pool = GACHA_REWARDS["史诗"]
            else:
                pool = GACHA_REWARDS["传说"]
        
        if pool:
            pet_type = random.choices(list(pool.keys()), weights=list(pool.values()))[0]
        
        if pet_type:
            temp_pet = {
                "type": pet_type,
                "temp_data": True,
                "gacha_time": time.time()
            }
            await update_user_pet(uid, temp_pet)
            pet_data = get_pet_data()
            rarity = pet_data[pet_type]["rarity"]
            await event_adapter.send_message(uevent, 
                f"🎉 恭喜！从[{gacha_name}]中抽中了{rarity}宠物【{pet_type}】！\n"
                f"请使用'领养宠物 [名字]'来领养它，或使用'放弃宠物'放弃。", at_sender=True)
        else:
            money.increase_user_money(uid, 'gold', GACHA_CONSOLE_PRIZE)
            await event_adapter.send_message(uevent, f"很遗憾，没有抽中宠物，获得{GACHA_CONSOLE_PRIZE}金币安慰奖！", at_sender=True)
            
    except Exception as e:
        logger.error(f"开启扭蛋失败: {e}")


# ===== 领养宠物 =====
adopt_cmd = on_startswith(("领养宠物", "#领养宠物", "/领养宠物"), priority=5, block=True)

@adopt_cmd.handle()
async def handle_adopt(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        pet_name = uevent.get_args(("领养宠物", "#领养宠物", "/领养宠物"))
        
        if not pet_name:
            await event_adapter.send_message(uevent, "请为你的宠物取个名字！\n例如：领养宠物 小白", at_sender=True)
            return
        
        if len(pet_name) > 10:
            await event_adapter.send_message(uevent, "宠物名字太长了，最多10个字符！", at_sender=True)
            return
        
        temp_pet = await get_user_pet(uid)
        if not temp_pet or not temp_pet.get("temp_data"):
            await event_adapter.send_message(uevent, "你没有待领养的宠物，不妨试试开启扭蛋获取一个？", at_sender=True)
            return
        
        # 检查名字是否已存在
        user_pets = await get_user_pets()
        for other_uid, pet in user_pets.items():
            if pet.get("name") == pet_name and other_uid != uid:
                await event_adapter.send_message(uevent, f"名字'{pet_name}'已被使用，请换一个！", at_sender=True)
                return
        
        pet_type = temp_pet["type"]
        pet_data = get_pet_data()
        base_pet = pet_data[pet_type]

        new_pet = {
            "type": pet_type,
            "name": pet_name,
            "hunger": base_pet["max_hunger"],
            "energy": base_pet["max_energy"],
            "happiness": base_pet["max_happiness"],
            "max_hunger": base_pet["max_hunger"],
            "max_energy": base_pet["max_energy"],
            "max_happiness": base_pet["max_happiness"],
            "growth": 0,
            "growth_rate": base_pet["growth_rate"],
            "stage": 0,
            "growth_required": GROWTH_STAGE_1,
            "last_event_date": None,
            "skills": [],
            "runaway": False,
            "last_update": time.time(),
            "adopted_time": time.time()
        }
        
        await update_user_pet(uid, new_pet)
        await event_adapter.send_message(uevent, f"🎉 恭喜！你成功领养了一只{pet_name}({pet_type})！", at_sender=True)
        
    except Exception as e:
        logger.error(f"领养宠物失败: {e}")


# ===== 放弃宠物 =====
cancel_adopt_cmd = on_fullmatch(("放弃宠物", "#放弃宠物", "/放弃宠物"), priority=5, block=True)

@cancel_adopt_cmd.handle()
async def handle_cancel_adopt(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        temp_pet = await get_user_pet(uid)
        if not temp_pet or not temp_pet.get("temp_data"):
            await event_adapter.send_message(uevent, "你没有待领养的宠物！", at_sender=True)
            return
        
        pet_type = temp_pet["type"]
        await remove_user_pet(uid)
        await event_adapter.send_message(uevent, f"你放弃了一只{pet_type}。", at_sender=True)
        
    except Exception as e:
        logger.error(f"放弃宠物失败: {e}")


# ===== 我的宠物 =====
my_pet_cmd = on_fullmatch(("我的宠物", "#我的宠物", "/我的宠物"), priority=5, block=True)

@my_pet_cmd.handle()
async def handle_my_pet(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        pet = await get_user_pet(uid)
        if not pet:
            await event_adapter.send_message(uevent, "你还没有宠物！使用'开启 普通扭蛋'来获取一个吧~", at_sender=True)
            return
        
        if pet.get("temp_data"):
            await event_adapter.send_message(uevent, f"你有一只待领养的{pet['type']}，请使用'领养宠物 [名字]'来领养！", at_sender=True)
            return
        
        pet = await update_pet_status(pet)
        await update_user_pet(uid, pet)
        
        stage_names = ["幼年体", "成长体", "成年体"]
        stage_name = stage_names[min(pet["stage"], 2)]
        
        hunger_desc = get_status_description("hunger", pet["hunger"])
        energy_desc = get_status_description("energy", pet["energy"])
        happiness_desc = get_status_description("happiness", pet["happiness"])
        
        skills_str = "、".join(pet.get("skills", [])) or "暂无"
        
        status_emoji = "🏃" if pet.get("runaway") else "🐾"
        
        # 格式化领养日期
        adopted_time = pet.get("adopted_time")
        if adopted_time:
            adopted_date = datetime.fromtimestamp(adopted_time).strftime("%Y-%m-%d")
        else:
            adopted_date = "未知"
        
        # 检查是否已誓约（状态值无限大）
        status = min(pet["max_hunger"], pet["max_happiness"], pet["max_energy"])
        if status > 999999:
            # 已誓约时显示特殊状态
            if pet["stage"] == 2:
                growth_str = f'{pet["growth"]:.1f}'
            else:
                growth_str = f'{pet["growth"]:.1f}/{pet["growth_required"]}'
            msg = f"""
━━━━━━━━━━
名称: {pet['name']}
类型: {pet['type']} ({stage_name})
饱食度: 『满足』
精力: 『活泼』
好感度: 『爱慕』
成长值: {growth_str}
技能: {skills_str}
领养日期: {adopted_date}
请好好照顾她哦，也可以发送 宠物帮助 来查看全部指令~"""
        else:
            msg = f"""
━━━━━━━━━━
名称: {pet['name']}
类型: {pet['type']} ({stage_name})
饱食度: {pet['hunger']:.1f}/{pet['max_hunger']} ({hunger_desc})
精力: {pet['energy']:.1f}/{pet['max_energy']} ({energy_desc})
好感度: {pet['happiness']:.1f}/{pet['max_happiness']} ({happiness_desc})
成长值: {pet['growth']:.1f}/{pet['growth_required']}
技能: {skills_str}
领养日期: {adopted_date}
请好好照顾她哦，也可以发送 宠物帮助 来查看全部指令~"""
        
        if pet.get("runaway"):
            msg += "\n\n⚠️ 宠物已离家出走！使用'寻回宠物'找回~"
        
        await event_adapter.send_message(uevent, msg, at_sender=True)
        
    except Exception as e:
        logger.error(f"查看宠物失败: {e}")


# ===== 宠物商店 =====
shop_cmd = on_fullmatch(("宠物商店", "#宠物商店", "/宠物商店"), priority=5, block=True)

@shop_cmd.handle()
async def handle_shop(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        
        item_list = []
        for name, info in PET_SHOP_ITEMS.items():
            price = info["price"]
            effect = info.get("effect", "")
            item_list.append(f"• {name} - {price}宝石 ({effect})")
        
        msg = "🏪 宠物商店\n━━━━━━━━━━\n" + "\n".join(item_list)
        msg += "\n\n使用: 购买 物品名 [数量]"
        
        await event_adapter.send_message(uevent, msg)
        
    except Exception as e:
        logger.error(f"宠物商店失败: {e}")


# ===== 购买 =====
buy_cmd = on_startswith(("购买", "#购买", "/购买"), priority=5, block=True)

@buy_cmd.handle()
async def handle_buy(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        args = uevent.get_args(("购买", "#购买", "/购买")).split()
        if not args:
            return
        
        item_name = args[0]
        try:
            quantity = int(args[1]) if len(args) > 1 else 1
            if quantity <= 0:
                await event_adapter.send_message(uevent, "购买数量必须是正整数！", at_sender=True)
                return
        except ValueError:
            await event_adapter.send_message(uevent, "购买数量必须是有效的数字！", at_sender=True)
            return
        
        if item_name not in PET_SHOP_ITEMS:
            return
        
        price = PET_SHOP_ITEMS[item_name]["price"] * quantity
        user_stones = money.get_user_money(uid, 'kirastone') or 0
        
        if user_stones < price:
            await event_adapter.send_message(uevent, f"宝石不足！购买{quantity}个{item_name}需要{price}宝石，你只有{user_stones}宝石。", at_sender=True)
            return
        
        if money.reduce_user_money(uid, 'kirastone', price):
            await add_user_item(uid, item_name, quantity)
            await event_adapter.send_message(uevent, f"✅ 成功购买了{quantity}个{item_name}！", at_sender=True)
        else:
            await event_adapter.send_message(uevent, "购买失败，请稍后再试！", at_sender=True)
            
    except Exception as e:
        logger.error(f"购买失败: {e}")


# ===== 宠物背包 =====
pet_bag_cmd = on_fullmatch(("宠物背包", "#宠物背包", "/宠物背包"), priority=5, block=True)

@pet_bag_cmd.handle()
async def handle_pet_bag(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        user_items = await get_user_items(uid)
        
        if not user_items:
            await event_adapter.send_message(uevent, "你目前没有宠物用品。使用'购买'来获取。", at_sender=True)
            return
        
        item_list = [f"• {name} ×{count}" for name, count in user_items.items()]
        msg = "🎒 宠物背包\n━━━━━━━━━\n" + "\n".join(item_list)
        
        await event_adapter.send_message(uevent, msg, at_sender=True)
        
    except Exception as e:
        logger.error(f"宠物背包失败: {e}")


# ===== 退还宠物用品 =====
return_item_cmd = on_startswith(("退还", "#退还", "/退还"), priority=5, block=True)

@return_item_cmd.handle()
async def handle_return_item(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        args = uevent.get_args(("退还", "#退还", "/退还")).split()
        
        # 检查参数
        if not args:
            return
        
        item_name = args[0]
        if item_name not in PET_SHOP_ITEMS:
            return
        
        user_items = await get_user_items(uid)
        count = user_items.get(item_name, 0)
        
        try:
            quantity = int(args[1]) if len(args) > 1 else 1
            if quantity <= 0:
                await event_adapter.send_message(uevent, "退还数量必须是正整数！", at_sender=True)
                return
            if count < quantity:
                await event_adapter.send_message(uevent, f"你当前只有{count}个{item_name}！", at_sender=True)
                return
        except ValueError:
            await event_adapter.send_message(uevent, "退还数量必须是有效的数字！", at_sender=True)
            return
        
        # 计算退还价格（50%）
        return_fee = getattr(config, 'return_item_fee', 0.5)
        price = int(PET_SHOP_ITEMS[item_name]["price"] * quantity * return_fee)
        fee_percent = int(return_fee * 100)
        
        if await use_user_item(uid, item_name, quantity):
            money.increase_user_money(uid, 'kirastone', price)
            await event_adapter.send_message(uevent, 
                f"按照{fee_percent}%的价格成功退还了{quantity}个{item_name}！\n你获得了{price}个宝石。", at_sender=True)
        else:
            await event_adapter.send_message(uevent, "操作失败，请稍后再试！", at_sender=True)
            
    except Exception as e:
        logger.error(f"退还宠物用品失败: {e}")


# ===== 投喂 =====
feed_cmd = on_startswith(("投喂", "#投喂", "/投喂"), priority=5, block=True)

@feed_cmd.handle()
async def handle_feed(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        food_type = uevent.get_args(("投喂", "#投喂", "/投喂"))
        
        valid_foods = {"普通料理", "高级料理", "豪华料理"}
        if food_type not in valid_foods:
            await event_adapter.send_message(uevent, "请指定正确的食物：普通/高级/豪华料理\n例如：投喂 高级料理", at_sender=True)
            return
        
        if not await use_user_item(uid, food_type):
            await event_adapter.send_message(uevent, f"你没有{food_type}！", at_sender=True)
            return
        
        pet = await get_user_pet(uid)
        if not pet or pet.get("temp_data"):
            await add_user_item(uid, food_type)
            await event_adapter.send_message(uevent, "你还没有宠物！", at_sender=True)
            return
        
        pet = await update_pet_status(pet)
        if pet.get("runaway"):
            await add_user_item(uid, food_type)
            await event_adapter.send_message(uevent, f"你的宠物【{pet['name']}】离家出走了，无法投喂！", at_sender=True)
            return
        
        item = PET_SHOP_ITEMS[food_type]
        pet["hunger"] = min(pet["max_hunger"], pet["hunger"] + item["hunger"])
        pet["energy"] = min(pet["max_energy"], pet["energy"] + item["energy"])
        pet["happiness"] = min(pet["max_happiness"], pet["happiness"] + item["happiness"])
        pet["growth"] = min(pet["growth_required"], pet["growth"] + item["growth"])
        
        await update_user_pet(uid, pet)
        
        await event_adapter.send_message(uevent, 
            f"你给{pet['name']}投喂了{food_type}！\n"
            f"饱食度+{item['hunger']} 精力+{item['energy']} "
            f"好感度+{item['happiness']} 成长值+{item['growth']}", at_sender=True)
        
    except Exception as e:
        logger.error(f"投喂失败: {e}")


# ===== 摸摸宠物 =====
pat_cmd = on_fullmatch(("摸摸宠物", "#摸摸宠物", "/摸摸宠物"), priority=5, block=True)

@pat_cmd.handle()
async def handle_pat(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        pet = await get_user_pet(uid)
        if not pet or pet.get("temp_data"):
            await event_adapter.send_message(uevent, "你还没有宠物！", at_sender=True)
            return
        
        pet = await update_pet_status(pet)
        
        if pet["energy"] < 20:
            await event_adapter.send_message(uevent, f"{pet['name']}太累了，需要休息！", at_sender=True)
            return
        
        pet["energy"] = max(0, pet["energy"] - 5)
        pet["happiness"] = min(pet["max_happiness"], pet["happiness"] + 15)
        await update_user_pet(uid, pet)
        
        await event_adapter.send_message(uevent, 
            f"{pet['name']}很享受你的抚摸，用脸蛋轻轻蹭了蹭你的手...\n精力-5 好感+15", at_sender=True)
        
    except Exception as e:
        logger.error(f"摸摸宠物失败: {e}")


# ===== 补充精力 =====
energy_cmd = on_fullmatch(("补充精力", "#补充精力", "/补充精力"), priority=5, block=True)

@energy_cmd.handle()
async def handle_energy(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        if not await use_user_item(uid, "能量饮料"):
            await event_adapter.send_message(uevent, "你没有能量饮料！", at_sender=True)
            return
        
        pet = await get_user_pet(uid)
        if not pet or pet.get("temp_data"):
            await add_user_item(uid, "能量饮料")
            await event_adapter.send_message(uevent, "你还没有宠物！", at_sender=True)
            return
        
        pet = await update_pet_status(pet)
        if pet.get("runaway"):
            await add_user_item(uid, "能量饮料")
            await event_adapter.send_message(uevent, f"你的宠物【{pet['name']}】离家出走了！", at_sender=True)
            return
        
        item = PET_SHOP_ITEMS["能量饮料"]
        pet["energy"] = min(pet["max_energy"], pet["energy"] + item["energy"])
        pet["happiness"] = min(pet["max_happiness"], pet["happiness"] + item["happiness"])
        
        await update_user_pet(uid, pet)
        await event_adapter.send_message(uevent, 
            f"你给{pet['name']}喝了能量饮料，它立刻精神焕发！\n精力+{item['energy']} 好感+{item['happiness']}", at_sender=True)
        
    except Exception as e:
        logger.error(f"补充精力失败: {e}")


# ===== 学习技能 =====
learn_skill_cmd = on_fullmatch(("学习技能", "#学习技能", "/学习技能"), priority=5, block=True)

@learn_skill_cmd.handle()
async def handle_learn_skill(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        if not await use_user_item(uid, "技能药水"):
            await event_adapter.send_message(uevent, "你没有技能药水！购买需要50宝石。", at_sender=True)
            return
        
        pet = await get_user_pet(uid)
        if not pet or pet.get("temp_data"):
            await add_user_item(uid, "技能药水")
            await event_adapter.send_message(uevent, "你还没有宠物！", at_sender=True)
            return
        
        pet = await update_pet_status(pet)
        if pet.get("runaway"):
            await add_user_item(uid, "技能药水")
            await event_adapter.send_message(uevent, f"你的宠物【{pet['name']}】离家出走了！", at_sender=True)
            return
        
        available_skills = [s for s in PET_SKILLS.keys() if s not in pet.get("skills", [])]
        if not available_skills:
            await event_adapter.send_message(uevent, f"你的宠物已学会所有技能！", at_sender=True)
            return
        
        max_skills = 1 + pet["stage"] * 2
        # 检查是否已誓约（状态值无限大）
        status = min(pet["max_hunger"], pet["max_happiness"], pet["max_energy"])
        if status > 999999:
            max_skills += 999
        if len(pet.get("skills", [])) >= max_skills:
            await add_user_item(uid, "技能药水")
            await event_adapter.send_message(uevent, f"技能槽已满（当前最多{max_skills}个）！", at_sender=True)
            return
        
        if random.random() < 0.6:
            new_skill = random.choice(available_skills)
            if "skills" not in pet:
                pet["skills"] = []
            pet["skills"].append(new_skill)
            await update_user_pet(uid, pet)
            await event_adapter.send_message(uevent, 
                f"🎉 {pet['name']}学会了【{new_skill}】！\n效果：{PET_SKILLS[new_skill]['description']}", at_sender=True)
        else:
            await event_adapter.send_message(uevent, "学习失败了...技能药水已消耗。", at_sender=True)
        
    except Exception as e:
        logger.error(f"学习技能失败: {e}")


# ===== 宠物事件 =====
pet_event_cmd = on_fullmatch(("宠物事件", "#宠物事件", "/宠物事件"), priority=5, block=True)

@pet_event_cmd.handle()
async def handle_pet_event(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        now_date = datetime.now().date()
        
        pet = await get_user_pet(uid)
        if not pet or pet.get("temp_data"):
            await event_adapter.send_message(uevent, "你还没有宠物！", at_sender=True)
            return
        
        pet = await update_pet_status(pet)
        if pet.get("runaway"):
            await event_adapter.send_message(uevent, f"你的宠物【{pet['name']}】离家出走了！", at_sender=True)
            return
        
        # 检查今日是否已触发
        last_event = pet.get("last_event_date")
        if last_event:
            try:
                if isinstance(last_event, str):
                    last_date = datetime.strptime(last_event, "%Y-%m-%d").date()
                else:
                    last_date = datetime.fromtimestamp(last_event).date()
                if last_date == now_date:
                    await event_adapter.send_message(uevent, "今天已触发过宠物事件了，明天再来！", at_sender=True)
                    return
            except:
                pass
        
        if not pet.get("skills"):
            await event_adapter.send_message(uevent, f"{pet['name']}还没学会任何技能！", at_sender=True)
            return
        
        results = []
        for skill_name in pet["skills"]:
            try:
                if skill_name == "宝石爱好者":
                    amount = random.randint(1, 20)
                    money.increase_user_money(uid, 'kirastone', amount)
                    results.append(f"💎 捡回了{amount}枚宝石")
                elif skill_name == "盼望长大":
                    pet['growth'] = min(pet.get('growth_required', math.inf), pet['growth'] + 10)
                    results.append("📈 成长值+10")
                elif skill_name == "金币爱好者":
                    amount = random.randint(1000, 20000)
                    money.increase_user_money(uid, 'gold', amount)
                    results.append(f"💰 捡回了{amount}金币")
                elif skill_name == "幸运星":
                    amount = random.randint(5, 7)
                    money.increase_user_money(uid, 'luckygold', amount)
                    results.append(f"🍀 幸运币+{amount}")
                elif skill_name == "卖萌":
                    amount = random.randint(100, 2000)
                    money.increase_user_money(uid, 'starstone', amount)
                    results.append(f"⭐ 星星+{amount}")
                elif skill_name == "美食家":
                    food = random.choice(["普通料理", "高级料理", "豪华料理", "能量饮料"])
                    await add_user_item(uid, food)
                    results.append(f"🍱 获得{food}")
                elif skill_name == "自我管理":
                    enum = random.randint(10, 80)
                    hnum = random.randint(10, 80)
                    pet["energy"] = min(pet["max_energy"], pet["energy"] + enum)
                    pet["happiness"] = min(pet["max_happiness"], pet["happiness"] + hnum)
                    results.append(f"💪 精力+{enum} 好感+{hnum}")
                elif skill_name == "捕鱼达人":
                    buff = 2 if "猫" in pet["type"] else 1
                    add_count = random.randint(1, 5) * 100 * (3 ** pet["stage"]) * buff
                    results.append(f"🎣 钓鱼次数+{add_count}")
            except Exception as e:
                results.append(f"【{skill_name}】发动失败")
        
        pet["last_event_date"] = now_date.strftime("%Y-%m-%d")
        await update_user_pet(uid, pet)
        
        msg = f"🐾 {pet['name']}今天的事件：\n" + "\n".join(results)
        await event_adapter.send_message(uevent, msg, at_sender=True)
        
    except Exception as e:
        logger.error(f"宠物事件失败: {e}")


# ===== 宠物进化 =====
evolve_cmd = on_fullmatch(("宠物进化", "#宠物进化", "/宠物进化"), priority=5, block=True)

@evolve_cmd.handle()
async def handle_evolve(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        pet = await get_user_pet(uid)
        if not pet or pet.get("temp_data"):
            await event_adapter.send_message(uevent, "你还没有宠物！", at_sender=True)
            return
        
        pet = await update_pet_status(pet)
        
        if pet["stage"] == 0 and pet["growth"] >= pet.get("growth_required", 100):
            if not await use_user_item(uid, "奶油蛋糕"):
                await event_adapter.send_message(uevent, "进化需要奶油蛋糕！", at_sender=True)
                return
            
            if random.random() < 0.4:
                await event_adapter.send_message(uevent, f"很可惜，{pet['name']}进化失败了...", at_sender=True)
                return
            
            evolution_options = EVOLUTIONS.get(pet["type"], {})
            if isinstance(evolution_options, dict):
                evolution_choice = random.choice(list(evolution_options.keys()))
                new_type = evolution_options[evolution_choice]
                pet["type"] = new_type
                pet["stage"] = 1
                pet["growth"] = 0
                pet["growth_required"] = GROWTH_STAGE_2
                await update_user_pet(uid, pet)
                await event_adapter.send_message(uevent, f"🎉 {pet['name']}成功进化为【{new_type}】！", at_sender=True)
            else:
                await event_adapter.send_message(uevent, "进化路线有误！", at_sender=True)
                
        elif pet["stage"] == 1 and pet["growth"] >= pet.get("growth_required", 200):
            if not await use_user_item(uid, "豪华蛋糕"):
                await event_adapter.send_message(uevent, "进化需要豪华蛋糕！", at_sender=True)
                return
            
            if random.random() < 0.4:
                await event_adapter.send_message(uevent, f"很可惜，{pet['name']}进化失败了...", at_sender=True)
                return
            
            new_type = EVOLUTIONS.get(pet["type"])
            if new_type and isinstance(new_type, str):
                pet["type"] = new_type
                pet["stage"] = 2
                pet["growth"] = 0
                pet["growth_required"] = math.inf
                await update_user_pet(uid, pet)
                await event_adapter.send_message(uevent, f"🎉 {pet['name']}成功进化为【{new_type}】！", at_sender=True)
            else:
                await event_adapter.send_message(uevent, "进化路线有误！", at_sender=True)
        else:
            await event_adapter.send_message(uevent, 
                f"{pet['name']}还不满足进化条件（成长值需达到上限）", at_sender=True)
        
    except Exception as e:
        logger.error(f"宠物进化失败: {e}")


# ===== 宠物改名 =====
rename_cmd = on_startswith(("宠物改名", "#宠物改名", "/宠物改名"), priority=5, block=True)

@rename_cmd.handle()
async def handle_rename(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        new_name = uevent.get_args(("宠物改名", "#宠物改名", "/宠物改名"))
        
        if not new_name:
            await event_adapter.send_message(uevent, "请提供新名字！例如：宠物改名 小黑", at_sender=True)
            return
        
        if len(new_name) > 10:
            await event_adapter.send_message(uevent, "名字太长了，最多10个字符！", at_sender=True)
            return
        
        pet = await get_user_pet(uid)
        if not pet or pet.get("temp_data"):
            await event_adapter.send_message(uevent, "你还没有宠物！", at_sender=True)
            return
        
        old_name = pet["name"]
        pet["name"] = new_name
        await update_user_pet(uid, pet)
        await event_adapter.send_message(uevent, f"成功将'{old_name}'改名为'{new_name}'！", at_sender=True)
        
    except Exception as e:
        logger.error(f"宠物改名失败: {e}")


# ===== 寻回宠物 =====
retrieve_cmd = on_fullmatch(("寻回宠物", "#寻回宠物", "/寻回宠物"), priority=5, block=True)

@retrieve_cmd.handle()
async def handle_retrieve(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        if not await use_user_item(uid, "最初的契约"):
            await event_adapter.send_message(uevent, "你没有最初的契约！", at_sender=True)
            return
        
        pet = await get_user_pet(uid)
        if not pet or pet.get("temp_data"):
            await add_user_item(uid, "最初的契约")
            await event_adapter.send_message(uevent, "你还没有宠物！", at_sender=True)
            return
        
        pet = await update_pet_status(pet)
        if not pet.get("runaway"):
            await add_user_item(uid, "最初的契约")
            await event_adapter.send_message(uevent, "你的宠物没有离家出走！", at_sender=True)
            return
        
        pet["runaway"] = False
        pet["happiness"] = pet["max_happiness"] * 0.3
        pet["hunger"] = pet["max_hunger"] * 0.3
        pet["energy"] = pet["max_energy"] * 0.3
        pet["last_update"] = time.time()
        
        await update_user_pet(uid, pet)
        await event_adapter.send_message(uevent, f"你找回了{pet['name']}，这一次，一定要好好珍惜哦~", at_sender=True)
        
    except Exception as e:
        logger.error(f"寻回宠物失败: {e}")


# ===== 永恒誓约 =====
oath_cmd = on_fullmatch(("永恒誓约", "#永恒誓约", "/永恒誓约"), priority=5, block=True)

@oath_cmd.handle()
async def handle_eternal_oath(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        uid = uevent.uid
        
        pet = await get_user_pet(uid)
        if not pet or pet.get("temp_data"):
            await event_adapter.send_message(uevent, "你还没有宠物！", at_sender=True)
            return
        
        pet = await update_pet_status(pet)
        
        # 检查是否已经誓约
        status = min(pet["max_hunger"], pet["max_happiness"], pet["max_energy"])
        if status > 999999:
            msg = f'\n{pet["name"]}有些害羞地看向你...\n“那种事情...不是已经做过了吗...”'
            await event_adapter.send_message(uevent, msg, at_sender=True)
            return
        
        # 检查是否是成年体
        if pet.get("stage") != 2:
            msg = f'\n{pet["name"]}有些害羞的看着你...\n“hentai！人家...还没成年呢。”'
            await event_adapter.send_message(uevent, msg, at_sender=True)
            return
        
        # 检查是否离家出走
        if pet.get("runaway"):
            await event_adapter.send_message(uevent, f"{pet['name']}已经离家出走了！使用'最初的契约'可以寻回它。", at_sender=True)
            return
        
        # 检查是否有誓约戒指
        if not await use_user_item(uid, "誓约戒指"):
            msg = f'\n{pet["name"]}有些失落地看着你...\n“那种事情...没有戒指怎么行...”'
            await event_adapter.send_message(uevent, msg, at_sender=True)
            return
        
        # 誓约效果
        pet["energy"] = math.inf
        pet["happiness"] = math.inf
        pet["hunger"] = math.inf
        pet["max_happiness"] = math.inf
        pet["max_energy"] = math.inf
        pet["max_hunger"] = math.inf
        pet["growth"] = pet.get("growth", 0) + 1000
        pet["growth_rate"] = round(pet.get("growth_rate", 1.0) * 1.1, 2)
        
        await update_user_pet(uid, pet)
        msg = (f'\n成长值+1000\n基础成长速度+10%\n最大技能数量+999\n\n'
               f'{pet["name"]}有些害羞的看着你，乖巧地等你为她戴上戒指，最后轻轻在你额头上落下一吻...\n'
               f'“以后...不许丢下我。”')
        await event_adapter.send_message(uevent, msg, at_sender=True)
        
    except Exception as e:
        logger.error(f"永恒誓约失败: {e}")


# ===== 技能帮助 =====
skill_help_cmd = on_fullmatch(("技能帮助", "#技能帮助", "/技能帮助"), priority=5, block=True)

# 生成技能帮助内容
skill_list = []
for skill_name, skill_info in PET_SKILLS.items():
    skill_list.append(f'"{skill_name}": {skill_info["description"]}')

pet_skill = f"""幼年体/成长体/成年体可学习1/3/5个技能
指令：
学习技能 （消耗1个技能药水）
遗忘技能 技能名称 （消耗1个遗忘药水） 
可学习的技能一览：
{chr(10).join(skill_list)}"""

@skill_help_cmd.handle()
async def handle_skill_help(event: Event, bot: Bot):
    try:
        uevent = await event_adapter.adapt_event(event, bot)
        
        # 构建转发消息链
        chain = []
        await event_adapter.chain_reply(uevent, chain, pet_skill)
        
        # 发送转发消息
        await event_adapter.send_group_forward_msg(uevent, chain)
    except Exception as e:
        logger.error(f"技能帮助失败: {e}")


# ===== 初始化 =====
driver = get_driver()

@driver.on_startup
async def init_chongwu():
    """初始化宠物插件"""
    from pathlib import Path
    plugin_dir = Path(__file__).parent.parent.parent
    db_path = plugin_dir / "src" / "database" / "koinoribot.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    set_db_path(str(db_path))
    init_pet_database()
    logger.info("Chongwu 宠物插件初始化完成")
