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
    
    # Feature flags for sync system redesign
    feature_error_classification: bool = False
    feature_enhanced_circuit_breaker: bool = False
    feature_multi_dimensional_health: bool = False
    feature_auto_error_recovery: bool = False
    feature_graduated_states_ui: bool = False
    
    # CSV Export Configuration
    csv_export_streaming_threshold: int = 10000  # Auto-enable streaming above this count
    csv_export_max_batch_size: int = 10000  # Maximum batch size for exports
    csv_export_default_batch_size: int = 1000  # Default batch size
    csv_export_timeout: int = 300  # Export timeout in seconds (5 minutes)
    csv_export_chunk_size: int = 8192  # Response chunk size in bytes

    class Config:
        env_file = ".env"


settings = Settings()

def get_settings():
    """Get settings instance"""
    return settings