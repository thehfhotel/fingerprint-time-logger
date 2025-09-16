"""
Comprehensive tests for configuration module
Tests all settings, environment variables, and helper functions
"""

import pytest
import os
from unittest.mock import patch, Mock
from pydantic import ValidationError

from app.core.config import (
    Settings,
    settings,
    get_settings,
    get_database_url,
    get_device_config,
    get_server_config
)


class TestSettingsModel:
    """Test Settings pydantic model functionality"""

    def test_default_settings_initialization(self):
        """Test Settings model with default values"""
        config = Settings()

        # Database defaults
        assert config.database_url == "sqlite:///./database/attendance.db"

        # ZKTeco device defaults
        assert config.zkteco_host == "192.168.100.209"
        assert config.zkteco_port == 4370
        assert config.zkteco_password == 0
        assert config.zkteco_timeout == 5
        assert config.zkteco_max_retries == 3

        # Server defaults
        assert config.server_host == "0.0.0.0"
        assert config.server_port == 5000
        assert config.secret_key == "fingerprint-time-logger-2025"

        # Logging defaults
        assert config.log_level == "INFO"

        # Sync defaults
        assert config.sync_interval_seconds == 30
        assert config.clear_device_after_sync is False

        # Export defaults
        assert config.export_max_records == 50000
        assert config.export_timeout_seconds == 300
        assert config.export_default_format == "csv"

        # Environment defaults
        assert config.environment == "development"
        assert config.debug is True

    def test_custom_settings_initialization(self):
        """Test Settings model with custom values"""
        custom_config = Settings(
            database_url="postgresql://user:pass@localhost/db",
            zkteco_host="192.168.1.100",
            zkteco_port=8080,
            server_port=3000,
            environment="production",
            debug=False
        )

        assert custom_config.database_url == "postgresql://user:pass@localhost/db"
        assert custom_config.zkteco_host == "192.168.1.100"
        assert custom_config.zkteco_port == 8080
        assert custom_config.server_port == 3000
        assert custom_config.environment == "production"
        assert custom_config.debug is False

    def test_environment_properties(self):
        """Test environment property methods"""
        # Development environment
        dev_config = Settings(environment="development")
        assert dev_config.is_development is True
        assert dev_config.is_production is False

        # Production environment
        prod_config = Settings(environment="production")
        assert prod_config.is_production is True
        assert prod_config.is_development is False

        # Case insensitive
        upper_prod_config = Settings(environment="PRODUCTION")
        assert upper_prod_config.is_production is True

        # Mixed case
        mixed_config = Settings(environment="Development")
        assert mixed_config.is_development is True

    def test_settings_validation(self):
        """Test settings validation for invalid values"""
        # Test invalid port numbers
        with pytest.raises((ValidationError, ValueError)):
            Settings(zkteco_port="invalid")

        with pytest.raises((ValidationError, ValueError)):
            Settings(server_port="not_a_number")

        # Test negative values where appropriate
        config_negative_timeout = Settings(zkteco_timeout=-1)
        assert config_negative_timeout.zkteco_timeout == -1  # Pydantic allows this

        config_zero_retries = Settings(zkteco_max_retries=0)
        assert config_zero_retries.zkteco_max_retries == 0


