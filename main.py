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
current_year_month = today.strftime('%Y-%m')

# 房號排序專用小工具
def get_room_number_key(tenant_obj):
    r_name = str(tenant_obj.get('room', '')).replace('房', '').strip()
    try:
        return (0, int(r_name)) # 純數字房號優先排序 (如 101, 102)
    except ValueError:
        return (1, r_name)     # 含有文字的排後面 (如 A房, 店面)

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

    # ─── 分流 A：確認收到租金（支援正常收租與提前繳租） ───
    if action_type in ["confirm_receipt", "advance_receipt"]:
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        today_str = date.today().strftime("%Y-%m-%d")
        this_month_key = today_str[:7]
        
        web_elec = payload.get("electricity")
        
        mode_text = "正常收租" if action_type == "confirm_receipt" else "提前繳租"
        print(f"▶ 執行【{mode_text}確認】: {location} - {room}")
        updated = False
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                # 關鍵邏輯：無論是提早還是當天，只要登記了，就將最後繳租日設為今天（例如：2026-07-05）
                t["last_paid_date"] = today_str
                
                # 確定本月最終要歸檔的電費金額
                elec_amount = int(web_elec) if web_elec is not None else t.get('electricity', 0)
                
                if "electricity_history" not in t:
                    t["electricity_history"] = {}
                
                t["electricity_history"][this_month_key] = elec_amount
                t["electricity"] = 0 # 收齊後，待繳電費歸零
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
                "electricity_history": {},
                "pay_day": int(payload.get("pay_day") or 1),
                "contract_start": payload.get("contract_start") or "",
                "contract_end": payload.get("contract_end") or "",
                "last_paid_date": ""
            }
            tenants.append(new_tenant)
            print(f"✅ 全新房客 {name} 登記成功！")

    else:
        print(f"⚠️ 未知的網頁動作: {action_type}")
        return True

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(tenants, f, ensure_ascii=False, indent=4)
    print("💾 資料庫 tenants.json 更新完成！")
    return True


# ==========================================
# ⏰ 每日催繳與到期檢查邏輯 (定時排程觸發)
# ==========================================
def check_tenants_and_notify():
    if not bot_token or not chat_id:
        print("⚠️ 找不到 Telegram Token 或 Chat ID，跳過通知檢查。")
        return

    has_notification = False
    vacant_rooms = []

    for t in tenants:
        if int(t.get('rent') or 0) == 0 or t.get('name') == "待租":
            vacant_rooms.append(t)
            continue
            
        try:
            loc_room = f"📍 <b>[{t['location']} - {t['room']}]</b>"
            reminders = []
            buttons = []
            
            elec_amount = t.get('electricity', 0)
            elec_text = f" + ⚡ 電費:{elec_amount}元" if elec_amount > 0 else ""

            # 💡 檢查「最後繳租日」的年月份
            last_paid_ym = t.get('last_paid_date', '')[:7] if t.get('last_paid_date') else ""
            
            # 如果今天日期大於等於房客的繳租日，且「這個月還沒繳過租金」才觸發提醒
            if today.day >= t['pay_day'] and last_paid_ym != current_year_month:
                status_label = "📅 <b>【今日繳租提醒】</b>" if today.day == t['pay_day'] else "🚨 ⚠️ <b>【未收租催繳】</b>"
                reminders.append(
                    f"{loc_room}\n"
                    f"👤 房客：{t['name']}\n"
                    f"💡 狀態：{status_label} 尚未登記 {current_year_month} 月款項！\n"
                    f"💰 應繳金額：租金 {t['rent']} 元{elec_text}\n"
                    f"📅 上次付款日：<code>{t.get('last_paid_date') or '無紀錄'}</code>"
                )
                
                # 催繳通知附帶雙功能按鈕，並傳遞該房客的參數直連 add.html
                buttons.append([
                    {
                        "text": f"🟢 正常收租 ({t['name']})", 
                        "url": f"https://2025yang2025.github.io/rent-form/add.html?tab=advance&action=confirm&room={t['room']}&location={t['location']}"
                    },
                    {
                        "text": f"⏩ 提前繳租 ({t['name']})", 
                        "url": f"https://2025yang2025.github.io/rent-form/add.html?tab=advance&action=advance&room={t['room']}&location={t['location']}"
                    }
                ])

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

        except Exception as room_error:
            print(f"💥 處理房間 [{t.get('location')}-{t.get('room')}] 時發生錯誤: {room_error}")

    if not has_notification:
        print("🎉 檢查完畢：今日無任何房客需要催繳！")


