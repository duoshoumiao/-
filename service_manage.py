from functools import cmp_to_key
from nonebot import CommandSession, on_command, permission as perm
from nonebot.argparse import ArgumentParser
from hoshino import Service, priv
import asyncio
import json
import time
import os
from nonebot import get_bot, scheduler

# 存储授权信息的字典，格式为 {群号: 到期时间戳}
kaiqi_groups = {}

# 使用绝对路径存储数据文件
DATA_FILE = os.path.join(os.path.dirname(__file__), 'kaiqi_groups.json')

# 加载保存的数据
def load_kaiqi_data():
    global kaiqi_groups
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                kaiqi_groups = json.load(f)
                # 转换键为整数类型（JSON保存时会变成字符串）
                kaiqi_groups = {int(k): v for k, v in kaiqi_groups.items()}
            print(f"已加载定时关闭数据，共 {len(kaiqi_groups)} 个群组")
        except Exception as e:
            print(f"加载定时关闭数据失败: {e}")
            kaiqi_groups = {}

# 保存数据到文件
def save_kaiqi_data():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(kaiqi_groups, f, ensure_ascii=False, indent=2)

# 初始化加载数据
load_kaiqi_data()

async def disable_group_services(group_id):
    """禁用指定群组的所有服务"""
    svs = Service.get_loaded_services()
    for sv in svs.values():
        sv.set_disable(group_id)
    if group_id in kaiqi_groups:
        del kaiqi_groups[group_id]
        save_kaiqi_data()
    try:
        bot = list(svs.values())[0].bot  # 获取任意一个服务的bot对象
        await bot.send_group_msg(group_id=group_id, message="")
    except Exception as e:
        print(f"")

# 定时关闭任务
async def schedule_disable(group_id, delay_seconds):
    await asyncio.sleep(delay_seconds)
    await disable_group_services(group_id)

async def restore_scheduled_tasks(bot):
    """重启后恢复所有定时任务"""
    current_time = int(time.time())
    print(f"正在恢复定时关闭任务，当前时间: {current_time}")
    
    expired_groups = []
    for group_id, expire_time in list(kaiqi_groups.items()):
        if expire_time <= current_time:
            # 已过期的任务立即执行关闭
            expired_groups.append(group_id)
        else:
            # 计算剩余时间并重新设置定时任务
            delay = expire_time - current_time
            asyncio.create_task(schedule_disable(group_id, delay))
            print(f"已恢复群 {group_id} 的定时关闭，剩余时间: {delay}秒")
    
    # 处理已过期的群组
    for group_id in expired_groups:
        await disable_group_services(group_id)
    
    print(f"定时关闭任务恢复完成，共处理 {len(kaiqi_groups)} 个群组")

PRIV_TIP = f'群主={priv.OWNER} 群管={priv.ADMIN} 群员={priv.NORMAL} bot维护组={priv.SUPERUSER}'

async def get_all_groups(bot):
    """获取机器人所在的所有群组"""
    try:
        group_list = await bot.get_group_list()
        return [g['group_id'] for g in group_list]
    except Exception as e:
        print(f"获取群列表失败: {e}")
        return []

