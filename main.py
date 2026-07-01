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
    print(f"⚠️ 讀取 tenants.json 失敗: {e}")

bot_token = os.getenv('TG_BOT_TOKEN')
chat_id = os.getenv('TG_CHAT_ID')

today = datetime.today()
current_year_month = today.strftime('%Y-%m')  # 格式如 "2026-06"

# ==========================================
# 📥 核心功能：處理來自網頁直連的 Dispatch 訊號
# ==========================================
def handle_web_dispatch():
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    client_payload_str = os.getenv("CLIENT_PAYLOAD", "{}")
    
    if event_name != "repository_dispatch":
        return False 

    print("📥 偵測到來自網頁的直連訊號 (repository_dispatch)")
    
    try:
        payload = json.loads(client_payload_str)
    except Exception as e:
        print(f"❌ 解析網頁 Payload 失敗: {e}")
        return True

    action_type = payload.get("action_type")
    global tenants

    def clean_str(s):
        return "".join(str(s).split()).replace("房", "").lower()

    # ─── 分流 A：確認收到租金 ───
    if action_type == "confirm_receipt":
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        today_str = date.today().strftime("%Y-%m-%d")
        
        print(f"▶ 執行【收租確認】: {location} - {room}")
        updated = False
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                t["last_paid_date"] = today_str
                updated = True
                print(f"✅ 成功更新最後繳租日為 {today_str}")
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
        tenants = [t for t in tenants if not (clean_str(t.get("room", "")) == clean_str(new_tenant["room"]) and clean_str(t.get("location", "")) == clean_str(new_tenant["location"]))]
        tenants.append(new_tenant)
        print(f"✅ 成功將新房客 {new_tenant['name']} 寫入暫存")

    # ─── 💡 新增分流 C：辦理租客續約 ───
    elif action_type == "renew_contract":
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        new_rent = int(payload.get("rent", 0))
        new_start = payload.get("contract_start")
        new_end = payload.get("contract_end")
        
        print(f"▶ 執行【房客續約展延】: {location} - {room}")
        updated = False
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                t["rent"] = new_rent
                t["contract_start"] = new_start
                t["contract_end"] = new_end
                # 續約成功後，把最後繳租日清空，讓新合約重新計算催繳
                t["last_paid_date"] = ""
                updated = True
                print(f"✅ 成功幫房客 {t['name']} 展延合約至 {new_end}，新租金 {new_rent} 元！")
                break
        if not updated:
            print(f"⚠️ 找不到對應房間無法續約：{location} {room}")

    else:
        print(f"⚠️ 未知的網頁動作: {action_type}")
        return True

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

        # ─── 條件 A：收租預告 (當月繳租日前 3 天) ───
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

        # ─── 條件 B：當天提醒與未收租催繳 ───
        last_paid_ym = t['last_paid_date'][:7] if t['last_paid_date'] else ""
        if today.day >= t['pay_day'] and last_paid_ym != current_year_month:
            status_label = "📅 <b>【今日繳租提醒】</b>" if today.day == t['pay_day'] else "🚨 ⚠️ <b>【未收租催繳】</b>"
            reminders.append(
                f"{loc_room}\n"
                f"👤 房客：{t['name']}\n"
                f"💡 狀態：{status_label} 尚未登記 {current_year_month} 月的租金！\n"
                f"📅 上次付款日：<code>{t['last_paid_date'] or '無紀錄'}</code>"
            )
            buttons.append([
                {
                    "text": f"🟢 確認收到 {t['name']} 租金", 
                    "url": f"https://2025yang2025.github.io/rent-form/confirm.html?room={t['room']}&location={t['location']}"
                }
            ])

        # ─── 條件 C：💡 租約到期提醒 (結束日前 30 天內，並自動帶入續約按鈕) ───
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
                # 🎯 自動塞入「一鍵前往續約」的直連按鈕，並貼心地帶入房號與地點參數
                buttons.append([
                    {
                        "text": f"📝 辦理 {t['name']} 續約展延", 
                        "url": f"https://2025yang2025.github.io/rent-form/renew.html?room={t['room']}&location={t['location']}"
                    }
                ])
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

            requests.post(url, json=payload)

    if not has_notification:
        print("🎉 檢查完畢：今日無任何房客需要催繳或預告！")


