# SanBot

A Discord bot that harvests messages from a target user, trains a local language model on them, and periodically replies to random users in a specified channel — mimicking the target's writing style.

Designed to run on a **Raspberry Pi 5** within a **1 GB RAM** budget.

---

## Features

| Feature | Detail |
|---|---|
| Message harvesting | Paginates through all guild channels for a target user |
| SQLite database | Stores every message with deduplication |
| Markov chain model | Trains in seconds, <100 MB RAM — default backend |
| llama.cpp backend | TinyLlama 1.1B Q4_K_M (~638 MB) — optional, better quality |
| Random reply timer | Configurable interval, replies to a random recent message |
| Full slash commands | Everything configurable without touching config files |

---

## Setup

### 1. Clone & install

```bash
cd sanbot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Discord bot permissions

Create a bot at <https://discord.com/developers/applications> and enable:

- **Privileged intents**: `Message Content`, `Server Members`
- **Bot permissions**: `Read Messages`, `Read Message History`, `Send Messages`

Copy your token into `.env`:

```
DISCORD_TOKEN=your_token_here
```

### 3. Run

```bash
python bot.py
```

---

## Slash Commands

All admin commands require the `Administrator` permission.

| Command | Description |
|---|---|
| `/setsource @user` | Set the user whose messages will be harvested |
| `/setchannel #channel` | Set the channel SanBot replies in |
| `/addharvestchannel #channel` | Add a channel to the harvest scope |
| `/removeharvestchannel #channel` | Remove a channel from the harvest scope |
| `/harvest` | Start harvesting messages from the source user |
| `/train` | Train the model on harvested messages |
| `/setinterval <min> <max>` | Set reply interval in seconds |
| `/togglereplies` | Pause / resume random replies |
| `/setbackend markov\|llama [path]` | Switch generation backend |
| `/forcereply` | Trigger a reply immediately (testing) |
| `/sanstatus` | Show current config and stats |

---

## LLM Backends

### Markov chain (default)

- Trains directly on harvested messages
- Uses ~2–10 MB RAM for typical Discord users
- Starts generating immediately after `/train`
- No extra downloads needed

### llama.cpp (optional, better quality)

Requires the TinyLlama model file (~638 MB):

```bash
wget https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
pip install llama-cpp-python
```

Then in Discord:
```
/setbackend llama model_path:/home/pi/sanbot/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
/train
```

The bot uses the harvested messages as a few-shot persona prompt — no GPU fine-tuning required.

---

## Raspberry Pi 5 RAM usage

| Component | RAM |
|---|---|
| Python + discord.py | ~80 MB |
| Markov model (typical) | ~5–20 MB |
| SQLite (shared cache) | ~10 MB |
| **Total (Markov backend)** | **~100–120 MB** |
| TinyLlama Q4_K_M | ~638 MB |
| **Total (llama backend)** | **~750–780 MB** |

Both options fit comfortably under the 1 GB limit.

---

## Data layout

```
sanbot/
├── data/
│   ├── sanbot.db      # SQLite message database
│   ├── markov.pkl     # Trained Markov model
│   └── config.json    # Runtime configuration
└── ...
```
