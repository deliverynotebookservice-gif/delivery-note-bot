import os
import re
import hashlib
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from supabase import create_client, Client

app = Flask(__name__)

# 🔑 1. 從系統環境變數讀取密鑰（極致安全防禦）
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ⏳ 內建 3 秒冷卻 CD 牆記憶體（防止惡意連續攻擊）
USER_COOLDOWN = {}

# 🧼 核心洗滌大腦：地址清洗與防呆標準化
def clean_and_validate_address(raw_address):
    # A. 砍掉所有空格、全形轉半形
    address = raw_address.replace(" ", "").strip()
    address = address.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    
    # B. 常見錯字或口語格式校正（例如：一九路 -> 19路）
    num_map = {'一': '1', '二': '2', '三': '3', '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '○': '0', '零': '0'}
    for k, v in num_map.items():
        address = address.replace(f"{k}段", f"{v}段")
        address = address.replace(f"{k}路", f"{k}路") # 路名保持原字，僅校正段別
        
    # 🚨 終極強制防呆：檢查是否包含「縣/市」以及「區/鄉/鎮/市」
    has_city = any(x in address for x in ["市", "縣"])
    has_district = any(x in address for x in ["區", "鄉", "鎮"])
    
    if not has_city or not has_district:
        return None, "❌【格式錯誤】\n兄弟，請務必輸入包含「縣市」與「行政區」的完整地址！\n\n💡 範例：\n台中市西屯區台灣大道三段99號5樓"
        
    # C. 擷取縣市行政區標籤，以便後台商業報表分流
    match = re.search(r"([^縣市]+[縣市][^區鄉鎮市]+[區鄉鎮市])", address)
    region_info = match.group(1) if match else "未分類"
    
    return address, region_info

# 🔒 特工級 SHA-256 數位碎紙機
def hash_address(clean_address):
    return hashlib.sha256(clean_address.encode('utf-8')).hexdigest()

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text.strip()
    now = datetime.utcnow() + timedelta(hours=8) # 轉台灣時間
    
    # 🛑 1. 防惡意攻擊：3秒點擊 CD 牆
    if user_id in USER_COOLDOWN:
        last_time = USER_COOLDOWN[user_id]
        if (now - last_time).total_seconds() < 3:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚡ 動作太快了，請隔 3 秒後再試！"))
            return
    USER_COOLDOWN[user_id] = now

    # 🛑 2. 第一道防線：檢查合約白名單（如果還沒註冊，一律強制簽名，後面什麼都動不了）
    user_check = supabase.table("user_contracts").select("*").eq("line_uid", user_id).execute()
    
    # 如果完全沒紀錄，或者同意狀態為 False
    if not user_check.data or not user_check.data[0].get("signed_agreement"):
        # 模擬一進來盲測秒懂的「假合約按鈕」（正式上線會換成精美網頁連結）
        if user_text == "簽署協議":
            # 幫他開通，自動綁定中部（此處可由按鈕帶參數）
            supabase.table("user_contracts").upsert({
                "line_uid": user_id, "signed_agreement": True, "region_tag": "測試堂口"
            }).execute()
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🔒 安全憑證已開通！全台神兵功能已解鎖，請直接輸入完整地址開始使用！"))
        else:
            msg = "❌【系統提示：防禦門禁攔截】\n\n兄弟，出門在外安全第一！請先簽署保密協議開通權限。\n\n👉 請對話框輸入「簽署協議」完成盲測授權！"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
        return

    # 🛑 3. 殭屍帳戶自動清洗機制：只要超過 30 天沒動靜，重新融斷鎖定
    last_active = datetime.fromisoformat(user_check.data[0]["last_active_at"].replace('+00:00', '')) + timedelta(hours=8)
    if (now - last_active).days >= 30:
        supabase.table("user_contracts").update({"signed_agreement": False}).eq("line_uid", user_id).execute()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌【安全憑證已過期】\n兄弟，你已超過 30 天未與總部連線。憑證已暫時休眠，請重新輸入「簽署協議」解鎖。"))
        return

    # 📊 更新該用戶在後台的「最後活躍時間」，保持即時報表記錄
    supabase.table("user_contracts").update({"last_active_at": now.isoformat()}).eq("line_uid", user_id).execute()

    # 🚀 進入核心业务邏輯：回報功能 or 查詢功能
    if user_text.startswith("回報/"):
        parts = user_text.split("/")
        if len(parts) < 3:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 格式錯誤。請依範例輸入：\n回報/完整地址/狀態描述"))
            return
            
        raw_address = parts[1]
        status_desc = parts[2]
        
        # 洗滌地址與行政區防呆
        clean_addr, region = clean_and_validate_address(raw_address)
        if not clean_addr:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=region)) # 噴出錯誤提示
            return
            
        # 數位碎紙
        addr_hash = hash_address(clean_addr)
        
        # 寫入或更新（接力續命）資料庫
        supabase.table("environment_notes").upsert({
            "address_hash": addr_hash,
            "region_info": region,
            "status": status_desc,
            "details": f"包含樓層：{clean_addr}",
            "updated_at": now.isoformat()
        }).execute()
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🟩【情報成功入庫】\n\n地區：{region}\n狀態：{status_desc}\n系統已完成 SHA-256 去識別化碎紙，感謝前線兄弟！"))

    # 🔍 查詢功能（直接打字輸入完整地址即可查）
    else:
        clean_addr, region = clean_and_validate_address(user_text)
        if not clean_addr:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=region))
            return
            
        addr_hash = hash_address(clean_addr)
        
        # 去保險箱撈取該地址代碼
        db_query = supabase.table("environment_notes").select("*").eq("address_hash", addr_hash).execute()
        
        if not db_query.data:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚪【查無筆記】\n當前地址尚無兄弟回報紀錄，現場環境請自行覆查並注意安全！"))
            return
            
        note = db_query.data[0]
        update_time = datetime.fromisoformat(note["updated_at"].replace('+00:00', '')) + timedelta(hours=8)
        time_diff = now - update_time
        
        # ⏳ 30天/60天 衰退綠黃灰變色邏輯
        if time_diff.days < 7:
            freshness = "🟢【情報新鮮】"
            advice = "當前環境特徵極新，具備高度參考價值。"
        elif time_diff.days < 30:
            freshness = "🟡【情報老化】"
            advice = "⚠️ 本筆記已超過 7 天未經兄弟覆查，請小心現場環境變動！"
        else:
            freshness = "🔴【歷史封存】"
            advice = "❌ 此情報已過期封存。請抵達現場後，優先回報最新環境以利重啟筆記！"
            
        result_msg = f"{freshness}\n\n📍 歸屬分流：{note['region_info']}\n📝 現狀情報：{note['status']}\n⏰ 更新時間：{update_time.strftime('%m-%d %H:%M')}\n\n💡 總部提示：\n{advice}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result_msg))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
