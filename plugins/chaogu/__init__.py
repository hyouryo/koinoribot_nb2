"""
炒股插件 - chaogu

完整迁移自旧版 koinoribot
功能：股票交易、行情查看、持仓管理、市场事件
"""

import math
import random
import time
import asyncio
import gc
import base64
from datetime import datetime, timedelta
from typing import Optional, Dict

from nonebot import on_command, on_regex, get_driver, require
from nonebot.exception import FinishedException
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Event, Bot
from nonebot.params import Depends, RegexGroup
from nonebot import logger

from ... import money
from ...koinori_config import config
from ...tools import get_uid, send_group_forward_msg, build_forward_chain

from .stock_utils import (
    set_db_path, init_stock_database,
    STOCKS, MARKET_EVENTS, MANUAL_EVENT_TYPES, HISTORY_DURATION_HOURS,
    get_stock_data, save_stock_data,
    get_user_portfolios, save_user_portfolios,
    get_user_portfolio, update_user_portfolio,
    get_current_stock_price, get_stock_price_history,
    generate_stock_chart
)

__plugin_meta__ = PluginMetadata(
    name="chaogu",
    description="股票市场系统 - 完整版",
    usage="股票列表 / 买入 / 卖出 / 我的股仓 等",
)

# 事件触发概率配置
EVENT_PROBABILITY = 0.9999
EVENT_COOLDOWN = 3500


# ===== 股票帮助 =====
stock_help_cmd = on_command("股票帮助", priority=5, block=True)

# 炒股帮助内容（迁移自old_bot完整版）
help_chaogu = '''炒股游戏帮助：

温馨提醒：股市有风险，切莫上头。

**指令列表：**
1.  股票列表：查看所有股票的名字和实时价格
2.  买入 [股票名称] [具体数量]：例如：买入 萝莉股 10
3.  卖出 [股票名称] [具体数量]：例如：卖出 萝莉股 10
4.  我的股仓：查看自己现在持有的股票
5.  [股票名称]走势：查看某一股票的价格折线图走势（会炸内存，慎用），例如：萝莉股走势
6.  市场动态/股市新闻/市场事件：查看最近市场上的事件，可能利好或利空
初始股票价格：
    "萝莉股": 50.0,
    "猫娘股": 60.0,
    "魔法少女股": 70.0,
    "梦月股": 250.0,
    "梦馨股": 100.0,
    "高达股": 40.0,
    "雾月股": 120.0,
    "傲娇股": 60.0,
    "病娇股": 30.0,
    "梦灵股": 120.0,
    "铃音股": 110.0,
    "音祈股": 500.0,
    "梦铃股": 250.0,
    "姐妹股": 250.0,
    "橘馨股": 250.0,
    "白芷股": 250.0,
    "雾织股": 250.0,
    "筑梦股": 250.0,
    "摇篮股": 250.0,
    "筑梦摇篮股": 500.0,
'''

@stock_help_cmd.handle()
async def handle_stock_help(event: Event, bot: Bot):
    # 构建转发消息链
    chain = await build_forward_chain(bot, [help_chaogu])
    # 发送转发消息
    await send_group_forward_msg(event, bot, chain)


# ===== 股票列表 =====
stock_list_cmd = on_command("股票列表", priority=5, block=True)

@stock_list_cmd.handle()
async def handle_stock_list(event: Event, bot: Bot):
    stock_data = await get_stock_data()
    
    if not stock_data:
        await stock_list_cmd.finish("暂时无法获取股市数据，请稍后再试。")
    
    lines = ["📈 当前股市行情概览:"]
    
    # 按初始价格排序
    stock_list = []
    for stock_name, data in stock_data.items():
        initial_price = data["initial_price"]
        current_price = await get_current_stock_price(stock_name, stock_data)
        stock_list.append((stock_name, initial_price, current_price))
    
    stock_list.sort(key=lambda x: x[1])
    
    for stock_name, initial_price, current_price in stock_list:
        if current_price is not None:
            history = stock_data[stock_name].get("history", [])
            
            if len(history) > 1:
                prev_price = history[-2][1]
                change_percent = (current_price - prev_price) / prev_price * 100
            else:
                change_percent = (current_price - initial_price) / initial_price * 100
            
            symbol = "↑" if change_percent >= 0 else "↓"
            lines.append(
                f"◽ {stock_name}: {current_price:.2f}金币 "
                f"(初始{initial_price:.2f}) [{symbol}{abs(change_percent):.1f}%]"
            )
        else:
            lines.append(f"◽ {stock_name}: 价格未知 (初始: {initial_price:.2f})")
    
    # 使用转发消息发送
    chain = await build_forward_chain(bot, ["\n".join(lines)])
    await send_group_forward_msg(event, bot, chain)


