"""
公网多端白名单子插件 - public_whitelist

只有白名单中的bot才能触发事件。
领养流程：用户申请 → SU审核 → 通过后加入白名单。
使用SQLite持久化，启动时和新增/删除白名单时更新内存缓存。

迁移自旧版 koinoribot public_whitelist
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Set, List

import nonebot.adapters.onebot.v11 as onebot_adapter
from nonebot import on_command, get_driver
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Event, Bot, Message
from nonebot import logger
from nonebot.params import CommandArg, Depends
from nonebot.message import event_preprocessor
from nonebot.exception import IgnoredException

from ...tools import (
    get_uid, get_group_id_optional, build_forward_node,
    send_group_forward_msg, get_sender_nickname, is_onebot, is_qqbot
)
from ...uid_manager import get_external_ids
from ...su_manager import is_su
from ...koinori_config import get_config

__plugin_meta__ = PluginMetadata(
    name="public_whitelist",
    description="公网多端白名单管理 — 领养申请 + SU审核 + 白名单过滤",
    usage="领养云冰祈 / 审核列表 / 审核通过 <id> / 审核拒绝 <id> / 查询领养状态",
)

# ================== 数据库 ==================

def _get_db_path() -> str:
    plugin_dir = Path(__file__).parent.parent
    return str(plugin_dir / "src" / "database" / "koinoribot.db")


def _init_tables():
    conn = sqlite3.connect(_get_db_path())
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS public_whitelist (
                owner_qq TEXT PRIMARY KEY,
                bot_qq TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS whitelist_review (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_qq TEXT NOT NULL,
                bot_qq TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                compliance_commit TEXT NOT NULL DEFAULT '',
                group_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer_qq TEXT DEFAULT NULL,
                review_comment TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT DEFAULT NULL
            )
        ''')
        conn.commit()
    finally:
        conn.close()


# ================== 内存缓存 ==================

_cache_owner_to_bot: Dict[str, str] = {}
_cache_bot_set: Set[str] = set()


def load_cache():
    global _cache_owner_to_bot, _cache_bot_set
    conn = sqlite3.connect(_get_db_path())
    try:
        rows = conn.execute(
            'SELECT owner_qq, bot_qq FROM public_whitelist'
        ).fetchall()
        _cache_owner_to_bot = {row[0]: row[1] for row in rows}
        _cache_bot_set = {row[1] for row in rows}
        logger.info(f"[public_whitelist] 已加载 {len(_cache_owner_to_bot)} 个白名单bot到内存")
    finally:
        conn.close()


def is_whitelisted(bot_qq: str) -> bool:
    return bot_qq in _cache_bot_set


def get_owner(bot_qq: str) -> Optional[str]:
    for owner, bqq in _cache_owner_to_bot.items():
        if bqq == bot_qq:
            return owner
    return None


def add_to_whitelist(owner_qq: str, bot_qq: str) -> bool:
    conn = sqlite3.connect(_get_db_path())
    try:
        conn.execute(
            'INSERT INTO public_whitelist (owner_qq, bot_qq, created_at) VALUES (?, ?, ?)',
            (owner_qq, bot_qq, datetime.now().isoformat())
        )
        conn.commit()
        _cache_owner_to_bot[owner_qq] = bot_qq
        _cache_bot_set.add(bot_qq)
        logger.info(f"[public_whitelist] 添加白名单: owner={owner_qq}, bot={bot_qq}")
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_from_whitelist(owner_qq: str) -> Optional[str]:
    conn = sqlite3.connect(_get_db_path())
    try:
        row = conn.execute(
            'SELECT bot_qq FROM public_whitelist WHERE owner_qq = ?', (owner_qq,)
        ).fetchone()
        if not row:
            return None
        bot_qq = row[0]
        conn.execute('DELETE FROM public_whitelist WHERE owner_qq = ?', (owner_qq,))
        conn.commit()
        _cache_owner_to_bot.pop(owner_qq, None)
        _cache_bot_set.discard(bot_qq)
        logger.info(f"[public_whitelist] 删除白名单: owner={owner_qq}, bot={bot_qq}")
        return bot_qq
    finally:
        conn.close()


def get_whitelist_size() -> int:
    return len(_cache_owner_to_bot)


# ================== WS地址配置 ==================

_address_config: dict = {}
_address_file: Path = Path(__file__).parent / "address.json"

ADDRESS_TEMPLATE = {
    "ws_address": "ws://your_ip:port/ws",
    "connection_help": [
        "请依次对你的bot私聊发送以下每一行内容。(确保你的云崽安装了ws-plugin)",
        "#ws添加连接",
        "ko,1",
        "ws://your_ip:port/ws,5,0"
    ]
}


def load_address_config():
    """加载 address.json，不存在则创建空白模板"""
    global _address_config
    if _address_file.exists():
        try:
            with open(_address_file, 'r', encoding='utf-8') as f:
                _address_config = json.load(f)
            logger.info(f"[public_whitelist] 已加载WS地址配置: {_address_config.get('ws_address', '未设置')}")
        except Exception as e:
            logger.warning(f"[public_whitelist] 加载 address.json 失败: {e}，使用空白模板")
            _address_config = ADDRESS_TEMPLATE.copy()
    else:
        _address_config = ADDRESS_TEMPLATE.copy()
        try:
            with open(_address_file, 'w', encoding='utf-8') as f:
                json.dump(ADDRESS_TEMPLATE, f, ensure_ascii=False, indent=2)
            logger.info(f"[public_whitelist] 已创建 address.json 模板: {_address_file}")
        except Exception as e:
            logger.warning(f"[public_whitelist] 创建 address.json 失败: {e}")


def get_ws_info() -> dict:
    """获取WS连接信息"""
    return _address_config.copy()


# ================== 跨平台私信 ==================

async def send_private_message(bot: Bot, event: Event, uid: int, message: str):
    """跨平台发送私聊消息（OneBot用send_private_msg，QQ-Bot用send_to_c2c）"""
    external_ids = get_external_ids(uid)

    if is_onebot(event):
        qq = external_ids.get('onebot_id')
        if qq:
            try:
                await bot.send_private_msg(user_id=int(qq), message=message)
                return
            except Exception as e:
                logger.error(f"[public_whitelist] OneBot私信发送失败: {e}")

    if is_qqbot(event):
        openid = external_ids.get('qqbot_id')
        if openid:
            try:
                await bot.send_to_c2c(openid=openid, message=message)
                return
            except Exception as e:
                logger.error(f"[public_whitelist] QQ-Bot私信发送失败: {e}")

    logger.warning(f"[public_whitelist] 无法发送私信: uid={uid}, onebot_id={external_ids.get('onebot_id')}, qqbot_id={external_ids.get('qqbot_id')}")


# ================== 事件过滤器 ==================

@event_preprocessor
async def _whitelist_filter(event: Event):
    config = get_config()
    if not config.public_bot:
        return

    self_id = str(getattr(event, 'self_id', ''))
    if not self_id:
        return

    permit_bot = {str(b) for b in config.permit_bot}
    if not permit_bot:
        return

    if self_id not in permit_bot:
        return

    if not _cache_bot_set:
        return

    if self_id not in _cache_bot_set:
        raise IgnoredException(
            f"[public_whitelist] bot({self_id}) 不在白名单中，事件已忽略"
        )


# ================== 领养申请上下文（内存，多轮对话用） ==================

_apply_context: Dict[str, dict] = {}  # {user_id: {step, owner_qq, bot_qq, reason, ...}}


# ================== 领养云冰祈 — 多轮对话 ==================

adopt_cmd = on_command("领养云冰祈", priority=5, block=True)


@adopt_cmd.handle()
async def handle_adopt_start(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """领养云冰祈 — 第一步：检查资格，开始流程"""
    group_id = get_group_id_optional(event)

    if not group_id:
        await adopt_cmd.finish("领养云冰祈仅支持群聊~")

    # 获取主人QQ号（必须绑定QQ号才能领养）
    external_ids = get_external_ids(uid)
    owner_qq = external_ids.get('onebot_id')
    if not owner_qq:
        await adopt_cmd.finish(
            "你还没有绑定QQ号，无法领养云冰祈~\n"
            "请先在onebot端使用bot，或在设置中绑定QQ号",
            at_sender=True
        )

    # 检查是否已有白名单
    if owner_qq in _cache_owner_to_bot:
        await adopt_cmd.finish(
            "你已经领养过一个云冰祈了~\n如果想重新领养，请先 注销云冰祈",
            at_sender=True
        )

    # 检查是否已有待审核的申请
    conn = sqlite3.connect(_get_db_path())
    try:
        row = conn.execute(
            'SELECT id FROM whitelist_review WHERE owner_qq = ? AND status = ?',
            (owner_qq, 'pending')
        ).fetchone()
        if row:
            await adopt_cmd.finish(
                f"你已有一个待审核的领养申请（ID: {row[0]}），请耐心等待审核~",
                at_sender=True
            )
    finally:
        conn.close()

    # 初始化申请上下文（key 用 event.get_user_id() 以便 pause 后匹配）
    _apply_context[event.get_user_id()] = {
        'step': 'bot_qq',
        'owner_qq': owner_qq,
        'bot_qq': '',
        'reason': '',
        'compliance_commit': '',
        'group_id': group_id,
    }

    await adopt_cmd.send(
        "要领养云冰祈咯~\n请先确保已添加bot为好友（否则发不出私信）。\n\n请输入要注册的bot的QQ号（回复 退出 结束领养）：",
        at_sender=True
    )
    await adopt_cmd.pause()


@adopt_cmd.handle()
async def handle_adopt_step(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """领养云冰祈 — 多轮对话步骤处理"""
    user_id = event.get_user_id()
    user_input = event.get_plaintext().strip()

    ctx = _apply_context.get(user_id)
    if not ctx:
        return

    step = ctx.get('step', '')

    if user_input == '退出':
        _apply_context.pop(user_id, None)
        await adopt_cmd.finish("已结束领养云冰祈~", at_sender=True)

    # Step 1: 输入bot QQ
    if step == 'bot_qq':
        if not user_input.isdigit():
            await adopt_cmd.reject("需要输入QQ号码~", at_sender=True)

        if user_input == user_id:
            await adopt_cmd.reject("请使用bot账号的QQ~而且不能是自己的QQ", at_sender=True)

        # 检查bot QQ是否已被注册
        if user_input in _cache_bot_set:
            await adopt_cmd.finish("该bot已被认领~", at_sender=True)

        # 检查bot QQ是否已有待审核申请
        conn = sqlite3.connect(_get_db_path())
        try:
            row = conn.execute(
                'SELECT id FROM whitelist_review WHERE bot_qq = ? AND status = ?',
                (user_input, 'pending')
            ).fetchone()
            if row:
                await adopt_cmd.finish("该bot已有待审核的领养申请~", at_sender=True)
        finally:
            conn.close()

        ctx['bot_qq'] = user_input
        ctx['step'] = 'reason'
        await adopt_cmd.send(
            f"bot QQ: {user_input}\n\n请输入领养理由（如：想让bot活跃群气氛、在别的群使用冰祈、仅自用等）：",
            at_sender=True
        )
        await adopt_cmd.pause()
        return

    # Step 2: 输入领养理由
    if step == 'reason':
        ctx['reason'] = user_input
        ctx['step'] = 'compliance'
        await adopt_cmd.send(
            "请确认是否承诺合规使用云冰祈：\n"
            "- 不用于违法、违规用途\n"
            "- 不用于骚扰、广告等行为\n"
            "- 遵守QQ平台用户协议\n\n"
            "请回复 我承诺合规使用 确认：",
            at_sender=True
        )
        await adopt_cmd.pause()
        return

    # Step 3: 确认合规承诺
    if step == 'compliance':
        if user_input != '我承诺合规使用':
            await adopt_cmd.reject(
                "请回复 我承诺合规使用 来确认承诺，或回复 退出 取消申请",
                at_sender=True
            )

        ctx['compliance_commit'] = user_input
        ctx['step'] = 'confirm'

        # 汇总信息
        summary = (
            "=== 领养申请确认 ===\n"
            f"主人QQ: {ctx['owner_qq']}\n"
            f"bot QQ: {ctx['bot_qq']}\n"
            f"领养理由: {ctx['reason']}\n"
            f"合规承诺: {ctx['compliance_commit']}\n"
            f"申请群号: {ctx['group_id']}\n"
            f"申请时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"==================\n"
            "回复 确认提交 提交审核，或回复 退出 取消"
        )
        await adopt_cmd.send(summary, at_sender=True)
        await adopt_cmd.pause()
        return

    # Step 4: 确认提交
    if step == 'confirm':
        if user_input != '确认提交':
            await adopt_cmd.reject(
                "请回复 确认提交 来提交申请，或回复 退出 取消",
                at_sender=True
            )

        # 保存到审核列表
        now_iso = datetime.now().isoformat()
        conn = sqlite3.connect(_get_db_path())
        try:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO whitelist_review
                   (owner_qq, bot_qq, reason, compliance_commit, group_id, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (ctx['owner_qq'], ctx['bot_qq'], ctx['reason'],
                 ctx['compliance_commit'], ctx['group_id'], 'pending', now_iso)
            )
            conn.commit()
            review_id = cursor.lastrowid
        finally:
            conn.close()

        owner_qq = ctx['owner_qq']
        _apply_context.pop(user_id, None)

        # 发送WS连接信息私信
        ws_info = get_ws_info()
        ws_help = "\n".join(ws_info.get('connection_help', []))
        await send_private_message(bot, event, uid,
            f"=== 云冰祈领养申请已提交 ===\n"
            f"申请编号: {review_id}\n"
            f"bot QQ: {ctx['bot_qq']}\n\n"
            f"请先配置你的bot连接：\n{ws_help}\n\n"
            f"WS地址: {ws_info.get('ws_address', '未配置')}\n\n"
            f"审核通过后你的bot即可接入~\n"
            f"发送「查询领养状态」查看进度"
        )

        await adopt_cmd.finish(
            f"领养申请已提交！\n申请编号: {review_id}\n"
            "WS连接信息已通过私信发送，请注意查收~\n"
            "请耐心等待管理员审核，发送「查询领养状态」查看进度",
            at_sender=True
        )


# ================== SU审核命令 ==================

review_list_cmd = on_command("审核列表", aliases={"审核云冰祈"}, priority=5, block=True)


@review_list_cmd.handle()
async def handle_review_list(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """SU查看待审核列表（合并转发消息）"""
    if not is_su(uid):
        return

    conn = sqlite3.connect(_get_db_path())
    try:
        rows = conn.execute(
            '''SELECT id, owner_qq, bot_qq, reason, compliance_commit,
                      group_id, created_at
               FROM whitelist_review
               WHERE status = 'pending'
               ORDER BY id ASC'''
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        await review_list_cmd.finish("没有待审核的领养申请~")

    chain = onebot_adapter.Message()
    for row in rows:
        info = (
            f"=== 审核编号: {row[0]} ===\n"
            f"主人QQ: {row[1]}\n"
            f"bot QQ: {row[2]}\n"
            f"领养理由: {row[3]}\n"
            f"合规承诺: {row[4]}\n"
            f"申请群号: {row[5]}\n"
            f"申请时间: {row[6]}\n"
            "——————————————\n"
            "操作: 审核通过 {id}  或  审核拒绝 {id} [理由]"
        )
        node = await build_forward_node(bot, info)
        chain.append(node)

    chain.append(await build_forward_node(bot, f"共 {len(rows)} 条待审核申请"))

    if isinstance(event, onebot_adapter.GroupMessageEvent):
        await bot.send_group_forward_msg(group_id=event.group_id, messages=chain)
    else:
        await bot.send_private_forward_msg(user_id=event.get_user_id(), messages=chain)


approve_cmd = on_command("审核通过", priority=5, block=True)


@approve_cmd.handle()
async def handle_approve(
    event: Event,
    bot: Bot,
    args: Message = CommandArg(),
    uid: int = Depends(get_uid)
):
    """SU审核通过"""
    if not is_su(uid):
        return

    text = args.extract_plain_text().strip()
    try:
        review_id = int(text.split()[0])
    except (ValueError, IndexError):
        await approve_cmd.finish("用法: 审核通过 <申请编号>")

    conn = sqlite3.connect(_get_db_path())
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            'SELECT owner_qq, bot_qq FROM whitelist_review WHERE id = ? AND status = ?',
            (review_id, 'pending')
        ).fetchone()

        if not row:
            await approve_cmd.finish(f"申请编号 {review_id} 不存在或已处理")

        owner_qq, bot_qq = row[0], row[1]

        # 添加到白名单
        if not add_to_whitelist(owner_qq, bot_qq):
            await approve_cmd.finish(
                f"添加白名单失败：主人({owner_qq})或bot({bot_qq})已存在"
            )

        # 更新审核状态
        now_iso = datetime.now().isoformat()
        cursor.execute(
            '''UPDATE whitelist_review
               SET status = 'approved', reviewer_qq = ?, reviewed_at = ?
               WHERE id = ?''',
            (str(event.get_user_id()), now_iso, review_id)
        )
        conn.commit()
    finally:
        conn.close()

    await approve_cmd.finish(
        f"审核通过！bot({bot_qq})已加入白名单，绑定主人({owner_qq})"
    )


reject_cmd = on_command("审核拒绝", priority=5, block=True)


@reject_cmd.handle()
async def handle_reject(
    event: Event,
    bot: Bot,
    args: Message = CommandArg(),
    uid: int = Depends(get_uid)
):
    """SU审核拒绝"""
    if not is_su(uid):
        return

    text = args.extract_plain_text().strip()
    parts = text.split(maxsplit=1)
    try:
        review_id = int(parts[0])
    except (ValueError, IndexError):
        await reject_cmd.finish("用法: 审核拒绝 <申请编号> [理由]")

    reason = parts[1] if len(parts) > 1 else "无"

    conn = sqlite3.connect(_get_db_path())
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            'SELECT owner_qq, bot_qq FROM whitelist_review WHERE id = ? AND status = ?',
            (review_id, 'pending')
        ).fetchone()

        if not row:
            await reject_cmd.finish(f"申请编号 {review_id} 不存在或已处理")

        now_iso = datetime.now().isoformat()
        cursor.execute(
            '''UPDATE whitelist_review
               SET status = 'rejected', reviewer_qq = ?, review_comment = ?, reviewed_at = ?
               WHERE id = ?''',
            (str(event.get_user_id()), reason, now_iso, review_id)
        )
        conn.commit()
    finally:
        conn.close()

    await reject_cmd.finish(
        f"已拒绝申请编号 {review_id} (bot: {row[1]})\n理由: {reason}"
    )


# ================== 用户自助查询 ==================

query_cmd = on_command("查询领养状态", aliases={"我的领养"}, priority=5, block=True)


@query_cmd.handle()
async def handle_query_status(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """用户自助查询领养审核状态"""
    external_ids = get_external_ids(uid)
    owner_qq = external_ids.get('onebot_id')
    if not owner_qq:
        await query_cmd.finish("你还没有绑定QQ号~", at_sender=True)

    # 先查白名单
    if owner_qq in _cache_owner_to_bot:
        bot_qq = _cache_owner_to_bot[owner_qq]
        await query_cmd.finish(
            f"你已成功领养云冰祈~\n主人QQ: {owner_qq}\nbot QQ: {bot_qq}",
            at_sender=True
        )

    # 查审核列表
    conn = sqlite3.connect(_get_db_path())
    try:
        rows = conn.execute(
            '''SELECT id, bot_qq, status, reason, review_comment, reviewed_at, created_at
               FROM whitelist_review
               WHERE owner_qq = ?
               ORDER BY id DESC LIMIT 5''',
            (owner_qq,)
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        await query_cmd.finish("你还没有领养过云冰祈~\n发送 领养云冰祈 开始领养", at_sender=True)

    status_map = {'pending': '待审核', 'approved': '已通过', 'rejected': '已拒绝'}
    lines = ["=== 领养状态查询 ==="]
    for row in rows:
        status_text = status_map.get(row[2], row[2])
        line = (
            f"申请编号: {row[0]}\n"
            f"bot QQ: {row[1]}\n"
            f"审核状态: {status_text}\n"
            f"申请时间: {row[6]}"
        )
        if row[2] == 'rejected':
            line += f"\n拒绝理由: {row[4] or '无'}"
        if row[2] == 'approved':
            line += f"\n通过时间: {row[5]}"
        lines.append(line)

    await query_cmd.finish("\n\n".join(lines), at_sender=True)


# ================== SU手动添加白名单 ==================

add_wl = on_command("添加公网白名单", priority=5, block=True)


@add_wl.handle()
async def handle_add_whitelist(
    event: Event,
    bot: Bot,
    args: Message = CommandArg(),
    uid: int = Depends(get_uid)
):
    """SU手动添加白名单（跳过审核）"""
    if not is_su(uid):
        return

    text = args.extract_plain_text().strip()
    parts = text.split()
    if len(parts) != 2:
        await add_wl.finish("用法: 添加公网白名单 <主人QQ> <botQQ>")

    owner_qq = parts[0]
    bot_qq = parts[1]

    if not bot_qq.isdigit():
        await add_wl.finish("botQQ必须是数字")

    if owner_qq in _cache_owner_to_bot:
        await add_wl.finish("该主人已有bot~")
    if bot_qq in _cache_bot_set:
        await add_wl.finish("该bot已被认领~")

    if add_to_whitelist(owner_qq, bot_qq):
        await add_wl.finish(f"已成功添加该bot({bot_qq})，并绑定主人({owner_qq})")
    else:
        await add_wl.finish("添加失败，可能已存在")


# ================== 注销云冰祈 ==================

logout_wl = on_command("注销云冰祈", priority=5, block=True)


@logout_wl.handle()
async def handle_logout_whitelist(
    event: Event,
    bot: Bot,
    uid: int = Depends(get_uid)
):
    """用户自助注销云冰祈"""
    external_ids = get_external_ids(uid)
    owner_qq = external_ids.get('onebot_id')
    if not owner_qq:
        await logout_wl.finish("你还没有绑定QQ号~", at_sender=True)

    bot_qq = remove_from_whitelist(owner_qq)
    if bot_qq:
        await logout_wl.finish(f"bot({bot_qq})注销云冰祈了...", at_sender=True)
    else:
        await logout_wl.finish("你还没有领养云冰祈...", at_sender=True)


# ================== 启动初始化 ==================

driver = get_driver()


@driver.on_startup
async def _init_whitelist():
    _init_tables()
    load_cache()
    load_address_config()
