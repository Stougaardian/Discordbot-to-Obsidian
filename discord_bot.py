import asyncio
import discord
import aiohttp

from config import settings

IDENTITY_LINE = "Jeg hedder Dory, jeg er din digitale praktikant."


intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=settings.request_timeout_s)
        _session = aiohttp.ClientSession(timeout=timeout)
    return _session


async def _post_json(url: str, payload: dict) -> dict:
    session = await _get_session()
    async with session.post(url, json=payload) as response:
        response.raise_for_status()
        return await response.json()


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.guild is not None:
        return

    content = message.content.strip()
    if not content:
        return

    if content.lower().startswith("!whoami"):
        await message.channel.send(IDENTITY_LINE)
        return

    if content.lower().startswith("!sources"):
        try:
            payload = {
                "user_id": str(message.author.id),
                "channel_id": str(message.channel.id),
            }
            data = await _post_json(settings.agent_api_url.replace("/chat", "/sources"), payload)
            sources = data.get("sources", [])
            if not sources:
                await message.channel.send("No sources recorded for this session.")
            else:
                formatted = "Sources:\n" + "\n".join(f"- {src}" for src in sources)
                await message.channel.send(formatted)
        except Exception as exc:
            await message.channel.send(f"Failed to fetch sources: {exc}")
        return

    payload = {
        "user_id": str(message.author.id),
        "channel_id": str(message.channel.id),
        "text": content,
    }

    try:
        data = await _post_json(settings.agent_api_url, payload)
        reply = data.get("reply", "")
    except asyncio.TimeoutError:
        reply = "Backend timeout. Please try again."
    except Exception as exc:
        reply = f"Backend error: {exc}"

    if reply:
        await message.channel.send(reply)


if __name__ == "__main__":
    if not settings.discord_bot_token:
        raise SystemExit("DISCORD_BOT_TOKEN is required")
    client.run(settings.discord_bot_token)
