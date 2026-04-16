"""
超级用户 (Superuser) 管理工具

提供 SU 身份判定、权限等级查询、权限检查等功能。
优先查询 superusers 数据库表，表不存在时回退到 koinori_config 配置。
koinori_config 中的 SU 视为 level 0（最高权限 / contributor）。

权限等级:
    0 - contributor（最高权限，无任何限制）
    1 - 普通 SU（红包/转账每日上限 100000，打款仅限自己）
"""

import sqlite3
from datetime import datetime
from typing import Optional

from nonebot.log import logger


# 权限常量
SU_LEVEL_CONTRIBUTOR = 0  # 最高权限
SU_LEVEL_NORMAL = 1       # 普通 SU

# SU level 1 的每日限制常量
SU_HONGBAO_DAILY_LIMIT = 100000      # 红包每日上限
SU_TRANSFER_DAILY_LIMIT = 100000     # 转账每日上限


def _get_db_path() -> str:
    """获取数据库路径"""
    from pathlib import Path
    plugin_dir = Path(__file__).parent
    return str(plugin_dir / "src" / "database" / "koinoribot.db")


def _get_config_superusers() -> list:
    """从 koinori_config 获取 superuser 列表（视为 level 0）"""
    try:
        from .koinori_config import config
        return getattr(config, 'superusers', [])
    except Exception:
        return []


def _query_table(uid: int) -> Optional[int]:
    """
    查询 superusers 表中的用户权限等级。

    Returns:
        int: 权限等级（0 或 1）
        None: 用户不在表中

    Raises:
        sqlite3.OperationalError: 表不存在
    """
    conn = sqlite3.connect(_get_db_path())
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT level FROM superusers WHERE uid = ?", (uid,))
        row = cursor.fetchone()
        if row is not None:
            return row[0]
        return None
    finally:
        conn.close()


def _table_exists() -> bool:
    """检查 superusers 表是否存在"""
    conn = sqlite3.connect(_get_db_path())
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='superusers'"
        )
        return cursor.fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()


def is_su(uid: int) -> bool:
    """
    判定用户是否为超级用户。

    优先查询 superusers 表，表不存在则回退到 koinori_config。

    Args:
        uid: 用户 UID

    Returns:
        True 如果是 SU，否则 False
    """
    return get_su_level(uid) is not None


def get_su_level(uid: int) -> Optional[int]:
    """
    获取用户的 SU 权限等级。

    优先查询 superusers 表，表不存在则回退到 koinori_config（视为 level 0）。

    Args:
        uid: 用户 UID

    Returns:
        0: contributor（最高权限）
        1: 普通 SU
        None: 非 SU 用户
    """
    try:
        # 优先查表
        level = _query_table(uid)
        if level is not None:
            return level
    except sqlite3.OperationalError:
        # 表不存在，回退到 config
        config_sus = _get_config_superusers()
        if uid in config_sus:
            return SU_LEVEL_CONTRIBUTOR
        return None
    except Exception as e:
        logger.error(f"[su_manager] 查询 SU 表异常: {e}")

    # 表存在但用户不在表中，也检查 config
    config_sus = _get_config_superusers()
    if uid in config_sus:
        return SU_LEVEL_CONTRIBUTOR
    return None


def get_all_su_uids() -> list[int]:
    """
    获取所有 SU 用户 UID 列表。

    用于排行榜过滤等场景。合并表中用户和 koinori_config 中的用户。

    Returns:
        所有 SU 用户的 UID 列表
    """
    su_uids = set()

    # 从 config 获取
    config_sus = _get_config_superusers()
    su_uids.update(config_sus)

    # 从表获取
    try:
        if _table_exists():
            conn = sqlite3.connect(_get_db_path())
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT uid FROM superusers")
                for row in cursor.fetchall():
                    su_uids.add(row[0])
            finally:
                conn.close()
    except Exception as e:
        logger.error(f"[su_manager] 获取所有 SU 列表异常: {e}")

    return list(su_uids)


def get_excluded_su_uids() -> list[int]:
    """
    获取排行榜需要排除的 SU 用户 UID 列表。

    排除等级不为 1 的 SU 用户（即排除 level 0/contributor 等，保留 level 1 的普通 SU）。
    level 1 的 SU 是通过飞升获得权限的用户，应在排行榜中展示。

    Returns:
        需要排除的 SU 用户 UID 列表
    """
    excluded = set()

    # 从 config 获取的 SU 视为 level 0，需要排除
    config_sus = _get_config_superusers()
    excluded.update(config_sus)

    # 从表获取，排除 level != 1 的用户
    try:
        if _table_exists():
            conn = sqlite3.connect(_get_db_path())
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT uid, level FROM superusers")
                for row in cursor.fetchall():
                    if row[1] != SU_LEVEL_NORMAL:
                        excluded.add(row[0])
            finally:
                conn.close()
    except Exception as e:
        logger.error(f"[su_manager] 获取排除 SU 列表异常: {e}")

    return list(excluded)


