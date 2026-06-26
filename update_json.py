import json
import os
from datetime import datetime

JSON_FILE = 'tenants.json'
if not os.path.exists(JSON_FILE):
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f)

with open(JSON_FILE, 'r', encoding='utf-8') as f:
    try:
        tenants = json.load(f)
    except json.JSONDecodeError:
        tenants = []

event_type = os.getenv('EVENT_TYPE')  # add_new_tenant, confirm_receipt, delete_tenant
payload_str = os.getenv('PAYLOAD', '{}')
payload = json.loads(payload_str)

today_str = datetime.today().strftime('%Y-%m-%d')

if event_type == 'add_new_tenant':
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
    target_location = payload.get('location')
    target_room = payload.get('room')
    updated = False
    for t in tenants:
        if t['location'] == target_location and t['room'] == target_room:
            t['last_paid_date'] = today_str
            updated = True
            print(f"成功更新收租紀錄: {t['location']} - {t['room']}")
            break

# ─── 💡 新增：刪除房客邏輯 ───
elif event_type == 'delete_tenant':
    target_location = payload.get('location')
    target_room = payload.get('room')
    
    # 篩選掉符合「地點」與「房間」的房客（等於將其刪除）
    original_count = len(tenants)
    tenants = [t for t in tenants if not (t['location'] == target_location and t['room'] == target_room)]
    
    if len(tenants) < original_count:
        print(f"成功刪除房客紀錄: {target_location} - {target_room}")
    else:
        print("找不到對應房客，未刪除任何資料。")

# 寫回檔案
with open(JSON_FILE, 'w', encoding='utf-8') as f:
    json.dump(tenants, f, ensure_ascii=False, indent=2)
