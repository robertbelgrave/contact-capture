"""
Contact Capture Bot

Polls a Telegram bot for voice notes, text messages, and business card
photos about people you've just met. Parses contact details with Claude,
enriches via Apollo, researches via Exa, synthesizes a dossier, and
creates a Notion contact card.

Runs as a scheduled GitHub Action (twice daily).

Setup: See README.md for full instructions.
"""

import os
import sys
import re
import json
import base64
import requests
from datetime import datetime, timezone

# --- Config ---
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # Restrict to your chat only

# Optional — each enables additional features
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")  # Voice note transcription
EXA_API_KEY = os.environ.get("EXA_API_KEY")  # Web research for dossier
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY")  # Contact enrichment (email, LinkedIn)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# --- Telegram ---

def get_updates():
    """Fetch unprocessed messages from Telegram."""
    resp = requests.get(f"{TELEGRAM_API}/getUpdates", params={"timeout": 0})
    resp.raise_for_status()
    return resp.json().get("result", [])


def confirm_updates(offset):
    """Mark updates as processed so they don't repeat."""
    requests.get(f"{TELEGRAM_API}/getUpdates", params={"offset": offset})


def send_message(chat_id, text):
    """Send a confirmation message back to Telegram."""
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    })


def download_file(file_id, save_path):
    """Download any file from Telegram by file_id."""
    resp = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
    resp.raise_for_status()
    file_path = resp.json()["result"]["file_path"]

    file_resp = requests.get(
        f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    )
    file_resp.raise_for_status()

    with open(save_path, "wb") as f:
        f.write(file_resp.content)
    return save_path


# --- Transcription ---

def transcribe_audio(file_path):
    """Transcribe audio via OpenAI Whisper API."""
    if not OPENAI_API_KEY:
        return None

    with open(file_path, "rb") as audio_file:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": ("voice.ogg", audio_file, "audio/ogg")},
            data={"model": "whisper-1"},
        )
    resp.raise_for_status()
    return resp.json()["text"]


# --- Business Card OCR ---

def extract_business_card(photo_path):
    """Use Claude vision to read a business card photo."""
    from anthropic import Anthropic

    with open(photo_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    media_type = "image/png" if photo_path.endswith(".png") else "image/jpeg"

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Extract all information from this business card. "
                        "Return a natural sentence like: "
                        "'Met [Name], [Title] at [Company]. Email: [email]. Phone: [phone]. Website: [url].' "
                        "Include every detail visible on the card."
                    ),
                },
            ],
        }],
    )

    return message.content[0].text


# --- Claude Parsing ---

def parse_contact(text):
    """Use Claude to extract structured contact info from a raw note."""
    from anthropic import Anthropic

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""Extract contact information from this note. Someone just met this person at an event or meeting and quickly jotted this down.

Note: "{text}"

Return a JSON object with these fields (use null for anything not mentioned):
{{
  "name": "Full name of the person",
  "company": "Company or organization name",
  "title": "Job title or role if mentioned",
  "email": "Email address if mentioned",
  "phone": "Phone number if mentioned",
  "event": "Event name or location where they met",
  "context": "Key topics discussed, interests, or notable details",
  "follow_up": "One concrete suggested follow-up action based on the context",
  "search_company_domain": "Best guess at company website domain for enrichment (e.g. kelloggs.com). null if unsure."
}}

