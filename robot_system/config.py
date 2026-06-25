"""Global configuration for the robot greeting system."""

import os
from pathlib import Path

# Face recognition
FACE_DB_SIZE = 200
FACE_MATCH_THRESHOLD = 0.75
FACE_EMBEDDING_DIM = 128
FACE_EMBEDDING_VERSION = 1
CANDIDATE_POOL_MAX = int(os.environ.get("ROBOT_CANDIDATE_POOL_MAX", "256"))

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

# Demo / deployment
DEMO_MODE = os.environ.get("ROBOT_DEMO_MODE", "0").lower() in ("1", "true", "yes")

# Health monitor
HEALTH_CHECK_INTERVAL = 10.0

# Greeting — same person same day: first full welcome, later nod-only silent ack
DAILY_SILENT_REPEAT = os.environ.get("ROBOT_DAILY_SILENT_REPEAT", "1").lower() in ("1", "true", "yes")

# Recognition guard
RECOGNITION_DEBOUNCE_SEC = float(os.environ.get("ROBOT_RECOGNITION_DEBOUNCE_SEC", "1.5"))
IDENTITY_CONFIRM_COUNT = int(os.environ.get("ROBOT_IDENTITY_CONFIRM_COUNT", "3"))
WELCOME_ZONE_DWELL_SEC = float(os.environ.get("ROBOT_WELCOME_ZONE_DWELL_SEC", "2.0"))
GROUP_DETECTION_WINDOW_SEC = float(os.environ.get("ROBOT_GROUP_WINDOW_SEC", "10.0"))
GROUP_GREETING_THRESHOLD = int(os.environ.get("ROBOT_GROUP_THRESHOLD", "3"))

# Speech throttle
PERSON_GREETING_COOLDOWN = float(os.environ.get("ROBOT_PERSON_GREETING_COOLDOWN", str(30 * 60)))
GLOBAL_GREETING_INTERVAL = float(os.environ.get("ROBOT_GLOBAL_GREETING_INTERVAL", "20.0"))
SALES_ENGAGED = os.environ.get("ROBOT_SALES_ENGAGED", "0").lower() in ("1", "true", "yes")

# Error recovery
ERROR_AUTO_RECOVERY = os.environ.get("ROBOT_ERROR_AUTO_RECOVERY", "1").lower() in ("1", "true", "yes")
ERROR_RECOVERY_DELAY_SEC = float(os.environ.get("ROBOT_ERROR_RECOVERY_DELAY_SEC", "5.0"))

# Farewell / zone exit
ZONE_EXIT_TIMEOUT_SEC = float(os.environ.get("ROBOT_ZONE_EXIT_TIMEOUT_SEC", "15.0"))
FAREWELL_PERSON_COOLDOWN = float(os.environ.get("ROBOT_FAREWELL_PERSON_COOLDOWN", str(30 * 60)))

# Face DB persistence
_DEFAULT_DB_DIR = Path(__file__).resolve().parent / "data"
FACE_DB_PERSIST_PATH = os.environ.get(
    "ROBOT_FACE_DB_PATH",
    str(_DEFAULT_DB_DIR / "face_db.json"),
)
FACE_DB_SEED = os.environ.get("ROBOT_FACE_DB_SEED", "1").lower() in ("1", "true", "yes")

# Face DB capacity (灵犀 X2 SDK hard limit)
FACE_DB_MAX_CAPACITY = int(os.environ.get("ROBOT_FACE_DB_MAX_CAPACITY", "1000"))
FACE_CAPACITY_WARNING_THRESHOLD = int(os.environ.get("ROBOT_FACE_CAPACITY_WARNING", "850"))
FACE_CAPACITY_EMERGENCY_THRESHOLD = int(os.environ.get("ROBOT_FACE_CAPACITY_EMERGENCY", "950"))
VISITOR_EXPIRE_DAYS = int(os.environ.get("ROBOT_VISITOR_EXPIRE_DAYS", "30"))

# Logging
LOG_LEVEL = os.environ.get("ROBOT_LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
