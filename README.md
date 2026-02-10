# Contact Capture

Meet someone at an event. Send a voice note, text, or snap a business card. Get a researched dossier in Notion by the time you sit down.

**The problem:** You meet 30 people at a conference. By dinner, you've forgotten half of them. The business cards are crumpled in your pocket. The ones you do remember, you know nothing about beyond what they told you.

**The solution:** A Telegram bot backed by Claude, Apollo, and Exa that turns a 10-second voice note into a fully researched contact profile in Notion.

## How It Works

```
You (Telegram) → Voice note / text / business card photo
                         ↓
               GitHub Action (scheduled)
                         ↓
            ┌─ Whisper transcribes audio
            ├─ Claude Vision reads business cards
            ├─ Claude parses name, company, context
            ├─ Apollo enriches (email, LinkedIn, title)
            ├─ Exa researches (articles, talks, press)
            └─ Claude synthesizes dossier
                         ↓
              Notion contact card + dossier
                         ↓
             Telegram confirmation with link
```

## What You Get in Notion

Each contact card includes:

- **Dossier** — Background, current role, recent activity, company context, connection points, and a specific suggested follow-up approach
- **Meeting notes** — Your original context from the voice note/text
- **Contact details** — Email, LinkedIn, title, company (from Apollo)
- **Raw note** — Exactly what you said/typed, for reference

## Three Input Modes

1. **Text message** — Type or dictate: "Just met Sarah Chen from General Mills, VP Brand Strategy. Talked about their organic line."
2. **Voice note** — Hold the mic button and talk. Whisper transcribes it.
3. **Business card photo** — Snap a photo. Claude Vision reads every field. Add a caption for context: "Met at FMI conference, interested in research."

## Setup (15 minutes)

### 1. Create a Telegram Bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`, pick a name and username
3. Copy the bot token

### 2. Create a Notion Integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Create a new integration, copy the token
3. Create a page in Notion where you want the contacts database
4. Share that page with your integration (... menu → Connections → add your integration)

### 3. Create the Notion Database

```bash
NOTION_TOKEN=ntn_xxx NOTION_PARENT_PAGE_ID=xxx python setup_notion.py
```

This creates the database with all the right fields. Save the database ID it outputs.

### 4. Fork This Repo and Add Secrets

Fork this repo, then go to Settings → Secrets and variables → Actions. Add these secrets:

**Required:**
| Secret | What it is |
|--------|-----------|
| `TELEGRAM_BOT_TOKEN` | From BotFather |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `NOTION_TOKEN` | Your Notion integration token |
| `NOTION_DATABASE_ID` | From step 3 |

**Optional (each adds features):**
| Secret | What it adds |
|--------|-------------|
| `OPENAI_API_KEY` | Voice note transcription via Whisper |
| `EXA_API_KEY` | Web research for dossier (articles, talks, LinkedIn) |
| `APOLLO_API_KEY` | Contact enrichment (email, LinkedIn URL, title) |
| `TELEGRAM_CHAT_ID` | Restricts bot to only your messages (see below) |

### 5. Get Your Chat ID

Send any message to your bot, then manually trigger the Action from the GitHub Actions tab. Check the run logs — it prints your `chat_id`. Add it as the `TELEGRAM_CHAT_ID` secret to lock the bot to only you.

### 6. Adjust the Schedule

Edit `.github/workflows/contact-capture.yml` to change when the bot checks for messages. Default is noon and 7 PM Eastern. The bot also has a manual trigger button in the Actions tab.

## Cost

This runs on GitHub Actions free tier and costs almost nothing:

| Component | Cost |
|-----------|------|
| GitHub Actions | Free (uses ~30 of 2,000 free minutes/month) |
| Anthropic API | ~$0.03-0.05 per contact (parsing + dossier) |
| OpenAI Whisper | ~$0.003 per voice note |
| Exa | ~$0.01-0.05 per contact |
| Apollo | Free tier available, or ~$0.10/contact on paid plans |

**Total: roughly $0.05-0.15 per contact captured.**

## Minimum Viable Version

Don't want to set up everything? The bot works with just the required secrets. You'll get:

- Text message parsing ✓
- Business card photo reading ✓
- Claude-parsed contact details ✓
- Notion contact cards ✓
- Basic follow-up suggestions ✓

Add the optional APIs later for voice notes (OpenAI), enrichment (Apollo), and full dossiers (Exa).

## Built With

- [Claude](https://anthropic.com) — Contact parsing, business card OCR, dossier synthesis
- [Telegram Bot API](https://core.telegram.org/bots/api) — Input interface
- [Notion API](https://developers.notion.com) — Contact storage
- [Exa](https://exa.ai) — Semantic web research
- [Apollo](https://apollo.io) — Contact enrichment
- [OpenAI Whisper](https://platform.openai.com/docs/guides/speech-to-text) — Voice transcription
- [GitHub Actions](https://github.com/features/actions) — Free scheduled execution

## License

MIT — do whatever you want with it.