Return ONLY valid JSON. No markdown, no explanation."""
        }],
    )

    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(response_text)


# --- Apollo Enrichment ---

def enrich_with_apollo(name, company_domain=None):
    """Search Apollo for the contact and return enrichment data."""
    if not APOLLO_API_KEY:
        return None

    payload = {
        "q_person_name": name,
        "page": 1,
        "per_page": 1,
    }
    if company_domain:
        payload["q_organization_domains"] = company_domain

    resp = requests.post(
        "https://api.apollo.io/api/v1/mixed_people/api_search",
        headers={"X-Api-Key": APOLLO_API_KEY, "Content-Type": "application/json"},
        json=payload,
    )

    if resp.status_code != 200:
        print(f"Apollo API error: {resp.status_code} — {resp.text[:200]}")
        return None

    people = resp.json().get("people", [])
    if not people:
        return None

    p = people[0]
    org = p.get("organization") or {}
    return {
        "name": p.get("name"),
        "title": p.get("title"),
        "email": p.get("email"),
        "linkedin_url": p.get("linkedin_url"),
        "company": org.get("name"),
        "company_website": org.get("website_url"),
        "city": p.get("city"),
        "state": p.get("state"),
        "country": p.get("country"),
    }


# --- Exa Research ---

def exa_research(name, company=None):
    """Search Exa for web content about the contact."""
    if not EXA_API_KEY:
        print("No EXA_API_KEY — skipping web research")
        return []

    queries = []
    if company:
        queries.append(f"{name} {company}")
        queries.append(f"{name} {company} interview OR keynote OR article OR LinkedIn")
    else:
        queries.append(name)

    all_results = []
    seen_urls = set()

    for query in queries:
        try:
            resp = requests.post(
                "https://api.exa.ai/search",
                headers={
                    "x-api-key": EXA_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "num_results": 5,
                    "type": "neural",
                    "contents": {
                        "text": {"max_characters": 1500},
                    },
                },
            )
            if resp.status_code == 200:
                for r in resp.json().get("results", []):
                    url = r.get("url", "")
                    if url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append({
                            "title": r.get("title", ""),
                            "url": url,
                            "text": r.get("text", ""),
                        })
            else:
                print(f"Exa search error: {resp.status_code} — {resp.text[:200]}")
        except Exception as e:
            print(f"Exa error (non-fatal): {e}")

    print(f"Exa: found {len(all_results)} results across {len(queries)} queries")
    return all_results


# --- Dossier Synthesis ---

def synthesize_dossier(parsed, enriched, exa_results, raw_text):
    """Have Claude synthesize all research into a contact dossier."""
    from anthropic import Anthropic

    sections = [f"Original note from meeting: {raw_text}"]

    if parsed:
        sections.append(f"Parsed contact info: {json.dumps(parsed)}")

    if enriched:
        sections.append(f"Apollo database enrichment: {json.dumps(enriched)}")

    if exa_results:
        sections.append("Web research results:")
        for i, r in enumerate(exa_results, 1):
            sections.append(
                f"  [{i}] {r['title']} ({r['url']})\n  {r['text'][:1000]}"
            )

    context = "\n\n".join(sections)

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""Based on the following information about a person I just met, write a concise dossier/briefing.

{context}

Write the dossier using these sections (skip any section where you genuinely have no information — do NOT fabricate):

**Background:** Career history, education, key roles. Be specific with companies, titles, and dates where available.

**Current Role:** What they do now, their responsibilities, recent initiatives or focus areas.

**Recent Activity:** Articles, talks, panels, projects, or news mentions. Include specifics — titles, dates, venues.

**Company Context:** What's happening at their company that's relevant — strategy, news, challenges, market position.

**Connection Points:** Based on my note about our conversation, what are natural threads to continue? Shared interests, mutual challenges, collaboration angles.

**Suggested Approach:** A specific, actionable follow-up suggestion that references something concrete from the research. Not generic — make it something only someone who did their homework would say.

Be direct and specific. No filler, no corporate speak. If the web research is thin, say so honestly rather than padding with generalities."""
        }],
    )

    return message.content[0].text


# --- Notion ---

def _notion_paragraph(text):
    """Create a Notion paragraph block, handling the 2000 char limit."""
    blocks = []
    while text:
        chunk = text[:2000]
        text = text[2000:]
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": chunk}}]},
        })
    return blocks


def _notion_heading(text):
    """Create a Notion heading_3 block."""
    return {
        "object": "block", "type": "heading_3",
        "heading_3": {"rich_text": [{"text": {"content": text}}]},
    }


def _parse_rich_text(text):
    """Convert markdown bold (**text**) to Notion rich text annotations."""
    segments = []
    parts = re.split(r'(\*\*.*?\*\*)', text)
    for part in parts:
        if not part:
            continue
        if part.startswith('**') and part.endswith('**'):
            content = part[2:-2]
            if content:
                segments.append({
                    "text": {"content": content[:2000]},
                    "annotations": {"bold": True},
                })
        else:
            segments.append({"text": {"content": part[:2000]}})
    return segments if segments else [{"text": {"content": ""}}]


def _markdown_to_notion_blocks(markdown_text):
    """Convert a markdown dossier into native Notion blocks."""
    blocks = []
    for line in markdown_text.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue

        # H1 heading → heading_2 (page title is h1)
        if stripped.startswith('# '):
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": stripped[2:].strip()[:2000]}}]},
            })

        # H2 heading
        elif stripped.startswith('## '):
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"text": {"content": stripped[3:].strip()[:2000]}}]},
            })

        # Standalone bold line like **Background:** → section heading
        elif re.match(r'^\*\*[^*]+\*\*\s*$', stripped):
            heading_text = stripped.strip('* ').rstrip(':')
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"text": {"content": heading_text[:2000]}}]},
            })

        # Bullet item
        elif stripped.startswith('- ') or stripped.startswith('* '):
            item_text = stripped[2:].strip()
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": _parse_rich_text(item_text)},
            })

        # Regular paragraph with inline bold support
        else:
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": _parse_rich_text(stripped)},
            })

    return blocks


