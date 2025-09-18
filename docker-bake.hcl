# Docker Bake configuration for fingerprint-time-logger
# Simplified configuration optimized for Docker Compose integration

# Variables for image naming
variable "IMAGE_TAG" {
  default = "latest"
}

variable "IMAGE_NAME" {
  default = "fingerprint-logger"
}

# Cache busting variable - change this to force cache invalidation
variable "CACHEBUST" {
  default = "1"
}

# No-cache option for complete rebuilds
variable "NO_CACHE" {
  default = false
}

# Default group
group "default" {
  targets = ["fingerprint-logger"]
}

# Main application target (matches compose service)
target "fingerprint-logger" {
  dockerfile = "Dockerfile"
  context = "."
  tags = ["${IMAGE_NAME}:${IMAGE_TAG}"]
  target = "fingerprint-logger"

  # Cache control
  no-cache = NO_CACHE

  # Build optimization with cache busting
  args = {
    BUILD_TYPE = "production"
    CACHEBUST = "${CACHEBUST}"
  }

  # Platform specification
  platforms = ["linux/amd64"]

  # Metadata labels
  labels = {
    "org.opencontainers.image.title" = "Fingerprint Time Logger"
    "org.opencontainers.image.description" = "ZKTeco biometric device integration"
    "org.opencontainers.image.version" = "${IMAGE_TAG}"
    "org.opencontainers.image.created" = "${timestamp()}"
    "build.cachebust" = "${CACHEBUST}"
  }
}

# Development target
target "fingerprint-logger-dev" {
  inherits = ["fingerprint-logger"]
  tags = ["${IMAGE_NAME}:dev"]
  target = "development"
  args = {
    INSTALL_DEV_DEPS = "true"
    BUILD_TYPE = "development"
    CACHEBUST = "${CACHEBUST}"
  }
}

# Production optimized target
target "fingerprint-logger-prod" {
  inherits = ["fingerprint-logger"]
  tags = ["${IMAGE_NAME}:prod"]
  args = {
    BUILD_TYPE = "production"
    PYTHON_OPTIMIZE = "2"
    CACHEBUST = "${CACHEBUST}"
  }
}