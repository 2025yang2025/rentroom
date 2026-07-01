import os
import json
from datetime import datetime, date
import requests

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
current_year_month = today.strftime('%Y-%m') # 格式如 "2026-07"

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

    # ─── 分流 A：確認收到租金（含每月電費存檔） ───
    if action_type == "confirm_receipt":
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        today_str = date.today().strftime("%Y-%m-%d")
        this_month_key = today_str[:7] # "2026-07"
        
        print(f"▶ 執行【收租確認】: {location} - {room}")
        updated = False
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                t["last_paid_date"] = today_str
                
                # 💡 核心改動：將當月抄表電費移入歷史紀錄，記錄為該地區該月份的電費收入
                elec_amount = t.get("electricity", 0)
                if "electricity_history" not in t:
                    t["electricity_history"] = {}
                
                # 寫入當月歷史（如果重複點擊會覆蓋，確保數據不重複計算）
                t["electricity_history"][this_month_key] = elec_amount
                
                # 存檔後將當期電費歸零，等待下個月底或下個月初重新抄表
                t["electricity" ] = 0 
                updated = True
                print(f"✅ 更新最後繳租日為 {today_str}，本月電費 {elec_amount} 元已歸檔並歸零。")
                break
        if not updated:
            print(f"⚠️ 找不到對應房間：{location} {room}")

    # ─── 分流 B：萬用新增 / 欄位追加修改 ───
    elif action_type == "add_tenant":
        room = payload.get("room")
        location = payload.get("location")
        name = payload.get("name")
        
        print(f"▶ 執行【房客資料異動/新增】: {location} - {room}")
        
        existing_tenant = None
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                existing_tenant = t
                break
        
        if existing_tenant:
            print(f"🔍 偵測到現存房間，啟動欄位「智能追加修改」模式...")
            if payload.get("rent") is not None: existing_tenant["rent"] = int(payload.get("rent"))
            if payload.get("deposit") is not None: existing_tenant["deposit"] = int(payload.get("deposit"))
            if payload.get("electricity") is not None: existing_tenant["electricity"] = int(payload.get("electricity"))
            if payload.get("pay_day") is not None: existing_tenant["pay_day"] = int(payload.get("pay_day"))
            if payload.get("contract_start") is not None: existing_tenant["contract_start"] = payload.get("contract_start")
            if payload.get("contract_end") is not None: existing_tenant["contract_end"] = payload.get("contract_end")
            if name: existing_tenant["name"] = name
            print(f"✅ 房間 [{location}-{room}] 資料修訂完成！")
        else:
            print(f"🆕 找不到歷史紀錄，建立全新房客...")
            new_tenant = {
                "location": location,
                "room": room,
                "name": name,
                "rent": int(payload.get("rent") or 0),
                "deposit": int(payload.get("deposit") or 0),
                "electricity": int(payload.get("electricity") or 0),
                "electricity_history": {}, # 建立空的電費歷史區
                "pay_day": int(payload.get("pay_day") or 1),
                "contract_start": payload.get("contract_start") or "",
                "contract_end": payload.get("contract_end") or "",
                "last_paid_date": ""
            }
            tenants.append(new_tenant)
            print(f"✅ 全新房客 {name} 登記成功！")

    # ─── 分流 C：辦理租客續約 ───
    elif action_type == "renew_contract":
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        
        print(f"▶ 執行【房客續約展延】: {location} - {room}")
        updated = False
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                t["rent"] = int(payload.get("rent", 0))
                if payload.get("deposit") is not None: t["deposit"] = int(payload.get("deposit"))
                t["contract_start"] = payload.get("contract_start")
                t["contract_end"] = payload.get("contract_end")
                t["last_paid_date"] = ""
                updated = True
                print(f"✅ 成功幫房客 {t['name']} 展延合約。")
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
        return

    has_notification = False

    for t in tenants:
        loc_room = f"📍 <b>[{t['location']} - {t['room']}]</b>"
        reminders = []
        buttons = []
        
        elec_amount = t.get('electricity', 0)
        elec_text = f" + ⚡ 電費:{elec_amount}元" if elec_amount > 0 else ""

        # ─── 條件 A：收租預告 ───
        try:
            rent_date_this_month = datetime(today.year, today.month, t['pay_day'])
            days_to_pay = (rent_date_this_month - today).days
            if days_to_pay == 3:
                reminders.append(
                    f"{loc_room}\n"
                    f"👤 房客：{t['name']}\n"
                    f"💰 應繳：租金 <code>{t['rent']}</code> 元{elec_text}\n"
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
                f"💡 狀態：{status_label} 尚未登記 {current_year_month} 月款項！\n"
                f"💰 應繳金額：租金 {t['rent']} 元{elec_text}\n"
                f"📅 上次付款日：<code>{t['last_paid_date'] or '無紀錄'}</code>"
            )
            buttons.append([
                {
                    "text": f"🟢 確認收到 {t['name']} 租金" + (f"(含電費)" if elec_amount > 0 else ""), 
                    "url": f"https://2025yang2025.github.io/rent-form/confirm.html?room={t['room']}&location={t['location']}"
                }
            ])

        # ─── 條件 C：租約到期提醒 ───
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
                buttons.append([
                    {
                        "text": f"📝 辦理 {t['name']} 續約展延", 
                        "url": f"https://2025yang2025.github.io/rent-form/renew.html?room={t['room']}&location={t['location']}"
                    }
                ])
        except Exception:
            pass

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