@on_command('开启天数', aliases=('定时关闭', '临时开启'), permission=perm.GROUP, only_to_me=False)
async def enable_temporarily(session: CommandSession):
    argv = session.current_arg_text.strip().split()
    if len(argv) < 1 or not argv[0].replace('.', '').isdigit():
        await session.send("❌ 请指定开启的天数（支持小数）\n例：开启x天 1.5 (开启1天半)", at_sender=True)
        return
    
    try:
        days = float(argv[0])
    except ValueError:
        await session.send("❌ 请输入有效的天数\n例：开启x天 0.5 (开启12小时)", at_sender=True)
        return
    
    if days <= 0:
        await session.send("❌ 时间必须大于0天", at_sender=True)
        return
    
    seconds = int(days * 24 * 3600)  # 将天数转换为秒数
    
    group_id = session.ctx['group_id']
    u_priv = priv.get_user_priv(session.ctx)
    if u_priv < priv.SUPERUSER:
        await session.send(f'⚠️ 权限不足！需要：{priv.SUPERUSER}，您的：{u_priv}\n{PRIV_TIP}', at_sender=True)
        return
    
    # 启用所有服务
    svs = Service.get_loaded_services()
    for sv in svs.values():
        sv.set_enable(group_id)
    
    # 设置定时关闭
    expire_time = int(time.time()) + seconds
    kaiqi_groups[group_id] = expire_time
    save_kaiqi_data()
    
    # 启动定时任务
    asyncio.create_task(schedule_disable(group_id, seconds))
    
    # 转换时间为易读格式
    if days < 1/24/60:  # 小于1分钟
        time_str = f"{seconds}秒"
    elif days < 1/24:  # 小于1小时
        minutes = seconds // 60
        time_str = f"{minutes}分钟{seconds%60}秒"
    elif days < 1:  # 小于1天
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        time_str = f"{hours}小时{minutes}分钟"
    else:
        if days == int(days):
            time_str = f"{int(days)}天"
        else:
            total_hours = days * 24
            if total_hours == int(total_hours):
                time_str = f"{days}天 ({int(total_hours)}小时)"
            else:
                time_str = f"{days}天"
    
    await session.send(f"✅ 所有服务已开启，将在 {time_str} 后自动关闭", at_sender=True)

# 在机器人启动时恢复定时任务
@scheduler.scheduled_job('interval', minutes=5)
async def check_expired_groups():
    try:
        bot = get_bot()
        await restore_scheduled_tasks(bot)
    except Exception as e:
        print(f"检查过期群组失败: {e}")

# 以下是原有的服务管理命令（保持不变）
@on_command('lssv', aliases=('服务列表', '功能列表'), permission=perm.GROUP_ADMIN, only_to_me=False, shell_like=True)
async def lssv(session: CommandSession):
    parser = ArgumentParser(session=session)
    parser.add_argument('-a', '--all', action='store_true')
    parser.add_argument('-H', '--hidden', action='store_true')
    parser.add_argument('-g', '--group', type=int, default=0)
    args = parser.parse_args(session.argv)
    
    verbose_all = args.all
    only_hidden = args.hidden
    if session.ctx['user_id'] in session.bot.config.SUPERUSERS:
        gid = args.group or session.ctx.get('group_id')
        if not gid:
            session.finish('Usage: -g|--group <group_id> [-a|--all]')
    else:
        gid = session.ctx['group_id']

    msg = [f"群聊-{gid}服务一览："]
    svs = Service.get_loaded_services().values()
    svs = map(lambda sv: (sv, sv.check_enabled(gid)), svs)
    key = cmp_to_key(lambda x, y: (y[1] - x[1]) or (-1 if x[0].name < y[0].name else 1 if x[0].name > y[0].name else 0))
    svs = sorted(svs, key=key)
    for sv, on in svs:
        if verbose_all or (sv.visible ^ only_hidden):
            x = '○' if on else '×'
            msg.append(f"|{x}| {sv.name}")
    await session.send('\n'.join(msg))

# 启用/禁用服务
@on_command('enable', aliases=('启用', '开启', '打开'), permission=perm.GROUP, only_to_me=False)
async def enable_service(session: CommandSession):
    await switch_service(session, turn_on=True)

@on_command('disable', aliases=('禁用', '关闭'), permission=perm.GROUP, only_to_me=False)
async def disable_service(session: CommandSession):
    await switch_service(session, turn_on=False)

