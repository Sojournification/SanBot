"""
SanBot — Discord message harvester + local LLM persona bot.
"""

import asyncio
import logging
import os
from typing import Optional

import discord
from discord import app_commands
from dotenv import load_dotenv

import database
import harvester
import markov as markov_module
import llama_backend
from config import Config
from scheduler import ReplyScheduler

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sanbot")

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

cfg = Config.load()
_markov: Optional[markov_module.MarkovChain] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_model():
    global _markov
    _markov = markov_module.MarkovChain.load()
    if _markov:
        logger.info("Markov model loaded from disk")
    else:
        logger.info("No trained model found — run /train after harvesting")


async def _generate(seed: Optional[str]) -> Optional[str]:
    """Generate a response using the configured backend."""
    loop = asyncio.get_event_loop()

    if cfg.model_backend == "llama" and cfg.llama_model_path:
        return await loop.run_in_executor(
            None, lambda: llama_backend.generate(cfg.llama_model_path, seed, cfg.max_response_length)
        )

    if _markov and _markov._trained:
        return await loop.run_in_executor(
            None, lambda: _markov.generate(max_words=cfg.max_response_length, seed=seed)
        )

    return None


# ---------------------------------------------------------------------------
# Scheduler wiring
# ---------------------------------------------------------------------------

scheduler = ReplyScheduler(bot, _generate)


def _sync_scheduler_from_cfg():
    scheduler.target_channel_id = cfg.target_channel_id
    scheduler.min_interval = cfg.min_interval
    scheduler.max_interval = cfg.max_interval
    scheduler.enabled = cfg.reply_enabled


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    logger.info("SanBot online as %s (id=%s)", bot.user, bot.user.id)
    await tree.sync()
    _load_model()
    _sync_scheduler_from_cfg()
    if cfg.reply_enabled:
        scheduler.start()


# ---------------------------------------------------------------------------
# /setsource — set the user whose messages to harvest
# ---------------------------------------------------------------------------

@tree.command(name="setsource", description="Set the user whose messages SanBot will harvest and mimic.")
@app_commands.describe(user="The Discord user to harvest messages from")
@app_commands.default_permissions(administrator=True)
async def setsource(interaction: discord.Interaction, user: discord.Member):
    cfg.source_user_id = user.id
    cfg.save()
    await interaction.response.send_message(
        f"Source user set to **{user.display_name}** (`{user.id}`).\n"
        f"Run `/harvest` to start collecting their messages.",
        ephemeral=True,
    )


# ---------------------------------------------------------------------------
# /setchannel — set the reply target channel
# ---------------------------------------------------------------------------

@tree.command(name="setchannel", description="Set the channel SanBot replies in on the random timer.")
@app_commands.describe(channel="Target channel for random replies")
@app_commands.default_permissions(administrator=True)
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg.target_channel_id = channel.id
    cfg.save()
    scheduler.target_channel_id = channel.id
    await interaction.response.send_message(
        f"Reply channel set to {channel.mention}.", ephemeral=True
    )


# ---------------------------------------------------------------------------
# /addharvestchannel / /removeharvestchannel — control harvest scope
# ---------------------------------------------------------------------------

@tree.command(name="addharvestchannel", description="Add a channel to the harvest scope.")
@app_commands.describe(channel="Channel to include in harvesting")
@app_commands.default_permissions(administrator=True)
async def addharvestchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if channel.id not in cfg.harvest_channel_ids:
        cfg.harvest_channel_ids.append(channel.id)
        cfg.save()
    await interaction.response.send_message(
        f"{channel.mention} added to harvest scope.", ephemeral=True
    )


@tree.command(name="removeharvestchannel", description="Remove a channel from the harvest scope.")
@app_commands.describe(channel="Channel to remove from harvesting")
@app_commands.default_permissions(administrator=True)
async def removeharvestchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if channel.id in cfg.harvest_channel_ids:
        cfg.harvest_channel_ids.remove(channel.id)
        cfg.save()
    await interaction.response.send_message(
        f"{channel.mention} removed from harvest scope.", ephemeral=True
    )


