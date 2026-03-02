from nonebot import on_command
from nonebot.params import Depends
from nonebot.plugin import PluginMetadata

from ...money import UserWallet, wallet_manager

__plugin_meta__ = PluginMetadata(
    name="say_goodnight",
    description="说晚安",
    usage="说晚安"
)


say_goodnight = on_command("晚安")


@say_goodnight.handle()
async def say_goodnight_handle(
    user_wallet: UserWallet = Depends(wallet_manager),
) -> None:
    if user_wallet.gold >= 50:  # noqa: PLR2004
        user_wallet.gold -= 50
        await say_goodnight.finish("晚安喵")
