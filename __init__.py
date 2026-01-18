"""
Koinoribot NB2 - 主插件入口

从旧版 hoshinobot/nonebot1.8 迁移的 koinoribot
支持 OneBot V11 和 QQ-Bot 双协议
"""

from pathlib import Path
import nonebot
from nonebot import get_plugin_config, get_driver
from nonebot.plugin import PluginMetadata

from .config import Config

# 导入核心模块
from . import uid_manager
from . import money
from . import resources
from .koinori_config import config as koinori_config

__plugin_meta__ = PluginMetadata(
    name="koinoribot_nb2",
    description="Koinoribot NoneBot2 版本 - 集成多种娱乐功能",
    usage="签到、钓鱼、宠物、炒股、红包等功能",
    config=Config,
)

# 获取配置
config = get_plugin_config(Config)

# 获取驱动器
driver = get_driver()


@driver.on_startup
async def init_koinoribot():
    """初始化 koinoribot"""
    # 设置资源目录
    plugin_dir = Path(__file__).parent
    src_dir = plugin_dir / "src"
    resources.set_resource_dir(src_dir)
    
    # 设置数据库路径
    db_path = src_dir / "database" / "koinoribot.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    uid_manager.set_database_path(str(db_path))
    money.set_database_path(str(db_path))
    
    # 初始化数据库
    uid_manager.init_uid_database()
    money.init_money_database()
    
    nonebot.logger.info("Koinoribot NB2 初始化完成")


# 加载子插件
sub_plugins = nonebot.load_plugins(
    str(Path(__file__).parent.joinpath("plugins").resolve())
)
