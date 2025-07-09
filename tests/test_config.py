"""
Test configuration and settings
"""

import pytest
from app.core.config import Settings, get_settings


def test_default_settings():
    """Test that default settings are correctly loaded"""
    settings = Settings()
    
    assert settings.database_url == "sqlite:///./database/attendance.db"
    assert settings.zkteco_host == "192.168.100.209"
    assert settings.zkteco_port == 4370
    assert settings.server_port == 5000
    assert settings.environment == "development"
    assert settings.debug is True


def test_environment_detection():
    """Test environment detection methods"""
    settings = Settings()
    
    assert settings.is_development is True
    assert settings.is_production is False
    
    # Test production environment
    settings.environment = "production"
    assert settings.is_development is False
    assert settings.is_production is True


def test_device_config():
    """Test device configuration helper"""
    from app.core.config import get_device_config
    
    config = get_device_config()
    
    assert "host" in config
    assert "port" in config
    assert "password" in config
    assert "timeout" in config
    assert "max_retries" in config
    assert config["port"] == 4370


def test_server_config():
    """Test server configuration helper"""
    from app.core.config import get_server_config
    
    config = get_server_config()
    
    assert "host" in config
    assert "port" in config
    assert "log_level" in config
    assert "reload" in config
    assert config["port"] == 5000


def test_get_settings():
    """Test settings dependency injection"""
    settings = get_settings()
    
    assert isinstance(settings, Settings)
    assert settings.database_url == "sqlite:///./database/attendance.db"