import json
import os
import requests

# 讀取房客資料
with open('tenants.json', 'r', encoding='utf-8') as f:
    tenants = json.load(f)

bot_token = os.getenv('TG_BOT_TOKEN')
chat_id = os.getenv('TG_CHAT_ID')

# 1. 這裡示範：主選單訊息（包含「新增房客」按鈕）
def send_main_menu():
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # 設定按鈕：一個指向新增網頁（稍後解釋），一個是點擊直接觸發 GitHub 收租
    payload = {
        "chat_id": chat_id,
        "text": "👑 <b>房東管理主選單</b>\n請選擇您要執行的操作：",
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    # 透過 Telegram 內建網頁（Web App）直接開啟精美網頁輸入欄位！
                    {"text": "➕ 填寫新房客資料", "web_app": {"url": f"https://{os.getenv('GH_USERNAME')}.github.io/{os.getenv('GH_REPO')}/add.html"}}
                ],
                [
                    {"text": "📊 查看所有房客狀態", "callback_data": "view_all"}
                ]
            ]
        }
    }
    requests.post(url, json=payload)

# 2. 每日催繳通知（帶有「確認收租」按鈕）
# 這裡在原本的催繳邏輯中，幫每個房客加上 callback_data 或 Webhook 連結
# （此處簡化邏輯，主要給予按鈕概念）
