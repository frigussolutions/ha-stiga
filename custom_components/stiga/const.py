"""Constants for the STIGA integration."""

from datetime import timedelta

DOMAIN = "stiga"

CONF_BLOCKS = "blocks"
MAX_BLOCKS = 3

# Upstream project the protocol was ported from; attributed in the UI.
STIGA_API_URL = "https://github.com/matthewgream/stiga-api"

# Public Firebase web key of the STIGA.GO app (identical for every user).
FIREBASE_API_KEY = "AIzaSyCPtRBU_hwWZYsguHp9ucGrfNac0kXR6ug"
FIREBASE_AUTH_URL = "https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword"

API_URL = "https://connectivity-production.stiga.com"

MQTT_HOST = "robot-mqtt-{broker}.stiga.com"
MQTT_PORT = 8883
MQTT_USERNAME = "firebaseauth|connectivity-production.stiga.com"

# Status request cadence: tight while the robot is out, relaxed while it is home.
TICK_INTERVAL = timedelta(seconds=60)
IDLE_POLL_TICKS = 5
# Entities go unavailable when no status has arrived for this long.
STALE_AFTER = timedelta(minutes=20)
COMMAND_ACK_TIMEOUT = 15
