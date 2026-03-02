from pathlib import Path

from nonebot import on_command
from nonebot.adapters import Event, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from ...build_image import BuildImage
from ...tools import build_image_msg

__plugin_meta__ = PluginMetadata(
    name="luxunsaid",
    description="",
    usage="",
)
luxun_author = BuildImage(
    0,
    0,
    plain_text="——鲁迅",
    font_size=30,
    font="STKAITI.TTF",
    font_color=(255, 255, 255),
)
shake_author = BuildImage(
    0,
    0,
    plain_text="——莎士比亚",
    font_size=30,
    font="HGFS_CNKI.TTF",
    font_color=(255, 255, 255),
)

luxunsaid = on_command("鲁迅说过", aliases={"鲁迅说", "鲁迅讲", "鲁迅讲过"})


@luxunsaid.handle()
async def luxunsaid_handle(event: Event, msg: Message = CommandArg()) -> None:
    message = msg.extract_plain_text().strip()
    for biaodian in [",", "，", ":", "："]:
        if message.startswith(biaodian):
            message.strip(biaodian)
    image_file = Path(__file__).parent / "luxun.jpg"
    bg = BuildImage(0, 0, font_size=37, background=image_file, font="STKAITI.TTF")
    say = ""
    if len(message) > 40:  # noqa: PLR2004
        say = "太长了，我说不完。"
    if len(message) == 0:
        say = "你得让我说点啥。"
    if not say:
        while bg.getsize(message)[0] > bg.w - 50:
            n = int(len(message) / 2)
            say += message[:n] + "\n"
            message = message[n:]
        say += message
    if len(say.split("\n")) > 2:  # noqa: PLR2004
        say = "太长了，我说不完。"
    bg.text(
        (int((480 - bg.getsize(say.split("\n")[0])[0]) / 2), 300), say, (255, 255, 255)
    )
    bg.paste(luxun_author, (320, 400), alpha=True)
    bg_base64 = bg.pic2bs4()
    bg_bytes = build_image_msg(event, bg_base64)
    await luxunsaid.finish(bg_bytes)


shashibiyasaid = on_command(
    "莎士比亚说过", aliases={"莎士比亚说", "莎士比亚讲", "莎士比亚讲过"}
)


@shashibiyasaid.handle()
async def shashibiyasaid_handle(event: Event, msg: Message = CommandArg()) -> None:
    message = msg.extract_plain_text().strip()
    for biaodian in [",", "，", ":", "："]:
        if message.startswith(biaodian):
            message.strip(biaodian)
    image_file = Path(__file__).parent / "shashibiya.jpg"
    bg = BuildImage(0, 0, font_size=37, background=image_file, font="HGFS_CNKI.TTF")
    say = ""
    if len(message) > 40:  # noqa: PLR2004
        say = "太长了，这是个问题。"
    if len(message) == 0:
        say = "我什么也没有说。"
    if not say:
        while bg.getsize(message)[0] > bg.w - 50:
            n = int(len(message) / 2)
            say += message[:n] + "\n"
            message = message[n:]
        say += message
    if len(say.split("\n")) > 2:  # noqa: PLR2004
        say = "太长了，这是个问题。"
    bg.text(
        (int((440 - bg.getsize(say.split("\n")[0])[0]) / 2), 380), say, (255, 255, 255)
    )
    bg.paste(shake_author, (230, 510), alpha=True)
    bg_base64 = bg.pic2bs4()
    bg_bytes = build_image_msg(event, bg_base64)
    await shashibiyasaid.finish(bg_bytes)