# 3. 主選單訊息 (分區財務報表 + 各地區每月電費獨立統計)
def send_main_menu():
    if not bot_token or not chat_id:
        return

    location_stats = {}
    for t in tenants:
        loc = t.get('location', '未分類').strip()
        rent_amount = t.get('rent', 0)
        room_name = t.get('room', '')
        tenant_name = t.get('name', '')
        
        # 讀取當期網頁輸入的待繳電費
        elec_amount = t.get('electricity', 0)
        
        # 讀取「歷史紀錄」中屬於本月(current_year_month)已收完歸檔的電費
        history = t.get('electricity_history', {})
        collected_elec_this_month = history.get(current_year_month, 0)
        
        if loc not in location_stats:
            location_stats[loc] = {
                "expected_rent": 0, 
                "received_rent": 0, 
                "total_collected_elec": 0, # 各地區本月累計實收電費
                "elec_detail_list": [],    # 電費明細清單
                "paid": [], 
                "unpaid": []
            }
        
        # 租金財務統計
        location_stats[loc]["expected_rent"] += rent_amount
        last_paid_ym = t.get('last_paid_date', '')[:7] if t.get('last_paid_date') else ""
        
        elec_show = f" + ⚡當期電費:{elec_amount}元" if elec_amount > 0 else ""
        room_info = f"{room_name} ({tenant_name} / {rent_amount}元{elec_show})"
        
        if last_paid_ym == current_year_month:
            location_stats[loc]["received_rent"] += rent_amount
            location_stats[loc]["paid"].append(f"🟢 {room_info}")
        else:
            location_stats[loc]["unpaid"].append(f"🔴 {room_info}")
            
        # 💡 電費獨立歷史統計：不論租金收了沒，只要本月有做過收租確認（或電費歸檔），就計入該區本月實收電費
        if collected_elec_this_month > 0:
            location_stats[loc]["total_collected_elec"] += collected_elec_this_month
            location_stats[loc]["elec_detail_list"].append(f"⚡ {room_name}: {collected_elec_this_month} 元")

    finance_text = f"📊 <b>【{current_year_month} 月收租分區財務報表】</b>\n"
    if location_stats:
        for loc, stats in location_stats.items():
            exp_r = stats["expected_rent"]
            recv_r = stats["received_rent"]
            progress = round((recv_r / exp_r) * 100 if exp_r > 0 else 0, 1)
            
            paid_summary = "\n   ".join(stats["paid"]) if stats["paid"] else "   <i>暫無</i>"
            unpaid_summary = "\n   ".join(stats["unpaid"]) if stats["unpaid"] else "   <i>✨ 全數繳齊！</i>"
            
            # 組裝本地區電費明細
            elec_total = stats["total_collected_elec"]
            elec_summary = "\n   ".join(stats["elec_detail_list"]) if stats["elec_detail_list"] else "   <i>暫無實收電費紀錄</i>"
            
            finance_text += (
                f"=====================\n"
                f"📍 <b>【{loc}地區】財務統計</b>\n"
                f"💰 實收租金：<b>{recv_r}</b> / {exp_r} 元\n"
                f"📈 租金進度：<code>{progress}%</code>\n"
                f"🔌 <b>本月實收電費總計：<u>{elec_total} 元</u></b>\n" # 👈 地區每月實收電費加總
                f"   {elec_summary}\n\n"                       # 👈 顯示誰繳了多少
                f"✅ <b>已收租房間：</b>\n   {paid_summary}\n"
                f"⚠️ <b>未收租房間：</b>\n   {unpaid_summary}\n"
            )
    else:
        finance_text += "=====================\n<i>目前暫無地區統計資料。</i>"

    tenant_list_text = ""
    if tenants:
        for i, t in enumerate(tenants, 1):
            last_pay = t.get('last_paid_date')
            last_pay_show = f"<code>{last_pay}</code>" if last_pay else "<i>無紀錄</i>"
            deposit_show = f"{t.get('deposit', 0)}"
            elec_current = t.get('electricity', 0)
            
            tenant_list_text += (
                f"{i}. 📍 <b>{t['location']} - {t['room']}</b>\n"
                f"   👤 房客：{t['name']} ({t['rent']}元 / {t.get('pay_day', 1)}號繳)\n"
                f"   🔒 已收押金：<b>{deposit_show} 元</b>\n"
                f"   🔌 待繳電費(未對帳)：<b>{elec_current} 元</b>\n"
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