# ---------------------------------------------------------------------------
# /harvest — collect messages from source user
# ---------------------------------------------------------------------------

@tree.command(name="harvest", description="Harvest messages from the source user and store them.")
@app_commands.default_permissions(administrator=True)
async def harvest(interaction: discord.Interaction):
    if not cfg.source_user_id:
        await interaction.response.send_message(
            "No source user set. Use `/setsource` first.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    user = interaction.guild.get_member(cfg.source_user_id)
    if user is None:
        try:
            user = await bot.fetch_user(cfg.source_user_id)
        except discord.NotFound:
            await interaction.followup.send("Source user not found in this server.", ephemeral=True)
            return

    status_msgs: list[str] = []

    async def progress(count: int):
        status_msgs.append(f"…{count} messages so far")

    total = await harvester.harvest_guild(
        interaction.guild,
        user,
        channel_ids=cfg.harvest_channel_ids or None,
        progress_callback=progress,
    )

    db_total = database.get_message_count(str(cfg.source_user_id))
    await interaction.followup.send(
        f"Harvest complete. **{total}** new messages collected.\n"
        f"Total stored for this user: **{db_total}**.\n"
        f"Run `/train` to update the model.",
        ephemeral=True,
    )


# ---------------------------------------------------------------------------
# /train — (re)train the model on stored messages
# ---------------------------------------------------------------------------

@tree.command(name="train", description="Train the language model on harvested messages.")
@app_commands.default_permissions(administrator=True)
async def train(interaction: discord.Interaction):
    global _markov

    if not cfg.source_user_id:
        await interaction.response.send_message("Set a source user first with `/setsource`.", ephemeral=True)
        return

    messages = database.get_all_messages_for_user(
        str(cfg.source_user_id),
        guild_id=str(interaction.guild_id),
    )
    if not messages:
        await interaction.response.send_message(
            "No messages in the database. Run `/harvest` first.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    run_id = database.log_training_start("markov")
    loop = asyncio.get_event_loop()

    def _do_train():
        m = markov_module.MarkovChain(order=cfg.markov_order)
        m.train(messages)
        m.save()
        return m

    try:
        _markov = await loop.run_in_executor(None, _do_train)
        database.log_training_finish(run_id, len(messages), "done")

        if cfg.model_backend == "llama" and cfg.llama_model_path:
            sample = messages[:20]
            await loop.run_in_executor(None, lambda: llama_backend.build_persona(sample))

        await interaction.followup.send(
            f"Model trained on **{len(messages)}** messages.\n"
            f"Unique Markov states: **{len(_markov.chain)}**.\n"
            f"Backend: `{cfg.model_backend}`",
            ephemeral=True,
        )
    except Exception as exc:
        database.log_training_finish(run_id, 0, f"error: {exc}")
        await interaction.followup.send(f"Training failed: {exc}", ephemeral=True)
        raise


# ---------------------------------------------------------------------------
# /setinterval — configure random reply timing
# ---------------------------------------------------------------------------

@tree.command(name="setinterval", description="Set the random reply interval in seconds.")
@app_commands.describe(
    minimum="Minimum wait in seconds (default 300)",
    maximum="Maximum wait in seconds (default 3600)",
)
@app_commands.default_permissions(administrator=True)
async def setinterval(interaction: discord.Interaction, minimum: int, maximum: int):
    if minimum < 30:
        await interaction.response.send_message("Minimum must be ≥ 30 seconds.", ephemeral=True)
        return
    if maximum <= minimum:
        await interaction.response.send_message("Maximum must be greater than minimum.", ephemeral=True)
        return

    cfg.min_interval = minimum
    cfg.max_interval = maximum
    cfg.save()
    scheduler.min_interval = minimum
    scheduler.max_interval = maximum
    scheduler.restart()

    await interaction.response.send_message(
        f"Interval set to **{minimum}s – {maximum}s** "
        f"({minimum//60}m – {maximum//60}m). Scheduler restarted.",
        ephemeral=True,
    )


# ---------------------------------------------------------------------------
# /togglereplies — pause / resume random replies
# ---------------------------------------------------------------------------

@tree.command(name="togglereplies", description="Pause or resume SanBot's random replies.")
@app_commands.default_permissions(administrator=True)
async def togglereplies(interaction: discord.Interaction):
    cfg.reply_enabled = not cfg.reply_enabled
    cfg.save()
    scheduler.enabled = cfg.reply_enabled

    if cfg.reply_enabled and not scheduler._task or scheduler._task.done():
        scheduler.start()

    state = "enabled" if cfg.reply_enabled else "paused"
    await interaction.response.send_message(f"Random replies **{state}**.", ephemeral=True)


# ---------------------------------------------------------------------------
# /setbackend — switch between markov and llama
# ---------------------------------------------------------------------------

@tree.command(name="setbackend", description="Switch the generation backend (markov / llama).")
@app_commands.describe(
    backend="markov = lightweight Markov chain; llama = llama.cpp (needs model file)",
    model_path="Path to the .gguf model file (required for llama backend)",
)
@app_commands.choices(backend=[
    app_commands.Choice(name="markov", value="markov"),
    app_commands.Choice(name="llama", value="llama"),
])
@app_commands.default_permissions(administrator=True)
async def setbackend(
    interaction: discord.Interaction,
    backend: app_commands.Choice[str],
    model_path: Optional[str] = None,
):
    cfg.model_backend = backend.value
    if model_path:
        cfg.llama_model_path = model_path
    cfg.save()

    note = ""
    if backend.value == "llama":
        if not cfg.llama_model_path:
            note = "\n⚠ No model path set — pass `model_path` or run again with it."
        elif not os.path.exists(cfg.llama_model_path):
            note = f"\n⚠ Model file not found at `{cfg.llama_model_path}`."

    await interaction.response.send_message(
        f"Backend set to `{backend.value}`.{note}", ephemeral=True
    )


# ---------------------------------------------------------------------------
# /forcereply — trigger a reply right now (for testing)
# ---------------------------------------------------------------------------

@tree.command(name="forcereply", description="Trigger a reply immediately (admin/test).")
@app_commands.default_permissions(administrator=True)
async def forcereply(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await scheduler._send_reply()
    await interaction.followup.send("Reply sent (if a model is trained and channel is set).", ephemeral=True)


# ---------------------------------------------------------------------------
# /status — display current configuration and stats
# ---------------------------------------------------------------------------

@tree.command(name="sanstatus", description="Show SanBot configuration and database stats.")
async def sanstatus(interaction: discord.Interaction):
    source_mention = f"<@{cfg.source_user_id}>" if cfg.source_user_id else "*not set*"
    target_mention = f"<#{cfg.target_channel_id}>" if cfg.target_channel_id else "*not set*"
    harvest_channels = (
        " ".join(f"<#{cid}>" for cid in cfg.harvest_channel_ids)
        if cfg.harvest_channel_ids
        else "*all channels*"
    )
    msg_count = database.get_message_count(str(cfg.source_user_id)) if cfg.source_user_id else 0
    model_ready = "yes" if (_markov and _markov._trained) else "no"
    interval_str = f"{cfg.min_interval}s – {cfg.max_interval}s"

    embed = discord.Embed(title="SanBot Status", color=0x5865F2)
    embed.add_field(name="Source user",       value=source_mention,   inline=True)
    embed.add_field(name="Reply channel",     value=target_mention,   inline=True)
    embed.add_field(name="Harvest channels",  value=harvest_channels, inline=False)
    embed.add_field(name="Messages in DB",    value=str(msg_count),   inline=True)
    embed.add_field(name="Model trained",     value=model_ready,      inline=True)
    embed.add_field(name="Backend",           value=cfg.model_backend, inline=True)
    embed.add_field(name="Reply interval",    value=interval_str,     inline=True)
    embed.add_field(name="Replies enabled",   value=str(cfg.reply_enabled), inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN not set in environment / .env file")

    database.init_db()
    bot.run(token)
