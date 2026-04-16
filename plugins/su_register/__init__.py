"""
超级用户注册插件 - su_register

提供 superusers 表的创建和 SU 注册功能。
本文件不上传 git 仓库。

命令:
    注册su 激活码 - 使用激活码注册为 level 1 SU
"""

import sqlite3
import time
import aiohttp

from nonebot import get_driver, on_command
from nonebot.adapters import Bot, Event, Message
from nonebot.log import logger
from nonebot.params import CommandArg, Depends
from nonebot.plugin import PluginMetadata

from ...tools import get_uid
from ...su_manager import is_su, get_su_level, SU_LEVEL_NORMAL

__plugin_meta__ = PluginMetadata(
    name="su_register",
    description="超级用户注册管理",
    usage="注册su 激活码",
)


def _get_db_path() -> str:
    """获取数据库路径"""
    from pathlib import Path
    plugin_dir = Path(__file__).parent.parent.parent
    return str(plugin_dir / "src" / "database" / "koinoribot.db")


def _init_superusers_table():
    """创建 superusers 表（如不存在）"""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS superusers (
                uid INTEGER PRIMARY KEY,
                level INTEGER NOT NULL DEFAULT 1,
                activated_at REAL NOT NULL,
                activation_code TEXT,
                daily_hongbao_used INTEGER NOT NULL DEFAULT 0,
                daily_transfer_used INTEGER NOT NULL DEFAULT 0,
                daily_date TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.commit()
        logger.info("[su_register] superusers 表初始化完成")
    except Exception as e:
        logger.error(f"[su_register] superusers 表创建失败: {e}")
    finally:
        conn.close()


async def _validate_activation_code(code: str, uid: int) -> bool:
    """
    验证激活码是否有效。

    通过远程服务获取正确的激活码进行比对。
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:5000/salt?uid={uid}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    expected = data.get("key", "")
                    return bool(expected) and code.lower() == expected.lower()
                else:
                    logger.error(f"[su_register] 验证激活码失败，HTTP状态码: {resp.status}")
                    return False
    except Exception as e:
        logger.error(f"[su_register] 验证激活码异常: {e}")
        return False


def _register_su(uid: int, level: int, activation_code: str) -> bool:
    """
    将用户注册为 SU。

    Args:
        uid: 用户 UID
        level: 权限等级
        activation_code: 使用的激活码

    Returns:
        True 注册成功，False 失败
    """
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO superusers (uid, level, activated_at, activation_code)
            VALUES (?, ?, ?, ?)
            """,
            (uid, level, time.time(), activation_code)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # 用户已存在
        logger.warning(f"[su_register] 用户 {uid} 已是 SU，跳过注册")
        return False
    except Exception as e:
        logger.error(f"[su_register] 注册 SU 失败: {e}")
        return False
    finally:
        conn.close()


# ===== 启动时初始化表 =====
driver = get_driver()


@driver.on_startup
async def init_su_register():
    """初始化 SU 注册插件"""
    _init_superusers_table()
    logger.info("[su_register] SU 注册插件初始化完成")


# ===== 注册su 命令 =====
register_su_cmd = on_command("注册su", priority=5, block=True)


@register_su_cmd.handle()
async def handle_register_su(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid),
    args: Message = CommandArg()
):
    """处理 SU 注册命令"""
    # 检查是否已经是 SU
    if is_su(uid):
        current_level = get_su_level(uid)
        await register_su_cmd.finish(
            f"你已经是 SU 用户了（权限等级: {current_level}）",
            at_sender=True
        )

    # 解析激活码
    activation_code = args.extract_plain_text().strip()
    if not activation_code:
        await register_su_cmd.finish(
            "\n请提供激活码！\n用法: 注册su 激活码",
            at_sender=True
        )

    # 验证激活码
    if not await _validate_activation_code(activation_code, uid):
        await register_su_cmd.finish(
            "\n激活码无效！（使用 注册激活码 可以获取你的激活码）",
            at_sender=True
        )

    # 注册为 level 1 SU
    if _register_su(uid, SU_LEVEL_NORMAL, activation_code):
        await register_su_cmd.finish(
            "✅ SU 注册成功！\n"
            f"权限等级: {SU_LEVEL_NORMAL}\n"
            "注意: SU 用户不参与任何排行榜。",
            at_sender=True
        )
    else:
        await register_su_cmd.finish(
            "注册失败，请稍后再试或联系管理员。",
            at_sender=True
        )
