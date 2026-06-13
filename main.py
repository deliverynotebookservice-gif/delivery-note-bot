import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 從雲端環境變數讀取你剛剛拿到的雙金鑰
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

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
    user_msg = event.message.text
    
    # 極簡純文字判定，完全不偵測定位
    if user_msg == "進入筆記回報":
        reply = "⚠️【法律免責聲明與回報須知】\n本包廂環境數據已全自動絞碎匿名，無個資留存。\n\n請直接輸入『完整大樓地址』開始客觀環境回報："
    elif user_msg == "進入筆記查詢":
        reply = "🔍 請輸入您想查詢的『完整地址』，系統將自動為您檢索包廂兄弟的客觀提報："
    elif user_msg == "查看衰退機制":
        reply = "⏳【筆記新陳代謝公告】\n本系統具備「60天滾動退場機制」。超過60天無人重複提報之大樓地址，系統將自動洗白，只留最新最準的情報！"
    elif user_msg == "開啟更多設定":
        reply = "⚙️【功能與安全設定】\n1. 查閱免責兄弟合約\n2. 隱私權與權利申訴通道（請來信專用Gmail）"
    elif user_msg == "測試今日運勢":
        reply = "🔮【今日運勢抽籤】\n跑單順遂，紅綠燈全綠！今日宜低調，祝兄弟爆小費！"
    elif user_msg == "查看結拜包廂":
        reply = "👥【我的結拜包廂主控台】\n當前包廂人數：1 / 5 人\n您的專屬邀請碼：👉 BK-8888 👈\n（滿 5 人解鎖下一階段秘密任務！）"
    else:
        # 這裡未來會接 SHA-256 碎紙機與 Supabase 資料庫，今天我們先做通訊測試
        reply = f"系統已收到地址！[測試模式發動]\n您輸入的內容是：{user_msg}\n（後台同步將其碎紙化為亂碼儲存中...）"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)