async def switch_service(session: CommandSession, turn_on: bool):
    action_tip = '启用' if turn_on else '禁用'
    argv = session.current_arg_text.strip().split()
    
    # 解析参数
    all_groups = False
    service_names = []
    group_ids = []
    
    for arg in argv:
        if arg in ('-a', '--all'):
            all_groups = True
        elif arg.isdigit():
            group_ids.append(int(arg))
        else:
            service_names.append(arg)
    
    if session.ctx['message_type'] == 'group':
        if all_groups:
            await session.send("❌ 群聊内不能使用 -a 参数，请私聊使用", at_sender=True)
            return
            
        if not service_names:
            session.finish(f"请指定要{action_tip}的服务名\n例：启用 天气 签到", at_sender=True)
        
        group_id = session.ctx['group_id']
        svs = Service.get_loaded_services()
        results = {'success': [], 'not_found': [], 'no_perm': []}
        
        for name in service_names:
            if name in svs:
                sv = svs[name]
                u_priv = priv.get_user_priv(session.ctx)
                if u_priv >= priv.SUPERUSER:
                    sv.set_enable(group_id) if turn_on else sv.set_disable(group_id)
                    results['success'].append(name)
                else:
                    results['no_perm'].append(name)
            else:
                results['not_found'].append(name)
        
        msg = []
        if results['success']:
            msg.append(f"✅ 已{action_tip}服务：{', '.join(results['success'])}")
        if results['no_perm']:
            msg.append(f"⚠️ 权限不足：{', '.join(results['no_perm'])}\n{PRIV_TIP}")
        
        await session.send('\n'.join(msg))
    
    else:  # 私聊模式
        if session.ctx['user_id'] not in session.bot.config.SUPERUSERS:
            return
            
        if not service_names:
            session.finish(f"请指定服务名\n例：enable 签到 -a\n或：enable 签到 123456 789012")
        
        if all_groups:
            group_ids = await get_all_groups(session.bot)
            if not group_ids:
                session.finish("❌ 获取群列表失败或未加入任何群组")
        elif not group_ids:
            session.finish("请指定群号或使用 -a 参数\n例：enable 签到 -a\n或：enable 签到 123456")
        
        svs = Service.get_loaded_services()
        valid_services = [name for name in service_names if name in svs]
        invalid_services = [name for name in service_names if name not in svs]
        
        success_groups = []
        for gid in group_ids:
            try:
                for name in valid_services:
                    sv = svs[name]
                    sv.set_enable(gid) if turn_on else sv.set_disable(gid)
                success_groups.append(gid)
            except Exception as e:
                print(f"操作群{gid}失败: {e}")
        
        msg = []
        if valid_services and success_groups:
            msg.append(f"✅ 已{action_tip}服务 {', '.join(valid_services)} 于 {len(success_groups)} 个群组")
            if len(success_groups) <= 10:
                msg.append(f"群组列表: {success_groups}")
        
        await session.send('\n'.join(msg) if msg else "没有操作被执行")
# 一键启用/禁用所有服务
@on_command('enable_all', aliases=('启用所有功能', '一键开启'), permission=perm.GROUP, only_to_me=False)
async def enable_all_services(session: CommandSession):
    await switch_all_services(session, turn_on=True)

@on_command('disable_all', aliases=('禁用所有功能', '一键关闭'), permission=perm.GROUP, only_to_me=False)
async def disable_all_services(session: CommandSession):
    await switch_all_services(session, turn_on=False)

async def switch_all_services(session: CommandSession, turn_on: bool):
    action_tip = '启用' if turn_on else '禁用'
    argv = session.current_arg_text.strip().split()
    
    # 解析参数
    all_groups = '-a' in argv or '--all' in argv
    group_ids = [int(arg) for arg in argv if arg.isdigit()]
    
    if session.ctx['message_type'] == 'group':
        if all_groups:
            await session.send("❌ 群聊内不能使用 -a 参数，请私聊使用", at_sender=True)
            return
            
        group_id = session.ctx['group_id']
        u_priv = priv.get_user_priv(session.ctx)
        if u_priv < priv.SUPERUSER:
            await session.send(f'⚠️ 权限不足！{action_tip}所有功能需要：{priv.SUPERUSER}，您的：{u_priv}\n{PRIV_TIP}', at_sender=True)
            return
        
        svs = Service.get_loaded_services()
        sv_names = []
        for name, sv in svs.items():
            if turn_on:
                sv.set_enable(group_id)
            else:
                sv.set_disable(group_id)
            sv_names.append(name)
        
        await session.send(f"✅ 已{action_tip}所有功能（共 {len(sv_names)} 个服务）", at_sender=True)
    
    else:  # 私聊模式
        if session.ctx['user_id'] not in session.bot.config.SUPERUSERS:
            return
            
        if all_groups:
            group_ids = await get_all_groups(session.bot)
            if not group_ids:
                session.finish("❌ 获取群列表失败或未加入任何群组")
        elif not group_ids:
            session.finish(f"请指定群号或使用 -a 参数\n例：disable_all -a\n或：disable_all 123456 789012")
        
        svs = Service.get_loaded_services()
        success_groups = []
        for gid in group_ids:
            try:
                for sv in svs.values():
                    if turn_on:
                        sv.set_enable(gid)
                    else:
                        sv.set_disable(gid)
                success_groups.append(gid)
            except Exception as e:
                print(f"操作群{gid}失败: {e}")
        
        msg = f"✅ 所有服务已于 {len(success_groups)} 个群组内{action_tip}"
        if len(success_groups) <= 10:
            msg += f"\n群组列表: {success_groups}"
        await session.send(msg)

