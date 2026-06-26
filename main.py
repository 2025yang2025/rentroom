import json
import os
from datetime import datetime
import requests

# 讀取房客資料
with open('tenants.json', 'r', encoding='utf-8') as f:
    tenants = json.load(f)

today = datetime.today()
current_year_month = today.strftime('%Y-%m')  # 格式如 "2026-06"

reminders = []

for t in tenants:
    loc_room = f"📍 <b>[{t['location']} - {t['room']}]</b>"
    
    # 1. 檢查【收租預告】(當月繳租日前 3 天)
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
        pass  # 預防少數月份無該日期的極端情況

    # 2. 檢查【未收租催繳】
    # 條件：今天已經過了繳租日，且「最後付款日期」的月份不是這個月
    last_paid_ym = t['last_paid_date'][:7] if t['last_paid_date'] else ""
    if today.day > t['pay_day'] and last_paid_ym != current_year_month:
        reminders.append(
            f"{loc_room}\n"
            f"👤 房客：{t['name']}\n"
            f"🚨 狀態：⚠️ <b>【未收租催繳】</b>尚未登記 {current_year_month} 月的租金！\n"
            f"📅 上次付款日：<code>{t['last_paid_date'] or '無紀錄'}</code>"
        )

    # 3. 檢查【合約到期續約提醒】(結束日前 30 天內)
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

# 如果有任何提醒事項，發送到 Telegram
if reminders:
    full_message = "\n\n------------------------\n\n".join(reminders)
    
    bot_token = os.getenv('TG_BOT_TOKEN')
    chat_id = os.getenv('TG_CHAT_ID')
    
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": f"🏠 <b>房東收租與合約自動提醒系統</b>\n\n{full_message}",
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("Telegram 提醒訊息發送成功！")
        else:
            print(f"發送失敗，錯誤碼: {response.status_code}, 內容: {response.text}")
    else:
        print("【本地測試列印】未偵測到環境變數，以下為通知內容：\n")
        print(full_message)