# 3. 主選單訊息 (分區財務報表)
def send_main_menu():
    if not bot_token or not chat_id:
        return

    location_stats = {}
    for t in tenants:
        loc = t.get('location', '未分類').strip()
        rent_amount = t.get('rent', 0)
        room_name = t.get('room', '')
        tenant_name = t.get('name', '')
        
        if loc not in location_stats:
            location_stats[loc] = {"expected": 0, "received": 0, "paid": [], "unpaid": []}
        
        location_stats[loc]["expected"] += rent_amount
        last_paid_ym = t.get('last_paid_date', '')[:7] if t.get('last_paid_date') else ""
        room_info = f"{room_name} ({tenant_name} / {rent_amount}元)"
        
        if last_paid_ym == current_year_month:
            location_stats[loc]["received"] += rent_amount
            location_stats[loc]["paid"].append(f"🟢 {room_info}")
        else:
            location_stats[loc]["unpaid"].append(f"🔴 {room_info}")

    finance_text = f"📊 <b>【{current_year_month} 月收租分區財務報表】</b>\n"
    if location_stats:
        for loc, stats in location_stats.items():
            exp = stats["expected"]
            recv = stats["received"]
            progress = round((recv / exp) * 100 if exp > 0 else 0, 1)
            paid_summary = "\n   ".join(stats["paid"]) if stats["paid"] else "   <i>暫無</i>"
            unpaid_summary = "\n   ".join(stats["unpaid"]) if stats["unpaid"] else "   <i>✨ 全數繳齊！</i>"
            
            finance_text += (
                f"=====================\n"
                f"📍 <b>【{loc}地區】</b>\n"
                f"💰 實收租金：<b>{recv}</b> / {exp} 元\n"
                f"📈 收租進度：<code>{progress}%</code>\n"
                f"✅ <b>已收房間：</b>\n   {paid_summary}\n"
                f"⚠️ <b>未收房間：</b>\n   {unpaid_summary}\n"
            )
    else:
        finance_text += "=====================\n<i>目前暫無地區統計資料。</i>"

    tenant_list_text = ""
    if tenants:
        for i, t in enumerate(tenants, 1):
            last_pay = t.get('last_paid_date')
            last_pay_show = f"<code>{last_pay}</code>" if last_pay else "<i>無紀錄</i>"
            tenant_list_text += (
                f"{i}. 📍 <b>{t['location']} - {t['room']}</b>\n"
                f"   👤 房客：{t['name']} ({t['rent']}元)\n"
                f"   ⏳ 租約到期：{t['contract_end']}\n"
                f"   💰 上次收租：{last_pay_show}\n"
                f"---------------------\n"
            )
    else:
        tenant_list_text = "<i>目前系統內無任何房客資料。</i>\n---------------------\n"

    menu_message = f"👑 <b>房東管理主選單</b>\n\n{finance_text}\n=====================\n📋 <b>下方可前往網頁操作：</b>"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    payload_menu = {
        "chat_id": chat_id,
        "text": menu_message,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[{"text": "➕ 填寫新房客資料 (前往網頁)", "url": "https://2025yang2025.github.io/rent-form/add.html"}]]
        }
    }
    requests.post(url, json=payload_menu)

    list_message = f"📋 <b>系統內現存【完整房客名冊】</b>\n---------------------\n{tenant_list_text}"
    requests.post(url, json={"chat_id": chat_id, "text": list_message, "parse_mode": "HTML"})


if __name__ == "__main__":
    print("🚀 開始執行房東管理系統...")
    is_web_signal = handle_web_dispatch()
    if not is_web_signal:
        print("⏰ 偵測到定時排程，開始執行每日房客狀態檢查...")
        check_tenants_and_notify()
        send_main_menu()
    else:
        print("🏁 網頁資料處理完畢，已成功跳過排程通知並更新選單。")
