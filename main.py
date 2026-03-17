import time
import requests
import hmac
import hashlib
import base64
import urllib.parse
import json
import logging
import sys
import traceback
from datetime import datetime

# ================= 配置区域 =================
UID = "322005137"  # 要监控的 UP主 UID
INTERVAL = 60  # 监控频率（秒）
COOKIE = "buvid3=A717EB3B-04E1-0797-33D3-2A19F618430A98314infoc; b_nut=1772672698; _uuid=951B101C2-79F9-2F84-109D10-DA3A310109A53198734infoc; home_feed_column=5; browser_resolution=1680-825; buvid4=5526D767-C785-B5E5-F482-B13C96386FBA99630-026030509-gALdnCa2vIL56Qi/sHSAHA%3D%3D; buvid_fp=533bb5a3b8b82244fe4a5742e9fd4db3; theme-tip-show=SHOWED; bp_t_offset_1473780483=1176176420347445248; theme-avatar-tip-show=SHOWED; hit-dyn-v2=1; bsource=search_baidu; CURRENT_FNVAL=4048; CURRENT_QUALITY=0; __at_once=1148157507745224466; bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NzM4ODQyMTksImlhdCI6MTc3MzYyNDk1OSwicGx0IjotMX0.DG2C4nTqMgs9vDZ8ihw5WPcUCVNSfugqbgk2knSXNJ8; bili_ticket_expires=1773884159; SESSDATA=aa5da86d%2C1789177052%2C62271%2A31CjB36AGP7d9dq3bM01qc5pn_jC-qkATWrIZCWHS2BKKGLpqKnjo0Pk0b-QOQE6_h4q0SVm9uQUo4RFIzNmEzbFNXRXpvYkFCdk83ekwxeXBoczBfUE1MTXRaV1pGUm9tUWFDR1JvdTFxUUNDWDVwRks2NXg4a3JHM3ktVkZPaFloQUlzTmw4UDJ3IIEC; bili_jct=3e0eb7a96ab53a87b6402b13e41b07e2; DedeUserID=1473780483; DedeUserID__ckMd5=0bec4023695630a8; sid=qfawbu0n; b_lsid=45AC6C42_19CF49E32F3"  # （可选）建议填入你浏览器中 B站 的 Cookie。如果请求失败或被风控拦截，请务必填入 Cookie。


# 钉钉机器人配置
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=13c85c94d5becaa7ec6a5001437be40fccbd2a887cc984a889a3752cc53de8c0"
DINGTALK_SECRET = "SEC8999134be62359e2b2b81a3d3ed2cc291739ab45cbe9d0fe2ef66d5dc4d332ef"

LOG_FILE = "bilibili_monitor.log"
HEARTBEAT_TIME = "09:00"  # 每天固定发送存活报告的时间
# ============================================

# ============================================
# 🌟 新增：B站要求的新版特性参数，不加这个参数，API会自动把文本阉割掉！
BILI_PARAMS = "timezone_offset=-480&platform=web&features=itemOpusStyle,opusBigCover,onlyfansVote,endFooterHidden,decorationCard,onlyfansAssetsV2,ugcDelete,onlyfansQaCard,editable,opusPrivateVisible,avatarAutoTheme,sunflowerStyle,cardsEnhance,eva3CardOpus,eva3CardVideo,eva3CardComment,eva3CardVote,eva3CardUser"
# ============================================

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


