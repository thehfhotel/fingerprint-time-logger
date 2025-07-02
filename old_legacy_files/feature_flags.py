"""
Feature flags for gradual rollout of sync system redesign

This module provides centralized feature flag management to enable/disable
new sync system features during migration and testing phases.
"""

import os
from typing import Dict, Any


class FeatureFlags:
    """Feature flags for gradual rollout of sync system redesign"""
    
    # Feature flag names
    ERROR_CLASSIFICATION = "error_classification"
    ENHANCED_CIRCUIT_BREAKER = "enhanced_circuit_breaker"
    MULTI_DIMENSIONAL_HEALTH = "multi_dimensional_health"
    AUTO_ERROR_RECOVERY = "auto_error_recovery"
    GRADUATED_STATES_UI = "graduated_states_ui"
    
    @staticmethod
    def is_enabled(flag_name: str) -> bool:
        """
        Check if a feature flag is enabled
        
        Args:
            flag_name: Name of the feature flag to check
            
        Returns:
            True if feature is enabled, False otherwise
        """
        env_var_name = f"FEATURE_{flag_name.upper()}"
        return os.getenv(env_var_name, "False").lower() in ("true", "1", "yes", "on")
    
    @staticmethod
    def get_all_flags() -> Dict[str, bool]:
        """
        Get all feature flags and their current states
        
        Returns:
            Dictionary mapping feature names to their enabled/disabled state
        """
        return {
            FeatureFlags.ERROR_CLASSIFICATION: FeatureFlags.is_enabled(FeatureFlags.ERROR_CLASSIFICATION),
            FeatureFlags.ENHANCED_CIRCUIT_BREAKER: FeatureFlags.is_enabled(FeatureFlags.ENHANCED_CIRCUIT_BREAKER),
            FeatureFlags.MULTI_DIMENSIONAL_HEALTH: FeatureFlags.is_enabled(FeatureFlags.MULTI_DIMENSIONAL_HEALTH),
            FeatureFlags.AUTO_ERROR_RECOVERY: FeatureFlags.is_enabled(FeatureFlags.AUTO_ERROR_RECOVERY),
            FeatureFlags.GRADUATED_STATES_UI: FeatureFlags.is_enabled(FeatureFlags.GRADUATED_STATES_UI)
        }
    
    @staticmethod
    def is_error_classification_enabled() -> bool:
        """Check if error classification feature is enabled"""
        return FeatureFlags.is_enabled(FeatureFlags.ERROR_CLASSIFICATION)
    
    @staticmethod
    def is_enhanced_circuit_breaker_enabled() -> bool:
        """Check if enhanced circuit breaker feature is enabled"""
        return FeatureFlags.is_enabled(FeatureFlags.ENHANCED_CIRCUIT_BREAKER)
    
    @staticmethod
    def is_multi_dimensional_health_enabled() -> bool:
        """Check if multi-dimensional health assessment is enabled"""
        return FeatureFlags.is_enabled(FeatureFlags.MULTI_DIMENSIONAL_HEALTH)
    
    @staticmethod
    def is_auto_error_recovery_enabled() -> bool:
        """Check if automatic error recovery is enabled"""
        return FeatureFlags.is_enabled(FeatureFlags.AUTO_ERROR_RECOVERY)
    
    @staticmethod
    def is_graduated_states_ui_enabled() -> bool:
        """Check if graduated states UI is enabled"""
        return FeatureFlags.is_enabled(FeatureFlags.GRADUATED_STATES_UI)
    
    @staticmethod
    def require_feature(flag_name: str) -> None:
        """
        Require a feature to be enabled, raise exception if not
        
        Args:
            flag_name: Name of the required feature flag
            
        Raises:
            RuntimeError: If the feature is not enabled
        """
        if not FeatureFlags.is_enabled(flag_name):
            raise RuntimeError(
                f"Feature '{flag_name}' is required but not enabled. "
                f"Set environment variable FEATURE_{flag_name.upper()}=True to enable."
            )
    
    @staticmethod
    def get_enabled_features() -> list[str]:
        """
        Get list of currently enabled features
        
        Returns:
            List of enabled feature names
        """
        all_flags = FeatureFlags.get_all_flags()
        return [name for name, enabled in all_flags.items() if enabled]
    
    @staticmethod
    def print_feature_status() -> None:
        """Print current feature flag status to console"""
        print("🚀 Sync System Feature Flags Status:")
        flags = FeatureFlags.get_all_flags()
        
        for feature, enabled in flags.items():
            status_icon = "✅" if enabled else "❌"
            status_text = "ENABLED" if enabled else "DISABLED"
            print(f"  {status_icon} {feature}: {status_text}")
        
        enabled_count = sum(1 for enabled in flags.values() if enabled)
        print(f"\n📊 Summary: {enabled_count}/{len(flags)} features enabled")


# Environment variable configuration examples:
"""
To enable features, set environment variables:

# Enable error classification
export FEATURE_ERROR_CLASSIFICATION=True

# Enable enhanced circuit breaker
export FEATURE_ENHANCED_CIRCUIT_BREAKER=True

# Enable multi-dimensional health assessment
export FEATURE_MULTI_DIMENSIONAL_HEALTH=True

# Enable automatic error recovery
export FEATURE_AUTO_ERROR_RECOVERY=True

# Enable graduated states UI
export FEATURE_GRADUATED_STATES_UI=True

# Or in .env file:
FEATURE_ERROR_CLASSIFICATION=True
FEATURE_ENHANCED_CIRCUIT_BREAKER=False
FEATURE_MULTI_DIMENSIONAL_HEALTH=False
FEATURE_AUTO_ERROR_RECOVERY=False
FEATURE_GRADUATED_STATES_UI=False
"""