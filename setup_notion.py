"""
One-time setup: creates the Contact Capture database in Notion.

Usage:
  NOTION_TOKEN=ntn_xxx NOTION_PARENT_PAGE_ID=xxx python setup_notion.py

The parent page ID is any Notion page where you want the database to live.
To find it: open the page in Notion, copy the URL, grab the 32-char hex ID.
"""

import os
import sys
import json
import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
PARENT_PAGE_ID = os.environ.get("NOTION_PARENT_PAGE_ID")

if not NOTION_TOKEN or not PARENT_PAGE_ID:
    print("Usage: NOTION_TOKEN=ntn_xxx NOTION_PARENT_PAGE_ID=xxx python setup_notion.py")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

database_payload = {
    "parent": {"type": "page_id", "page_id": PARENT_PAGE_ID},
    "title": [{"type": "text", "text": {"content": "Contact Capture"}}],
    "properties": {
        "Name": {"title": {}},
        "Company": {"rich_text": {}},
        "Title": {"rich_text": {}},
        "Email": {"email": {}},
        "LinkedIn": {"url": {}},
        "Date Met": {"date": {}},
        "Source": {
            "select": {
                "options": [
                    {"name": "Voice Note", "color": "blue"},
                    {"name": "Text", "color": "green"},
                    {"name": "Business Card", "color": "orange"},
                ]
            }
        },
        "Status": {
            "select": {
                "options": [
                    {"name": "New", "color": "yellow"},
                    {"name": "Followed Up", "color": "green"},
                    {"name": "Connected", "color": "purple"},
                    {"name": "Not Relevant", "color": "gray"},
                ]
            }
        },
        "Apollo Enriched": {"checkbox": {}},
    },
}

print("Creating Notion database...")
resp = requests.post(
    "https://api.notion.com/v1/databases",
    headers=HEADERS,
    json=database_payload,
)

if resp.status_code != 200:
    print(f"Error {resp.status_code}: {resp.text}")
    sys.exit(1)

result = resp.json()
db_id = result["id"]
db_url = result["url"]

print(f"\nDatabase created!")
print(f"  URL: {db_url}")
print(f"  ID:  {db_id}")
print(f"\nAdd this as the NOTION_DATABASE_ID secret in your GitHub repo.")
