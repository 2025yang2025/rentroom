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

    # ─── 分流 A：確認收到本月租金（點擊當天即為紀錄日，適用當天與提前繳租） ───
    if action_type == "confirm_receipt":
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        today_str = date.today().strftime("%Y-%m-%d") 
        this_month_key = today_str[:7]                 
        
        print(f"▶ 執行【確認收租】: {location} - {room} (記錄日期: {today_str})")
        updated = False
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                t["last_paid_date"] = today_str
                
                elec_amount = t.get("electricity", 0)
                if "electricity_history" not in t:
                    t["electricity_history"] = {}
                
                t["electricity_history"][this_month_key] = elec_amount
                t["electricity"] = 0 
                updated = True
                print(f"✅ 更新最後繳租日為 {today_str}，本月電費 {elec_amount} 元已歸檔。")
                break

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
            if payload.get("rent") is not None: existing_tenant["rent"] = int(payload.get("rent"))
            if payload.get("deposit") is not None: existing_tenant["deposit"] = int(payload.get("deposit"))
            if payload.get("electricity") is not None: existing_tenant["electricity"] = int(payload.get("electricity"))
            if payload.get("pay_day") is not None: existing_tenant["pay_day"] = int(payload.get("pay_day"))
            if payload.get("contract_start") is not None: existing_tenant["contract_start"] = payload.get("contract_start")
            if payload.get("contract_end") is not None: existing_tenant["contract_end"] = payload.get("contract_end")
            if name: existing_tenant["name"] = name
            print(f"✅ 房間 [{location}-{room}] 資料修訂完成！")
        else:
            new_tenant = {
                "location": location, "room": room, "name": name,
                "rent": int(payload.get("rent") or 0), "deposit": int(payload.get("deposit") or 0),
                "electricity": int(payload.get("electricity") or 0), "electricity_history": {},
                "pay_day": int(payload.get("pay_day") or 1), "contract_start": payload.get("contract_start") or "",
                "contract_end": payload.get("contract_end") or "", "last_paid_date": ""
            }
            tenants.append(new_tenant)
            print(f"✅ 全新房客 {name} 登記成功！")

    # ─── 分流 C：辦理租客續約 ───
    elif action_type == "renew_contract":
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        updated = False
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                t["rent"] = int(payload.get("rent", 0))
                if payload.get("deposit") is not None: t["deposit"] = int(payload.get("deposit"))
                t["contract_start"] = payload.get("contract_start")
                t["contract_end"] = payload.get("contract_end")
                t["last_paid_date"] = ""
                updated = True
                break

    else:
        print(f"⚠️ 未知的網頁動作: {action_type}")
        return True

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(tenants, f, ensure_ascii=False, indent=4)
    print("💾 資料庫 tenants.json 更新完成！")
    return True


# 2. 每日狀態與催繳彙整（不帶個別按鈕，純訊息記錄）
def check_tenants_and_notify():
    if not bot_token or not chat_id:
        return

    daily_reports = []
    vacant_rooms = []

    for t in tenants:
        if int(t.get('rent') or 0) == 0 or t.get('name') == "待租":
            vacant_rooms.append(t)
            continue
            
        try:
            loc_room = f"📍 <b>[{t['location']} - {t['room']}]</b>"
            elec_amount = t.get('electricity', 0)
            elec_text = f" + ⚡ 電費:{elec_amount}元" if elec_amount > 0 else ""
            last_paid_ym = t.get('last_paid_date', '')[:7] if t.get('last_paid_date') else ""

            # 狀況一：今天剛好是繳租日
            if today.day == t['pay_day'] and last_paid_ym != current_year_month:
                daily_reports.append(
                    f"{loc_room} 👤 {t['name']}\n📅 <b>【今日到期提醒】</b> 尚未交租\n"
                    f"💰 應繳：租金 {t['rent']} 元{elec_text}\n"
                )
            # 狀況二：過期未繳催繳
            elif today.day > t['pay_day'] and last_paid_ym != current_year_month:
                daily_reports.append(
                    f"{loc_room} 👤 {t['name']}\n🚨 <b>【逾期未收催繳】</b> 請留意對帳\n"
                    f"💰 應繳：租金 {t['rent']} 元{elec_text}\n"
                )
            # 狀況三：尚未到期，但本月還沒繳（供房東隨時掌握誰可能提前繳）
            elif today.day < t['pay_day'] and last_paid_ym != current_year_month:
                daily_reports.append(
                    f"{loc_room} 👤 {t['name']}\n⏳ <b>【本月尚未到期】</b> ({t['pay_day']}號繳)\n"
                )

            # 租約到期提醒
            try:
                if t.get('contract_end'):
                    contract_end_date = datetime.strptime(t['contract_end'], '%Y-%m-%d')
                    days_to_contract_end = (contract_end_date - today).days
                    if 0 <= days_to_contract_end <= 30:
                        daily_reports.append(
                            f"{loc_room} 👤 {t['name']}\n⏳ <b>【租約即將到期】</b> 剩餘 {days_to_contract_end} 天\n"
                        )
            except Exception:
                pass

        except Exception as room_error:
            print(f"💥 處理房間時發生非預期錯誤: {room_error}")

    # 發送每日房客動態彙整
    if daily_reports:
        report_message = f"🔔 <b>【今日房客繳租動態彙整】</b>\n=====================\n\n" + "\n".join(daily_reports)
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": report_message, "parse_mode": "HTML"})

    # 發送空房廣播
    if vacant_rooms:
        sorted_vacant = sorted(vacant_rooms, key=lambda x: (x.get('location', ''), get_room_number_key(x)))
        vacant_lines = [f"🚪 <b>{v.get('location')} - {v.get('room')}</b>" for v in sorted_vacant]
        vacant_message = "🔍 <b>【目前待租空房名單】</b>\n\n" + "\n".join(vacant_lines)
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": vacant_message, "parse_mode": "HTML"})


