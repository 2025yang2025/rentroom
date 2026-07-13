import os
import json
from datetime import date
import requests
import urllib.parse

json_path = "tenants.json"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("=== 🔍 系統環境檢查 ===")
print(f"TELEGRAM_BOT_TOKEN 存在狀態: { '✓ 填寫中' if BOT_TOKEN else '✗ 找不到變數(空值)' }")
print(f"TELEGRAM_CHAT_ID 存在狀態: { '✓ 填寫中' if CHAT_ID else '✗ 找不到變數(空值)' }")

if os.path.exists(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        try:
            tenants = json.load(f)
            print(f"📂 成功載入資料庫，目前共有 {len(tenants)} 筆房客資料。")
        except Exception as e:
            print(f"❌ 讀取 tenants.json 失敗（可能 JSON 格式壞掉了）: {e}")
            tenants = []
else:
    print("⚠️ 找不到 tenants.json，初始化空列表。")
    tenants = []

def handle_web_dispatch():
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    client_payload_str = os.getenv("CLIENT_PAYLOAD", "{}")
    
    if event_name != "repository_dispatch":
        return False 

    print("📥 偵測到來自網頁的直連訊號...")
    try:
        payload = json.loads(client_payload_str)
    except Exception as e:
        print(f"❌ 解析網頁 Payload 失敗: {e}")
        return True

    action_type = payload.get("action_type")
    global tenants

    def clean_str(s):
        return "".join(str(s).split()).replace("房", "").lower()

    if action_type in ["confirm_receipt", "advance_receipt"]:
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        elec_amount = int(payload.get("electricity") or 0)
        
        record_date = date.today()
        today_str = record_date.strftime("%Y-%m-%d") 
        this_month_key = today_str[:7]
        
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                t["last_paid_date"] = today_str
                if "electricity_history" not in t:
                    t["electricity_history"] = {}
                t["electricity_history"][this_month_key] = elec_amount
                t["electricity"] = 0
                break

    elif action_type == "add_tenant":
        room = payload.get("room")
        location = payload.get("location")
        name = payload.get("name")
        
        existing_tenant = None
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                existing_tenant = t
                break
        
        if existing_tenant:
            if payload.get("rent") is not None: existing_tenant["rent"] = int(payload.get("rent"))
            if payload.get("pay_day") is not None: existing_tenant["pay_day"] = int(payload.get("pay_day"))
            if payload.get("contract_start") is not None: existing_tenant["contract_start"] = payload.get("contract_start")
            if payload.get("contract_end") is not None: existing_tenant["contract_end"] = payload.get("contract_end")
            if name: existing_tenant["name"] = name
        else:
            new_tenant = {
                "location": location, "room": room, "name": name,
                "rent": int(payload.get("rent") or 0), "electricity": 0, "electricity_history": {},
                "pay_day": int(payload.get("pay_day") or 10), "contract_start": payload.get("contract_start") or "",
                "contract_end": payload.get("contract_end") or "", "last_paid_date": ""
            }
            tenants.append(new_tenant)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(tenants, f, ensure_ascii=False, indent=4)
    return True

def send_main_menu():
    print("🎬 開始建立 Telegram 訊息與按鈕...")
    today = date.today()
    current_month_str = today.strftime("%Y-%m")
    
    unpaid_list = []
    paid_list = []
    
    for t in tenants:
        last_paid = t.get("last_paid_date", "")
        if last_paid and current_month_str in last_paid:
            paid_list.append(t)
        else:
            unpaid_list.append(t)

    msg = f"<b>👑 房東智慧收租管理主選單</b>\n"
    msg += f"📅 統計月份：{today.strftime('%Y年%m月')}\n"
    msg += f"───────────────────\n\n"
    msg += f"🔴 <b>【本月待繳 / 未完成名單】</b>\n"
    
    inline_keyboard = []

    if not unpaid_list:
        msg += " 暫無未繳房客，全部收齊囉！🎉\n"
    else:
        for t in unpaid_list:
            current_elec = t.get("electricity", 0)
            msg += f" 📍 {t['location']}-{t['room']} {t['name']} (每月{t['pay_day']}日)\n"
            msg += f"    ↳ 💰 租金: {t['rent']} 元 / ⚡ 當期電費: {current_elec} 元\n"
            
            safe_loc = urllib.parse.quote(str(t['location']))
            safe_room = urllib.parse.quote(str(t['room']))
            base_url = f"https://2025yang2025.github.io/rent-form/add.html?loc={safe_loc}&room={safe_room}"
            
            inline_keyboard.append([
                {"text": f"🟢 確認收租 ({t['location']}-{t['room']})", "url": f"{base_url}&action=normal"},
                {"text": f"⏩ 提前繳租 ({t['location']}-{t['room']})", "url": f"{base_url}&action=advance"}
            ])
            
    msg += f"\n🟢 <b>【本月已收租房間】</b>\n"
    if not paid_list:
        msg += " 今日尚無已繳資料。\n"
    else:
        for t in paid_list:
            this_month_key = today.strftime("%Y-%m")
            history_elec = t.get("electricity_history", {}).get(this_month_key, 0)
            msg += f" ✅ {t['location']}-{t['room']} {t['name']}\n"
            msg += f"    ↳ 已於 {t['last_paid_date']} 勾記 (實收電費: {history_elec} 元)\n"

    inline_keyboard.append([
        {"text": "⚙️ 開啟智慧管理後台主網頁", "url": "https://2025yang2025.github.io/rent-form/add.html"}
    ])

    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": inline_keyboard}
    }
    
    url = f"https://api.telegram.com/bot{BOT_TOKEN}/sendMessage"
    
    print("📡 正在嘗試發送完整選單至 Telegram API...")
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"📥 Telegram 原始回應代碼: {res.status_code}")
        print(f"📥 Telegram 原始回應內文: {res.text}")
        
        if not res.ok:
            print("⚠️ 完整選單發送被拒，嘗試安全降級（只保留單一後台按鈕）...")
            fallback_keyboard = [[{"text": "⚙️ 開啟智慧管理後台主網頁", "url": "https://2025yang2025.github.io/rent-form/add.html"}]]
            payload["reply_markup"] = {"inline_keyboard": fallback_keyboard}
            res_fallback = requests.post(url, json=payload, timeout=10)
            print(f"📥 降級回應代碼: {res_fallback.status_code}")
            print(f"📥 降級回應內文: {res_fallback.text}")
    except Exception as api_err:
        print(f"❌ 連線至 Telegram API 時發生網路層崩潰: {api_err}")

if __name__ == "__main__":
    handle_web_dispatch()
    send_main_menu()
