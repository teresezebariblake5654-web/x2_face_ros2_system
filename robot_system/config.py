"""Global configuration for the robot greeting system."""

import os

# Face recognition
FACE_DB_SIZE = 200
FACE_MATCH_THRESHOLD = 0.75
FACE_EMBEDDING_DIM = 128
FACE_EMBEDDING_VERSION = 1

# Timing (seconds) — monotonic
FACE_ENGINE_INTERVAL = 3.0
BRAIN_TICK_INTERVAL = 0.1
GREETING_COOLDOWN = 5.0
DIALOG_TIMEOUT = 30.0
NAV_TIMEOUT = 30.0
NAV_RETRY_MAX = 3
ACTION_TIMEOUT = 5.0
ACTION_QUEUE_MAX = 32

# EventBus
EVENT_QUEUE_MAX_SIZE = 1024

# Logging
LOG_LEVEL = os.environ.get("ROBOT_LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