# 3. 主選單訊息 (集中放置管理與登記按鈕)
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
                "total_collected_elec": 0, "elec_detail_list": [],
                "paid_raw_tenants": [], "unpaid_raw_tenants": [], "raw_tenants_list": []
            }
        
        location_stats[loc]["raw_tenants_list"].append(t)
        
        elec_amount = t.get('electricity', 0)
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
            
            paid_summary = "\n   ".join([f"🟢 {t.get('room','')} ({t.get('name','')})" for t in sorted_paid_objs]) if sorted_paid_objs else "   <i>暫無</i>"
            unpaid_summary = "\n   ".join([f"🔴 {t.get('room','')} ({t.get('name','')})" for t in sorted_unpaid_objs]) if sorted_unpaid_objs else "   <i>✨ 全數繳齊！</i>"
            
            finance_text += (
                f"=====================\n"
                f"📍 <b>【{loc}地區】財務統計</b>\n"
                f"💰 實收租金：<b>{recv_r}</b> / {exp_r} 元\n"
                f"📈 租金進度：<code>{progress}%</code>\n\n"
                f"✅ <b>已收租房間：</b>\n   {paid_summary}\n"
                f"⚠️ <b>未收租房間：</b>\n   {unpaid_summary}\n"
            )

    tenant_list_text = ""
    if location_stats:
        for loc, stats in location_stats.items():
            tenant_list_text += f"🏠 <b>【{loc}地區名冊】</b>\n"
            sorted_room_list = sorted(stats["raw_tenants_list"], key=get_room_number_key)
            for idx, t in enumerate(sorted_room_list, 1):
                tenant_list_text += f"  {idx}. 🚪 <b>{t['room']}</b> - {t['name']} ({t.get('pay_day')}號繳)\n     📅 上次對帳：<code>{t.get('last_paid_date') or '無'}</code>\n"

    # ✨ 集中在主選單下方的管理鍵（點擊即可前往你的記帳/管理網頁）
    main_menu_buttons = [
        [
            {"text": "🔗 前往房東收租/記帳網頁", "url": "https://2025yang2025.github.io/rent-form/add.html"}
        ]
    ]

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # 發送財務主選單（帶有管理網頁的按鈕）
    payload_menu = {
        "chat_id": chat_id,
        "text": f"👑 <b>房東管理主選單</b>\n\n{finance_text}",
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": main_menu_buttons}
    }
    requests.post(url, json=payload_menu)
    
    # 發送名冊
    requests.post(url, json={"chat_id": chat_id, "text": f"📋 <b>房客名冊</b>\n=====================\n{tenant_list_text}", "parse_mode": "HTML"})


if __name__ == "__main__":
    is_web_signal = handle_web_dispatch()
    if not is_web_signal:
        check_tenants_and_notify()
        send_main_menu()
    else:
        send_main_menu()
