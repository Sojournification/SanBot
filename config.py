import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "data", "config.json")


@dataclass
class Config:
    source_user_id: Optional[int] = None
    target_channel_id: Optional[int] = None
    harvest_channel_ids: list = field(default_factory=list)  # channels to harvest from
    min_interval: int = 300    # seconds (5 min default)
    max_interval: int = 3600   # seconds (1 hour default)
    markov_order: int = 2
    model_backend: str = "markov"   # "markov" or "llama"
    llama_model_path: Optional[str] = None
    max_response_length: int = 200
    reply_enabled: bool = True

    def save(self):
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls) -> "Config":
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception:
                pass
        return cls()