stock_trend_cmd = on_regex(r'^(.+股)走势$', priority=5, block=True)

@stock_trend_cmd.handle()
async def handle_stock_trend(event: Event, bot: Bot, groups: tuple = RegexGroup()):
    chart_buf = b64_str = None
    try:
        # 使用 RegexGroup 获取匹配到的股票名称
        if not groups or len(groups) < 1:
            logger.warning("股票走势: 正则匹配组为空")
            await stock_trend_cmd.finish("无法解析股票名称，请检查指令格式。")
        
        stock_name = groups[0]
        logger.info(f"股票走势: 开始处理 {stock_name}")
        
        if stock_name not in STOCKS:
            await stock_trend_cmd.finish(f"未知股票: {stock_name}。可用的股票有: {', '.join(STOCKS.keys())}")
        
        stock_data = await get_stock_data()
        logger.info(f"股票走势: 已获取股票数据")
        
        history = await get_stock_price_history(stock_name, stock_data)
        logger.info(f"股票走势: {stock_name} 历史记录条数={len(history) if history else 0}")
        
        if not history:
            initial_price = stock_data[stock_name]["initial_price"]
            await stock_trend_cmd.finish(f"{stock_name} 暂时还没有价格历史记录。初始价格为 {initial_price:.2f} 金币。")
        
        # 在线程池中生成图表
        logger.info(f"股票走势: 开始生成图表")
        loop = asyncio.get_running_loop()
        try:
            chart_buf = await asyncio.wait_for(
                loop.run_in_executor(
                    None, generate_stock_chart, stock_name, history, stock_data
                ),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.error(f"股票走势: 图表生成超时 (10s)")
            chart_buf = None
        except Exception as e:
            logger.error(f"股票走势: 图表生成出错: {e}")
            chart_buf = None
        
        logger.info(f"股票走势: 图表生成完成，结果={chart_buf is not None}")
        
        if chart_buf:
            # 转换为 Base64 并发送图片
            from nonebot.adapters.onebot.v11 import MessageSegment
            image_bytes = chart_buf.getvalue()
            b64_str = base64.b64encode(image_bytes).decode()
            img_msg = MessageSegment.image(f"base64://{b64_str}")
            logger.info(f"股票走势: 发送图片")
            await stock_trend_cmd.finish(img_msg)
        else:
            # 图表生成失败，发送文字版
            current_price = history[-1][1]
            initial_price = stock_data[stock_name]["initial_price"]
            min_price = min(p for _, p in history)
            max_price = max(p for _, p in history)
            
            if len(history) > 1:
                first_price = history[0][1]
                change = (current_price - first_price) / first_price * 100
            else:
                change = (current_price - initial_price) / initial_price * 100
            
            symbol = "📈" if change >= 0 else "📉"
            
            msg = f"""{symbol} 【{stock_name}】走势

💰 当前价格: {current_price:.2f}金币
📊 初始价格: {initial_price:.2f}金币
📈 最高价格: {max_price:.2f}金币
📉 最低价格: {min_price:.2f}金币
{'↑' if change >= 0 else '↓'} 涨跌幅: {change:+.2f}%
⏰ 数据点数: {len(history)}个

（图表生成失败，显示文字版）"""
            
            await stock_trend_cmd.finish(msg)
    except FinishedException:
        raise
    except Exception as e:
        logger.error(f"股票走势处理异常: {e}")
        import traceback
        traceback.print_exc()
        await stock_trend_cmd.finish(f"处理股票走势时发生错误: {e}")
    finally:
        if chart_buf:
            chart_buf.close()
        del chart_buf, b64_str
        gc.collect()


# ===== 买入股票 =====
buy_stock_cmd = on_regex(r'^买入\s*(.+股)\s*(\d+)$', priority=5, block=True)

@buy_stock_cmd.handle()
async def handle_buy_stock(event: Event, bot: Bot, uid: int = Depends(get_uid), groups: tuple = RegexGroup()):
    # 使用 RegexGroup 获取匹配到的参数
    if not groups or len(groups) < 2:
        await buy_stock_cmd.finish("无法解析购买指令，请检查格式。", at_sender=True)
    
    stock_name = groups[0]
    amount_to_buy = int(groups[1])
    
    if amount_to_buy <= 0:
        await buy_stock_cmd.finish("购买数量必须是正整数", at_sender=True)
    
    if stock_name not in STOCKS:
        await buy_stock_cmd.finish(f"未知股票: {stock_name}", at_sender=True)
    
    # 检查持仓限制
    user_portfolio = await get_user_portfolio(uid)
    current_holding = user_portfolio.get(stock_name, 0)
    
    max_type = getattr(config, 'maxtype', 5)
    max_count = getattr(config, 'maxcount', 10000)
    
    if len(user_portfolio) >= max_type and stock_name not in user_portfolio:
        await buy_stock_cmd.finish(
            f"每位用户最多持有{max_type}种不同股票，您已持有{len(user_portfolio)}种。", at_sender=True)
    
    if current_holding >= max_count:
        await buy_stock_cmd.finish(
            f"每种股票持有上限为{max_count}股，请先卖出部分。", at_sender=True)
    
    if current_holding + amount_to_buy > max_count:
        amount_to_buy = max_count - current_holding
    
    current_price = await get_current_stock_price(stock_name)
    if current_price is None:
        await buy_stock_cmd.finish(f"{stock_name} 当前无法交易", at_sender=True)
    
    # 计算成本
    base_cost = current_price * amount_to_buy
    fee = math.ceil(base_cost * 0.01)
    total_cost = math.ceil(base_cost) + fee
    
    user_gold = money.get_user_money(uid, 'gold') or 0
    if user_gold < total_cost:
        await buy_stock_cmd.finish(
            f"金币不足！购买{amount_to_buy}股{stock_name}需要{total_cost}金币"
            f"（含{fee}手续费），您只有{user_gold}金币。", at_sender=True)
    
    # 执行购买
    if money.reduce_user_money(uid, 'gold', total_cost):
        if await update_user_portfolio(uid, stock_name, amount_to_buy):
            await buy_stock_cmd.finish(
                f"✅ 购买成功！\n"
                f"股票: {stock_name}\n"
                f"数量: {amount_to_buy}股\n"
                f"单价: {current_price:.2f}金币\n"
                f"费用: {total_cost}金币（含{fee}手续费）", at_sender=True)
        else:
            money.increase_user_money(uid, 'gold', total_cost)
            await buy_stock_cmd.finish("购买失败，金币已退回。", at_sender=True)
    else:
        await buy_stock_cmd.finish("购买失败，扣除金币时发生错误。", at_sender=True)


# ===== 卖出股票 =====
sell_stock_cmd = on_regex(r'^卖出\s*(.+股)(?:\s*(\d+))?$', priority=5, block=True)

@sell_stock_cmd.handle()
async def handle_sell_stock(event: Event, bot: Bot, uid: int = Depends(get_uid), groups: tuple = RegexGroup()):
    # 使用 RegexGroup 获取匹配到的参数
    if not groups or len(groups) < 1:
        await sell_stock_cmd.finish("无法解析卖出指令，请检查格式。", at_sender=True)
    
    stock_name = groups[0]
    amount_to_sell = int(groups[1]) if groups[1] else 9999
    
    if stock_name not in STOCKS:
        await sell_stock_cmd.finish(f"未知股票: {stock_name}", at_sender=True)
    
    user_portfolio = await get_user_portfolio(uid)
    current_holding = user_portfolio.get(stock_name, 0)
    
    if current_holding == 0:
        await sell_stock_cmd.finish(f"您没有持有{stock_name}", at_sender=True)
    
    if current_holding < amount_to_sell:
        amount_to_sell = current_holding
    
    current_price = await get_current_stock_price(stock_name)
    if current_price is None:
        await sell_stock_cmd.finish(f"{stock_name} 当前无法交易", at_sender=True)
    
    # 计算收入
    base_earnings = current_price * amount_to_sell
    fee = math.floor(base_earnings * 0.02)
    total_earnings = math.floor(base_earnings) - fee
    
    # 执行出售
    if await update_user_portfolio(uid, stock_name, -amount_to_sell):
        money.increase_user_money(uid, 'gold', total_earnings)
        await sell_stock_cmd.finish(
            f"✅ 卖出成功！\n"
            f"股票: {stock_name}\n"
            f"数量: {amount_to_sell}股\n"
            f"单价: {current_price:.2f}金币\n"
            f"收入: {total_earnings}金币（扣除{fee}手续费）", at_sender=True)
    else:
        await sell_stock_cmd.finish("卖出失败，更新持仓时发生错误。", at_sender=True)


# ===== 我的股仓 =====
my_portfolio_cmd = on_command("我的股仓", priority=5, block=True)

@my_portfolio_cmd.handle()
async def handle_my_portfolio(event: Event, bot: Bot, uid: int = Depends(get_uid)):
    user_portfolio = await get_user_portfolio(uid)
    
    if not user_portfolio:
        await my_portfolio_cmd.finish("您的股仓是空的，快去买点股票吧！", at_sender=True)
    
    stock_data = await get_stock_data()
    
    lines = ["💼 您的股仓详情:"]
    total_value = 0.0
    
    for stock_name, amount in user_portfolio.items():
        current_price = await get_current_stock_price(stock_name, stock_data)
        if current_price is None:
            current_price = stock_data.get(stock_name, {}).get("initial_price", 0)
        
        value = current_price * amount
        total_value += value
        lines.append(f"• {stock_name}: {amount}股 × {current_price:.2f} = {value:.2f}金币")
    
    lines.append(f"\n📊 股仓总价值: {total_value:.2f}金币")
    
    await my_portfolio_cmd.finish("\n".join(lines), at_sender=True)


# ===== 市场动态 =====
market_events_cmd = on_command("市场动态", priority=5, block=True)

@market_events_cmd.handle()
async def handle_market_events(event: Event, bot: Bot):
    stock_data = await get_stock_data()
    
    # 收集所有事件
    all_events = []
    for stock_name, data in stock_data.items():
        for evt in data.get("events", []):
            evt["stock"] = stock_name
            all_events.append(evt)
    
    all_events.sort(key=lambda x: x["time"], reverse=True)
    
    if not all_events:
        await market_events_cmd.finish("近期没有重大市场事件发生。")
    
    recent_events = all_events[:5]
    
    lines = ["📢 最新市场动态:"]
    for evt in recent_events:
        event_time = datetime.fromtimestamp(evt["time"]).strftime('%m-%d %H:%M')
        
        if evt.get("scope") == "global":
            lines.append(f"【{event_time}】{evt['message']}\n  影响范围: 所有股票")
        else:
            if evt.get("old_price") and evt.get("new_price"):
                change_percent = (evt["new_price"] - evt["old_price"]) / evt["old_price"] * 100
                change_dir = "↑" if change_percent >= 0 else "↓"
                lines.append(
                    f"【{event_time}】{evt['message']}\n"
                    f"  {evt['stock']}价格: {evt['old_price']:.2f} → {evt['new_price']:.2f} "
                    f"({change_dir}{abs(change_percent):.1f}%)"
                )
            else:
                lines.append(f"【{event_time}】{evt.get('message', '未知事件')}")
    
    # 使用转发消息发送
    chain = await build_forward_chain(bot, ["\n\n".join(lines)])
    await send_group_forward_msg(event, bot, chain)


# ===== 股价更新定时任务 =====
async def hourly_price_update():
    """定时更新所有股票价格"""
    try:
        logger.info("Running hourly stock price update...")
        stock_data = await get_stock_data()
        current_time = time.time()
        cutoff_time = current_time - HISTORY_DURATION_HOURS * 3600
        
        changed = False
        event_triggered = False
        affected_stocks = []
        
        # 获取最后事件时间
        try:
            last_event_time = max([
                max([e["time"] for e in stock.get("events", [])], default=0)
                for stock in stock_data.values()
            ], default=0)
        except:
            last_event_time = 0
        
        can_trigger_event = (current_time - last_event_time) >= EVENT_COOLDOWN
        
        # 决定是否触发事件
        if can_trigger_event and random.random() < EVENT_PROBABILITY:
            event_type = random.choice(list(MARKET_EVENTS.keys()))
            event_info = MARKET_EVENTS[event_type]
            event_triggered = True
            
            if event_info["scope"] == "single":
                affected_stocks = [random.choice(list(STOCKS.keys()))]
            else:
                affected_stocks = list(STOCKS.keys())
            
            # 应用事件影响
            for stock_name in affected_stocks:
                if stock_name not in stock_data:
                    continue
                
                if stock_data[stock_name]["history"]:
                    current_price = stock_data[stock_name]["history"][-1][1]
                else:
                    current_price = stock_data[stock_name]["initial_price"]
                
                new_price = event_info["effect"](current_price)
                new_price = max(stock_data[stock_name]["initial_price"] * 0.01,
                               min(new_price, stock_data[stock_name]["initial_price"] * 2.00))
                new_price = round(new_price, 2)
                
                template = random.choice(event_info["templates"])
                event_message = template.format(stock=stock_name)
                
                stock_data[stock_name]["events"].append({
                    "time": current_time,
                    "type": event_type,
                    "message": event_message,
                    "old_price": current_price,
                    "new_price": new_price
                })
                stock_data[stock_name]["events"] = stock_data[stock_name]["events"][-10:]
                stock_data[stock_name]["history"].append((current_time, new_price))
                changed = True
        
        # 正常价格波动
        for name, data in stock_data.items():
            if event_triggered and name in affected_stocks:
                continue
            
            initial_price = data["initial_price"]
            history = data.get("history", [])
            
            # 清理旧数据
            history = [(ts, price) for ts, price in history if ts >= cutoff_time]
            
            if not history:
                current_price = initial_price
            else:
                current_price = history[-1][1]
            
            # 随机波动
            change_percent = random.uniform(-0.05, 0.05)
            regression_factor = 0.03
            change_percent += regression_factor * (initial_price - current_price) / current_price
            
            new_price = current_price * (1 + change_percent)
            new_price = max(initial_price * 0.01, min(new_price, initial_price * 2.00))
            new_price = round(new_price, 2)
            
            history.append((current_time, new_price))
            stock_data[name]["history"] = history
            changed = True
        
        if changed:
            await save_stock_data(stock_data)
            logger.info("Stock prices updated and saved.")
    except Exception as e:
        logger.error(f"股价更新失败: {e}")


# ===== 初始化 =====
driver = get_driver()

@driver.on_startup
async def init_chaogu():
    """初始化炒股插件"""
    from pathlib import Path
    plugin_dir = Path(__file__).parent.parent.parent
    db_path = plugin_dir / "src" / "database" / "koinoribot.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    set_db_path(str(db_path))
    init_stock_database()
    
    # 初始化股票数据
    stock_data = await get_stock_data()
    for name, initial_price in STOCKS.items():
        if name not in stock_data:
            stock_data[name] = {
                "initial_price": initial_price,
                "history": [],
                "events": []
            }
    await save_stock_data(stock_data)
    
    logger.info("Chaogu 炒股插件初始化完成")


# 定时任务（使用 APScheduler）
try:
    scheduler = require("nonebot_plugin_apscheduler").scheduler
    scheduler.add_job(hourly_price_update, "cron", hour="*", minute="0", id="stock_price_update")
    logger.info("股价更新定时任务已注册")
except Exception as e:
    logger.warning(f"定时任务注册失败: {e}，需要手动安装 nonebot_plugin_apscheduler")
