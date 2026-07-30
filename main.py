import os
import json
from datetime import datetime, date, timedelta
import requests
import sys

json_path = 'tenants.json'
try:
    with open(json_path, 'r', encoding='utf-8') as f:
        tenants = json.load(f)
    print(f"💾 成功讀取資料庫，目前共有 {len(tenants)} 筆房客資料。")
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

def send_tg_error(msg):
    """專用緊急通知工具，確保錯誤一定能傳到手機上"""
    if bot_token and chat_id:
        try:
            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"})
        except Exception as e:
            print(f"發送 TG 錯誤失敗: {e}")

# 房號排序專用小工具
def get_room_number_key(tenant_obj):
    r_name = str(tenant_obj.get('room', '')).replace('房', '').strip()
    try:
        return (0, int(r_name))
    except ValueError:
        return (1, r_name)

# ==========================================
# 📥 核心功能：處理來自網頁直連的 Dispatch 訊號
# ==========================================
def handle_web_dispatch():
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    
    if event_name != "repository_dispatch":
        return False 

    print("📥 偵測到來自網頁的直連訊號 (repository_dispatch)")
    
    try:
        if event_path and os.path.exists(event_path):
            with open(event_path, 'r', encoding='utf-8') as f:
                event_data = json.load(f)
            payload = event_data.get("client_payload", {})
            print(f"✅ 成功解析 GitHub 官方事件檔案！Payload 內容: {payload}")
        else:
            print("⚠️ 找不到 GITHUB_EVENT_PATH 檔案，嘗試讀取環境變數...")
            client_payload_str = os.getenv("CLIENT_PAYLOAD", "{}")
            payload = json.loads(client_payload_str)
    except Exception as e:
        err = f"❌ 解析網頁 Payload 失敗: {e}"
        print(err)
        send_tg_error(err)
        return True

    action_type = payload.get("action_type")
    global tenants

    if not action_type:
        err = f"⚠️ 警告：收到的網頁資料中沒有 action_type 欄位！\nPayload: {payload}"
        print(err)
        send_tg_error(err)
        return True

    def clean_str(s):
        if not s:
            return ""
        for remove_char in ["房", "地區", "【", "】", " ", "\t", "\n", "\r"]:
            s = str(s).replace(remove_char, "")
        return s.strip().lower()

    room = str(payload.get("room", "")).strip()
    location = str(payload.get("location", "")).strip()
    name = payload.get("name", "")
    
    today_date = date.today()
    today_str = today_date.strftime("%Y-%m-%d")

    target_room_clean = clean_str(room)
    target_loc_clean = clean_str(location)

    # 尋找是否為資料庫已有的舊房客
    existing_tenant = None
    for t in tenants:
        current_room_clean = clean_str(t.get("room", ""))
        current_loc_clean = clean_str(t.get("location", ""))
        if (target_loc_clean in current_loc_clean or current_loc_clean in target_loc_clean) and (target_room_clean == current_room_clean):
            existing_tenant = t
            break

    # ─── 強固邏輯：只要是已有房客，不管 action_type 是甚麼，一律進行銷帳 ───
    if existing_tenant:
        print(f"▶ 執行已有房客資料異動與銷帳: 地點={location}, 房號={room}")
        
        # 1. 更新基本欄位
        if payload.get("rent") is not None: existing_tenant["rent"] = int(payload.get("rent"))
        if payload.get("deposit") is not None: existing_tenant["deposit"] = int(payload.get("deposit"))
        if payload.get("pay_day") is not None: existing_tenant["pay_day"] = int(payload.get("pay_day"))
        if payload.get("contract_start") is not None: existing_tenant["contract_start"] = payload.get("contract_start")
        if payload.get("contract_end") is not None: existing_tenant["contract_end"] = payload.get("contract_end")
        if name: existing_tenant["name"] = name

        # 2. 自動判定銷帳歸屬月份 (解決提前繳租問題)
        pay_day = int(existing_tenant.get("pay_day", 1))
        
        if action_type == "advance_receipt" or (today_date.day > pay_day and existing_tenant.get("last_paid_date", "")[:7] == current_year_month):
            first_day_next_month = (today_date.replace(day=28) + timedelta(days=4)).replace(day=1)
            target_month_key = first_day_next_month.strftime("%Y-%m")
            print(f"⏩ 偵測到提前繳租，將款項歸檔至下個月：{target_month_key}")
        else:
            target_month_key = current_year_month

        existing_tenant["last_paid_date"] = today_str
        web_elec = payload.get("electricity")
        elec_amount = int(web_elec) if web_elec is not None else int(existing_tenant.get('electricity') or 0)
        
        if "electricity_history" not in existing_tenant:
            existing_tenant["electricity_history"] = {}
        
        existing_tenant["electricity_history"][target_month_key] = elec_amount
        existing_tenant["electricity"] = 0 
        print(f"✅ 自動銷帳成功！[{target_month_key}] 紀錄電費 {elec_amount} 元已歸檔並歸零。")

    elif action_type == "add_tenant":
        print(f"▶ 執行【全新房客建立】: {location} - {room}")
        new_tenant = {
            "location": location, "room": room, "name": name,
            "rent": int(payload.get("rent") or 0), "deposit": int(payload.get("deposit") or 0),
            "electricity": int(payload.get("electricity") or 0), "electricity_history": {},
            "pay_day": int(payload.get("pay_day") or 1), "contract_start": payload.get("contract_start") or "",
            "contract_end": payload.get("contract_end") or "", "last_paid_date": ""
        }
        tenants.append(new_tenant)
    else:
        all_rooms_debug = "\n".join([f"• <code>[{t.get('location')}]</code> - <code>[{t.get('room')}]</code> ({t.get('name')})" for t in tenants])
        err_msg = (
            f"❌ <b>比對失敗：找不到對應房間無法銷帳！</b>\n\n"
            f"網頁傳來地點：<code>{location}</code>\n"
            f"網頁傳來房號：<code>{room}</code>\n\n"
            f"📋 <b>資料庫目前現有房間：</b>\n{all_rooms_debug}"
        )
        send_tg_error(err_msg)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(tenants, f, ensure_ascii=False, indent=4)
    print("💾 資料庫 tenants.json 更新完成！")
    return True

