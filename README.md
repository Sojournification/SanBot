# SanBot

A Discord bot that harvests messages from a target user, trains a local language model on them, and periodically replies to random users in a specified channel — mimicking the target's writing style.

Designed to run on a **Raspberry Pi 5** within a **1 GB RAM** budget.

---

## Installation

### Prerequisites

- Python 3.10+
- Git
- A Discord account with server admin access

---

### Step 1 — Clone the repo

```bash
git clone https://github.com/Sojournification/SanBot.git
cd SanBot
```

---

### Step 2 — Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux / macOS / Raspberry Pi
# .venv\Scripts\activate         # Windows
```

---

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

---

### Step 4 — Create a Discord bot

1. Go to <https://discord.com/developers/applications> and click **New Application**
2. Name it `SanBot`, then go to the **Bot** tab
3. Click **Reset Token**, copy it somewhere safe
4. Under **Privileged Gateway Intents**, enable:
   - `Server Members Intent`
   - `Message Content Intent`
5. Go to **OAuth2 → URL Generator**, select:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Read Messages/View Channels`, `Read Message History`, `Send Messages`
6. Open the generated URL and invite the bot to your server

---

### Step 5 — Configure your token

```bash
cp .env.example .env
```

Open `.env` and paste your bot token:

```
DISCORD_TOKEN=your_token_here
```

---

### Step 6 — Run the bot

```bash
python bot.py
```

You should see `SanBot online as SanBot#XXXX` in the console. Slash commands will sync to your server automatically on first start (may take up to 1 minute to appear).

---

## First-time setup in Discord

Run these slash commands in order:

```
/setsource @user              — pick whose messages to harvest
/addharvestchannel #general   — add channels to search (repeat for each)
/setchannel #general          — set where SanBot will post replies
/harvest                      — collect messages (may take a few minutes)
/train                        — train the model on collected messages
/setinterval 300 3600         — reply every 5–60 minutes at random
```

That's it. SanBot will now post replies on the random timer.

---

## Slash Commands

All commands except `/sanstatus` require the `Administrator` permission.

| Command | Description |
|---|---|
| `/setsource @user` | Set the user whose messages will be harvested |
| `/setchannel #channel` | Set the channel SanBot replies in |
| `/addharvestchannel #channel` | Add a channel to the harvest scope |
| `/removeharvestchannel #channel` | Remove a channel from the harvest scope |
| `/harvest` | Collect messages from the source user |
| `/train` | Train the model on collected messages |
| `/setinterval <min> <max>` | Reply interval in seconds (e.g. `300 3600`) |
| `/togglereplies` | Pause or resume random replies |
| `/setbackend markov\|llama [path]` | Switch generation backend |
| `/forcereply` | Trigger a reply right now (for testing) |
| `/sanstatus` | Show current config and database stats |

---

## Optional — llama.cpp backend (better quality)

The default Markov backend trains instantly and uses ~10 MB RAM. For more natural responses, you can switch to TinyLlama via llama.cpp (~638 MB).

**1. Install the Python bindings**

```bash
pip install llama-cpp-python
```

> On Raspberry Pi, add `--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu` if the build fails.

**2. Download the model** (~638 MB)

```bash
wget https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
```

**3. Enable it in Discord**

```
/setbackend llama model_path:/home/pi/SanBot/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
/train
```

---

## Running as a service on Raspberry Pi

To keep SanBot running after you close your SSH session:

```bash
sudo nano /etc/systemd/system/sanbot.service
```

Paste:

```ini
[Unit]
Description=SanBot Discord Bot
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/SanBot
ExecStart=/home/pi/SanBot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable sanbot
sudo systemctl start sanbot
sudo systemctl status sanbot   # check it's running
```

Logs:

```bash
journalctl -u sanbot -f
```

---

## RAM usage (Raspberry Pi 5)

| Component | RAM |
|---|---|
| Python + discord.py | ~80 MB |
| Markov model (typical) | ~5–20 MB |
| SQLite | ~10 MB |
| **Total — Markov backend** | **~100–120 MB** |
| TinyLlama Q4_K_M | ~638 MB |
| **Total — llama backend** | **~750–780 MB** |

Both options fit under the 1 GB budget.

---

## Data layout

```
SanBot/
├── data/                  # created automatically on first run
│   ├── sanbot.db          # SQLite message database
│   ├── markov.pkl         # trained Markov model
│   └── config.json        # runtime configuration (channels, intervals, etc.)
├── .env                   # your bot token (never commit this)
└── ...
```
