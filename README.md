# Personal AI Ironman Coach

Sync your Garmin Connect data locally and get evidence-based Ironman coaching from any AI — Cursor, ChatGPT, Claude, or anything that reads markdown.

## How It Works

```
Garmin Connect ──▶ coach sync ──▶ SQLite DB ──▶ coach context ──▶ training_context.md
                    (API)          (local)        (query+build)         │
                                                                       ▼
                                                              Cursor AI Chat
                                                          (@training_context.md
                                                            + @athlete_docs)
```

1. **`coach sync`** pulls your training activities and health metrics (HRV, sleep, stress, body battery, training readiness) from Garmin Connect into a local SQLite database.
2. **`coach context`** queries the database and generates a compact `training_context.md` — weekly volume summaries, acute/chronic training load ratio, recent activities with HR/pace/power, health trends, and auto-detected fatigue flags.
3. **In Cursor**, reference `@training_context.md` (and optionally `@athlete_docs`) in chat — the Cursor rule activates automatically and makes the AI respond as an evidence-based Ironman coach grounded in your actual data.

## Prerequisites

- **Python 3.11+** — check with `python3 --version`. Install via [python.org](https://www.python.org/downloads/) or `brew install python` on macOS.
- **Garmin Connect account** — with a Garmin device syncing your training data.
- **Any AI chat** — Cursor (has auto-activating coaching rule), ChatGPT, Claude, etc.

## Setup

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/personal-ai-coach.git
cd personal-ai-coach

# Create virtual environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Log in to Garmin Connect (credentials stored in system keychain, 2FA supported)
coach login

# Configure athlete profile (race date, goals, etc.)
coach config
```

### Athlete Context (optional but recommended)

Create an `athlete_docs/` directory with markdown files describing your profile, race targets, fueling strategy, injury history, etc. The more context you provide, the better the coaching. See `config.example.yaml` for the config format.

## Daily Workflow

```bash
# Activate the virtual environment
source .venv/bin/activate

# Sync latest data from Garmin (do this after each training session)
coach sync

# Generate context file for Cursor AI
coach context

# Quick status check in terminal
coach status
```

Then ask your AI for coaching:

**Cursor** (recommended) — the `.cursor/rules/ironman-coach.mdc` rule auto-activates when you reference the files:
- `@training_context.md How should I adjust this week based on my fatigue?`
- `@training_context.md @athlete_docs Review my last week — am I on track?`

**ChatGPT / Claude / any AI** — paste the contents of `training_context.md` (and optionally your `athlete_docs/`) into the chat, then ask your questions. The context file is compact (~2-5k tokens) so it's cheap to include.

## Commands

| Command | Description |
|---------|-------------|
| `coach login` | Authenticate with Garmin Connect (saves to system keychain) |
| `coach sync` | Pull latest activities and health data from Garmin |
| `coach context` | Generate `training_context.md` for AI (use --live for live API data) |
| `coach summary` | Print weekly training summary table |
| `coach status` | Show training load, health snapshot, recent activities |
| `coach config` | View/edit athlete profile (race date, goals, etc.) |
| `coach reset` | Reset local database |

### Options

```bash
coach sync --lookback 120       # Sync more history (default: 90 days)
coach sync --health-days 30     # More health data (default: 14 days)
coach summary --weeks 12        # Show more weeks
coach context --output ctx.md   # Custom output path
coach context --live            # Generate from live API data instead of database
```

## What Data Is Synced

All data stays on your machine:

- **Activities**: sport type, duration, distance, HR zones, pace, power, TSS, training effect, elevation, cadence
- **Health metrics**: resting HR, HRV, sleep score/duration, body battery, stress, training readiness, VO2 max, weight

### Where Data Lives

| Location | What |
|----------|------|
| `~/.config/personal-ai-coach/data/coach.db` | SQLite database (activities, health metrics, sync log) |
| `~/.config/personal-ai-coach/garmin_session/` | Garmin auth tokens (avoids re-login) |
| `~/.config/personal-ai-coach/config.yaml` | Athlete profile (race date, goals — no secrets) |
| macOS Keychain | Garmin email + password (service: `personal-ai-coach`) |
| `training_context.md` (project root) | Generated context for Cursor AI (gitignored) |
| `athlete_docs/` (project root) | Your personal coaching docs (gitignored) |

You can query the database directly:

```bash
sqlite3 ~/.config/personal-ai-coach/data/coach.db \
  "SELECT start_time, sport_type, duration_seconds/60 as mins, distance_meters/1000 as km, avg_hr FROM activities ORDER BY start_time DESC LIMIT 5;"
```

## Security

- Garmin credentials are stored in your OS credential store (macOS Keychain / Linux SecretService / Windows Credential Locker), not in any file
- 2FA/MFA is supported — you'll be prompted in the terminal when needed
- No data is sent anywhere except to Garmin Connect (for sync) and your AI tool (when you chat)
- `athlete_docs/`, `training_context.md`, and `config.yaml` are gitignored — your personal health data never hits the repo

## Platform Support

Tested on macOS. Should work on Linux and Windows since all dependencies are cross-platform:
- `keyring` uses the native OS credential store on each platform
- `sqlite3` is built into Python
- `garminconnect` is pure Python

## Model Context Protocol (MCP) Server

This project supports the [Model Context Protocol (MCP)](https://github.com/modelcontext/protocol) for seamless context injection into AI tools like Claude Desktop.

### MCP Setup - Local

1. **Install [uv](https://github.com/astral-sh/uv) (fast Python package manager):**

2. **Sync the project:**

  ```bash
  uv sync
  ```

3. **Start the MCP server:**

### Claude Desktop Integration

Add to your Claude Desktop MCP settings:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```JSON
{
  "mcpServers": {
    "garmin-coach-context": {
      "command": "uv",
      "args": [
        "--directory",
        "<full path to garmin-coach-context local repo>",
        "run",
        "coach-mcp"
      ]
    }
  }
}
```

To use the MCP server with Claude Desktop:

1. Open Claude Desktop and go to **Settings → Model Context Protocol**.
2. Enable MCP

3. Save settings. Claude will now automatically generate your training context when it needs it. You can also request that it syncs your data with Garmin Connect. It's limited to syncing with Garmin Connect once every hour.

### Test MCP for Development with Inspector
The MCP inspector lets you inspect and test tools for development

Prerequisites: Node.js

1. Run the MCP inspector directly with npx

```bash
npx @modelcontextprotocol/inspector uv run coach-mcp
```


## Project Structure

```
garmin-coach-context/
  src/
    coach/
      __init__.py           # Package marker
      cli.py                # CLI entry point (Typer)
      garmin_client.py      # Garmin Connect sync engine
      database.py           # SQLite storage layer
      context.py            # Generates training_context.md
      mcp.py                # MCP server implementation
      config.py             # Configuration management
      models.py             # Pydantic data models
      utils.py              # Utility functions
    personal_ai_coach.egg-info/ # Packaging metadata
  athlete_docs/             # Your personal coaching context (gitignored)
  .cursor/rules/            # Cursor AI coaching rule (for Cursor editor)
  training_context.md       # Auto-generated context for AI (gitignored)
  config.example.yaml       # Example configuration
  plan.md                   # Example training plan (optional)
  pyproject.toml            # Python project metadata
  README.md                 # Project documentation
```