# ==========================================
# ⏰ 每日催繳與到期檢查邏輯
# ==========================================
def check_tenants_and_notify():
    if not bot_token or not chat_id:
        return

    for t in tenants:
        if int(t.get('rent') or 0) == 0 or t.get('name') == "待租":
            continue
            
        try:
            loc_room = f"📍 <b>[{t['location']} - {t['room']}]</b>"
            reminders = []
            buttons = []
            
            elec_amount = t.get('electricity', 0)
            elec_text = f" + ⚡ 電費:{elec_amount}元" if elec_amount > 0 else ""
            p_day = t.get('pay_day', 1)
            last_paid_ym = t.get('last_paid_date', '')[:7] if t.get('last_paid_date') else ""
            
            if today.day >= p_day and last_paid_ym != current_year_month:
                status_label = f"📅 <b>【今日繳租提醒 (每月 {p_day} 日)】</b>" if today.day == p_day else f"🚨 ⚠️ <b>【未收租催繳 (逾期)】</b>"
                reminders.append(
                    f"{loc_room}\n"
                    f"👤 房客：{t['name']} (每月 {p_day} 日繳租)\n"
                    f"💡 狀態：{status_label} 尚未登記 {current_year_month} 月款項！\n"
                    f"💰 應繳金額：租金 {t['rent']} 元{elec_text}\n"
                    f"📅 上次付款日：<code>{t.get('last_paid_date') or '無紀錄'}</code>"
                )
                
                base_url = f"https://2025yang2025.github.io/rent-form/add.html?tab=advance&location={t['location']}&room={t['room']}&name={t['name']}&rent={t['rent']}&pay_day={p_day}"
                buttons.append([
                    {"text": f"🟢 正常收租 ({t['name']})", "url": f"{base_url}&action=confirm"},
                    {"text": f"⏩ 提前繳租 ({t['name']})", "url": f"{base_url}&action=advance"}
                ])

            if reminders:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {"chat_id": chat_id, "text": "\n".join(reminders), "parse_mode": "HTML"}
                if buttons: payload["reply_markup"] = {"inline_keyboard": buttons}
                requests.post(url, json=payload)
        except Exception as room_error:
            print(f"💥 處理房間錯誤: {room_error}")

