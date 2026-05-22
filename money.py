"""
用户资产管理模块

管理用户金币、星星、宝石等资产
使用统一 UID 系统
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional, Union

from nonebot.log import logger

from .koinori_config import get_config

# 默认初始资产
DEFAULT_ASSETS = {
    "gold": 3000,  # 金币
    "luckygold": 1,  # 幸运币
    "starstone": 12500,  # 星星
    "kirastone": 5,  # 羽毛石/宝石
    "last_login": 0,  # 最后签到日期
    "rp": 0,  # 运势值
    "logindays": 0,  # 连续签到天数
    "exgacha": 0,  # 抽卡券
    "goodluck": 0,  # 宜做事项索引
    "badluck": 0,  # 忌做事项索引
}

# 资产上限
GOLD_MAX = get_config().gold_max

KEYWORD_LIST = list(DEFAULT_ASSETS.keys())
KEY_LIST = ["gold", "luckygold", "starstone", "kirastone"]

# 货币名称映射
NAME_MAP = {
    "starstone": ["starstone", "星星", "星石", "星", "stars", "爱星", "艾星"],
    "luckygold": ["luckygold", "lucky", "幸运", "幸运币"],
    "gold": ["gold", "金币", "金子", "黄金"],
    "exgacha": ["井券", "兑换券", "exgacha"],
    "kirastone": ["羽毛石", "宝石", "kirastone"],
}


class money:
    """货币管理类 - 封装所有货币/资产相关操作"""

    _db_path: Optional[str] = None
    _db_initialized: bool = False

    # ===== 数据库路径管理 =====

    @classmethod
    def set_database_path(cls, path: str):
        """设置数据库路径"""
        cls._db_path = path
        cls._db_initialized = False

    @classmethod
    def get_database_path(cls) -> str:
        """获取数据库路径"""
        if cls._db_path is None:
            raise RuntimeError("数据库路径未设置，请先调用 money.set_database_path()")
        return cls._db_path

    @classmethod
    def _get_connection(cls) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(cls.get_database_path())
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ===== 数据库初始化 =====

    @classmethod
    def init_database(cls):
        """初始化用户资产数据库表"""
        if cls._db_initialized:
            return

        conn = cls._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_money (
                uid INTEGER PRIMARY KEY,
                gold INTEGER NOT NULL DEFAULT 3000,
                luckygold INTEGER NOT NULL DEFAULT 0,
                starstone INTEGER NOT NULL DEFAULT 12500,
                kirastone INTEGER NOT NULL DEFAULT 0,
                last_login INTEGER NOT NULL DEFAULT 0,
                rp INTEGER NOT NULL DEFAULT 0,
                logindays INTEGER NOT NULL DEFAULT 0,
                exgacha INTEGER NOT NULL DEFAULT 0,
                goodluck INTEGER NOT NULL DEFAULT 0,
                badluck INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (uid) REFERENCES user_uid_mapping(uid) ON UPDATE CASCADE ON DELETE CASCADE
            )
        """)

        conn.commit()
        conn.close()
        cls._db_initialized = True

    @classmethod
    def _ensure_initialized(cls):
        """确保数据库已初始化"""
        if not cls._db_initialized:
            cls.init_database()

    @classmethod
    def _ensure_user_exists(cls, cursor, uid: int) -> bool:
        """确保用户记录存在，不存在则创建"""
        cursor.execute("SELECT uid FROM user_money WHERE uid = ?", (uid,))
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO user_money
                (uid, gold, luckygold, starstone, kirastone, last_login, rp, logindays, exgacha, goodluck, badluck)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    uid,
                    DEFAULT_ASSETS["gold"],
                    DEFAULT_ASSETS["luckygold"],
                    DEFAULT_ASSETS["starstone"],
                    DEFAULT_ASSETS["kirastone"],
                    DEFAULT_ASSETS["last_login"],
                    DEFAULT_ASSETS["rp"],
                    DEFAULT_ASSETS["logindays"],
                    DEFAULT_ASSETS["exgacha"],
                    DEFAULT_ASSETS["goodluck"],
                    DEFAULT_ASSETS["badluck"],
                ),
            )
            return True
        return False

    # ===== 名称翻译 =====

    @classmethod
    def translate_name(cls, name: str) -> str:
        """将货币昵称转换为关键字"""
        for key, names in NAME_MAP.items():
            if name in names:
                return key
        return ""

    # ===== 用户货币 CRUD =====

    @classmethod
    def get_user_money(cls, uid: int, *keys: str) -> Optional[Union[int, tuple]]:
        """
        获取用户指定资源的数量

        Args:
            uid: 用户 UID
            *keys: 资源关键字

        Returns:
            单个值或值元组
        """
        cls._ensure_initialized()

        if not keys:
            return None

        for key in keys:
            if key not in KEYWORD_LIST:
                return None

        conn = None
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()

            created = cls._ensure_user_exists(cursor, uid)
            if created:
                conn.commit()

            columns = ", ".join(keys)
            cursor.execute(f"SELECT {columns} FROM user_money WHERE uid = ?", (uid,))
            result = cursor.fetchone()

            if result is None:
                return None

            if len(keys) == 1:
                return int(result[0]) if result[0] is not None else None
            else:
                return tuple(int(v) if v is not None else None for v in result)

        except Exception as e:
            logger.error(f"[money] 获取用户数据失败: {e}")
            return None
        finally:
            if conn:
                conn.close()

    @classmethod
    def set_user_money(cls, uid: int, key: str, value: int) -> int:
        """
        直接设置用户某种资源

        Args:
            uid: 用户 UID
            key: 资源关键字
            value: 新值

        Returns:
            1 成功，0 失败
        """
        cls._ensure_initialized()

        if key not in KEYWORD_LIST:
            return 0

        if key == "gold":
            value = min(value, GOLD_MAX)

        conn = None
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()

            cls._ensure_user_exists(cursor, uid)
            cursor.execute(f"UPDATE user_money SET {key} = ? WHERE uid = ?", (value, uid))

            conn.commit()
            return 1
        except Exception as e:
            logger.error(f"[money] 设置用户数据失败: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    @classmethod
    def increase_user_money(cls, uid: int, key: str, value: int) -> int:
        """
        增加用户某种资源

        Args:
            uid: 用户 UID
            key: 资源关键字
            value: 增加量

        Returns:
            1 成功，0 失败
        """
        cls._ensure_initialized()

        if key not in KEYWORD_LIST:
            return 0

        conn = None
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()

            cls._ensure_user_exists(cursor, uid)
            if key == "gold":
                cursor.execute(
                    f"UPDATE user_money SET {key} = MIN({key} + ?, ?) WHERE uid = ?",
                    (value, GOLD_MAX, uid),
                )
            else:
                cursor.execute(
                    f"UPDATE user_money SET {key} = {key} + ? WHERE uid = ?", (value, uid)
                )

            conn.commit()
            return 1
        except Exception as e:
            logger.error(f"[money] 增加用户资产失败: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    @classmethod
    def reduce_user_money(cls, uid: int, key: str, value: int) -> int:
        """
        减少用户某种资源

        Args:
            uid: 用户 UID
            key: 资源关键字
            value: 减少量

        Returns:
            1 成功，0 失败
        """
        cls._ensure_initialized()

        if key not in KEYWORD_LIST:
            return 0

        conn = None
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()

            created = cls._ensure_user_exists(cursor, uid)
            if created:
                conn.commit()
                return 0  # 新用户无法扣款

            cursor.execute(
                f"UPDATE user_money SET {key} = {key} - ? WHERE uid = ?", (value, uid)
            )

            conn.commit()
            return 1
        except Exception as e:
            logger.error(f"[money] 减少用户资产失败: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    # ===== 批量操作 =====

    @classmethod
    def increase_all_user_money(cls, key: str, value: int) -> int:
        """增加所有用户某种资源"""
        cls._ensure_initialized()

        if key not in KEYWORD_LIST:
            return 0

        conn = None
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()

            if key == "gold":
                cursor.execute(f"UPDATE user_money SET {key} = MIN({key} + ?, ?)", (value, GOLD_MAX))
            else:
                cursor.execute(f"UPDATE user_money SET {key} = {key} + ?", (value,))

            conn.commit()
            return 1
        except Exception as e:
            logger.error(f"[money] 增加所有用户资产失败: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    @classmethod
    def get_all_user_money(cls, key: str) -> dict[int, int]:
        """
        获取所有用户指定资产

        Returns:
            {uid: value}
        """
        cls._ensure_initialized()

        if key not in KEYWORD_LIST:
            return {}

        conn = None
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()

            cursor.execute(f"SELECT uid, {key} FROM user_money")
            results = cursor.fetchall()

            return {row["uid"]: row[key] for row in results}
        except Exception as e:
            logger.error(f"[money] 获取所有用户资产失败: {e}")
            return {}
        finally:
            if conn:
                conn.close()

    @classmethod
    def delete_user_account(cls, uid: int) -> int:
        """删除用户账户"""
        cls._ensure_initialized()

        conn = None
        try:
            conn = cls._get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_money WHERE uid = ?", (uid,))
            affected = cursor.rowcount

            conn.commit()
            return 1 if affected > 0 else 0
        except Exception as e:
            logger.error(f"[money] 删除用户账户失败: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    @classmethod
    def tran_kira(cls, uid: int, key: str, num: int) -> tuple[int, int]:
        """
        将羽毛石转换成其他资源

        Args:
            uid: 用户 UID
            key: 目标资源关键字
            num: 羽毛石数量

        Returns:
            (消耗的羽毛石, 获得的资源)
        """
        if key == "gold":
            value = num * 10
        elif key == "starstone":
            value = num * 10
        elif key == "luckygold":
            value = num // 50
            num = value * 50
        else:
            value = 0
            num = 0

        cls.increase_user_money(uid, key, value)
        cls.reduce_user_money(uid, "kirastone", num)
        return num, value


# ===== 模块级函数（向后兼容，委托给 money 类） =====

def set_database_path(path: str):
    money.set_database_path(path)


def get_database_path() -> str:
    return money.get_database_path()


def init_money_database():
    money.init_database()


def translate_name(name: str) -> str:
    return money.translate_name(name)


def get_user_money(uid: int, *keys: str) -> Optional[Union[int, tuple]]:
    return money.get_user_money(uid, *keys)


def set_user_money(uid: int, key: str, value: int) -> int:
    return money.set_user_money(uid, key, value)


def increase_user_money(uid: int, key: str, value: int) -> int:
    return money.increase_user_money(uid, key, value)


def reduce_user_money(uid: int, key: str, value: int) -> int:
    return money.reduce_user_money(uid, key, value)


def increase_all_user_money(key: str, value: int) -> int:
    return money.increase_all_user_money(key, value)


def get_all_user_money(key: str) -> dict[int, int]:
    return money.get_all_user_money(key)


def delete_user_account(uid: int) -> int:
    return money.delete_user_account(uid)


def tran_kira(uid: int, key: str, num: int) -> tuple[int, int]:
    return money.tran_kira(uid, key, num)


# ===== 用户背景管理 =====
_user_bg_cache: dict = {}


def _get_bg_path() -> str:
    """获取背景配置文件路径"""
    from pathlib import Path

    plugin_dir = Path(money.get_database_path()).parent
    bg_path = plugin_dir / "user_background.json"
    return str(bg_path)


def load_user_background() -> dict:
    """加载用户背景配置"""
    global _user_bg_cache
    import json

    try:
        bg_path = _get_bg_path()
        if os.path.exists(bg_path):
            with open(bg_path, "r", encoding="utf-8") as f:
                _user_bg_cache = json.load(f)
        else:
            _user_bg_cache = {}
    except Exception as e:
        logger.error(f"用户背景配置加载失败: {e}")
        _user_bg_cache = {}
    return _user_bg_cache


def save_user_background():
    """保存用户背景配置"""
    import json

    try:
        bg_path = _get_bg_path()
        with open(bg_path, "w", encoding="utf-8") as f:
            json.dump(_user_bg_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"用户背景配置保存失败: {e}")


def get_user_background(uid: int) -> dict:
    """获取用户背景配置"""
    if uid == 80000000:
        return {"default": "", "custom": "", "mode": 0}

    if not _user_bg_cache:
        load_user_background()

    uid_str = str(uid)
    if uid_str in _user_bg_cache:
        return _user_bg_cache[uid_str]
    return {"default": "", "custom": "", "mode": 0}


def set_user_background(uid: int, bg: str, kind: str = "default") -> int:
    """设置用户背景"""
    if uid == 80000000:
        return 0

    if not _user_bg_cache:
        load_user_background()

    try:
        uid_str = str(uid)
        if uid_str not in _user_bg_cache:
            _user_bg_cache[uid_str] = {"default": "", "custom": "", "mode": 0}
        _user_bg_cache[uid_str][kind] = bg
        save_user_background()
        return 1
    except:
        return 0


def set_user_bg_mode(uid: int, mode: int) -> int:
    """
    设置用户背景模式

    Args:
        uid: 用户 UID
        mode: 0-默认，1-hoshi，2-自定义
    """
    if uid == 80000000:
        return 0

    if not _user_bg_cache:
        load_user_background()

    try:
        uid_str = str(uid)
        if uid_str not in _user_bg_cache:
            _user_bg_cache[uid_str] = {"default": "", "custom": "", "mode": 0}
        _user_bg_cache[uid_str]["mode"] = mode
        save_user_background()
        return 1
    except:
        return 0


def check_mode(uid: int):
    """检查并更新用户背景模式"""
    if not _user_bg_cache:
        load_user_background()

    uid_str = str(uid)
    if uid_str not in _user_bg_cache:
        set_user_bg_mode(uid, 0)
        return

    user_data = _user_bg_cache[uid_str]
    if user_data.get("custom"):
        set_user_bg_mode(uid, 2)
    elif "hoshi" in user_data.get("default", ""):
        set_user_bg_mode(uid, 1)
    elif user_data.get("default"):
        set_user_bg_mode(uid, 0)
    else:
        set_user_background(uid, "Background3.jpg")
        set_user_bg_mode(uid, 0)
