import os
import json
import requests
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# =============== 工具函数 ===============

def clean_checkin_msg(msg: str) -> str:
    """极致精简：剔除客服反馈提示、账号信息提示及所有广告"""
    # 扩展黑名单，精准打击你提到的关键词
    junk_keywords = [
        '反馈工单', '网站客服', '卡顿', '速慢', '不流畅', '账号信息', 
        '精简不显示', '⚠️', '📚', 'Emby', '媒体库', '公益服', '资源服',
        'http', 't.me', '订阅', '教程', '群组', 'IPLC', 'IEPL'
    ]
    
    lines = msg.split('\n')
    filtered = []
    for line in lines:
        line = line.strip()
        # 如果行中包含黑名单关键词，直接整行舍弃
        if not line or any(kw in line for kw in junk_keywords):
            continue
        
        # 移除剩余行中的装饰性符号和多余空格
        line = re.sub(r'[━─\-]{5,}', '', line).strip()
        
        if line:
            filtered.append(line)
    
    # 将多行结果合并为一行，用空格分隔，看起来更清爽
    return ' '.join(filtered).strip() if filtered else "签到成功"

def mask_str(s: str, front=1, back=1, fill='*') -> str:
    """模糊化字符串"""
    if len(s) <= front + back:
        return fill * len(s)
    return s[:front] + fill * (len(s) - front - back) + s[-back:]

# =============== 核心逻辑 ===============

def fetch_and_extract_info(domain: str, sess: requests.Session) -> str:
    """增强版：提取用户信息，兼容不同版本的面板结构"""
    url = f"{domain}/user"
    try:
        # 使用 Session 保持登录状态
        response = sess.get(url, timeout=15)
        html_text = response.text
        
        if response.status_code != 200:
            return "⚠️ 页面访问异常，无法获取信息\n"

        # --- 策略 A: 从 window.ChatraIntegration 脚本中提取 ---
        # 这种方法最常用，包含过期时间和流量
        expire_match = re.search(r"'Class_Expire':\s*'([^']*)'", html_text)
        traffic_match = re.search(r"'Unused_Traffic':\s*'([^']*)'", html_text)
        
        expire_date = "未知"
        unused_traffic = "未知"

        if expire_match:
            expire_date = expire_match.group(1).split(' ')[0]
        if traffic_match:
            unused_traffic = traffic_match.group(1)

        # --- 策略 B: 如果策略 A 失败，尝试直接从 HTML 标签中抓取 (备用方案) ---
        if expire_date == "未知":
            soup = BeautifulSoup(html_text, 'html.parser')
            # 查找包含“到期”字样的元素
            expire_tags = soup.find_all(string=re.compile(r"到期|截止"))
            if expire_tags:
                expire_date = "已获取(请查看网页)" # 简单占位，说明网页结构变了

        # --- 订阅链接逻辑 ---
        # 很多机场隐藏了 token，通常在 /user 页面源码中搜索包含 link 的 URL
        sub_info = "🔗 <b>Clash 订阅</b> | <b>V2ray 订阅</b>"
        
        return (
            f"📅 <b>到期时间:</b> {expire_date}\n"
            f"📊 <b>剩余流量:</b> {unused_traffic}\n"
            f"{sub_info}\n"
        )

    except Exception as e:
        return f"⚠️ 获取信息时发生错误: {str(e)}\n"

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