# ==========================================
# 📄 獨立發送：房客租約到期日報表
# ==========================================
def send_contract_expiry_report():
    if not bot_token or not chat_id:
        return

    today_date = date.today()
    contract_lines = []

    # 整理房客資料並計算到期天數
    tenant_list = []
    for t in tenants:
        if int(t.get('rent') or 0) == 0 or t.get('name') == "待租":
            continue
        
        c_end_str = t.get('contract_end', '')
        days_left = None
        if c_end_str:
            try:
                c_end_date = datetime.strptime(c_end_str, "%Y-%m-%d").date()
                days_left = (c_end_date - today_date).days
            except ValueError:
                pass
        
        tenant_list.append({
            'obj': t,
            'days_left': days_left if days_left is not None else 9999
        })

    # 依照剩餘天數由少到多排序（最快到期的排前面）
    tenant_list.sort(key=lambda x: x['days_left'])

    for item in tenant_list:
        t = item['obj']
        days_left = item['days_left']
        c_start = t.get('contract_start', '未填寫')
        c_end = t.get('contract_end', '未填寫')
        loc = t.get('location', '')
        room = t.get('room', '')
        name = t.get('name', '')

        if days_left == 9999:
            status_tag = "⚪ 無到期日資料"
        elif days_left < 0:
            status_tag = f"🚨 <b>已逾期 {-days_left} 天</b>"
        elif days_left <= 30:
            status_tag = f"⚠️ <b>剩餘 {days_left} 天到期</b>"
        elif days_left <= 60:
            status_tag = f"⚡ 剩餘 {days_left} 天"
        else:
            status_tag = f"🟢 剩餘 {days_left} 天"

        contract_lines.append(
            f"📍 <b>[{loc} - {room}]</b> {name}\n"
            f"📅 租約：<code>{c_start}</code> ~ <code>{c_end}</code>\n"
            f"⏳ 狀態：{status_tag}\n"
        )

    if not contract_lines:
        contract_text = "📑 <b>【房客租約到期總覽】</b>\n\n目前暫無有效房客租約紀錄。"
    else:
        contract_text = f"📑 <b>【房客租約到期總覽】</b>\n==============================\n\n" + "\n".join(contract_lines) + "=============================="

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": contract_text, "parse_mode": "HTML"}
    res = requests.post(url, json=payload)
    print(f"📄 租約到期報表發送結果: {res.status_code}")

