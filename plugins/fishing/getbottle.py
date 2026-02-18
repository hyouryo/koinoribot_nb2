"""
漂流瓶模块 - getbottle.py

使用 SQLite 存储漂流瓶数据（bottles + bottle_comments 表）
"""

import time
import random
from typing import Optional, Tuple

from nonebot import logger

from .util import DatabaseManager


class BottleManager:
    """漂流瓶管理器（SQLite 版）"""

    @classmethod
    def get_next_bottle_id(cls) -> str:
        """获取下一个漂流瓶ID（基于 AUTOINCREMENT，仅供预览）"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'bottles'"
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return str(row[0] + 1)
        return "10001"

    @classmethod
    def create_bottle(cls, bottle_id: str, uid: int, group_id: str, content: str) -> str:
        """
        创建新漂流瓶

        Args:
            bottle_id: 预留参数（实际使用 AUTOINCREMENT，忽略此值）
            uid: 用户ID
            group_id: 群组ID
            content: 漂流瓶内容

        Returns:
            实际的漂流瓶ID
        """
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO bottles (uid, group_id, content, created_time) VALUES (?, ?, ?, ?)",
            (uid, group_id, content, int(time.time()))
        )
        real_id = str(cursor.lastrowid)
        conn.commit()
        conn.close()
        return real_id

    @classmethod
    def get_bottle_amount(cls) -> int:
        """获取有效漂流瓶数量（未删除的）"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM bottles WHERE deleted = 0")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    @classmethod
    def pick_random_bottle(cls) -> Tuple[Optional[str], Optional[dict]]:
        """
        随机捞取一个漂流瓶

        Returns:
            (bottle_id, bottle_data_dict) 或 (None, None)
        """
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()

        # 随机选一个未删除的漂流瓶
        cursor.execute(
            "SELECT id, uid, group_id, content, pick_count, created_time "
            "FROM bottles WHERE deleted = 0 ORDER BY RANDOM() LIMIT 1"
        )
        row = cursor.fetchone()

        if row is None:
            conn.close()
            return None, None

        bottle_id = str(row["id"])

        # 更新捞取次数
        new_pick = row["pick_count"] + 1
        cursor.execute(
            "UPDATE bottles SET pick_count = ? WHERE id = ?",
            (new_pick, row["id"])
        )
        conn.commit()

        # 查询评论
        cursor.execute(
            "SELECT uid, content, created_time FROM bottle_comments "
            "WHERE bottle_id = ? ORDER BY created_time ASC",
            (row["id"],)
        )
        comments = [
            {"uid": c["uid"], "content": c["content"], "time": c["created_time"]}
            for c in cursor.fetchall()
        ]

        conn.close()

        bottle = {
            "uid": row["uid"],
            "group_id": row["group_id"],
            "content": row["content"],
            "pick_count": new_pick,
            "time": row["created_time"],
            "comments": comments,
        }

        return bottle_id, bottle

    @classmethod
    def add_comment(cls, bottle_id: str, uid: int, content: str) -> bool:
        """
        给漂流瓶添加评论

        Args:
            bottle_id: 漂流瓶ID
            uid: 评论者UID
            content: 评论内容

        Returns:
            是否成功添加
        """
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()

        # 检查漂流瓶是否存在且未删除
        cursor.execute(
            "SELECT id FROM bottles WHERE id = ? AND deleted = 0",
            (int(bottle_id),)
        )
        if cursor.fetchone() is None:
            conn.close()
            return False

        cursor.execute(
            "INSERT INTO bottle_comments (bottle_id, uid, content, created_time) VALUES (?, ?, ?, ?)",
            (int(bottle_id), uid, content, int(time.time()))
        )
        conn.commit()
        conn.close()
        return True

    @classmethod
    def delete_bottle(cls, bottle_id: str) -> bool:
        """
        删除漂流瓶（软删除）

        Args:
            bottle_id: 漂流瓶ID

        Returns:
            是否成功删除
        """
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE bottles SET deleted = 1 WHERE id = ? AND deleted = 0",
            (int(bottle_id),)
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0
