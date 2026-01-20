"""
UID 统一管理模块

为 OneBot 和 QQ-Bot 双协议提供统一的用户标识(UID)系统。
- 自动创建唯一 UID（从 10001 开始）
- 双槽位设计：onebot_id 和 qqbot_id
- 预留手动绑定功能（后续实现）
"""

import sqlite3
from datetime import datetime
from typing import Literal, Optional

# 数据库路径
_db_path: Optional[str] = None
_db_initialized = False

# UID 起始值
UID_START = 10001


def set_database_path(path: str) -> None:
    """设置数据库路径"""
    global _db_path, _db_initialized
    _db_path = path
    _db_initialized = False


def get_database_path() -> str:
    """获取数据库路径"""
    if _db_path is None:
        raise RuntimeError("数据库路径未设置，请先调用 set_database_path()")
    return _db_path


def _get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(get_database_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_uid_database():
    """初始化 UID 数据库表结构"""
    global _db_initialized
    if _db_initialized:
        return
    
    conn = _get_connection()
    cursor = conn.cursor()
    
    # 用户 UID 映射表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_uid_mapping (
            uid INTEGER PRIMARY KEY,
            onebot_id TEXT UNIQUE,
            qqbot_id TEXT UNIQUE,
            created_at TEXT NOT NULL
        )
    ''')
    
    # UID 序列表（用于生成自增 UID）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uid_sequence (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            next_uid INTEGER NOT NULL DEFAULT 10001
        )
    ''')
    
    # 确保序列表有初始值
    cursor.execute('INSERT OR IGNORE INTO uid_sequence (id, next_uid) VALUES (1, ?)', (UID_START,))
    
    conn.commit()
    conn.close()
    _db_initialized = True


def _ensure_initialized():
    """确保数据库已初始化"""
    if not _db_initialized:
        init_uid_database()


def _get_next_uid() -> int:
    """获取下一个可用的 UID 并自增"""
    _ensure_initialized()
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT next_uid FROM uid_sequence WHERE id = 1')
    row = cursor.fetchone()
    next_uid = row['next_uid']
    
    cursor.execute('UPDATE uid_sequence SET next_uid = ? WHERE id = 1', (next_uid + 1,))
    conn.commit()
    conn.close()
    
    return next_uid


Platform = Literal["onebot", "qqbot"]


def get_uid(platform: Platform, external_id: str) -> int:
    """
    根据平台和外部 ID 获取或创建统一 UID
    
    Args:
        platform: "onebot" 或 "qqbot"
        external_id: 平台对应的用户标识（QQ号 或 OpenID）
    
    Returns:
        统一的内部 UID
    """
    _ensure_initialized()
    conn = _get_connection()
    cursor = conn.cursor()
    
    # 根据平台查询对应字段
    column = "onebot_id" if platform == "onebot" else "qqbot_id"
    
    cursor.execute(f'SELECT uid FROM user_uid_mapping WHERE {column} = ?', (external_id,))
    row = cursor.fetchone()
    
    if row:
        conn.close()
        return row['uid']
    
    # 未找到，创建新 UID
    new_uid = _get_next_uid()
    created_at = datetime.now().isoformat()
    
    if platform == "onebot":
        cursor.execute(
            'INSERT INTO user_uid_mapping (uid, onebot_id, qqbot_id, created_at) VALUES (?, ?, NULL, ?)',
            (new_uid, external_id, created_at)
        )
    else:  # qqbot
        cursor.execute(
            'INSERT INTO user_uid_mapping (uid, onebot_id, qqbot_id, created_at) VALUES (?, NULL, ?, ?)',
            (new_uid, external_id, created_at)
        )
    
    conn.commit()
    conn.close()
    
    return new_uid


def get_uid_by_external_id(platform: Platform, external_id: str) -> Optional[int]:
    """
    查询 UID（不自动创建）
    
    Args:
        platform: "onebot" 或 "qqbot"
        external_id: 平台对应的用户标识
    
    Returns:
        UID，如果未找到则返回 None
    """
    _ensure_initialized()
    conn = _get_connection()
    cursor = conn.cursor()
    
    column = "onebot_id" if platform == "onebot" else "qqbot_id"
    cursor.execute(f'SELECT uid FROM user_uid_mapping WHERE {column} = ?', (external_id,))
    row = cursor.fetchone()
    
    conn.close()
    return row['uid'] if row else None


def get_external_ids(uid: int) -> dict[str, Optional[str]]:
    """
    根据 UID 获取所有绑定的外部 ID
    
    Args:
        uid: 内部统一 UID
    
    Returns:
        {"onebot_id": ..., "qqbot_id": ...}
    """
    _ensure_initialized()
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT onebot_id, qqbot_id FROM user_uid_mapping WHERE uid = ?', (uid,))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return {
            "onebot_id": row['onebot_id'],
            "qqbot_id": row['qqbot_id']
        }
    return {"onebot_id": None, "qqbot_id": None}


def bind_external_id(uid: int, platform: Platform, external_id: str) -> bool:
    """
    为已有 UID 绑定新的外部 ID（手动绑定功能预留）
    
    Args:
        uid: 内部统一 UID
        platform: 要绑定的平台
        external_id: 外部 ID
    
    Returns:
        是否绑定成功
    """
    _ensure_initialized()
    conn = _get_connection()
    cursor = conn.cursor()
    
    column = "onebot_id" if platform == "onebot" else "qqbot_id"
    
    # 检查 UID 是否存在
    cursor.execute('SELECT uid FROM user_uid_mapping WHERE uid = ?', (uid,))
    if not cursor.fetchone():
        conn.close()
        return False
    
    # 检查该外部 ID 是否已被绑定
    cursor.execute(f'SELECT uid FROM user_uid_mapping WHERE {column} = ?', (external_id,))
    if cursor.fetchone():
        conn.close()
        return False  # 已被其他 UID 绑定
    
    # 执行绑定
    try:
        cursor.execute(f'UPDATE user_uid_mapping SET {column} = ? WHERE uid = ?', (external_id, uid))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_all_uids() -> list[int]:
    """获取所有 UID 列表"""
    _ensure_initialized()
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT uid FROM user_uid_mapping ORDER BY uid')
    rows = cursor.fetchall()
    
    conn.close()
    return [row['uid'] for row in rows]


def get_uid_count() -> int:
    """获取 UID 总数"""
    _ensure_initialized()
    conn = _get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) as count FROM user_uid_mapping')
    row = cursor.fetchone()
    
    conn.close()
    return row['count']