# ==========================================
# 📊 報表功能：發送主選單與財務總表
# ==========================================
def send_main_menu():
    if not bot_token or not chat_id:
        return

    first_day_of_this_month = today.replace(day=1)
    last_month_ym = (first_day_of_this_month - timedelta(days=1)).strftime('%Y-%m')

    location_stats = {}
    for t in tenants:
        if int(t.get('rent') or 0) == 0 or t.get('name') == "待租":
            continue

        loc = t.get('location', '未分類').strip()
        if loc not in location_stats:
            location_stats[loc] = {
                "paid_raw_tenants": [],   
                "unpaid_raw_tenants": [], 
                "raw_tenants_list": []
            }
        
        location_stats[loc]["raw_tenants_list"].append(t)
        
        last_paid_str = t.get('last_paid_date', '')
        last_paid_ym = last_paid_str[:7] if last_paid_str else ""
        p_day = int(t.get('pay_day', 1))
        
        is_paid = False
        
        if last_paid_ym == current_year_month:
            is_paid = True
        elif last_paid_ym == last_month_ym:
            try:
                last_paid_day = int(last_paid_str.split('-')[2])
                if today.day < p_day and last_paid_day >= p_day:
                    is_paid = True
            except:
                pass
        elif last_paid_ym > current_year_month:
            is_paid = True

        if is_paid:
            location_stats[loc]["paid_raw_tenants"].append(t)
        else:
            location_stats[loc]["unpaid_raw_tenants"].append(t)

    finance_text = f"👑 <b>房東管理主選單</b>\n\n📊 <b>【{current_year_month} 月收租分區財務報表】</b>\n=============================="
    
    if location_stats:
        for loc, stats in location_stats.items():
            sorted_paid_objs = sorted(stats["paid_raw_tenants"], key=get_room_number_key)
            sorted_unpaid_objs = sorted(stats["unpaid_raw_tenants"], key=get_room_number_key)
            
            exp_r = sum(int(t.get('rent') or 0) for t in stats["raw_tenants_list"])
            recv_r = sum(int(t.get('rent') or 0) for t in stats["paid_raw_tenants"])
            progress = round((recv_r / exp_r) * 100 if exp_r > 0 else 0, 1)
            
            paid_lines = []
            for t in sorted_paid_objs:
                hist = t.get('electricity_history', {})
                c_elec = hist.get(current_year_month, 0)
                if c_elec == 0:
                    next_month_date = (today.replace(day=28) + timedelta(days=4))
                    c_elec = hist.get(next_month_date.strftime("%Y-%m"), 0)
                
                elec_str = f" / ⚡ 電費:{c_elec}元" if c_elec > 0 else ""
                deposit_val = t.get('deposit', 0)
                paid_lines.append(f"🟢 {t.get('room','')} ({t.get('name','')} / {t.get('rent',0)}元 / 押金:{deposit_val}元 / 繳租日:{t.get('pay_day',1)}號{elec_str})")
            paid_summary = "\n".join(paid_lines) if paid_lines else "   <i>暫無紀錄</i>"
            
            unpaid_lines = []
            for t in sorted_unpaid_objs:
                curr_elec = t.get('electricity', 0)
                elec_str = f" / ⚡ 電費:{curr_elec}元" if curr_elec > 0 else ""
                deposit_val = t.get('deposit', 0)
                unpaid_lines.append(f"🔴 {t.get('room','')} ({t.get('name','')} / {t.get('rent',0)}元 / 押金:{deposit_val}元 / 繳租日:{t.get('pay_day',1)}號{elec_str})")
            unpaid_summary = "\n".join(unpaid_lines) if unpaid_lines else "   ✨ <i>全數繳齊！</i>"
            
            finance_text += (
                f"\n📍 <b>【{loc}地區】財務統計</b>\n"
                f"💰 實收租金：<b>{recv_r} / {exp_r} 元</b>\n"
                f"📈 租金進度：{progress:0.1f}%\n\n"
                f"✅ <b>已收租房間：</b>\n{paid_summary}\n"
                f"⚠️ <b>未收租房間：</b>\n{unpaid_summary}\n"
                f"=============================="
            )

    menu_message = f"{finance_text}\n📋 <b>下方可前往網頁操作：</b>"
    
    inline_buttons = [
        [
            {"text": "➕ 填寫新房客資料", "url": "https://2025yang2025.github.io/rent-form/add.html?tab=tenant"},
            {"text": "⏩ 房客提前繳租", "url": "https://2025yang2025.github.io/rent-form/add.html?tab=advance"}
        ]
    ]

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload_menu = {
        "chat_id": chat_id, 
        "text": menu_message, 
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": inline_buttons}
    }
    
    res = requests.post(url, json=payload_menu)
    print(f"📊 主選單發送結果: {res.status_code}")

if __name__ == "__main__":
    is_web_signal = handle_web_dispatch()
    
    if is_web_signal:
        print("⚡ 網頁銷帳處理完畢，發送租約到期報表與最新主選單...")
        send_contract_expiry_report()
        send_main_menu()
        sys.exit(0)
        
    check_tenants_and_notify()
    send_contract_expiry_report()
    send_main_menu()
