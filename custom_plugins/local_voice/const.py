"""Constants for the Local Voice RotorHazard plugin."""

PANEL_ID = "local_voice"
CONFIG_SECTION = "LOCAL_VOICE"
PLUGIN_PREFIX = "local_voice"

ENABLE_OPTION = f"{PLUGIN_PREFIX}_enabled"
VOICE_MODEL_OPTION = f"{PLUGIN_PREFIX}_voice_model"
SPEECH_SPEED_OPTION = f"{PLUGIN_PREFIX}_speech_speed"
NOISE_SCALE_OPTION = f"{PLUGIN_PREFIX}_noise_scale"
NOISE_W_SCALE_OPTION = f"{PLUGIN_PREFIX}_noise_w_scale"
TEST_PHRASE_OPTION = f"{PLUGIN_PREFIX}_test_phrase"

# Audio profile toggles
ENABLE_CROSSING_BEEPS_OPTION = f"{PLUGIN_PREFIX}_enable_crossing_beeps"

# SendSpin server
SENDSPIN_PORT = 8927

DEFAULT_TEST_PHRASE = "Pilot Rocket finishes lap three in twelve point four seconds."
DEFAULT_MODEL = "en_GB-alan-medium"
DEFAULT_SPEED = "1.2"
DEFAULT_NOISE_SCALE = "0.667"
DEFAULT_NOISE_W_SCALE = "0.8"

_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

VOICE_MODELS = {
    "en_GB-alan-medium": {
        "label": "English (GB) - Alan (medium)",
        "base_url": f"{_HF}/en/en_GB/alan/medium/en_GB-alan-medium",
    },
    "en_GB-cori-medium": {
        "label": "English (GB) - Cori (medium)",
        "base_url": f"{_HF}/en/en_GB/cori/medium/en_GB-cori-medium",
    },
    "en_GB-cori-high": {
        "label": "English (GB) - Cori (high)",
        "base_url": f"{_HF}/en/en_GB/cori/high/en_GB-cori-high",
    },
    "en_US-joe-medium": {
        "label": "English (US) - Joe (medium)",
        "base_url": f"{_HF}/en/en_US/joe/medium/en_US-joe-medium",
    },
    "en_US-lessac-medium": {
        "label": "English (US) - Lessac (medium)",
        "base_url": f"{_HF}/en/en_US/lessac/medium/en_US-lessac-medium",
    },
    "en_US-lessac-high": {
        "label": "English (US) - Lessac (high)",
        "base_url": f"{_HF}/en/en_US/lessac/high/en_US-lessac-high",
    },
    "nl_NL-alex-medium": {
        "label": "Dutch (NL) - Alex (medium)",
        "base_url": f"{_HF}/nl/nl_NL/alex/medium/nl_NL-alex-medium",
    },
    "nl_NL-mls-medium": {
        "label": "Dutch (NL) - MLS (medium)",
        "base_url": f"{_HF}/nl/nl_NL/mls/medium/nl_NL-mls-medium",
    },
    "nl_NL-pim-medium": {
        "label": "Dutch (NL) - Pim (medium)",
        "base_url": f"{_HF}/nl/nl_NL/pim/medium/nl_NL-pim-medium",
    },
    "nl_NL-ronnie-medium": {
        "label": "Dutch (NL) - Ronnie (medium)",
        "base_url": f"{_HF}/nl/nl_NL/ronnie/medium/nl_NL-ronnie-medium",
    },
    "de_DE-thorsten-medium": {
        "label": "German (DE) - Thorsten (medium)",
        "base_url": f"{_HF}/de/de_DE/thorsten/medium/de_DE-thorsten-medium",
    },
    "de_DE-thorsten-high": {
        "label": "German (DE) - Thorsten (high)",
        "base_url": f"{_HF}/de/de_DE/thorsten/high/de_DE-thorsten-high",
    },
}
