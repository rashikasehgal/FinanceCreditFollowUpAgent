import csv
import random
from datetime import datetime, timedelta
import os

os.makedirs('frontend', exist_ok=True)

# 20 records
records = []
names = ["Rajesh Kumar", "Priya Sharma", "Amit Patel", "Sneha Gupta", "Vikram Singh", 
         "Anjali Desai", "Rahul Verma", "Kavita Reddy", "Sanjay Mishra", "Pooja Joshi", 
         "Arjun Nair", "Neha Agarwal", "Manoj Tiwari", "Kiran Rao", "Vivek Menon",
         "Swati Iyer", "Deepak Chawla", "Ritu Kulkarni", "Ashish Jain", "Meera Pillai"]

# Current date: 2026-05-12
today = datetime(2026, 5, 12)

# Assign categories
categories = [
    (1, 7, 1),   # 1-7 days: count 1
    (8, 14, 2),  # 8-14 days: count 2
    (15, 21, 3), # 15-21 days: count 3
    (22, 30, 4), # 22-30 days: count 4
    (31, 60, 5)  # 30+ days: count 5
]

# Distribute 20 records roughly across categories
distribution = [4, 4, 4, 4, 4]
current_idx = 0

for i, count in enumerate(distribution):
    min_days, max_days, f_count = categories[i]
    for _ in range(count):
        days_overdue = random.randint(min_days, max_days)
        due_date = today - timedelta(days=days_overdue)
        amount = random.randint(5000, 100000)
        invoice_no = f"INV-2026-{1000 + current_idx + 1}"
        client_name = names[current_idx]
        email = f"{client_name.split()[0].lower()}@example.com"
        
        records.append({
            "invoice_no": invoice_no,
            "client_name": client_name,
            "amount": amount,
            "due_date": due_date.strftime("%Y-%m-%d"),
            "email": email,
            "followup_count": f_count
        })
        current_idx += 1

with open('frontend/mock_invoices.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=["invoice_no", "client_name", "amount", "due_date", "email", "followup_count"])
    writer.writeheader()
    writer.writerows(records)

print("Created frontend/mock_invoices.csv")