def _get_today_str() -> str:
    """获取今日日期字符串 YYYY-MM-DD"""
    return datetime.now().strftime("%Y-%m-%d")


def _get_daily_usage(uid: int) -> dict:
    """
    获取用户今日已用额度。

    如果 daily_date 不是今天，自动重置为 0。

    Returns:
        {'hongbao': int, 'transfer': int}
    """
    today = _get_today_str()
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT daily_hongbao_used, daily_transfer_used, daily_date FROM superusers WHERE uid = ?",
                (uid,)
            )
            row = cursor.fetchone()
            if row is None:
                return {'hongbao': 0, 'transfer': 0}
            # 日期不是今天，视为已重置
            if row['daily_date'] != today:
                return {'hongbao': 0, 'transfer': 0}
            return {
                'hongbao': row['daily_hongbao_used'] or 0,
                'transfer': row['daily_transfer_used'] or 0
            }
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[su_manager] 获取每日用量异常: {e}")
        return {'hongbao': 0, 'transfer': 0}


def record_su_usage(uid: int, action: str, amount: int) -> None:
    """
    记录 SU 用户的每日用量（操作成功后调用）。

    Args:
        uid: 用户 UID
        action: 'hongbao' 或 'transfer'
        amount: 本次使用金额
    """
    level = get_su_level(uid)
    if level is None or level == SU_LEVEL_CONTRIBUTOR:
        return  # 非 SU 或 level 0 不需要记录

    today = _get_today_str()
    column = 'daily_hongbao_used' if action == 'hongbao' else 'daily_transfer_used'

    try:
        conn = sqlite3.connect(_get_db_path())
        try:
            cursor = conn.cursor()
            # 检查当前日期
            cursor.execute("SELECT daily_date FROM superusers WHERE uid = ?", (uid,))
            row = cursor.fetchone()
            if row is None:
                return

            if row[0] != today:
                # 新的一天，重置所有计数
                cursor.execute(
                    "UPDATE superusers SET daily_hongbao_used = 0, daily_transfer_used = 0, daily_date = ? WHERE uid = ?",
                    (today, uid)
                )

            # 累加用量
            cursor.execute(
                f"UPDATE superusers SET {column} = {column} + ?, daily_date = ? WHERE uid = ?",
                (amount, today, uid)
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[su_manager] 记录每日用量异常: {e}")


def check_su_permission(uid: int, action: str, **kwargs) -> tuple[bool, str]:
    """
    统一的 SU 权限检查函数。

    对于 hongbao 和 transfer 操作，检查每日累计金额是否超限。
    注意：本函数仅做检查，不记录用量。操作成功后需调用 record_su_usage()。

    Args:
        uid: 用户 UID
        action: 操作类型
            - 'hongbao': 发红包，需要 kwargs['amount']
            - 'transfer': 转账，需要 kwargs['amount']
            - 'payment': 打款，需要 kwargs['target_uid'] 和 kwargs['amount']
        **kwargs: 操作相关参数

    Returns:
        (True, ""): 允许操作
        (False, "原因"): 拒绝操作
    """
    level = get_su_level(uid)
    if level is None:
        return (True, "")

    # level 0: contributor，无任何限制
    if level == SU_LEVEL_CONTRIBUTOR:
        return (True, "")

    # level 1: 普通 SU，有每日限制
    usage = _get_daily_usage(uid)

    if action == 'hongbao':
        amount = kwargs.get('amount', 0)
        used = usage['hongbao']
        remaining = SU_HONGBAO_DAILY_LIMIT - used
        if amount > remaining:
            return (False,
                f"SU用户(Lv.1)每日红包额度不足\n"
                f"每日上限: {SU_HONGBAO_DAILY_LIMIT} 金币\n"
                f"今日已用: {used} 金币\n"
                f"剩余额度: {remaining} 金币\n"
                f"本次请求: {amount} 金币")

    elif action == 'transfer':
        amount = kwargs.get('amount', 0)
        used = usage['transfer']
        remaining = SU_TRANSFER_DAILY_LIMIT - used
        if amount > remaining:
            return (False,
                f"SU用户(Lv.1)每日转账额度不足\n"
                f"每日上限: {SU_TRANSFER_DAILY_LIMIT} 金币\n"
                f"今日已用: {used} 金币\n"
                f"剩余额度: {remaining} 金币\n"
                f"本次请求: {amount} 金币")

    elif action == 'payment':
        target_uid = kwargs.get('target_uid', None)
        if target_uid is not None and target_uid != uid:
            return (False, "SU用户(Lv.1)只能向自己打款")

    return (True, "")