def create_notion_contact(parsed, enriched, raw_text, source, dossier=None):
    """Create a contact page in the Notion database."""
    name = parsed.get("name") or "Unknown Contact"

    e = enriched or {}
    title = e.get("title") or parsed.get("title") or ""
    company = e.get("company") or parsed.get("company") or ""
    email = e.get("email") or parsed.get("email") or ""
    linkedin = e.get("linkedin_url") or ""

    properties = {
        "Name": {"title": [{"text": {"content": name}}]},
        "Company": {"rich_text": [{"text": {"content": company}}]},
        "Title": {"rich_text": [{"text": {"content": title}}]},
        "Date Met": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}},
        "Source": {"select": {"name": source}},
        "Status": {"select": {"name": "New"}},
        "Apollo Enriched": {"checkbox": enriched is not None},
    }

    if email:
        properties["Email"] = {"email": email}
    if linkedin:
        properties["LinkedIn"] = {"url": linkedin}

    children = []

    if dossier:
        children.append(_notion_heading("Dossier"))
        children.extend(_markdown_to_notion_blocks(dossier))
        children.append({
            "object": "block", "type": "divider", "divider": {},
        })

    if parsed.get("context"):
        children.append(_notion_heading("Meeting Notes"))
        children.extend(_notion_paragraph(parsed["context"]))

    if parsed.get("event"):
        children.append(_notion_heading("Met At"))
        children.extend(_notion_paragraph(parsed["event"]))

    if parsed.get("follow_up") and not dossier:
        children.append(_notion_heading("Suggested Follow-Up"))
        children.extend(_notion_paragraph(parsed["follow_up"]))

    children.append(_notion_heading("Raw Note"))
    children.extend(_notion_paragraph(raw_text))

    if enriched:
        children.append(_notion_heading("Apollo Data"))
        apollo_lines = []
        if e.get("title"):
            apollo_lines.append(f"Title: {e['title']}")
        if e.get("email"):
            apollo_lines.append(f"Email: {e['email']}")
        if e.get("linkedin_url"):
            apollo_lines.append(f"LinkedIn: {e['linkedin_url']}")
        if e.get("company_website"):
            apollo_lines.append(f"Company site: {e['company_website']}")
        location_parts = [x for x in [e.get("city"), e.get("state"), e.get("country")] if x]
        if location_parts:
            apollo_lines.append(f"Location: {', '.join(location_parts)}")
        if apollo_lines:
            children.extend(_notion_paragraph("\n".join(apollo_lines)))

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        },
        json={
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": properties,
            "children": children,
        },
    )
    resp.raise_for_status()
    return resp.json()["url"]


# --- Main ---

