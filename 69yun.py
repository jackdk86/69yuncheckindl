import os
import json
import requests
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# =============== 工具函数 ===============

def clean_checkin_msg(msg: str) -> str:
    """过滤杂讯，只保留核心签到结果"""
    junk_keywords = [
        '反馈工单', '客服', '卡顿', '速慢', '不流畅', '账号信息', 
        '精简不显示', '⚠️', '📚', 'Emby', '媒体库', '公益服', 
        'http', 't.me', '订阅', '教程', '群组', 'IPLC'
    ]
    lines = msg.split('\n')
    filtered = []
    for line in lines:
        line = line.strip()
        if not line or any(kw in line for kw in junk_keywords):
            continue
        line = re.sub(r'[━─\-]{5,}', '', line).strip()
        if line:
            filtered.append(line)
    return ' '.join(filtered).strip() if filtered else "签到成功"

def mask_str(s: str, front=1, back=1, fill='*') -> str:
    if len(s) <= front + back: return fill * len(s)
    return s[:front] + fill * (len(s) - front - back) + s[-back:]

# =============== 核心逻辑 ===============

def fetch_and_extract_info(domain: str, sess: requests.Session) -> str:
    """提取到期时间、流量及订阅"""
    url = f"{domain}/user"
    try:
        resp = sess.get(url, timeout=15)
        html = resp.text
        if resp.status_code != 200: return "⚠️ 无法访问用户面板\n"

        # 增强正则：匹配单双引号及空格
        expire_match = re.search(r"['\"]Class_Expire['\"]:\s*['\"]([^'\"]*)['\"]", html)
        traffic_match = re.search(r"['\"]Unused_Traffic['\"]:\s*['\"]([^'\"]*)['\"]", html)
        
        expire_date = expire_match.group(1).split(' ')[0] if expire_match else "未知"
        unused_traffic = traffic_match.group(1) if traffic_match else "未知"

        return (
            f"📅 <b>到期时间:</b> {expire_date}\n"
            f"📊 <b>剩余流量:</b> {unused_traffic}\n"
            f"🔗 <b>Clash 订阅</b> | <b>V2ray 订阅</b>\n"
        )
    except:
        return "⚠️ 信息提取异常\n"

def send_message(msg: str, bot_token: str, chat_id: str):
    if not bot_token or not chat_id: return
    beijing_time = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    message_text = f"⏰ <b>执行时间:</b> {beijing_time}\n\n{msg}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message_text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try: requests.post(url, data=payload, timeout=10)
    except: print("发送失败")

def checkin(account: dict, domain: str, bot_token: str, chat_id: str):
    user, passwd = account['user'], account['pass']
    masked_user = mask_str(user, 1, 5)
    masked_pass = f"<tg-spoiler>{mask_str(passwd, 1, 1)}</tg-spoiler>"

    try:
        sess = requests.Session()
        sess.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        
        # 1. 登录
        login_resp = sess.post(f"{domain}/auth/login", json={'email': user, 'passwd': passwd}, timeout=10)
        login_json = login_resp.json()
        if login_json.get('ret') != 1: raise Exception(login_json.get('msg', '登录失败'))

        # 2. 签到
        checkin_resp = sess.post(f"{domain}/user/checkin", timeout=10)
        clean_msg = clean_checkin_msg(checkin_resp.json().get('msg', ''))

        # 3. 信息抓取
        user_info = fetch_and_extract_info(domain, sess)

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
        err_msg = f"❌ 签到失败\n账号: {masked_user}\n错误: {str(e)}"
        send_message(err_msg, bot_token, chat_id)
        return err_msg

# =============== 入口 ===============

if __name__ == "__main__":
    # 域名防错处理
    raw_domain = os.getenv('DOMAIN', 'https://69yun69.com').strip()
    domain = raw_domain if raw_domain.startswith('http') else f"https://{raw_domain}"
    domain = domain.rstrip('/')

    bot_token = os.getenv('BOT_TOKEN', '').strip()
    chat_id = os.getenv('CHAT_ID', '').strip()

    accounts = []
    i = 1
    while True:
        u, p = os.getenv(f'USER{i}'), os.getenv(f'PASS{i}')
        if not u or not p: break
        accounts.append({'user': u.strip(), 'pass': p.strip()})
        i += 1

    for acc in accounts:
        print(checkin(acc, domain, bot_token, chat_id))
