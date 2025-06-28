from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./attendance.db"
    
    zkteco_host: str = "192.168.1.201"
    zkteco_port: int = 4370
    zkteco_password: int = 0
    zkteco_timeout: int = 5
    
    redis_url: str = "redis://localhost:6379/0"
    
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "your-secret-key-change-this"
    
    sync_interval: int = 30
    max_retries: int = 3
    
    log_level: str = "INFO"
    
    # Clear device attendance after successful sync
    CLEAR_DEVICE_AFTER_SYNC: bool = False

    class Config:
        env_file = ".env"


settings = Settings()