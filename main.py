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
        
        # 修正：根據動作動態計算歸檔月份
        from datetime import timedelta
        today_date = date.today()
        today_str = today_date.strftime("%Y-%m-%d")
        
        if action_type == "advance_receipt":
            # 提前繳租：計算下個月的年月份 (例如 2026-07 變 2026-08)
            # 透過將當月最後一天再加 1 天來安全取得下個月
            next_month_date = (today_date.replace(day=28) + timedelta(days=4))
            this_month_key = next_month_date.strftime("%Y-%m")
            mode_text = "提前繳租"
        else:
            this_month_key = today_str[:7]
            mode_text = "正常收租"
            
        web_elec = payload.get("electricity")
        print(f"▶ 執行【{mode_text}確認】: {location} - {room} (歸檔月份: {this_month_key})")
        
        updated = False
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                # 銷帳關鍵：設定最後繳租日為今天
                t["last_paid_date"] = today_str
                
                # 確定本月最終要歸檔的電費金額
                elec_amount = int(web_elec) if web_elec is not None else t.get('electricity', 0)
                
                if "electricity_history" not in t:
                    t["electricity_history"] = {}
                
                # 寫入正確的月份歷史
                t["electricity_history"][this_month_key] = elec_amount
                t["electricity"] = 0 # 收齊後，當期應繳電費歸零
                updated = True
                print(f"✅ 更新最後繳租日為 {today_str}，[{this_month_key}] 紀錄電費 {elec_amount} 元已歸檔並歸零。")
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
            p_day = t.get('pay_day', 1)

            # 💡 檢查「最後繳租日」的年月份
            last_paid_ym = t.get('last_paid_date', '')[:7] if t.get('last_paid_date') else ""
            
            # 如果今天日期大於等於房客的繳租日，且「這個月還沒繳過租金」才觸發提醒
            if today.day >= p_day and last_paid_ym != current_year_month:
                status_label = f"📅 <b>【今日繳租提醒 (每月 {p_day} 日)】</b>" if today.day == p_day else f"🚨 ⚠️ <b>【未收租催繳 (逾期)】</b>"
                reminders.append(
                    f"{loc_room}\n"
                    f"👤 房客：{t['name']} (每月 {p_day} 日繳租)\n"
                    f"💡 狀態：{status_label} 尚未登記 {current_year_month} 月款項！\n"
                    f"💰 應繳金額：租金 {t['rent']} 元{elec_text}\n"
                    f"📅 上次付款日：<code>{t.get('last_paid_date') or '無紀錄'}</code>"
                )
                
                # 建立攜帶完整房客資訊的小尾巴網址，讓網頁頂部顯示動態精美標題
                base_url = f"https://2025yang2025.github.io/rent-form/add.html?tab=advance&location={t['location']}&room={t['room']}&name={t['name']}&rent={t['rent']}&pay_day={p_day}"
                
                buttons.append([
                    {
                        "text": f"🟢 正常收租 ({t['name']})", 
                        "url": f"{base_url}&action=confirm"
                    },
                    {
                        "text": f"⏩ 提前繳租 ({t['name']})", 
                        "url": f"{base_url}&action=advance"
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
            
            # 🟢 已收租名單加強版顯示：房號 (姓名 / 租金 / 押金 / 繳租日 / ⚡ 已繳電費)
            paid_lines = []
            for t in sorted_paid_objs:
                hist = t.get('electricity_history', {})
                c_elec = hist.get(current_year_month, 0)
                elec_str = f" / ⚡電費:{c_elec}元" if c_elec > 0 else ""
                deposit_val = t.get('deposit', 0)
                paid_lines.append(f"🟢 {t.get('room','')} ({t.get('name','')} / {t.get('rent',0)}元 / 押金:{deposit_val}元 / 繳租日:{t.get('pay_day',1)}號{elec_str})")
            paid_summary = "\n    ".join(paid_lines) if paid_lines else "    <i>暫無</i>"
            
            # 🔴 未收租名單加強版顯示：房號 (姓名 / 租金 / 押金 / 繳租日 / ⚡ 當期應繳電費)
            unpaid_lines = []
            for t in sorted_unpaid_objs:
                curr_elec = t.get('electricity', 0)
                elec_str = f" / ⚡電費:{curr_elec}元" if curr_elec > 0 else ""
                deposit_val = t.get('deposit', 0)
                unpaid_lines.append(f"🔴 {t.get('room','')} ({t.get('name','')} / {t.get('rent',0)}元 / 押金:{deposit_val}元 / 繳租日:{t.get('pay_day',1)}號{elec_str})")
            unpaid_summary = "\n    ".join(unpaid_lines) if unpaid_lines else "    <i>✨ 全數繳齊！</i>"
            
            finance_text += (
                f"=====================\n"
                f"📍 <b>【{loc}地區】財務統計</b>\n"
                f"💰 實收租金：<b>{recv_r}</b> / {exp_r} 元\n"
                f"📈 租金進度：<code>{progress}%</code>\n\n"
                f"✅ <b>已收租房間：</b>\n    {paid_summary}\n"
                f"⚠️ <b>未收租房間：</b>\n    {unpaid_summary}\n"
            )

    # ─── 主選單下方的功能按鈕群（直連對應至最新的 add.html） ───
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