def process_update(update):
    """Process a single Telegram message."""
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    if TELEGRAM_CHAT_ID and str(chat_id) != str(TELEGRAM_CHAT_ID):
        print(f"Ignored message from chat {chat_id} (not authorized)")
        return

    if not TELEGRAM_CHAT_ID:
        print(f"[SETUP] Message from chat_id: {chat_id} — add this as TELEGRAM_CHAT_ID secret")

    raw_text = None
    source = "Text"

    # --- Photo (business card) ---
    photos = message.get("photo")
    if photos:
        best_photo = photos[-1]
        print("Downloading photo...")
        photo_path = download_file(best_photo["file_id"], "/tmp/business_card.jpg")

        print("Reading business card with Claude Vision...")
        raw_text = extract_business_card(photo_path)
        source = "Business Card"

        caption = message.get("caption", "")
        if caption:
            raw_text = f"{raw_text}\nAdditional context: {caption}"

        print(f"Card text: {raw_text}")

    # --- Voice note ---
    elif message.get("voice") or message.get("audio"):
        voice = message.get("voice") or message.get("audio")
        if not OPENAI_API_KEY:
            send_message(chat_id, "Voice notes need OPENAI_API_KEY. Send text or a photo instead.")
            return

        print("Downloading voice note...")
        audio_path = download_file(voice["file_id"], "/tmp/voice_note.ogg")

        print("Transcribing...")
        raw_text = transcribe_audio(audio_path)
        source = "Voice Note"

        if not raw_text:
            send_message(chat_id, "Couldn't transcribe that. Try again or send text.")
            return

        print(f"Transcription: {raw_text}")

    # --- Text message ---
    elif message.get("text"):
        raw_text = message["text"]

        if raw_text.startswith("/"):
            if raw_text.strip() in ("/start", "/help"):
                send_message(
                    chat_id,
                    "*Contact Capture Bot*\n\n"
                    "Send me any of these:\n"
                    "- A *text message* about someone you met\n"
                    "- A *voice note* describing the person\n"
                    "- A *photo of a business card*\n\n"
                    "I'll research them and create a dossier in Notion.\n\n"
                    "_Example: Just met Joe Blogs from Kellogg's, VP Marketing. "
                    "Talked about their digital transformation program._"
                )
            return
    else:
        return

    # --- Processing pipeline ---
    preview = raw_text[:80] + ("..." if len(raw_text) > 80 else "")
    send_message(chat_id, f"Processing: _{preview}_")

    # 1. Parse with Claude
    print("Parsing with Claude...")
    try:
        parsed = parse_contact(raw_text)
        print(f"Parsed: {json.dumps(parsed, indent=2)}")
    except Exception as e:
        print(f"Parse error: {e}")
        send_message(chat_id, "Couldn't parse contact info. Try including a name and company.")
        return

    # 2. Enrich with Apollo
    enriched = None
    if parsed.get("name"):
        print(f"Searching Apollo for {parsed['name']}...")
        try:
            enriched = enrich_with_apollo(
                parsed["name"],
                parsed.get("search_company_domain"),
            )
            if enriched:
                print(f"Apollo match: {enriched.get('name')} — {enriched.get('title')}")
            else:
                print("Apollo: no match found")
        except Exception as e:
            print(f"Apollo error (non-fatal): {e}")

    # 3. Research with Exa
    exa_results = []
    if parsed.get("name"):
        print(f"Researching {parsed['name']} via Exa...")
        try:
            exa_results = exa_research(
                parsed["name"],
                parsed.get("company"),
            )
        except Exception as e:
            print(f"Exa error (non-fatal): {e}")

    # 4. Synthesize dossier
    dossier = None
    if exa_results or enriched:
        print("Synthesizing dossier...")
        try:
            dossier = synthesize_dossier(parsed, enriched, exa_results, raw_text)
            print(f"Dossier: {len(dossier)} chars")
        except Exception as e:
            print(f"Dossier synthesis error (non-fatal): {e}")

    # 5. Create Notion contact card
    print("Creating Notion contact...")
    try:
        notion_url = create_notion_contact(parsed, enriched, raw_text, source, dossier)
        print(f"Notion page: {notion_url}")
    except Exception as e:
        print(f"Notion error: {e}")
        send_message(chat_id, f"Parsed the contact but Notion write failed: {e}")
        return

    # 6. Send confirmation back to Telegram
    name = parsed.get("name", "Unknown")
    company = parsed.get("company", "")
    e = enriched or {}
    display_title = e.get("title") or parsed.get("title") or ""

    lines = [f"*{name}*"]
    if display_title:
        lines[0] += f" — {display_title}"
    if company:
        lines.append(f"_{company}_")
    if enriched and e.get("email"):
        lines.append(f"Email: {e['email']}")
    if enriched and e.get("linkedin_url"):
        lines.append(f"[LinkedIn]({e['linkedin_url']})")
    if dossier:
        lines.append("\nDossier ready in Notion")
    elif not enriched:
        lines.append("(no Apollo match — manual lookup may be needed)")
    if parsed.get("follow_up"):
        lines.append(f"\n_{parsed['follow_up']}_")
    lines.append(f"\n[Open in Notion]({notion_url})")

    send_message(chat_id, "\n".join(lines))


def main():
    print(f"Contact Capture — {datetime.now(timezone.utc).isoformat()}")

    updates = get_updates()
    print(f"{len(updates)} pending update(s)")

    if not updates:
        print("Nothing to process.")
        return

    processed = 0
    for update in updates:
        try:
            process_update(update)
            processed += 1
        except Exception as e:
            print(f"Error on update {update.get('update_id')}: {e}")
            import traceback
            traceback.print_exc()

    last_id = updates[-1]["update_id"]
    confirm_updates(last_id + 1)
    print(f"Done. Processed {processed}/{len(updates)} updates.")


if __name__ == "__main__":
    main()
