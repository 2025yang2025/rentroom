import json
import os
from datetime import datetime

# 確保檔案存在，若不存在則初始化空陣列
JSON_FILE = 'tenants.json'
if not os.path.exists(JSON_FILE):
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f)

# 讀取現有房客資料
with open(JSON_FILE, 'r', encoding='utf-8') as f:
    try:
        tenants = json.load(f)
    except json.JSONDecodeError:
        tenants = []

# 從 GitHub Actions 環境變數取得資料
event_type = os.getenv('EVENT_TYPE')  # add_new_tenant 或 confirm_receipt
payload_str = os.getenv('PAYLOAD', '{}')
payload = json.loads(payload_str)

today_str = datetime.today().strftime('%Y-%m-%d')

if event_type == 'add_new_tenant':
    # 建立新房客物件，確保型態正確
    new_tenant = {
        "location": payload.get('location', '').strip(),
        "room": payload.get('room', '').strip(),
        "name": payload.get('name', '').strip(),
        "rent": int(payload.get('rent', 0)),
        "pay_day": int(payload.get('pay_day', 1)),
        "contract_start": payload.get('contract_start', '').strip(),
        "contract_end": payload.get('contract_end', '').strip(),
        "last_paid_date": payload.get('last_paid_date', '').strip() or today_str
    }
    tenants.append(new_tenant)
    print(f"成功新增房客: {new_tenant['name']} ({new_tenant['room']})")

elif event_type == 'confirm_receipt':
    # 一鍵收租：透過 地點+房間 鎖定房客，並更新最後付款日為今天
    target_location = payload.get('location')
    target_room = payload.get('room')
    
    updated = False
    for t in tenants:
        if t['location'] == target_location and t['room'] == target_room:
            t['last_paid_date'] = today_str
            updated = True
            print(f"成功更新收租紀錄: {t['location']} - {t['room']} 的 {t['name']}")
            break
    if not updated:
        print("找不到對應的房客資料，無法更新收租。")

# 寫回 tenants.json 檔案
with open(JSON_FILE, 'w', encoding='utf-8') as f:
    json.dump(tenants, f, ensure_ascii=False, indent=2)
