import os
import string
import random
import time
import threading
import requests
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
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

# 🕒 核心功能：自動防冬眠打卡機制（每 10 分鐘自動戳一下 Supabase 與自身服務）
def keep_alive_ping():
    while True:
        try:
            # 1. 戳一下 Supabase，讓資料庫保持清醒
            supabase.table("user_contracts").select("id").limit(1).execute()
            print("⚡ [Keep-Alive] 成功戳了一下 Supabase，資料庫運作正常！")
        except Exception as e:
            print(f"⚠️ [Keep-Alive] 戳資料庫時發生異常: {str(e)}")
        
        # 每 600 秒（10分鐘）打卡一次
        time.sleep(600)

# 啟動背景打卡線程
ping_thread = threading.Thread(target=keep_alive_ping, daemon=True)
ping_thread.start()

@app.route("/", methods=['GET'])
def health_check():
    return "Bot is alive!", 200

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
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 初始化該用戶的每日計數器
    if user_id not in USER_RATE_LIMITS or USER_RATE_LIMITS[user_id]["date"] != today_str:
        USER_RATE_LIMITS[user_id] = {"date": today_str, "address_count": 0, "fortune_count": 0}

    # 🛑 規則一：合約關鍵字攔截
    if "合約" in user_msg or "簽" in user_msg:
        reply_text = (
            "⚠️【法律免責聲明與回報須知】\n"
            "本環境數據已全自動絞碎匿名，無個資留存。\n\n"
            "本系統為客觀環境數據收集工具，無權限涉入、不提供且拒絕簽署任何形式之法律合約。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🚧 專屬按鈕文字比對（避免被其他關鍵字誤判，優先於規則二判斷）
    if user_msg == "進入筆記回報":
        reply_text = (
            "🚨 開始回報配送環境筆記！\n\n"
            "請直接輸入完整大樓地址（例如：台中市公益路二段100號），\n"
            "系統會自動偵測並跳出客觀環境選項讓您勾選。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 👥 規則：結拜包廂管理入口——依身分動態顯示
    if user_msg == "查看結拜包廂":
        try:
            existing_user = supabase.table("users").select("*").eq("line_uid", user_id).execute()
            user_data = existing_user.data[0] if existing_user.data else None

            if user_data and user_data.get("group_id"):
                group_id = user_data["group_id"]
                role = user_data.get("group_role")
                group_info = supabase.table("groups").select("*").eq("id", group_id).execute().data[0]
                member_result = supabase.table("users").select("line_uid", count="exact").eq("group_id", group_id).execute()
                member_count = member_result.count if member_result.count is not None else 0

                try:
                    owner_profile = line_bot_api.get_profile(group_info["owner_line_uid"])
                    owner_name = owner_profile.display_name
                except Exception:
                    owner_name = "未知車友"

                role_text = "👑 群主（您自己）" if role == "OWNER" else f"👥 成員（群主：{owner_name}）"

                reply_text = (
                    "👥 您目前的結拜包廂資訊\n\n"
                    f"身分：{role_text}\n"
                    f"🔑 包廂密碼：{group_info['group_password']}\n"
                    f"👤 目前人數：{member_count}/{group_info['member_limit']}\n\n"
                    "如需離開，請點下方按鈕退出。"
                )
                quick_reply = QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="🚪 退出包廂", text="退出包廂"))
                ])
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text, quick_reply=quick_reply))
            else:
                quick_reply = QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="🏠 建立包廂", text="建立包廂")),
                    QuickReplyButton(action=MessageAction(label="🔑 我要加入包廂", text="我要加入包廂"))
                ])
                reply_text = "👥 結拜包廂管理\n\n請選擇要建立新包廂，還是輸入密碼加入車友的包廂："
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text, quick_reply=quick_reply))
        except Exception as e:
            reply_text = f"❌ 查詢包廂狀態時發生異常: {str(e)}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🚪 規則：退出包廂（含群主自動繼承機制＋全員通知）
    if user_msg == "退出包廂":
        try:
            existing_user = supabase.table("users").select("*").eq("line_uid", user_id).execute()
            user_data = existing_user.data[0] if existing_user.data else None

            if not user_data or not user_data.get("group_id"):
                reply_text = "⚠️ 您目前沒有加入任何包廂，無需退出。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            group_id = user_data["group_id"]
            role = user_data.get("group_role")

            try:
                leaving_profile = line_bot_api.get_profile(user_id)
                leaving_name = leaving_profile.display_name
            except Exception:
                leaving_name = "一位車友"

            supabase.table("users").update({
                "group_id": None, "group_role": None, "joined_group_at": None
            }).eq("line_uid", user_id).execute()

            if role == "OWNER":
                remaining = supabase.table("users").select("*").eq("group_id", group_id).order("joined_group_at").execute().data
                if remaining:
                    new_owner = remaining[0]
                    supabase.table("users").update({"group_role": "OWNER"}).eq("line_uid", new_owner["line_uid"]).execute()
                    supabase.table("groups").update({"owner_line_uid": new_owner["line_uid"]}).eq("id", group_id).execute()

                    try:
                        new_owner_profile = line_bot_api.get_profile(new_owner["line_uid"])
                        new_owner_name = new_owner_profile.display_name
                    except Exception:
                        new_owner_name = "新群主"

                    # 通知新群主本人
                    try:
                        line_bot_api.push_message(
                            new_owner["line_uid"],
                            TextSendMessage(text=f"👑 原群主（{leaving_name}）已退出包廂，您已自動升任為新群主！")
                        )
                    except Exception:
                        pass

                    # 通知其他剩餘成員（排除新群主本人）
                    for member in remaining[1:]:
                        try:
                            line_bot_api.push_message(
                                member["line_uid"],
                                TextSendMessage(text=f"📢 包廂公告：原群主（{leaving_name}）已退出，{new_owner_name} 已自動升任為新群主。")
                            )
                        except Exception:
                            pass
                else:
                    supabase.table("groups").delete().eq("id", group_id).execute()

            reply_text = "✅ 您已成功退出包廂。"
        except Exception as e:
            reply_text = f"❌ 退出包廂時發生異常: {str(e)}"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🏠 規則：建立包廂
    if user_msg == "建立包廂":
        try:
            existing_user = supabase.table("users").select("group_id").eq("line_uid", user_id).execute()
            if existing_user.data and existing_user.data[0].get("group_id"):
                reply_text = "⚠️ 您目前已經是某個包廂的成員，請先退出目前的包廂才能建立新包廂。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            new_password = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            group_insert = supabase.table("groups").insert({
                "group_password": new_password,
                "owner_line_uid": user_id
            }).execute()
            new_group_id = group_insert.data[0]["id"]

            supabase.table("users").upsert({
                "line_uid": user_id,
                "group_id": new_group_id,
                "group_role": "OWNER",
                "joined_group_at": datetime.now().isoformat()
            }).execute()

            reply_text = (
                "🎉 包廂建立成功！您已成為群主。\n\n"
                f"🔑 包廂密碼：{new_password}\n\n"
                f"請將此密碼分享給結拜車友，讓他們輸入「加入 {new_password}」即可加入。"
            )
        except Exception as e:
            reply_text = f"❌ 建立包廂時發生異常: {str(e)}"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🔑 規則：提示如何加入包廂
    if user_msg == "我要加入包廂":
        reply_text = "🔑 請直接輸入「加入 密碼」來加入車友的包廂，例如：\n加入 7XK2W9"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🔓 規則：加入包廂（支援「加入 密碼」或使用者忘記打「加入」、直接輸入 6 碼密碼）
    is_join_with_prefix = user_msg.startswith("加入")
    stripped_msg = user_msg.strip()
    is_bare_password_guess = (
        not is_join_with_prefix
        and len(stripped_msg) == 6
        and stripped_msg.isalnum()
    )

    if is_join_with_prefix or is_bare_password_guess:
        if is_join_with_prefix:
            input_password = user_msg[2:].strip().upper()
        else:
            input_password = stripped_msg.upper()

        if len(input_password) != 6:
            reply_text = "🔑 密碼格式不正確，請輸入「加入 密碼」，例如：\n加入 7XK2W9"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        try:
            existing_user = supabase.table("users").select("group_id").eq("line_uid", user_id).execute()
            if existing_user.data and existing_user.data[0].get("group_id"):
                reply_text = "⚠️ 您目前已經是某個包廂的成員，請先退出目前的包廂才能加入新包廂。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            group_query = supabase.table("groups").select("*").eq("group_password", input_password).execute()
            if not group_query.data:
                reply_text = "❌ 密碼錯誤，查無此包廂，請確認密碼是否正確。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            group_info = group_query.data[0]
            member_count = supabase.table("users").select("line_uid", count="exact").eq("group_id", group_info["id"]).execute()
            current_members = member_count.count if member_count.count is not None else 0

            if current_members >= group_info["member_limit"]:
                reply_text = f"⚠️ 此包廂人數已滿（{group_info['member_limit']}/{group_info['member_limit']}），無法加入。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            supabase.table("users").upsert({
                "line_uid": user_id,
                "group_id": group_info["id"],
                "group_role": "MEMBER",
                "joined_group_at": datetime.now().isoformat()
            }).execute()

            reply_text = "🎉 加入包廂成功！歡迎加入結拜車友的行列，一起互相避雷吧！"
        except Exception as e:
            reply_text = f"❌ 加入包廂時發生異常: {str(e)}"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    if user_msg in ["查看衰退機制", "開啟更多設定"]:
        reply_text = (
            f"🛠️ 【{user_msg}】功能開發中，敬請期待！\n\n"
            "此功能已列入企劃，會在下一階段陸續上線，感謝您的耐心等候 🙏"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return
    
    # 🔮 規則二：按鈕功能中樞——運勢抽籤（只要字串包含「運勢」就強制通關）
    if "運勢" in user_msg:
        if USER_RATE_LIMITS[user_id]["fortune_count"] >= 5:
            reply_text = "🔮 今日抽籤次數已達上限（5/5）。\n\n貪心會不靈驗喔！祝您今日外送平安，明天再來碰碰運氣吧！"
        else:
            USER_RATE_LIMITS[user_id]["fortune_count"] += 1
            current_count = USER_RATE_LIMITS[user_id]["fortune_count"]
            fortune_result = random.choice(FORTUNE_POOL)
            reply_text = f"【🔮 外送員今日運勢抽籤】\n\n{fortune_result}\n\n（今日已抽籤：{current_count}/5 次）"
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 📋 規則三：按鈕功能中樞——歷史筆記查詢（只要字串包含「回報」或「查詢」就強制通關）
    if "回報" in user_msg or "查詢" in user_msg:
        try:
            response = supabase.table("user_contracts").select("region_tag, created_at").eq("line_uid", user_id).order("created_at", desc=True).execute()
            records = response.data
            
            if not records:
                reply_text = "📋 您目前尚未有任何環境回報紀錄。\n\n💡 提示：請直接在對話框輸入大樓地址（例如：台中市公益路二段100號）即可自動入庫！"
            else:
                reply_text = "📋 您目前已回報的歷史筆記：\n"
                for idx, row in enumerate(records, 1):
                    addr = row.get("region_tag", "未知地址")
                    reply_text += f"\n{idx}. 📍 {addr}"
                reply_text += "\n\n💡 提示：所有回報紀錄將於 60 天後全自動老化銷毀，個人目前僅提供查看，如需刪除請聯繫包廂長。"
        except Exception as e:
            reply_text = f"❌ 讀取歷史筆記異常: {str(e)}"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🏢 規則四：地址偵測、標準化與入庫（一般打字時才會進來）
    clean_msg = user_msg.replace("臺", "台")
    if any(k in clean_msg for k in ["路", "街", "巷", "號", "樓"]):
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
            supabase.table("user_contracts").insert(data).execute()
            USER_RATE_LIMITS[user_id]["address_count"] += 1
            
            reply_text = (
                "✅ 數據已成功去識別化匿名入庫！\n\n"
                "系統已成功為您攔截並將此筆地址記錄至雲端去識別化資料庫。"
            )
        except Exception as e:
            reply_text = f"❌ 數據對接異常: {str(e)}"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🤖 規則五：萬用防呆回覆
    default_reply = (
        "💡 歡迎使用外送筆記本自動化安全防護系統。\n\n"
        "請直接輸入『完整大樓地址』開始客觀環境回報：\n"
        "（輸入關鍵字包含『合約』將觸發法律防禦機制）"
    )
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=default_reply))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
