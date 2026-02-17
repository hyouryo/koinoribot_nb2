import json
import random
import re
from decimal import Decimal
from pathlib import Path
from time import time

from aiofiles import open  # noqa: A004
from mathparse import mathparse
from nonebot import on_command, on_message
from nonebot.adapters import Event
from nonebot.plugin import PluginMetadata

from ...tools import get_sender_nickname
from .utils import format_expression

__plugin_meta__ = PluginMetadata(
    name="24点小游戏",
    description="24点小游戏",
    usage="24点",
)


twenty_four = on_command("24点")

start: bool = False
nums: list = []
answer: str = ""
time_out: float = 0

after_twenty_four_time = 0


answer_path = Path(__file__).parent / "answer.json"
@twenty_four.handle()
async def twenty_four_handle() -> None:
    global start  # noqa: PLW0603
    global nums  # noqa: PLW0603
    global answer # noqa: PLW0603
    global time_out # noqa: PLW0603
    if not start:
        start = True
    else:
        await twenty_four.finish(f"已有24点游戏，当前的4个数是：" + " ".join(nums))
    async with open(answer_path, encoding="utf-8") as f:
        file = await f.read()
    _dict:dict = json.loads(file)
    _list:list = list(_dict.keys())
    que_str:str = random.choice(_list)
    nums = que_str.split()
    nums.sort()
    answer = _dict[que_str]
    timestamp_now = time()
    time_out = timestamp_now + 600
    await twenty_four.finish(f"当前题目：{que_str}\n使用 算式 来回答结果\n可以使用+-*/和()\n例：(1+2)*3/4 即可回答")  # noqa: E501


get_twenty_four_answer = on_message(priority=10, block=False)

@get_twenty_four_answer.handle()
async def _(event:Event) -> None:
    global start  # noqa: PLW0603
    if not start:
        return
    if time() > time_out:
        start = False
        await get_twenty_four_answer.finish('24点游戏时间到~')
    submit = event.get_message().extract_plain_text().strip()
    if submit == '24点提示':
        await get_twenty_four_answer.finish(f'可以得到24点的式子：{answer}')
    format_ = format_expression(submit)
    try:
        answer_ = mathparse.parse(format_)  # 数
    except Exception:  # noqa: BLE001
        return
    if type(answer_) is float | Decimal:
        answer_ = round(answer_, 2)
    match = re.findall(r'(\d+)', submit)
    match.sort()
    if match != nums:
        await get_twenty_four_answer.finish('必须要用到题目里的四个数喔')
    if answer_ == 24:  # noqa: PLR2004
        start = False
        await get_twenty_four_answer.finish(f'{format_}={answer_}，{get_sender_nickname(event)}回答正确~')  # noqa: E501
    else:
        await get_twenty_four_answer.finish(f'{format_}={answer_}，答案不对喔...')
