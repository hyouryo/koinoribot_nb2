import json
import random
import re
from decimal import Decimal
from pathlib import Path
from time import time

from aiofiles import open  # noqa: A004
from mathparse import mathparse
from nonebot import on_command
from nonebot.adapters import Event
from nonebot.plugin import PluginMetadata

from ...tools import get_group_id, get_sender_nickname
from .utils import format_expression

__plugin_meta__ = PluginMetadata(
    name="24点小游戏",
    description="24点小游戏",
    usage="24点",
)


# 游戏会话，存储已经开始游戏的群聊


class TwentyFourGame:
    def __init__(self, group_id: str, numbers: list[str], answer: str) -> None:
        self.group_id = group_id
        self.numbers = numbers
        self.answer = answer
        self.create_time = time()

    def is_timeout(self) -> bool:
        return time() > self.create_time + 600

    def is_numbers(self, numbers: str) -> bool:
        match: list[str] = re.findall(r"(\d+)", numbers)
        match.sort()
        return match == self.numbers


twenty_four_start = on_command("24点",priority=10)
twenty_four_games: dict[str, TwentyFourGame] = {}

after_twenty_four_time = 0


answer_path = Path(__file__).parent / "answer.json"


@twenty_four_start.handle()
async def twenty_four_handle(event: Event) -> None:
    # 获取群号
    try:
        group_id = get_group_id(event)
    except ValueError:
        await twenty_four_start.finish("本功能仅支持群组使用")
    # 检查群是否已存在游戏
    if group_id in twenty_four_games:
        game = twenty_four_games[group_id]
        await twenty_four_start.finish(
            "已有24点游戏，当前的4个数是：" + " ".join(game.numbers)
        )
    # 获取所有可用的24点数字
    async with open(answer_path, encoding="utf-8") as f:
        file = await f.read()
    _dict: dict = json.loads(file)  # 类似 {"2 6 7 8":"(2+7-6)x8","2 6 7 8":"(2+7-6)x8"}
    _list: list = list(_dict.keys())  # 类似 ["2 6 7 8","2 6 7 8"]
    # 随机选择一个可用的24点数字
    que_str: str = random.choice(_list)  # 类似 "2 6 7 8"
    # 将数字切片并排序
    nums = que_str.split()  # 类似 [2, 6, 7, 8]
    nums.sort()
    # 获取答案
    answer = _dict[que_str]  # 类似 "(2+7-6)x8"

    # 创建游戏
    game = TwentyFourGame(group_id, nums, answer)
    # 放入游戏列表中
    twenty_four_games[group_id] = game

    await twenty_four_start.finish(
        f"当前题目：{que_str}\n使用 24答 算式 来回答结果\n可以使用+-*/和()\n例：24答 (1+2)*3/4\n发送 24点提示 可查看答案"  # noqa: E501
    )


twenty_four_hint = on_command("24点提示", priority=10)


@twenty_four_hint.handle()
async def twenty_four_hint_handle(event: Event) -> None:
    try:
        group_id = get_group_id(event)
    except ValueError:
        await twenty_four_hint.finish("本功能仅支持群组使用")
    if group_id not in twenty_four_games:
        await twenty_four_hint.finish("当前没有进行中的24点游戏哦")
    game = twenty_four_games[group_id]
    if game.is_timeout():
        twenty_four_games.pop(group_id)
        await twenty_four_hint.finish("24点游戏已超时~")
    await twenty_four_hint.finish(f"可以得到24点的式子：{game.answer}")


get_twenty_four_answer = on_command("24答", aliases={"24点答题"}, priority=10)


@get_twenty_four_answer.handle()
async def twenty_four_answer_handle(event: Event) -> None:
    # 获取群号
    try:
        group_id = get_group_id(event)
    except ValueError:
        await get_twenty_four_answer.finish("本功能仅支持群组使用")
    # 检查游戏列表中是否有该群的游戏
    if group_id not in twenty_four_games:
        await get_twenty_four_answer.finish("当前没有进行中的24点游戏哦")
    game = twenty_four_games[group_id]
    if game.is_timeout():
        twenty_four_games.pop(group_id)
        await get_twenty_four_answer.finish("24点游戏时间到~")
    submit = event.get_message().extract_plain_text().strip()
    if not submit:
        await get_twenty_four_answer.finish("请在命令后输入算式，例：24答 (1+2)*3/4")
    format_ = format_expression(submit)
    try:
        answer_ = mathparse.parse(format_)  # 数
    except Exception:  # noqa: BLE001
        await get_twenty_four_answer.finish("算式格式不正确，请检查后重试")
    if type(answer_) is float | Decimal:
        answer_ = round(answer_, 2)
    match = re.findall(r"(\d+)", submit)
    match.sort()
    if match != game.numbers:
        await get_twenty_four_answer.finish("必须要用到题目里的四个数喔")
    if answer_ == 24:  # noqa: PLR2004
        twenty_four_games.pop(group_id)
        await get_twenty_four_answer.finish(
            f"{format_}={answer_}，{get_sender_nickname(event)}回答正确~"
        )
    else:
        await get_twenty_four_answer.finish(f"{format_}={answer_}，答案不对喔...")