class TestEnvironmentVariables:
    """Test environment variable loading with prefix"""

    @patch.dict(os.environ, {
        'FINGERPRINT_DATABASE_URL': 'sqlite:///test.db',
        'FINGERPRINT_ZKTECO_HOST': '10.0.0.1',
        'FINGERPRINT_ZKTECO_PORT': '9999',
        'FINGERPRINT_SERVER_PORT': '8888',
        'FINGERPRINT_ENVIRONMENT': 'production',
        'FINGERPRINT_DEBUG': 'false'
    })
    def test_environment_variable_loading(self):
        """Test loading settings from environment variables with prefix"""
        config = Settings()

        assert config.database_url == 'sqlite:///test.db'
        assert config.zkteco_host == '10.0.0.1'
        assert config.zkteco_port == 9999
        assert config.server_port == 8888
        assert config.environment == 'production'
        assert config.debug is False

    @patch.dict(os.environ, {
        'FINGERPRINT_ZKTECO_PASSWORD': '12345',
        'FINGERPRINT_ZKTECO_TIMEOUT': '10',
        'FINGERPRINT_SYNC_INTERVAL_SECONDS': '60',
        'FINGERPRINT_EXPORT_MAX_RECORDS': '100000'
    })
    def test_numeric_environment_variables(self):
        """Test numeric environment variables are properly converted"""
        config = Settings()

        assert config.zkteco_password == 12345
        assert config.zkteco_timeout == 10
        assert config.sync_interval_seconds == 60
        assert config.export_max_records == 100000

    @patch.dict(os.environ, {
        'FINGERPRINT_CLEAR_DEVICE_AFTER_SYNC': 'true',
        'FINGERPRINT_DEBUG': 'True'
    })
    def test_boolean_environment_variables(self):
        """Test boolean environment variables are properly converted"""
        config = Settings()

        assert config.clear_device_after_sync is True
        assert config.debug is True

    @patch.dict(os.environ, {
        'FINGERPRINT_LOG_LEVEL': 'ERROR',
        'FINGERPRINT_EXPORT_DEFAULT_FORMAT': 'json',
        'FINGERPRINT_SECRET_KEY': 'custom-secret-key'
    })
    def test_string_environment_variables(self):
        """Test string environment variables"""
        config = Settings()

        assert config.log_level == 'ERROR'
        assert config.export_default_format == 'json'
        assert config.secret_key == 'custom-secret-key'

    @patch.dict(os.environ, {
        'DATABASE_URL': 'postgresql://localhost/test',  # Without prefix
        'FINGERPRINT_DATABASE_URL': 'sqlite:///prefixed.db'  # With prefix
    })
    def test_prefix_priority(self):
        """Test that prefixed environment variables take priority"""
        config = Settings()
        # Should use the prefixed version
        assert config.database_url == 'sqlite:///prefixed.db'

    def test_case_insensitive_loading(self):
        """Test case insensitive environment variable loading"""
        with patch.dict(os.environ, {
            'fingerprint_zkteco_host': '192.168.1.50',  # lowercase
            'FINGERPRINT_ZKTECO_PORT': '5555'           # uppercase
        }):
            config = Settings()
            assert config.zkteco_host == '192.168.1.50'
            assert config.zkteco_port == 5555


class TestGlobalSettingsInstance:
    """Test the global settings instance"""

    def test_global_settings_exists(self):
        """Test global settings instance exists and is Settings type"""
        from app.core.config import settings
        assert isinstance(settings, Settings)

    def test_get_settings_function(self):
        """Test get_settings function returns global instance"""
        retrieved_settings = get_settings()
        assert isinstance(retrieved_settings, Settings)
        assert retrieved_settings is settings

    def test_settings_singleton_behavior(self):
        """Test that get_settings always returns the same instance"""
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2


class TestHelperFunctions:
    """Test configuration helper functions"""

    def test_get_database_url(self):
        """Test get_database_url helper function"""
        with patch('app.core.config.settings') as mock_settings:
            mock_settings.database_url = 'test://database'
            result = get_database_url()
            assert result == 'test://database'

    def test_get_device_config(self):
        """Test get_device_config helper function"""
        with patch('app.core.config.settings') as mock_settings:
            mock_settings.zkteco_host = '192.168.1.1'
            mock_settings.zkteco_port = 1234
            mock_settings.zkteco_password = 999
            mock_settings.zkteco_timeout = 15
            mock_settings.zkteco_max_retries = 5

            result = get_device_config()

            expected = {
                "host": "192.168.1.1",
                "port": 1234,
                "password": 999,
                "timeout": 15,
                "max_retries": 5
            }
            assert result == expected

    def test_get_server_config(self):
        """Test get_server_config helper function"""
        with patch('app.core.config.settings') as mock_settings:
            mock_settings.server_host = '127.0.0.1'
            mock_settings.server_port = 8080
            mock_settings.log_level = 'DEBUG'
            mock_settings.is_development = True

            result = get_server_config()

            expected = {
                "host": "127.0.0.1",
                "port": 8080,
                "log_level": "debug",  # Should be lowercase
                "reload": True
            }
            assert result == expected

    def test_get_server_config_production(self):
        """Test get_server_config for production environment"""
        with patch('app.core.config.settings') as mock_settings:
            mock_settings.server_host = '0.0.0.0'
            mock_settings.server_port = 5000
            mock_settings.log_level = 'INFO'
            mock_settings.is_development = False

            result = get_server_config()

            expected = {
                "host": "0.0.0.0",
                "port": 5000,
                "log_level": "info",  # Should be lowercase
                "reload": False  # No reload in production
            }
            assert result == expected


