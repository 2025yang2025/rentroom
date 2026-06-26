import json
import os
from datetime import datetime
import requests

# 1. 讀取房客資料
try:
    with open('tenants.json', 'r', encoding='utf-8') as f:
        tenants = json.load(f)
except FileNotFoundError:
    tenants = []
    print("⚠️ 找不到 tenants.json 檔案，請確認檔案是否存在。")

bot_token = os.getenv('TG_BOT_TOKEN')
chat_id = os.getenv('TG_CHAT_ID')

today = datetime.today()
current_year_month = today.strftime('%Y-%m')  # 格式如 "2026-06"

# 2. 每日催繳、預告與到期檢查邏輯（發送獨立訊息並帶有「確認收租」按鈕）
def check_tenants_and_notify():
    if not bot_token or not chat_id:
        print("❌ 錯誤：未偵測到環境變數 TG_BOT_TOKEN 或 TG_CHAT_ID")
        return

    has_notification = False

    for t in tenants:
        loc_room = f"📍 <b>[{t['location']} - {t['room']}]</b>"
        reminders = []
        buttons = []

        # ─── 條件 A：檢查【收租預告】(當月繳租日前 3 天) ───
        try:
            rent_date_this_month = datetime(today.year, today.month, t['pay_day'])
            days_to_pay = (rent_date_this_month - today).days
            if days_to_pay == 3:
                reminders.append(
                    f"{loc_room}\n"
                    f"👤 房客：{t['name']}\n"
                    f"💰 租金：<code>{t['rent']}</code> 元\n"
                    f"📅 狀態：<b>【收租預告】</b>將於 3 天後 ({t['pay_day']} 號) 到期"
                )
        except ValueError:
            pass

        # ─── 條件 B：檢查【未收租催繳】───
        # 今天已經過了繳租日，且最後付款日的月份不是這個月
        last_paid_ym = t['last_paid_date'][:7] if t['last_paid_date'] else ""
        if today.day > t['pay_day'] and last_paid_ym != current_year_month:
            reminders.append(
                f"{loc_room}\n"
                f"👤 房客：{t['name']}\n"
                f"🚨 狀態：⚠️ <b>【未收租催繳】</b>尚未登記 {current_year_month} 月的租金！\n"
                f"📅 上次付款日：<code>{t['last_paid_date'] or '無紀錄'}</code>"
            )
            # 💡 關鍵：只有催繳時，下方帶入「確認收租」按鈕，傳送該房客的特定資料給 Repository Dispatch
            # 這裡為了純 GitHub 架構，按鈕改為觸發 Repository Dispatch 的說明（配合後面方案調整）
            # 目前先以 callback_data 示意，或直接導向未來的一鍵確認連結
            buttons.append([{"text": f"🟢 確認收到 {t['name']} 租金", "callback_data": f"pay_{t['location']}_{t['room']}"}])

        # ─── 條件 C：檢查【租約到期提醒】(結束日前 30 天內) ───
        contract_end_date = datetime.strptime(t['contract_end'], '%Y-%m-%d')
        days_to_contract_end = (contract_end_date - today).days
        if 0 <= days_to_contract_end <= 30:
            reminders.append(
                f"{loc_room}\n"
                f"👤 房客：{t['name']}\n"
                f"📝 狀態：⏳ <b>【租約即將到期】</b>\n"
                f"📅 合約期間：{t['contract_start']} ~ <b>{t['contract_end']}</b>\n"
                f"💡 提示：合約剩餘 <b>{days_to_contract_end}</b> 天，請準備連繫續約。"
            )

        # ─── 如果該房客符合上述任一條件，單獨發送一則訊息 ───
        if reminders:
            has_notification = True
            message_text = "\n".join(reminders)
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message_text,
                "parse_mode": "HTML"
            }
            if buttons:
                payload["reply_markup"] = {"inline_keyboard": buttons}

            print(f"正在發送 {t['name']} 的通知...")
            res = requests.post(url, json=payload)
            print(f"Telegram 回應: {res.status_code} - {res.text}")

    if not has_notification:
        print("🎉 檢查完畢：今日無任何房客需要催繳或預告！")

# 3. 主選單訊息（包含「➕ 填寫新房客資料」按鈕）
def send_main_menu():
    if not bot_token or not chat_id:
        print("❌ 錯誤：未偵測到環境變數，無法發送主選單。")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "👑 <b>房東管理主選單</b>\n請選擇您要執行的操作：",
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    # 透過你的 GitHub Pages 網址開啟 Web App 彈出表單
                    {"text": "➕ 填寫新房客資料", "web_app": {"url": "https://2025yang2025.github.io/rent-form/add.html"}}
                ],
                [
                    {"text": "📊 查看所有房客狀態", "callback_data": "view_all"}
                ]
            ]
        }
    }
    print("正在發送主選單...")
    res = requests.post(url, json=payload)
    print(f"主選單發送回應: {res.status_code} - {res.text}")

# ─── 執行主程式 ───
if __name__ == "__main__":
    print("🚀 開始執行房東管理檢查...")
    
    # 執行每日通知檢查
    check_tenants_and_notify()
    
    # 每次執行時，也順便發送主選單按鈕，方便隨時點擊「新增房客」
    send_main_menu()
