"""
Async Discord message harvester.
Walks channel history for a target user, with pagination and rate-limit awareness.
"""

import asyncio
import logging
from typing import AsyncGenerator, Optional

import discord

from database import insert_messages, update_harvest_state, get_harvest_state

logger = logging.getLogger(__name__)

BATCH_SIZE = 100   # messages per API call (Discord max)
DELAY = 0.5        # seconds between paginated calls


async def harvest_channel(
    channel: discord.TextChannel,
    user: discord.User,
    guild_id: str,
    *,
    limit: Optional[int] = None,
    progress_callback=None,
) -> int:
    """
    Fetch all messages by `user` in `channel`, store them, and return the count harvested.
    Resumes from the last harvested message_id when re-run.
    """
    state = get_harvest_state(str(user.id), str(channel.id))
    after_id = state["last_message_id"] if state else None
    after_obj = discord.Object(id=int(after_id)) if after_id else None

    harvested = 0
    last_id: Optional[str] = None
    batch: list[dict] = []

    try:
        async for message in channel.history(
            limit=limit,
            after=after_obj,
            oldest_first=True,
        ):
            if message.author.id != user.id:
                continue
            content = message.content.strip()
            if not content or content.startswith(("/", "!")):
                continue  # skip commands

            batch.append(
                {
                    "message_id": str(message.id),
                    "user_id": str(user.id),
                    "username": str(user.name),
                    "channel_id": str(channel.id),
                    "guild_id": guild_id,
                    "content": content,
                    "timestamp": message.created_at.isoformat(),
                }
            )
            last_id = str(message.id)

            if len(batch) >= BATCH_SIZE:
                inserted = insert_messages(batch)
                harvested += inserted
                batch.clear()
                if progress_callback:
                    await progress_callback(harvested)
                await asyncio.sleep(DELAY)

        if batch:
            inserted = insert_messages(batch)
            harvested += inserted

    except discord.Forbidden:
        logger.warning("No permission to read %s (#%s)", channel.name, channel.id)
        return harvested
    except discord.HTTPException as exc:
        logger.error("HTTP error harvesting %s: %s", channel.name, exc)
        return harvested

    if last_id:
        update_harvest_state(str(user.id), str(channel.id), last_id, harvested)

    logger.info("Harvested %d new messages from #%s", harvested, channel.name)
    return harvested


async def harvest_guild(
    guild: discord.Guild,
    user: discord.User,
    channel_ids: Optional[list[int]] = None,
    *,
    progress_callback=None,
) -> int:
    """
    Harvest from all text channels in the guild (or a subset if channel_ids given).
    Returns total new messages stored.
    """
    total = 0
    guild_id = str(guild.id)

    channels = (
        [guild.get_channel(cid) for cid in channel_ids]
        if channel_ids
        else guild.text_channels
    )

    for channel in channels:
        if not isinstance(channel, discord.TextChannel):
            continue
        perms = channel.permissions_for(guild.me)
        if not (perms.read_messages and perms.read_message_history):
            continue

        count = await harvest_channel(
            channel, user, guild_id, progress_callback=progress_callback
        )
        total += count

    return total
