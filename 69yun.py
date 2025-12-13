import os
import json
import requests
import time
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta

# =============== 工具函数 ===============

def clean_checkin_msg(msg: str) -> str:
    """清洗签到返回的消息，移除 Emby、广告、链接等无关内容"""
    lines = msg.split('\n')
    filtered = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 跳过包含关键词的行
        if any(kw in line for kw in [
            'Emby', '🌍', '🔗', 'IPLC', '更新订阅', '4K', 'https://emby',
            '基础服', '教学服', '资源服', '服务:', '账号:', '密码:', '快如闪电'
        ]):
            continue
        filtered.append(line)
    return '\n'.join(filtered).strip()

def mask_str(s: str, front=1, back=1, fill='*') -> str:
    """模糊化字符串，如 a****b"""
    if len(s) <= front + back:
        return fill * len(s)
    return s[:front] + fill * (len(s) - front - back) + s[-back:]

# =============== 核心逻辑 ===============

def fetch_and_extract_info(domain: str, headers: dict) -> str:
    url = f"{domain}/user"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return "用户信息获取失败，页面打开异常。\n"
    except Exception as e:
        return f"获取用户信息时出错: {e}\n"

    soup = BeautifulSoup(response.text, 'html.parser')
    script_tags = soup.find_all('script')

    chatra_script = None
    for script in script_tags:
        if script and 'window.ChatraIntegration' in script.text:
            chatra_script = script.text
            break

    if not chatra_script:
        return "未识别到用户信息\n"

    user_info = {}
    expire_match = re.search(r"'Class_Expire':\s*'([^']*)'", chatra_script)
    traffic_match = re.search(r"'Unused_Traffic':\s*'([^']*)'", chatra_script)
    user_info['到期时间'] = expire_match.group(1) if expire_match else "未知"
    user_info['剩余流量'] = traffic_match.group(1) if traffic_match else "未知"

    info_str = f"到期时间: {user_info['到期时间']}\n剩余流量: {user_info['剩余流量']}\n"

    # 提取订阅链接
    for script in script_tags:
        if script and 'oneclickImport' in script.text and 'clash' in script.text:
            link_match = re.search(r"https://checkhere\.top/link/([a-zA-Z0-9]+)", script.text)
            if link_match:
                token = link_match.group(1)
                info_str += (
                    f"Clash 订阅链接: https://checkhere.top/link/{token}?clash=1\n"
                    f"V2Ray 订阅链接: https://checkhere.top/link/{token}?sub=3\n\n"
                )
                break

    return info_str

def send_message(msg: str, bot_token: str, chat_id: str):
    if not bot_token or not chat_id:
        print("未配置 Telegram Bot Token 或 Chat ID，跳过发送消息。")
        return

    now = datetime.utcnow() + timedelta(hours=8)
    beijing_time = now.strftime("%Y-%m-%d %H:%M:%S")
    message_text = f"执行时间: {beijing_time}\n{msg}"

    keyboard = {
        "inline_keyboard": [[{"text": "项目地址", "url": "https://github.com/jackdk86/69yuncheckin"}]]
    }

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(keyboard)
    }

    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"发送 Telegram 消息失败: {e}")

def checkin(account: dict, domain: str, bot_token: str, chat_id: str):
    user = account['user']
    passwd = account['pass']
    masked_user = mask_str(user, 1, 5)
    masked_pass = f"<tg-spoiler>{mask_str(passwd, 1, 1)}</tg-spoiler>"

    try:
        login_url = f"{domain}/auth/login"
        login_data = {'email': user, 'passwd': passwd, 'remember_me': 'on', 'code': ''}
        login_headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Origin': domain.rstrip('/'),
            'Referer': f"{domain}/auth/login",
        }

        resp = requests.post(login_url, json=login_data, headers=login_headers, timeout=10)
        if resp.status_code != 200:
            raise Exception(f"登录请求失败: {resp.status_code}")

        login_json = resp.json()
        if login_json.get('ret') != 1:
            raise Exception(f"登录失败: {login_json.get('msg', '未知错误')}")

        cookies = resp.cookies
        if not cookies:
            raise Exception("未获取到 Cookie")

        time.sleep(1)

        checkin_url = f"{domain}/user/checkin"
        checkin_headers = {
            'Cookie': '; '.join([f"{k}={v}" for k, v in cookies.items()]),
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/json',
            'Origin': domain.rstrip('/'),
            'Referer': f"{domain}/user/panel",
        }

        checkin_resp = requests.post(checkin_url, headers=checkin_headers, timeout=10)
        checkin_json = checkin_resp.json()

        # 清洗签到消息
        raw_msg = checkin_json.get('msg', '签到成功' if checkin_json.get('ret') == 1 else '签到失败')
        clean_msg = clean_checkin_msg(raw_msg)
        result_msg = f"🎉 签到结果 🎉\n{clean_msg}"

        # 获取用户信息
        user_info = fetch_and_extract_info(domain, checkin_headers)

        # 构造完整消息
        full_msg = (
            f"地址: {mask_str(domain, 8, 5)}\n"
            f"账号: {masked_user}\n"
            f"密码: {masked_pass}\n\n"
            f"{user_info}"
            f"{result_msg}"
        )

        send_message(full_msg, bot_token, chat_id)
        return full_msg

    except Exception as e:
        error_msg = f"签到失败:\n账号: {masked_user}\n错误: {str(e)}"
        send_message(error_msg, bot_token, chat_id)
        return error_msg

def generate_config():
    domain = os.getenv('DOMAIN', 'https://69yun69.com').strip()
    bot_token = os.getenv('BOT_TOKEN', '').strip()
    chat_id = os.getenv('CHAT_ID', '').strip()

    accounts = []
    i = 1
    while True:
        user = os.getenv(f'USER{i}')
        passwd = os.getenv(f'PASS{i}')
        if not user or not passwd:
            break
        accounts.append({'user': user.strip(), 'pass': passwd.strip()})
        i += 1

    if not accounts:
        raise ValueError("未配置任何账号（USER1/PASS1 等）")

    return {
        'domain': domain,
        'BotToken': bot_token,
        'ChatID': chat_id,
        'accounts': accounts
    }

# =============== 主程序 ===============

if __name__ == "__main__":
    config = generate_config()
    domain = config['domain']
    bot_token = config['BotToken']
    chat_id = config['ChatID']

    for acc in config['accounts']:
        print("---------- 开始签到 ----------")
        result = checkin(acc, domain, bot_token, chat_id)
        print(result)
        print("---------- 签到结束 ----------\n")
