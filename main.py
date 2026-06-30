import os
import json
from datetime import datetime, date
import requests

# 1. 讀取房客資料庫 (tenants.json)
json_path = 'tenants.json'
try:
    with open(json_path, 'r', encoding='utf-8') as f:
        tenants = json.load(f)
except FileNotFoundError:
    tenants = []
    print("⚠️ 找不到 tenants.json 檔案，將建立新的房客清單。")
except Exception as e:
    tenants = []
    print(f"⚠️ 讀取 tenants.json 失敗 (可能格式毀損): {e}")

bot_token = os.getenv('TG_BOT_TOKEN')
chat_id = os.getenv('TG_CHAT_ID')

today = datetime.today()
current_year_month = today.strftime('%Y-%m')  # 格式如 "2026-06"

# ==========================================
# 📥 新增功能：處理來自網頁直連的 Dispatch 訊號
# ==========================================
def handle_web_dispatch():
    # 讀取 GitHub 傳進來的環境變數
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    client_payload_str = os.getenv("CLIENT_PAYLOAD", "{}")
    
    if event_name != "repository_dispatch":
        return False # 不是網頁傳來的，跳過此步驟，跑原本的定時通知

    print("📥 偵測到來自網頁的直連訊號 (repository_dispatch)")
    
    try:
        payload = json.loads(client_payload_str)
    except Exception as e:
        print(f"❌ 解析網頁 Payload 失敗: {e}")
        return True

    action_type = payload.get("action_type")
    global tenants

    # ─── 分流 A：確認收到租金 ───
    if action_type == "confirm_receipt":
        room = payload.get("room")
        location = payload.get("location")
        today_str = date.today().strftime("%Y-%m-%d")
        
        print(f"▶ 執行【收租確認】: {location} - {room}")
        updated = False
        for t in tenants:
            if t.get("room") == room and t.get("location") == location:
                t["last_paid_date"] = today_str
                updated = True
                print(f"✅ 成功將 {room} 的最後繳租日更新為 {today_str}")
                break
        if not updated:
            print(f"⚠️ 找不到對應房間：{location} {room}")

    # ─── 分流 B：新增房客資訊 ───
    elif action_type == "add_tenant":
        print("▶ 執行【新增房客資訊】")
        new_tenant = {
            "location": payload.get("location"),
            "room": payload.get("room"),
            "name": payload.get("name"),
            "rent": int(payload.get("rent", 0)),
            "pay_day": int(payload.get("pay_day", 1)),
            "contract_start": payload.get("contract_start"),
            "contract_end": payload.get("contract_end"),
            "last_paid_date": ""
        }
        
        # 檢查覆蓋舊房客（若同地點同房間）
        tenants = [t for t in tenants if not (t.get("room") == new_tenant["room"] and t.get("location") == new_tenant["location"])]
        tenants.append(new_tenant)
        print(f"✅ 成功將新房客 {new_tenant['name']} (房間: {new_tenant['room']}) 寫入暫存")

    else:
        print(f"⚠️ 未知的網頁動作: {action_type}")
        return True

    # 💾 把結果存回 json，讓 yml 下方的 git commit 能推上雲端
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(tenants, f, ensure_ascii=False, indent=4)
    print("💾 資料庫 tenants.json 更新完成！")
    return True


# 2. 每日催繳、預告與到期檢查邏輯
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
        last_paid_ym = t['last_paid_date'][:7] if t['last_paid_date'] else ""
        if today.day > t['pay_day'] and last_paid_ym != current_year_month:
            reminders.append(
                f"{loc_room}\n"
                f"👤 房客：{t['name']}\n"
                f"🚨 狀態：⚠️ <b>【未收租催繳】</b>尚未登記 {current_year_month} 月的租金！\n"
                f"📅 上次付款日：<code>{t['last_paid_date'] or '無紀錄'}</code>"
            )
            buttons.append([
                {
                    "text": f"🟢 確認收到 {t['name']} 租金", 
                    "url": f"https://2025yang2025.github.io/rent-form/confirm.html?room={t['room']}&location={t['location']}"
                }
            ])

        # ─── 條件 C：檢查【租約到期提醒】───
        try:
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
        except Exception:
            pass

        # 發送訊息
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

    if not has_notification:
        print("🎉 檢查完畢：今日無任何房客需要催繳或預告！")

# 3. 主選單訊息
def send_main_menu():
    if not bot_token or not chat_id:
        print("❌ 錯誤：未偵測到環境變數，無法發送主選單。")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "👑 <b>房東管理主選單</b>\n\n歡迎使用管理系統！請點擊下方連結前往操作：",
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "➕ 填寫新房客資料 (前往網頁)", 
                        # 💡 順手幫你校正手誤：原本錯連到 confirm.html，這邊改成正確的 add.html 囉！
                        "url": "https://2025yang2025.github.io/rent-form/add.html"
                    }
                ]
            ]
        }
    }
    print("正在發送主選單...")
    res = requests.post(url, json=payload)

# ─── 主程式進入點 ───
if __name__ == "__main__":
    print("🚀 開始執行房東管理系統...")
    
    # 1. 優先攔截檢查：看看這是不是網頁傳來的新資料
    is_web_signal = handle_web_dispatch()
    
    # 2. 如果「不是」網頁訊號（代表這是每天早上定時的 cron 觸發），才跑推播通知
    if not is_web_signal:
        print("⏰ 偵測到定時排程，開始執行每日房客狀態檢查...")
        check_tenants_and_notify()
        send_main_menu()
    else:
        print("🏁 網頁資料處理完畢，已成功跳過排程通知。")
