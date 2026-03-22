import os
import json
import requests
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# =============== 工具函数 ===============

def clean_checkin_msg(msg: str) -> str:
    """精简签到消息：移除链接、广告、Emby等无关内容"""
    # 过滤黑名单
    junk_keywords = [
        'Emby', 'emby', '媒体库', '公益服', '资源服', '线路', '节点', 
        'http', 'https', 't.me', '订阅', '规则', '教程', '群组',
        '🌍', '🔗', '🚀', '📢', '🎁', '💰', 'IPLC', 'IEPL', '更新订阅',
        '基础服', '教学服', '服务:', '账号:', '密码:', '快如闪电'
    ]
    
    lines = msg.split('\n')
    filtered = []
    for line in lines:
        line = line.strip()
        if not line or any(kw.lower() in line.lower() for kw in junk_keywords):
            continue
        # 移除可能残余的装饰线条
        line = re.sub(r'[━─\-]{5,}', '', line)
        if line:
            filtered.append(line)
    
    return ' '.join(filtered).strip() if filtered else "签到成功"

def mask_str(s: str, front=1, back=1, fill='*') -> str:
    """模糊化字符串"""
    if len(s) <= front + back:
        return fill * len(s)
    return s[:front] + fill * (len(s) - front - back) + s[-back:]

# =============== 核心逻辑 ===============

def fetch_and_extract_info(domain: str, headers: dict) -> str:
    """提取用户信息并格式化"""
    url = f"{domain}/user"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return "⚠️ 用户信息获取失败\n"
    except Exception as e:
        return f"⚠️ 出错: {e}\n"

    soup = BeautifulSoup(response.text, 'html.parser')
    script_tags = soup.find_all('script')
    chatra_script = next((s.text for s in script_tags if s and 'window.ChatraIntegration' in s.text), None)

    if not chatra_script:
        return "⚠️ 未识别到用户信息\n"

    # 正则提取
    expire_match = re.search(r"'Class_Expire':\s*'([^']*)'", chatra_script)
    traffic_match = re.search(r"'Unused_Traffic':\s*'([^']*)'", chatra_script)
    
    expire_date = expire_match.group(1).split(' ')[0] if expire_match else "未知"
    unused_traffic = traffic_match.group(1) if traffic_match else "未知"

    return (
        f"📅 <b>到期时间:</b> {expire_date}\n"
        f"📊 <b>剩余流量:</b> {unused_traffic}\n"
        f"🔗 <b>Clash 订阅</b> | <b>V2ray 订阅</b>\n"
    )

def send_message(msg: str, bot_token: str, chat_id: str):
    """发送格式化后的 Telegram 消息"""
    if not bot_token or not chat_id:
        print("未配置 Telegram 参数，跳过发送。")
        return

    now = datetime.now() + timedelta(hours=8)
    beijing_time = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # 构造最终消息体
    message_text = f"⏰ <b>执行时间:</b> {beijing_time}\n\n{msg}"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True # 禁用网页预览，保持简洁
    }

    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"发送失败: {e}")

def checkin(account: dict, domain: str, bot_token: str, chat_id: str):
    user = account['user']
    passwd = account['pass']
    masked_user = mask_str(user, 1, 5)
    # 使用 tg-spoiler 增加点击显示密码的效果（可选）
    masked_pass = f"<tg-spoiler>{mask_str(passwd, 1, 1)}</tg-spoiler>"

    try:
        # 1. 登录
        login_url = f"{domain}/auth/login"
        login_data = {'email': user, 'passwd': passwd, 'remember_me': 'on'}
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        sess = requests.Session()
        resp = sess.post(login_url, json=login_data, headers=headers, timeout=10)
        if resp.json().get('ret') != 1:
            raise Exception(resp.json().get('msg', '登录失败'))

        # 2. 签到
        checkin_url = f"{domain}/user/checkin"
        checkin_resp = sess.post(checkin_url, headers=headers, timeout=10)
        clean_msg = clean_checkin_msg(checkin_resp.json().get('msg', ''))

        # 3. 获取账户信息
        user_info = fetch_and_extract_info(domain, sess.headers)

        # 4. 组装模板
        full_msg = (
            f"🔹 <b>地址:</b> {domain}\n"
            f"🔑 <b>账号:</b> {masked_user}\n"
            f"🔒 <b>密码:</b> {masked_pass}\n"
            f"{user_info}\n"
            f"🎉 <b>签到结果:</b> ✅ {clean_msg}"
        )

        send_message(full_msg, bot_token, chat_id)
        return full_msg

    except Exception as e:
        err = f"❌ 签到失败\n账号: {masked_user}\n错误: {str(e)}"
        send_message(err, bot_token, chat_id)
        return err

def generate_config():
    domain = os.getenv('DOMAIN', 'https://69yun69.com').strip()
    bot_token = os.getenv('BOT_TOKEN', '').strip()
    chat_id = os.getenv('CHAT_ID', '').strip()
    accounts = []
    i = 1
    while True:
        user = os.getenv(f'USER{i}')
        passwd = os.getenv(f'PASS{i}')
        if not user or not passwd: break
        accounts.append({'user': user.strip(), 'pass': passwd.strip()})
        i += 1
    return {'domain': domain, 'BotToken': bot_token, 'ChatID': chat_id, 'accounts': accounts}

if __name__ == "__main__":
    conf = generate_config()
    for acc in conf['accounts']:
        print(f"执行中: {acc['user']}")
        result = checkin(acc, conf['domain'], conf['BotToken'], conf['ChatID'])
        print(result)