# ==========================================
# 📊 報表功能：發送主選單與財務總表
# ==========================================
def send_main_menu():
    if not bot_token or not chat_id:
        return

    location_stats = {}
    for t in tenants:
        if int(t.get('rent') or 0) == 0 or t.get('name') == "待租":
            continue

        loc = t.get('location', '未分類').strip()
        if loc not in location_stats:
            location_stats[loc] = {
                "total_collected_elec": 0,
                "elec_detail_list": [],
                "paid_raw_tenants": [],   
                "unpaid_raw_tenants": [], 
                "raw_tenants_list": []
            }
        
        location_stats[loc]["raw_tenants_list"].append(t)
        
        history = t.get('electricity_history', {})
        collected_elec_this_month = history.get(current_year_month, 0)
        last_paid_ym = t.get('last_paid_date', '')[:7] if t.get('last_paid_date') else ""
        
        if last_paid_ym == current_year_month:
            location_stats[loc]["paid_raw_tenants"].append(t)
        else:
            location_stats[loc]["unpaid_raw_tenants"].append(t)
            
        if collected_elec_this_month > 0:
            location_stats[loc]["total_collected_elec"] += collected_elec_this_month
            location_stats[loc]["elec_detail_list"].append((t, collected_elec_this_month))

    finance_text = f"📊 <b>【{current_year_month} 月收租分區財務報表】</b>\n"
    if location_stats:
        for loc, stats in location_stats.items():
            sorted_paid_objs = sorted(stats["paid_raw_tenants"], key=get_room_number_key)
            sorted_unpaid_objs = sorted(stats["unpaid_raw_tenants"], key=get_room_number_key)
            
            exp_r = sum(t.get('rent', 0) for t in stats["raw_tenants_list"])
            recv_r = sum(t.get('rent', 0) for t in stats["paid_raw_tenants"])
            progress = round((recv_r / exp_r) * 100 if exp_r > 0 else 0, 1)
            
            paid_lines = [f"🟢 {t.get('room','')} ({t.get('name','')} / {t.get('rent',0)}元)" for t in sorted_paid_objs]
            paid_summary = "\n   ".join(paid_lines) if paid_lines else "   <i>暫無</i>"
            
            unpaid_lines = [f"🔴 {t.get('room','')} ({t.get('name','')} / {t.get('rent',0)}元)" for t in sorted_unpaid_objs]
            unpaid_summary = "\n   ".join(unpaid_lines) if unpaid_lines else "   <i>✨ 全數繳齊！</i>"
            
            finance_text += (
                f"=====================\n"
                f"📍 <b>【{loc}地區】財務統計</b>\n"
                f"💰 實收租金：<b>{recv_r}</b> / {exp_r} 元\n"
                f"📈 租金進度：<code>{progress}%</code>\n\n"
                f"✅ <b>已收租房間：</b>\n   {paid_summary}\n"
                f"⚠️ <b>未收租房間：</b>\n   {unpaid_summary}\n"
            )

    # ─── 📊 總表下方的常駐主功能雙按鈕（直連對應至 add.html） ───
    inline_buttons = [
        [
            {"text": "➕ 填寫新房客資料", "url": "https://2025yang2025.github.io/rent-form/add.html?tab=tenant"},
            {"text": "⏩ 房客提前繳租", "url": "https://2025yang2025.github.io/rent-form/add.html?tab=advance"}
        ]
    ]

    menu_message = f"👑 <b>房東管理主選單</b>\n\n{finance_text}\n=====================\n📋 <b>下方可前往網頁操作：</b>"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    payload_menu = {
        "chat_id": chat_id,
        "text": menu_message,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": inline_buttons}
    }
    requests.post(url, json=payload_menu)


if __name__ == "__main__":
    is_web_signal = handle_web_dispatch()
    if not is_web_signal:
        check_tenants_and_notify()
    send_main_menu()
