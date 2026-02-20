import sqlite3
import os
from pathlib import Path
from nonebot.log import logger

from typing import Optional

# 数据库文件路径
DB_PATH: Optional[str] = None
_db_initialized = False


def set_db_path(path: str):
    """设置数据库路径"""
    global DB_PATH, _db_initialized
    DB_PATH = path
    _db_initialized = False


def get_database_path() -> str:
    """获取数据库路径"""
    if DB_PATH is None:
        raise RuntimeError("数据库路径未设置，请先调用 set_db_path()")
    return DB_PATH


def _get_connection():
    """获取数据库连接"""
    return sqlite3.connect(get_database_path())


def init_nickname_database():
    """确保数据库已初始化"""
    global _db_initialized
    if _db_initialized:
        return
    _init_db()
    _db_initialized = True


def _init_db():
    """初始化数据库表"""
    try:
        os.makedirs(os.path.dirname(get_database_path()), exist_ok=True)
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS call_me_please_users (
                    uid INTEGER PRIMARY KEY,
                    nickname TEXT NOT NULL
                )
                '''
            )
            conn.commit()
    except Exception as e:
        logger.error(f"[call_me_please] 数据库初始化失败: {e}")


def get_user_nickname(uid: int) -> str:
    """获取用户设定的昵称"""
    init_nickname_database()
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT nickname FROM call_me_please_users WHERE uid = ?", (uid,))
            row = cursor.fetchone()
            if row:
                return row[0]
            return ""
    except Exception as e:
        logger.error(f"[call_me_please] 获取用户昵称失败: {e}")
        return ""


def set_user_nickname(uid: int, nickname: str) -> bool:
    """设定或更新用户昵称"""
    init_nickname_database()
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO call_me_please_users (uid, nickname)
                VALUES (?, ?)
                ON CONFLICT(uid) DO UPDATE SET nickname=excluded.nickname
                ''',
                (uid, nickname)
            )
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"[call_me_please] 更新用户昵称失败: {e}")
        return False
