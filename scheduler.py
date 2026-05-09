"""
Random-interval scheduler that posts AI-generated replies in a target channel.
Picks a random recent human message as a "seed" to reply to.
"""

import asyncio
import logging
import random
from typing import Optional, Callable, Awaitable

import discord

logger = logging.getLogger(__name__)


class ReplyScheduler:
    def __init__(
        self,
        bot: discord.Client,
        generate_fn: Callable[[Optional[str]], Awaitable[Optional[str]]],
    ):
        self._bot = bot
        self._generate = generate_fn
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # runtime config — updated via /config commands
        self.target_channel_id: Optional[int] = None
        self.min_interval: int = 300
        self.max_interval: int = 3600
        self.enabled: bool = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="sanbot-scheduler")
        logger.info("Scheduler started (interval %ds–%ds)", self.min_interval, self.max_interval)

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Scheduler stopped")

    def restart(self):
        self.stop()
        self.start()

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    async def _loop(self):
        await self._bot.wait_until_ready()
        while self._running:
            wait = random.randint(self.min_interval, self.max_interval)
            logger.debug("Next reply in %ds", wait)
            await asyncio.sleep(wait)

            if not self.enabled:
                continue

            await self._send_reply()

    async def _send_reply(self):
        if not self.target_channel_id:
            logger.debug("No target channel set — skipping reply")
            return

        channel = self._bot.get_channel(self.target_channel_id)
        if not isinstance(channel, discord.TextChannel):
            logger.warning("Target channel %d not found or not a text channel", self.target_channel_id)
            return

        # pick a random recent non-bot message as the "seed"
        seed_text: Optional[str] = None
        seed_message: Optional[discord.Message] = None
        try:
            history = [
                m async for m in channel.history(limit=50)
                if not m.author.bot and m.content
            ]
            if history:
                seed_message = random.choice(history)
                seed_text = seed_message.content[:100]
        except discord.HTTPException:
            pass

        response = await self._generate(seed_text)
        if not response:
            logger.warning("Model returned empty response — skipping")
            return

        try:
            if seed_message:
                await seed_message.reply(response, mention_author=True)
            else:
                await channel.send(response)
            logger.info("Sent reply to #%s", channel.name)
        except discord.HTTPException as exc:
            logger.error("Failed to send reply: %s", exc)
