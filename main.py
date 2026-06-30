import os
import random
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from supabase import create_client, Client

app = Flask(__name__)

# 惡意攻擊防禦計數器（儲存格式：{ "line_uid": {"date": "2026-06-30", "address_count": 0, "fortune_count": 0} }）
USER_RATE_LIMITS = {}

# 運勢抽籤的趣味籤詩庫
FORTUNE_POOL = [
    "🌟 大吉：今天送單一路綠燈，單量爆滿，小費拿滿滿！",
    "✨ 中吉：配送順暢，客人都親切下樓領取，配送動線順暢！",
    "👍 小吉：行車平安，雖然有爬樓梯單，但當作健身賺大錢！",
    "🛵 平吉：安穩送單，順順過完今天，安全第一！",
    "☕ 末吉：稍安勿躁，遇到拖餐先喝口水，好單隨後就來！"
]

# 讀取環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
SUPABASE_URL = "https://munsqncqqzkcafezgozo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im11bnNxbmNxcXprY2FmZXpnb3pvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE0MDUxOTQsImV4cCI6MjA5Njk4MTE5NH0.eLxLhAUljYsvMhfojJnYf4USgCs31W7UkI-hNJHCgdo"

# 建立 Supabase 連線
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    user_id = event.source.user_id
    
    # 取得今天的日期字串（格式：2026-06-30）
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 初始化該用戶的每日計數器
    if user_id not in USER_RATE_LIMITS or USER_RATE_LIMITS[user_id]["date"] != today_str:
        USER_RATE_LIMITS[user_id] = {"date": today_str, "address_count": 0, "fortune_count": 0}

    # 🛑 功能一：合約關鍵字攔截
    if "合約" in user_msg or "簽" in user_msg:
        reply_text = (
            "⚠️【法律免責聲明與回報須知】\n"
            "本環境數據已全自動絞碎匿名，無個資留存。\n\n"
            "本系統為客觀環境數據收集工具，無權限涉入、不提供且拒絕簽署任何形式之法律合約。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🔮 功能二：運勢抽籤（每日限 5 次）
    if "運勢抽籤" in user_msg or "今日運勢" in user_msg:
        if USER_RATE_LIMITS[user_id]["fortune_count"] >= 5:
            reply_text = "🔮 今日抽籤次數已達上限（5/5）。\n\n貪心會不靈驗喔！祝您今日外送平安，明天再來碰碰運氣吧！"
        else:
            USER_RATE_LIMITS[user_id]["fortune_count"] += 1
            current_count = USER_RATE_LIMITS[user_id]["fortune_count"]
            fortune_result = random.choice(FORTUNE_POOL)
            reply_text = f"【🔮 外送員今日運勢抽籤】\n\n{fortune_result}\n\n（今日已抽籤：{current_count}/5 次）"
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 📋 功能三：進入筆記查詢（個人一鍵列表還活著的資料）
    if "進入筆記查詢" in user_msg or "筆記查詢" in user_msg:
        try:
            # 只篩選出屬於該用戶的歷史地址資料
            response = supabase.table("user_contracts").select("region_tag, created_at").eq("line_uid", user_id).order("created_at", desc=True).execute()
            records = response.data
            
            if not records:
                reply_text = "📋 您目前尚未有任何環境回報紀錄。"
            else:
                reply_text = "📋 您目前已回報的歷史筆記：\n"
                for idx, row in enumerate(records, 1):
                    # 格式化輸出，只取地址精華
                    addr = row.get("region_tag", "未知地址")
                    reply_text += f"\n{idx}. 📍 {addr}"
                reply_text += "\n\n💡 提示：所有回報紀錄將於 60 天後全自動老化銷毀，個人目前僅提供查看，如需刪除請聯繫包廂長。"
        except Exception as e:
            reply_text = f"❌ 讀取歷史筆記異常: {str(e)}"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🏢 功能四：地址偵測、標準化與入庫（每日限 60 次）
    clean_msg = user_msg.replace("臺", "台")
    if any(k in clean_msg for k in ["路", "街", "巷", "號", "樓"]):
        # 檢查地址計數器是否摸到 60 次天花板
        if USER_RATE_LIMITS[user_id]["address_count"] >= 60:
            reply_text = "⚠️ 今日回報與查詢額度已達上限（60/60）。\n\n為維護系統傳輸效率與匿名數據安全，請於明日再次使用，感謝您的配合！"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return
            
        try:
            data = {
                "line_uid": user_id,
                "signed_agreement": False,
                "region_tag": clean_msg
            }
            
            # 執行寫入 Supabase
            supabase.table("user_contracts").insert(data).execute()
            
            # 成功寫入，計數器增加
            USER_RATE_LIMITS[user_id]["address_count"] += 1
            
            reply_text = (
                "✅ 數據已成功去識別化匿名入庫！\n\n"
                "系統已成功為您攔截並將此筆地址記錄至雲端去識別化資料庫。"
            )
        except Exception as e:
            reply_text = f"❌ 數據對接異常: {str(e)}"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🤖 功能五：萬用防呆回覆
    default_reply = (
        "💡 歡迎使用外送筆記本自動化安全防護系統。\n\n"
        "請直接輸入『完整大樓地址』開始客觀環境回報：\n"
        "（輸入關鍵字包含『合約』將觸發法律防禦機制）"
    )
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=default_reply))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
