import os
import json
from datetime import datetime, date, timedelta
import requests

# 讀取房客資料
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

def get_room_number_key(tenant_obj):
    r_name = str(tenant_obj.get('room', '')).replace('房', '').strip()
    try:
        return (0, int(r_name))
    except ValueError:
        return (1, r_name)

def clean_str(s):
    return "".join(str(s).split()).replace("房", "").lower()

# ==========================================
# 📥 核心功能：處理來自網頁直連的 Dispatch 訊號
# ==========================================
def handle_web_dispatch():
    # GitHub Action 會透過 CLIENT_PAYLOAD 傳遞資料
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

    # 處理繳租 (正常 或 提前)
    if action_type in ["confirm_receipt", "advance_receipt"]:
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        
        today_date = date.today()
        today_str = today_date.strftime("%Y-%m-%d")
        
        if action_type == "advance_receipt":
            # 提前繳租：計算下個月月份
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
                t["last_paid_date"] = today_str
                elec_amount = int(web_elec) if web_elec is not None else t.get('electricity', 0)
                
                if "electricity_history" not in t:
                    t["electricity_history"] = {}
                
                t["electricity_history"][this_month_key] = elec_amount
                t["electricity"] = 0 
                updated = True
                print(f"✅ 更新完成，[{this_month_key}] 紀錄電費 {elec_amount} 元已歸檔。")
                break
        
        if not updated:
            print(f"⚠️ 找不到對應房間：{location} {room}")

    # 處理新增或修改房客
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
            if payload.get("deposit") is not None: existing_tenant["deposit"] = int(payload.get("deposit"))
            if payload.get("electricity") is not None: existing_tenant["electricity"] = int(payload.get("electricity"))
            if payload.get("pay_day") is not None: existing_tenant["pay_day"] = int(payload.get("pay_day"))
            if payload.get("contract_start") is not None: existing_tenant["contract_start"] = payload.get("contract_start")
            if payload.get("contract_end") is not None: existing_tenant["contract_end"] = payload.get("contract_end")
            if name: existing_tenant["name"] = name
        else:
            new_tenant = {
                "location": location, "room": room, "name": name,
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

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(tenants, f, ensure_ascii=False, indent=4)
    print("💾 資料庫更新完成！")
    return True

# (這裡接續你原本的 check_tenants_and_notify 與 send_main_menu 函式)
# 請將你原有的那兩段代碼貼在下面即可

if __name__ == "__main__":
    # 1. 先執行 Web 訊號處理
    is_web_signal = handle_web_dispatch()
    
    # 2. 如果是排程觸發 (is_web_signal 為 False)，則執行檢查與通知
    if not is_web_signal:
        print("🕒 開始執行排程檢查與催繳通知...")
        try:
            # 確保這裡的函式名稱與你程式碼中定義的完全一致
            check_tenants_and_notify()
            send_main_menu()
            print("✅ 排程通知已成功發送。")
        except Exception as e:
            print(f"❌ 排程通知執行失敗: {e}")
    else:
        print("📥 網頁訊號處理完畢，本次不執行排程催繳。")
