import os
import json
from datetime import date, datetime
import requests

# ─── 基礎路徑與環境變數設定 ───
json_path = "tenants.json"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 載入資料庫
if os.path.exists(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        tenants = json.load(f)
else:
    tenants = []

# ─── 核心功能：處理來自網頁直連的 Dispatch 訊號 ───
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

    # ─── 分流 A：確認收租（不論正常或提前，皆精確紀錄「今天」為實際繳租日） ───
    if action_type in ["confirm_receipt", "advance_receipt"]:
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        elec_amount = int(payload.get("electricity") or 0)
        
        # 統一使用【點擊按鈕的今天】作為實際收租紀錄日
        record_date = date.today()
        today_str = record_date.strftime("%Y-%m-%d") 
        this_month_key = today_str[:7] # 取得當前年月標記，例如 "2026-07"
        
        print(f"▶ 執行收租登記: {location} - {room} (實際收到日期: {today_str})")
        
        updated = False
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                # 1. 寫入精確的繳租日期
                t["last_paid_date"] = today_str
                
                # 2. 將當期電費存入該月的歷史紀錄中
                if "electricity_history" not in t:
                    t["electricity_history"] = {}
                
                t["electricity_history"][this_month_key] = elec_amount
                t["electricity"] = 0  # 歸檔後將當期未繳電費歸零
                updated = True
                print(f"✅ 更新最後繳租日為 {today_str}，本月電費 {elec_amount} 元已歸檔。")
                break

    # ─── 分流 B：萬用基本資料新增 / 欄位修改 ───
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
            if payload.get("pay_day") is not None: existing_tenant["pay_day"] = int(payload.get("pay_day"))
            if payload.get("contract_start") is not None: existing_tenant["contract_start"] = payload.get("contract_start")
            if payload.get("contract_end") is not None: existing_tenant["contract_end"] = payload.get("contract_end")
            if name: existing_tenant["name"] = name
            print(f"✅ 房間 [{location}-{room}] 資料修訂完成！")
        else:
            new_tenant = {
                "location": location, "room": room, "name": name,
                "rent": int(payload.get("rent") or 0), "electricity": 0, "electricity_history": {},
                "pay_day": int(payload.get("pay_day") or 10), "contract_start": payload.get("contract_start") or "",
                "contract_end": payload.get("contract_end") or "", "last_paid_date": ""
            }
            tenants.append(new_tenant)
            print(f"✅ 全新房客 {name} 登記成功！")

    else:
        print(f"⚠️ 未知的網頁動作: {action_type}")
        return True

    # 儲存回資料庫
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(tenants, f, ensure_ascii=False, indent=4)
    print("💾 資料庫 tenants.json 更新完成！")
    return True

# ─── 核心功能：發送 Telegram 整合主選單與帳務報告 ───
def send_main_menu():
    today = date.today()
    current_month_str = today.strftime("%Y-%m") # 當前年份與月份
    
    unpaid_list = []
    paid_list = []
    
    # 篩選已繳/未繳名單
    for t in tenants:
        last_paid = t.get("last_paid_date", "")
        if last_paid and current_month_str in last_paid:
            paid_list.append(t)
        else:
            unpaid_list.append(t)

    # 建立 Telegram 報告文本
    msg = f"👑 **房東智慧收租管理主選單**\n"
    msg += f"📅 統計月份：{today.strftime('%Y年%m月')}\n"
    msg += f"───────────────────\n\n"
    
    msg += f"🔴 **【本月待繳 / 未完成名單】**\n"
    
    inline_keyboard = []

    if not unpaid_list:
        msg += " 暫無未繳房客，全部收齊囉！🎉\n"
    else:
        for t in unpaid_list:
            current_elec = t.get("electricity", 0)
            msg += f" 📍 {t['location']}-{t['room']} {t['name']} (每月{t['pay_day']}日)\n"
            msg += f"    ↳ 💰 租金: {t['rent']} 元 / ⚡ 當期電費: {current_elec} 元\n"
            
            # 為這間房間生成獨立的按鈕連結
            base_url = f"https://2025yang2025.github.io/rent-form/add.html?loc={t['location']}&room={t['room']}"
            
            inline_keyboard.append([
                {"text": f"🟢 確認收租 ({t['location']}-{t['room']})", "url": f"{base_url}&action=normal"},
                {"text": f"⏩ 提前繳租 ({t['location']}-{t['room']})", "url": f"{base_url}&action=advance"}
            ])
            
    msg += f"\n🟢 **【本月已收租房間】**\n"
    if not paid_list:
        msg += " 今日尚無已繳資料。\n"
    else:
        for t in paid_list:
            this_month_key = today.strftime("%Y-%m")
            history_elec = t.get("electricity_history", {}).get(this_month_key, 0)
            msg += f" ✅ {t['location']}-{t['room']} {t['name']}\n"
            msg += f"    ↳ 已於 {t['last_paid_date']} 勾記 (實收電費: {history_elec} 元)\n"

    # 末端保留一個萬用按鈕
    inline_keyboard.append([
        {"text": "⚙️ 開啟智慧管理後台主網頁", "url": "https://2025yang2025.github.io/rent-form/add.html"}
    ])

    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": inline_keyboard}
    }
    
    url = f"https://api.telegram.com/bot{BOT_TOKEN}/sendMessage"
    res = requests.post(url, json=payload)
    if res.ok:
        print("🚀 Telegram 整合主選單與獨立按鈕發送成功！")
    else:
        print(f"❌ Telegram 發送失敗: {res.text}")

# ─── 執行主程序 ───
if __name__ == "__main__":
    is_dispatch = handle_web_dispatch()
    send_main_menu()
