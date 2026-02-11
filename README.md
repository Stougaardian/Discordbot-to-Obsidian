# Dory Discord POC

Dory is a local Discord bot and FastAPI backend that answers factual questions only from a local Obsidian vault. This v0 uses keyword search over markdown files and defaults to running `codex exec` locally.

**Mode**: DM-only. The bot responds only to direct messages.

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies.

```powershell
cd C:\Users\iwo\Documents\projects\Dory\discord
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Set environment variables.

Required:
- `DISCORD_BOT_TOKEN`
- `VAULT_PATH`

Optional:
- `AGENT_API_URL` (default: `http://localhost:8000/chat`)
- `MODEL_BACKEND=local|openai` (default: `local`)
- `CODEX_BIN` (default: `codex`)
- `CODEX_ARGS` (extra args for `codex exec`)
- `OPENAI_API_KEY` (only needed if `MODEL_BACKEND=openai`)

Example (PowerShell):

```powershell
$env:DISCORD_BOT_TOKEN="your_token_here"
$env:VAULT_PATH="C:\Users\iwo\Documents\projects\Dory\GS1DK_ServiceBrain"
$env:MODEL_BACKEND="local"
```

### Using `discordBotToken.env`

By default, `config.py` auto-loads `discord\discordBotToken.env` (override with `ENV_FILE`).  
Make sure it contains a line like:

```
DISCORD_BOT_TOKEN=your_token_here
```

### Using `.env` for `VAULT_PATH`

`config.py` also loads `discord\.env` by default (override with `VAULT_ENV_FILE`).  
Add your vault path there:

```
VAULT_PATH=C:\Users\iwo\Documents\projects\Dory\GS1DK_ServiceBrain
```

## Run

1. Start the backend API.

```powershell
cd C:\Users\iwo\Documents\projects\Dory\discord
uvicorn app:app --reload
```

2. Start the Discord bot in another terminal.

```powershell
cd C:\Users\iwo\Documents\projects\Dory\discord
python discord_bot.py
```

## Behavior

- DMs only.
- For factual questions, Dory uses a structured vault index and answers only from extracted snippets, with citations.
- Price/package questions use deterministic extraction from the relevant note(s); Codex is only used to format the output.
- If nothing is found, Dory replies: `I can't find that in the vault.`

## Example Queries

Pricing query (expects citations):

```
Hvad koster GS1Trade Image?
```

Missing info query (must not hallucinate):

```
What is the refund policy for GS1 DK?
```

Identity query:

```
Who are you?
```

Expected response:

```
Jeg hedder Dory, jeg er din digitale praktikant.
```

## Notes

- Local model runner: `LocalCodexRunner` runs `codex exec` via subprocess.
- OpenAI runner: set `MODEL_BACKEND=openai` and `OPENAI_API_KEY` to enable.
- Session context is stored in `discord\data\sessions.json`.
- Sources can be queried with `!sources` in DM.
- The vault index is built on backend startup. Restart the backend to pick up new notes.

