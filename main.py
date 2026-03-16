import time
import requests
import hmac
import hashlib
import base64
import urllib.parse
import json
import logging
import sys
from datetime import datetime

# ================= 配置区域 =================
UID = "322005137"  # 要监控的 UP主 UID
INTERVAL = 60  # 监控频率（秒），建议保持在 60 秒或以上
COOKIE = "buvid3=A717EB3B-04E1-0797-33D3-2A19F618430A98314infoc; b_nut=1772672698; _uuid=951B101C2-79F9-2F84-109D10-DA3A310109A53198734infoc; home_feed_column=5; browser_resolution=1680-825; buvid4=5526D767-C785-B5E5-F482-B13C96386FBA99630-026030509-gALdnCa2vIL56Qi/sHSAHA%3D%3D; buvid_fp=533bb5a3b8b82244fe4a5742e9fd4db3; theme-tip-show=SHOWED; bp_t_offset_1473780483=1176176420347445248; theme-avatar-tip-show=SHOWED; hit-dyn-v2=1; bsource=search_baidu; CURRENT_FNVAL=4048; CURRENT_QUALITY=0; __at_once=1148157507745224466; bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NzM4ODQyMTksImlhdCI6MTc3MzYyNDk1OSwicGx0IjotMX0.DG2C4nTqMgs9vDZ8ihw5WPcUCVNSfugqbgk2knSXNJ8; bili_ticket_expires=1773884159; SESSDATA=aa5da86d%2C1789177052%2C62271%2A31CjB36AGP7d9dq3bM01qc5pn_jC-qkATWrIZCWHS2BKKGLpqKnjo0Pk0b-QOQE6_h4q0SVm9uQUo4RFIzNmEzbFNXRXpvYkFCdk83ekwxeXBoczBfUE1MTXRaV1pGUm9tUWFDR1JvdTFxUUNDWDVwRks2NXg4a3JHM3ktVkZPaFloQUlzTmw4UDJ3IIEC; bili_jct=3e0eb7a96ab53a87b6402b13e41b07e2; DedeUserID=1473780483; DedeUserID__ckMd5=0bec4023695630a8; sid=qfawbu0n; b_lsid=45AC6C42_19CF49E32F3"  # （可选）建议填入你浏览器中 B站 的 Cookie。如果请求失败或被风控拦截，请务必填入 Cookie。

# 钉钉机器人配置
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=13c85c94d5becaa7ec6a5001437be40fccbd2a887cc984a889a3752cc53de8c0"
DINGTALK_SECRET = "SEC8999134be62359e2b2b81a3d3ed2cc291739ab45cbe9d0fe2ef66d5dc4d332ef"

# 日志文件名称
LOG_FILE = "bilibili_monitor.log"

# 💓 心跳存活通知设置
HEARTBEAT_TIME = "09:00"  # 每天固定发送存活报告的时间（24小时制，例如 09:00 或 18:30）
# ============================================

# 配置日志输出
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)


def get_time():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def fetch_dynamics(uid):
    """请求 B 站 API 获取动态"""
    url = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid={uid}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
        "Origin": "https://space.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive"
    }

    if COOKIE:
        headers["Cookie"] = COOKIE

    try:
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=False)
        if response.status_code == 412:
            logging.error("❌ 遭到 B 站风控拦截 (412 Precondition Failed)。")
            return []

        response.raise_for_status()
        data = response.json()

        if data['code'] != 0:
            logging.warning(f"⚠️ API 报错 (code: {data['code']}): {data.get('message', '未知错误')}")
            return []

        return data.get('data', {}).get('items', [])
    except Exception as e:
        logging.error(f"❌ 获取异常: {e}")
        return []