# 启用除指定外的所有服务
@on_command('enable_except', aliases=('一键开启除了', '启用除了', '开启除了'), permission=perm.GROUP, only_to_me=False)
async def enable_except_services(session: CommandSession):
    argv = session.current_arg_text.strip().split()
    
    # 解析参数
    all_groups = '-a' in argv or '--all' in argv
    except_names = [arg for arg in argv if not arg.isdigit() and arg not in ('-a', '--all')]
    group_ids = [int(arg) for arg in argv if arg.isdigit()]
    
    if session.ctx['message_type'] == 'group':
        if all_groups:
            await session.send("❌ 群聊内不能使用 -a 参数，请私聊使用", at_sender=True)
            return
            
        if not except_names:
            session.finish("请指定要排除的服务名\n例：启用除了 抽卡 签到", at_sender=True)
        
        group_id = session.ctx['group_id']
        u_priv = priv.get_user_priv(session.ctx)
        if u_priv < priv.SUPERUSER:
            await session.send(f'⚠️ 权限不足！需要：{priv.SUPERUSER}，您的：{u_priv}\n{PRIV_TIP}', at_sender=True)
            return
            
        svs = Service.get_loaded_services()
        enabled = []
        skipped = []
        
        for name, sv in svs.items():
            if name in except_names:
                skipped.append(name)
                continue
            sv.set_enable(group_id)
            enabled.append(name)
            
        msg = [
            f"✅ 已启用 {len(enabled)} 个服务",
            f"⏭️ 已跳过 {len(skipped)} 个服务: {', '.join(skipped)}"
        ]
        await session.send('\n'.join(msg), at_sender=True)
    
    else:  # 私聊模式
        if session.ctx['user_id'] not in session.bot.config.SUPERUSERS:
            return
            
        if not except_names:
            session.finish("请指定要排除的服务名\n例：enable_except 抽卡 -a\n或：enable_except 抽卡 123456")
        
        if all_groups:
            group_ids = await get_all_groups(session.bot)
            if not group_ids:
                session.finish("❌ 获取群列表失败或未加入任何群组")
        elif not group_ids:
            session.finish("请指定群号或使用 -a 参数")
        
        svs = Service.get_loaded_services()
        enabled_sv = [name for name in svs.keys() if name not in except_names]
        success_groups = []
        
        for gid in group_ids:
            try:
                for name in enabled_sv:
                    svs[name].set_enable(gid)
                success_groups.append(gid)
            except Exception as e:
                print(f"操作群{gid}失败: {e}")
        
        msg = [
            f"✅ 已为 {len(success_groups)} 个群组启用除了 {', '.join(except_names)} 外的服务",
            f"📋 共启用 {len(enabled_sv)} 个服务"
        ]
        if len(success_groups) <= 10:
            msg.append(f"群组列表: {success_groups}")
        await session.send('\n'.join(msg))        

# 在模块加载时恢复定时任务
async def on_bot_startup():
    try:
        bot = get_bot()
        await restore_scheduled_tasks(bot)
    except Exception as e:
        print(f"启动时恢复定时任务失败: {e}")

# 注册启动钩子
from nonebot import on_startup
on_startup(on_bot_startup)