from pydantic import BaseModel


# ======================== API ======================== #

class APIConfig(BaseModel):
    """Web API server settings."""
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080


# ======================== Sender ======================== #

class SpammerConfig(BaseModel):
    """Packet sender runtime settings."""
    autostart: bool = False
    packets_per_second: int = 10
    channel: int = 6


# ======================== Base Host Config ======================== #

class BaseHostConfig(BaseModel):
    """Base configuration for the host. Extend this in app/models/config.py."""
    api: APIConfig = APIConfig()
    sender: SpammerConfig = SpammerConfig()
