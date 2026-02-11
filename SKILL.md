---
name: dory-discord-vault
description: Build, run, and extend the Dory Discord + FastAPI backend that grounds answers in the local Obsidian vault (GS1DK_ServiceBrain). Use when working on vault scraping, indexing/extraction, environment setup, codex runner, or Discord bot behavior for this project.
---

# Scope

Use this skill to operate the Dory Discord + FastAPI system and the GS1DK vault tools in this repo.

# Repo Map

- `discord/app.py`: FastAPI controller. Detect info-seeking queries, route to the vault index, run deterministic extraction, and enforce Sources.
- `discord/vault_index.py`: Build a section index over the vault, generate aliases, and score sections.
- `discord/vault_tools.py`: Legacy keyword search + open_note utilities.
- `discord/model_runner.py`: LocalCodexRunner (`codex exec`) and OpenAIRunner.
- `discord/discord_bot.py`: Discord DM bot that forwards messages to the backend.
- `discord/config.py`: Env loading and runtime settings.
- `discord/discordBotToken.env`: `DISCORD_BOT_TOKEN`.
- `discord/.env`: `VAULT_PATH`, `CODEX_BIN`, `CODEX_ARGS`, `REQUEST_TIMEOUT_S`.

# Run And Validate

- Use the command list in `discord/quickstart.txt`.
- Restart the backend after vault changes so the index rebuilds.

# Vault Scraping

Use the Obsidian clipper script to refresh the vault:

- Services: `node tools/obsidian-clipper/scripts/clip-gs1dk.cjs services`
- Brancher: `node tools/obsidian-clipper/scripts/clip-gs1dk.cjs brancher`

Outputs:
- `GS1DK_ServiceBrain\GS1DK Services\`
- `GS1DK_ServiceBrain\GS1DK Brancher\`
- Index notes: `GS1DK Services Index.md`, `GS1DK Brancher Index.md`

# Retrieval And Extraction Pipeline

- Use `is_info_seeking` and `is_price_query` in `discord/app.py` to classify queries.
- Build candidate sections from `VaultIndex`.
- For price/package queries:
  - `_price_candidate_sections` -> `extract_price_items` -> `filter_price_items`
  - Fallback: `extract_inclusion_snippets` for lines like "inkl" or "gratis" when no explicit prices match.
- For industry count queries:
  - `build_brancher_count_snippets` reads `GS1DK Brancher Index.md`.
- Use Codex only as a formatter. The backend must supply the facts and enforce Sources.

# Troubleshooting

- "Local codex binary not found": set `CODEX_BIN` in `discord/.env`.
- Timeouts: increase `REQUEST_TIMEOUT_S` in `discord/.env` and restart.
- Missing facts: check the vault note. Deterministic extraction needs labels and prices on the same line or in clear tables.

# Extension Tips

- Prefer deterministic extractors over model inference for factual data.
- Make price lines self-describing (role + package + price) or use explicit markdown tables.
- Add new extractors in `discord/app.py` and keep Codex in formatter-only mode.