class TestConfigurationEdgeCases:
    """Test edge cases and error conditions"""

    def test_empty_string_values(self):
        """Test handling of empty string values"""
        config = Settings(
            zkteco_host="",  # Empty string
            secret_key="",
            log_level=""
        )

        assert config.zkteco_host == ""
        assert config.secret_key == ""
        assert config.log_level == ""

    def test_extreme_numeric_values(self):
        """Test extreme numeric values"""
        config = Settings(
            zkteco_port=1,  # Minimum port
            server_port=65535,  # Maximum port
            export_max_records=1000000,  # Large number
            sync_interval_seconds=1  # Minimum interval
        )

        assert config.zkteco_port == 1
        assert config.server_port == 65535
        assert config.export_max_records == 1000000
        assert config.sync_interval_seconds == 1

    def test_unicode_string_values(self):
        """Test Unicode string handling"""
        config = Settings(
            secret_key="🔐-secret-key-ไทย",
            zkteco_host="device.ไทย"
        )

        assert config.secret_key == "🔐-secret-key-ไทย"
        assert config.zkteco_host == "device.ไทย"

    @patch.dict(os.environ, {
        'FINGERPRINT_ZKTECO_PORT': 'invalid_port'
    })
    def test_invalid_environment_variable_types(self):
        """Test handling of invalid environment variable types"""
        with pytest.raises((ValidationError, ValueError)):
            Settings()

    def test_settings_immutability_simulation(self):
        """Test that settings behave consistently"""
        config1 = Settings()
        config2 = Settings()

        # Same defaults should produce same values
        assert config1.database_url == config2.database_url
        assert config1.zkteco_host == config2.zkteco_host
        assert config1.server_port == config2.server_port


class TestConfigurationIntegration:
    """Test integration between different configuration aspects"""

    def test_development_vs_production_behavior(self):
        """Test different behaviors between dev and prod environments"""
        dev_config = Settings(environment="development")
        prod_config = Settings(environment="production")

        # Development should have debug enabled
        assert dev_config.debug is True
        assert dev_config.is_development is True

        # Production might have debug disabled (default is True, but can be overridden)
        prod_config_with_debug_off = Settings(environment="production", debug=False)
        assert prod_config_with_debug_off.debug is False
        assert prod_config_with_debug_off.is_production is True

    def test_server_config_environment_dependency(self):
        """Test server config depends on environment settings"""
        with patch('app.core.config.settings') as mock_settings:
            # Development environment
            mock_settings.server_host = '127.0.0.1'
            mock_settings.server_port = 5000
            mock_settings.log_level = 'DEBUG'
            mock_settings.is_development = True

            dev_server_config = get_server_config()
            assert dev_server_config["reload"] is True
            assert dev_server_config["log_level"] == "debug"

            # Production environment
            mock_settings.is_development = False
            mock_settings.log_level = 'WARNING'

            prod_server_config = get_server_config()
            assert prod_server_config["reload"] is False
            assert prod_server_config["log_level"] == "warning"

    def test_device_config_completeness(self):
        """Test device config includes all necessary ZKTeco parameters"""
        device_config = get_device_config()

        required_keys = ["host", "port", "password", "timeout", "max_retries"]
        for key in required_keys:
            assert key in device_config
            assert device_config[key] is not None

    def test_config_consistency_across_functions(self):
        """Test consistency between different config access methods"""
        # Direct settings access vs helper functions should be consistent
        direct_db_url = settings.database_url
        helper_db_url = get_database_url()
        assert direct_db_url == helper_db_url

        # Device config should match individual settings
        device_config = get_device_config()
        assert device_config["host"] == settings.zkteco_host
        assert device_config["port"] == settings.zkteco_port
        assert device_config["password"] == settings.zkteco_password
        assert device_config["timeout"] == settings.zkteco_timeout
        assert device_config["max_retries"] == settings.zkteco_max_retries


class TestConfigurationDocumentation:
    """Test that configuration is well documented and structured"""

    def test_all_settings_have_defaults(self):
        """Test that all settings have reasonable default values"""
        config = Settings()

        # Check that no settings are None (all have defaults)
        config_dict = config.model_dump()
        for key, value in config_dict.items():
            assert value is not None, f"Setting {key} should have a default value"

    def test_settings_structure_consistency(self):
        """Test that settings structure is consistent and logical"""
        config = Settings()

        # Ports should be positive integers
        assert isinstance(config.zkteco_port, int)
        assert config.zkteco_port > 0
        assert isinstance(config.server_port, int)
        assert config.server_port > 0

        # Timeouts should be positive
        assert config.zkteco_timeout > 0
        assert config.export_timeout_seconds > 0

        # Intervals should be positive
        assert config.sync_interval_seconds > 0

        # Max values should be reasonable
        assert config.export_max_records > 0
        assert config.zkteco_max_retries > 0

    def test_environment_prefix_consistency(self):
        """Test that environment prefix is consistently applied"""
        # This tests the model_config.env_prefix setting
        config = Settings()
        assert hasattr(config, 'model_config')
        assert config.model_config.get('env_prefix') == "FINGERPRINT_"
        assert config.model_config.get('case_sensitive') is False