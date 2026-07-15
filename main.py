import os
import json
from datetime import datetime, date, timedelta
import requests

# 1. 初始化設定
json_path = 'tenants.json'
try:
    with open(json_path, 'r', encoding='utf-8') as f:
        tenants = json.load(f)
except Exception as e:
    tenants = []
    print(f"⚠️ 讀取檔案失敗: {e}")

bot_token = os.getenv('TG_BOT_TOKEN')
chat_id = os.getenv('TG_CHAT_ID')

def clean_str(s):
    return "".join(str(s).split()).replace("房", "").lower()

# 2. 核心函式：網頁訊號處理
def handle_web_dispatch():
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    client_payload_str = os.getenv("CLIENT_PAYLOAD", "{}")
    
    if event_name != "repository_dispatch":
        return False 

    print("📥 偵測到網頁訊號")
    try:
        payload = json.loads(client_payload_str)
    except:
        return True

    action_type = payload.get("action_type")
    global tenants

    if action_type in ["confirm_receipt", "advance_receipt"]:
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        today_date = date.today()
        
        # 判斷月份
        if action_type == "advance_receipt":
            next_month_date = (today_date.replace(day=28) + timedelta(days=4))
            this_month_key = next_month_date.strftime("%Y-%m")
        else:
            this_month_key = today_date.strftime("%Y-%m")
            
        web_elec = payload.get("electricity")
        
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                t["last_paid_date"] = today_date.strftime("%Y-%m-%d")
                t["electricity_history"][this_month_key] = int(web_elec) if web_elec else t.get('electricity', 0)
                t["electricity"] = 0 
                break
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(tenants, f, ensure_ascii=False, indent=4)
        print("💾 資料庫更新成功")
    return True

# 3. 請將你原本的通知函式填入這裡
def check_tenants_and_notify():
    print(f"DEBUG: BOT_TOKEN 是否存在: {'有' if bot_token else '沒有'}")
    print(f"DEBUG: CHAT_ID 是否存在: {chat_id}")
    # 如果顯示「沒有」，請到 GitHub Settings -> Secrets and variables -> Actions 確認 Token 名稱是否拼寫錯誤
    pass

def send_main_menu():
    # --- 請將你原本發送主選單的邏輯貼在這裡 ---
    print("正在發送主選單...")
    pass

# 4. 主程式執行入口
if __name__ == "__main__":
    is_web_signal = handle_web_dispatch()
    
    # 只有在非網頁觸發時，才跑原本的自動化通知
    if not is_web_signal:
        print("🕒 開始執行排程檢查與通知...")
        try:
            check_tenants_and_notify()
            send_main_menu()
            print("✅ 排程通知完成。")
        except Exception as e:
            print(f"❌ 排程通知失敗: {e}")
    else:
        print("📥 網頁訊號已處理，結束程式。")
