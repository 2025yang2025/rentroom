import os
import json
from datetime import datetime, date, timedelta
import requests

# 1. 初始化設定
json_path = 'tenants.json'
bot_token = os.getenv('TG_BOT_TOKEN')
chat_id = os.getenv('TG_CHAT_ID')

def load_tenants():
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def clean_str(s):
    return "".join(str(s).split()).replace("房", "").lower()

def send_telegram(text):
    """共用的 Telegram 發送函式"""
    if not bot_token or not chat_id:
        print("❌ 缺少 TG_BOT_TOKEN 或 TG_CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        res = requests.post(url, json=payload)
        res.raise_for_status()
        print("✅ Telegram 訊息已送出")
    except Exception as e:
        print(f"❌ Telegram 發送失敗: {e}")

# 2. 處理網頁訊號
def handle_web_dispatch():
    if os.getenv("GITHUB_EVENT_NAME") != "repository_dispatch":
        return False
    
    print("📥 偵測到網頁訊號")
    payload = json.loads(os.getenv("CLIENT_PAYLOAD", "{}"))
    action_type = payload.get("action_type")
    tenants = load_tenants()

    if action_type in ["confirm_receipt", "advance_receipt"]:
        room = str(payload.get("room", "")).strip()
        location = str(payload.get("location", "")).strip()
        this_month_key = (date.today().replace(day=28) + timedelta(days=4)).strftime("%Y-%m") if action_type == "advance_receipt" else date.today().strftime("%Y-%m")
        
        for t in tenants:
            if clean_str(t.get("room", "")) == clean_str(room) and clean_str(t.get("location", "")) == clean_str(location):
                t["last_paid_date"] = date.today().strftime("%Y-%m-%d")
                t.setdefault("electricity_history", {})[this_month_key] = int(payload.get("electricity") or 0)
                t["electricity"] = 0
                break
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(tenants, f, ensure_ascii=False, indent=4)
        print("💾 資料庫更新成功")
    return True

# 3. 催繳與主選單邏輯
def check_tenants_and_notify():
    print("🕒 執行檢查程序...")
    # 在此加入你原本的「檢查租金逾期」程式碼
    # 完成後呼叫: send_telegram("催繳通知內容...")
    pass

def send_main_menu():
    print("📋 發送主選單...")
    send_telegram("🏠 房務系統主選單：\n1. 查詢租金狀態\n2. 紀錄繳租")

# 4. 主程式
if __name__ == "__main__":
    is_web_signal = handle_web_dispatch()
    
    if not is_web_signal:
        try:
            check_tenants_and_notify()
            send_main_menu()
        except Exception as e:
            print(f"❌ 執行失敗: {e}")
    else:
        print("📥 網頁訊號處理完畢。")
