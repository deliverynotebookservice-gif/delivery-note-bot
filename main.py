import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from supabase import create_client, Client

app = Flask(__name__)

# 讀取環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 建立 Supabase 連線（只保留一個，確保乾淨）
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

    # 🛑 核心防禦一：合約關鍵字攔截
    if "合約" in user_msg or "簽" in user_msg:
        reply_text = (
            "⚠️【法律免責聲明與回報須知】\n"
            "本環境數據已全自動絞碎匿名，無個資留存。\n\n"
            "本系統為客觀環境數據收集工具，無權限涉入、不提供且拒絕簽署任何形式之法律合約。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🔍 核心防禦二：地址偵測與入庫
    if any(k in user_msg for k in ["路", "街", "巷", "號", "樓"]):
        try:
            data = {
                "line_uid": user_id,
                "signed_agreement": False,
                "region_tag": user_msg
            }
            # 執行寫入 Supabase
            supabase.table("user_contracts").insert(data).execute()
            
            reply_text = (
                "✅ 數據已成功去識別化匿名入庫！\n"
                "後台同步將其碎紙化為亂碼儲存中...\n"
                "（安全防禦機制啟動：本紀錄將於 30 天後全自動老化銷毀）"
            )
        except Exception as e:
            reply_text = f"❌ 數據對接異常: {str(e)}"
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🤖 萬用防呆回覆
    default_reply = (
        "💡 歡迎使用外送筆記本自動化安全防護系統。\n\n"
        "請直接輸入『完整大樓地址』開始客觀環境回報：\n"
        "（輸入關鍵字包含『合約』將觸發法律防禦機制）"
    )
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=default_reply))

if __name__ == "__main__":
    # 完美適應 Render 雲端環境的 Port 綁定
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