def get_headers(url_type="space"):
    """统一生成请求头"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Connection": "keep-alive"
    }
    if url_type == "space":
        headers["Referer"] = f"https://space.bilibili.com/{UID}/dynamic"
        headers["Origin"] = "https://space.bilibili.com"
    else:
        headers["Referer"] = "https://t.bilibili.com/"
        headers["Origin"] = "https://t.bilibili.com"

    if COOKIE:
        headers["Cookie"] = COOKIE
    return headers


def fetch_dynamics(uid):
    """请求 B 站列表 API (加上新版 features 参数防止数据降级)"""
    url = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid={uid}&{BILI_PARAMS}"
    try:
        response = requests.get(url, headers=get_headers("space"), timeout=15, allow_redirects=False)
        if response.status_code == 412:
            logging.error("❌ 遭到 B 站风控拦截 (412 Precondition Failed)。")
            return[]
        response.raise_for_status()
        data = response.json()
        if data['code'] == 0:
            return data.get('data', {}).get('items',[])
    except Exception as e:
        logging.error(f"❌ 列表获取异常: {e}")
    return[]

def fetch_dynamic_detail(dyn_id):
    """单独请求单条动态详情 API (加上新版 features 参数获取完整富文本)"""
    url = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/detail?id={dyn_id}&{BILI_PARAMS}"
    try:
        response = requests.get(url, headers=get_headers("detail"), timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data['code'] == 0:
                return data.get('data', {}).get('item', {})
    except Exception as e:
        logging.error(f"❌ 详情获取异常: {e}")
    return None


def parse_item(item):
    """解析动态数据（彻底解决 rich_text_nodes 提取与图片提取）"""
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
        topic = dynamic.get('topic') or {}

        text_parts = []
        pic_urls = []

        # --- 核心：提取富文本节点 ---
        def extract_text_from_node(content_node):
            if not isinstance(content_node, dict): return ""
            extracted = ""
            if 'rich_text_nodes' in content_node:
                for node in content_node['rich_text_nodes']:
                    extracted += node.get('orig_text') or node.get('text') or ""
            if not extracted and content_node.get('text'):
                extracted = content_node['text']
            return extracted.strip()

        # ----------------------------

        # 1. 提取话题
        if isinstance(topic, dict) and topic.get('name'):
            text_parts.append(f"#{topic['name']}#")

        # 2. 提取常规文本
        desc_text = extract_text_from_node(desc)
        if desc_text:
            text_parts.append(desc_text)

        # 3. 提取富媒体内容
        if isinstance(major, dict):
            major_type = major.get('type')

            if major_type == 'MAJOR_TYPE_OPUS':
                opus = major.get('opus', {})
                if opus.get('title'):
                    text_parts.append(f"【{opus['title']}】")

                summary = opus.get('summary', {})
                summary_text = extract_text_from_node(summary)
                if summary_text and summary_text not in " ".join(text_parts):
                    text_parts.append(summary_text)

                pics = opus.get('pics', [])
                for pic in pics:
                    if pic.get('url'): pic_urls.append(pic['url'])

            elif major_type == 'MAJOR_TYPE_ARCHIVE':
                archive = major.get('archive', {})
                text_parts.append(f"【发布了视频: {archive.get('title', '')}】")

            elif major_type == 'MAJOR_TYPE_ARTICLE':
                article = major.get('article', {})
                text_parts.append(f"【发布了专栏: {article.get('title', '')}】")

            elif major_type == 'MAJOR_TYPE_DRAW':
                draw_items = major.get('draw', {}).get('items', [])
                for draw_item in draw_items:
                    if draw_item.get('src'): pic_urls.append(draw_item['src'])

            elif major_type == 'MAJOR_TYPE_LIVE_RCMD':
                text_parts.append("【正在直播推送】")

        if item.get('orig') or item.get('type') == 'DYNAMIC_TYPE_FORWARD':
            text_parts.append("//【转发了他人动态】")

        text = "\n\n".join(text_parts).strip()
        if not text:
            text = "【该动态仅包含无法识别的媒体内容或纯图片】"

        pub_time = datetime.fromtimestamp(pub_ts).strftime('%Y-%m-%d %H:%M:%S') if pub_ts > 0 else get_time()

        return {
            'id': dyn_id,
            'name': name,
            'text': text,
            'pics': pic_urls,
            'url': f"https://t.bilibili.com/{dyn_id}",
            'pub_time': pub_time
        }
    except Exception as e:
        logging.error(f"❌ 解析出错: {e}\n{traceback.format_exc()}")
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
    """发送带图片与格式化文本的钉钉推送"""
    logging.info(f"🔔 检测到新动态，准备推送: {dyn['url']}")

    # 修复钉钉 Markdown 引用断裂：将每一个换行符后加 '> '
    quoted_text = dyn['text'].replace('\n', '\n> ')

    md_text = f"### 💡 {dyn['name']} 发新动态啦！\n\n**发布时间**：{dyn['pub_time']}\n\n**动态内容**：\n> {quoted_text}\n\n"

    if dyn.get('pics'):
        for pic_url in dyn['pics']:
            md_text += f"![配图]({pic_url})\n\n"

    md_text += f"[👉 点击这里直达动态]({dyn['url']})"

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"B站动态更新: {dyn['name']}",
            "text": md_text
        }
    }

    try:
        requests.post(generate_dingtalk_url(), json=payload, timeout=10)
        logging.info("✅ 钉钉推送成功！")
    except Exception as e:
        logging.error(f"❌ 钉钉请求失败: {e}")


def push_heartbeat(up_name):
    """发送每日存活通知"""
    logging.info("💓 触发每日存活报告，准备推送钉钉...")
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": "监控脚本运行正常",
            "text": f"### ✅ B站监控脚本运行正常\n\n**当前监控对象**：{up_name}\n\n**打卡时间**：{get_time()}\n\n*您的程序仍在后台默默打工，请放心！*"
        }
    }
    requests.post(generate_dingtalk_url(), json=payload, timeout=10)


def main():
    logging.info(f"🚀 开始监控 UP主 UID: {UID} 的动态...")
    last_heartbeat_date = ""

    initial_items = fetch_dynamics(UID)
    if not initial_items:
        max_id = 0
        up_name = "目标UP主"
    else:
        max_id = max(int(item['id_str']) for item in initial_items)
        # 指定id用于测试
        # max_id = 1180348719119204375
        up_name = initial_items[0].get('modules', {}).get('module_author', {}).get('name', '该UP主')
        logging.info(f"✅ 正在监控[{up_name}]，最新动态 ID: {max_id}")

    while True:
        # 心跳检测
        now = datetime.now()
        current_date = now.strftime('%Y-%m-%d')
        if now.strftime('%H:%M') == HEARTBEAT_TIME and last_heartbeat_date != current_date:
            push_heartbeat(up_name)
            last_heartbeat_date = current_date

        time.sleep(INTERVAL)
        items = fetch_dynamics(UID)
        if not items:
            continue

        new_dynamics = []
        for item in items:
            dyn_id = int(item['id_str'])
            if dyn_id > max_id:
                logging.info(f"🐛 发现新动态 (ID: {dyn_id})，正在拉取无损详情...")

                # ==========================================
                # 🌟 核心：用详情 API 拿到的完整数据替换掉列表阉割数据
                # ==========================================
                detail_item = fetch_dynamic_detail(dyn_id)
                target_item = detail_item if detail_item else item

                # 你可以把最终解析前的数据打印出来看看是不是有字了
                formatted_json = json.dumps(target_item, ensure_ascii=False, indent=2)
                logging.info(f"原始数据: {formatted_json}")

                parsed = parse_item(target_item)
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