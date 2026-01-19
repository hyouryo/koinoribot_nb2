"""
漂流瓶模块 - getbottle.py

包含漂流瓶管理类
"""

from pathlib import Path
from typing import Dict, Optional

from ...utils import save_data, load_data


class BottleManager:
    """漂流瓶管理器"""
    
    _bottle_path: Optional[str] = None
    
    @classmethod
    def get_bottle_path(cls) -> str:
        """获取漂流瓶数据路径"""
        if cls._bottle_path is None:
            plugin_dir = Path(__file__).parent.parent.parent
            cls._bottle_path = str(plugin_dir / "src" / "database" / "sea.json")
        return cls._bottle_path
    
    @classmethod
    def set_bottle_path(cls, path: str):
        """设置漂流瓶数据路径（用于测试或自定义路径）"""
        cls._bottle_path = path
    
    @classmethod
    def get_bottles(cls) -> dict:
        """获取所有漂流瓶"""
        return load_data(cls.get_bottle_path())
    
    @classmethod
    def save_bottles(cls, data: dict):
        """保存漂流瓶数据"""
        save_data(data, cls.get_bottle_path())
    
    @classmethod
    def get_bottle_amount(cls) -> int:
        """获取有效漂流瓶数量（未删除的）"""
        bottles = cls.get_bottles()
        return len([b for b in bottles.values() if not b.get('deleted', False)])
    
    @classmethod
    def create_bottle(cls, bottle_id: str, uid: int, group_id: str, content: str) -> None:
        """
        创建新漂流瓶
        
        Args:
            bottle_id: 漂流瓶ID
            uid: 用户ID
            group_id: 群组ID
            content: 漂流瓶内容
        """
        import time
        bottles = cls.get_bottles()
        bottles[bottle_id] = {
            'uid': uid,
            'group_id': group_id,
            'time': int(time.time()),
            'content': content,
            'pick_count': 0,
            'comments': [],
            'deleted': False
        }
        cls.save_bottles(bottles)
    
    @classmethod
    def pick_random_bottle(cls) -> tuple:
        """
        随机捞取一个漂流瓶
        
        Returns:
            (bottle_id, bottle_data) 或 (None, None) 如果没有可用漂流瓶
        """
        import random
        bottles = cls.get_bottles()
        available = [(bid, b) for bid, b in bottles.items() if not b.get('deleted', False)]
        
        if not available:
            return None, None
        
        bottle_id, bottle = random.choice(available)
        
        # 更新捞取次数
        bottles[bottle_id]['pick_count'] = bottles[bottle_id].get('pick_count', 0) + 1
        cls.save_bottles(bottles)
        
        return bottle_id, bottles[bottle_id]
    
    @classmethod
    def add_comment(cls, bottle_id: str, uid: int, content: str) -> bool:
        """
        给漂流瓶添加评论
        
        Args:
            bottle_id: 漂流瓶ID
            uid: 评论者ID
            content: 评论内容
            
        Returns:
            是否成功添加
        """
        import time
        bottles = cls.get_bottles()
        
        if bottle_id not in bottles or bottles[bottle_id].get('deleted', False):
            return False
        
        if 'comments' not in bottles[bottle_id]:
            bottles[bottle_id]['comments'] = []
        
        bottles[bottle_id]['comments'].append({
            'uid': uid,
            'content': content,
            'time': int(time.time())
        })
        cls.save_bottles(bottles)
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
        bottles = cls.get_bottles()
        if bottle_id not in bottles:
            return False
        
        bottles[bottle_id]['deleted'] = True
        cls.save_bottles(bottles)
        return True