def parse_item(item):
    """解析单条动态的数据结构"""
    try:
        dyn_id = int(item.get('id_str', 0))
        modules = item.get('modules', {})
        author = modules.get('module_author', {})
        name = author.get('name', 'Unknown')

        try:
            pub_ts = int(author.get('pub_ts', 0))
        except (ValueError, TypeError):
            pub_ts = 0

        dynamic = modules.get('module_dynamic', {})
        desc = dynamic.get('desc') or {}
        major = dynamic.get('major') or {}

        text = ""

        # 提取常规纯文字
        if isinstance(desc, dict) and desc.get('text'):
            text += desc['text']

        # 提取富媒体内容
        if isinstance(major, dict):
            major_type = major.get('type')
            if major_type == 'MAJOR_TYPE_OPUS':
                summary = major.get('opus', {}).get('summary', {})
                if summary.get('text') and summary['text'] not in text:
                    text += " " + summary['text']
            elif major_type == 'MAJOR_TYPE_ARCHIVE':
                archive = major.get('archive', {})
                text += f" 【发布了视频: {archive.get('title', '')}】"
            elif major_type == 'MAJOR_TYPE_ARTICLE':
                article = major.get('article', {})
                text += f" 【发布了专栏: {article.get('title', '')}】"
            elif major_type == 'MAJOR_TYPE_DRAW':
                if not text.strip():
                    pic_count = len(major.get('draw', {}).get('items', []))
                    text += f" 【发布了 {pic_count} 张图片】"
            elif major_type == 'MAJOR_TYPE_LIVE_RCMD':
                text += " 【正在直播推送】"

        if item.get('orig') or item.get('type') == 'DYNAMIC_TYPE_FORWARD':
            text += " //【转发了动态】"

        if not text.strip():
            text = "【该动态仅包含图片或无法识别的媒体内容】"

        pub_time = datetime.fromtimestamp(pub_ts).strftime('%Y-%m-%d %H:%M:%S') if pub_ts > 0 else get_time()

        return {
            'id': dyn_id,
            'name': name,
            'text': text.strip(),
            'url': f"https://t.bilibili.com/{dyn_id}",
            'pub_time': pub_time
        }
    except Exception as e:
        logging.error(f"❌ 解析出错: {e}")
        return None


def generate_dingtalk_url():
    """生成带签名的钉钉 Webhook URL"""
    timestamp = str(round(time.time() * 1000))
    secret_enc = DINGTALK_SECRET.encode('utf-8')
    string_to_sign = f'{timestamp}\n{DINGTALK_SECRET}'
    hmac_code = hmac.new(secret_enc, string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"


def push_notification(dyn):
    """发送新动态推送"""
    logging.info(f"🔔 检测到新动态，准备推送: {dyn['url']}")
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"B站动态更新: {dyn['name']}",
            "text": f"### 💡 {dyn['name']} 发新动态啦！\n\n**发布时间**：{dyn['pub_time']}\n\n**动态内容**：\n> {dyn['text']}\n\n[👉 点击这里直达动态]({dyn['url']})"
        }
    }
    requests.post(generate_dingtalk_url(), json=payload, timeout=10)


def push_heartbeat(up_name):
    """发送程序存活的日常打卡通知"""
    logging.info("💓 触发每日存活报告，准备推送钉钉...")
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": "监控脚本运行正常",
            "text": f"### ✅ B站监控脚本运行正常\n\n**当前监控对象**：{up_name}\n\n**打卡时间**：{get_time()}\n\n*您的云端程序仍在后台默默打工，请放心！*"
        }
    }
    try:
        requests.post(generate_dingtalk_url(), json=payload, timeout=10)
        logging.info("✅ 每日存活报告发送成功！")
    except Exception as e:
        logging.error(f"❌ 存活报告发送失败: {e}")


def main():
    logging.info(f"🚀 开始监控 UP主 UID: {UID} 的动态...")

    # 记录上一次发送心跳的日期，避免一天内重复发
    last_heartbeat_date = ""

    initial_items = fetch_dynamics(UID)
    if not initial_items:
        max_id = 0
        up_name = "目标UP主"
    else:
        max_id = max(int(item['id_str']) for item in initial_items)
        up_name = initial_items[0].get('modules', {}).get('module_author', {}).get('name', '该UP主')
        logging.info(f"✅ 正在监控[{up_name}]，最新动态 ID: {max_id}")

    while True:
        # ====== 每日定时心跳检测逻辑 ======
        now = datetime.now()
        current_date = now.strftime('%Y-%m-%d')  # 例如：2026-03-16
        current_time_hm = now.strftime('%H:%M')  # 例如：09:00

        if current_time_hm == HEARTBEAT_TIME and last_heartbeat_date != current_date:
            push_heartbeat(up_name)
            last_heartbeat_date = current_date  # 记录今天已发送，明天才会再次触发
        # ==================================

        time.sleep(INTERVAL)
        items = fetch_dynamics(UID)
        if not items:
            continue

        new_dynamics = []
        for item in items:
            dyn_id = int(item['id_str'])
            if dyn_id > max_id:
                formatted_json = json.dumps(item, ensure_ascii=False, indent=2)
                logging.info(f"🐛 发现新动态 (ID: {dyn_id}) \n{formatted_json}")

                parsed = parse_item(item)
                if parsed:
                    new_dynamics.append(parsed)

        if new_dynamics:
            new_dynamics.sort(key=lambda x: x['id'])
            for dyn in new_dynamics:
                push_notification(dyn)
            max_id = new_dynamics[-1]['id']


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logging.info("🛑 已手动停止监控。")