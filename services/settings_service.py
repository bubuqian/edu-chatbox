"""设置服务 - 读写 settings.json + app_state"""
import json
import os
from config import SETTINGS_PATH, DEFAULT_GEMINI_CONFIG, DEFAULT_IMESSAGE_CONFIG, DEFAULT_APP_STATE


class SettingsService:
    def __init__(self):
        self._cache = None

    def _load(self):
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
        else:
            self._cache = {
                "gemini_config": dict(DEFAULT_GEMINI_CONFIG),
                "imessage_config": dict(DEFAULT_IMESSAGE_CONFIG),
                "app_state": dict(DEFAULT_APP_STATE),
            }
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2, ensure_ascii=False)

    def _ensure_loaded(self):
        if self._cache is None:
            self._load()

    # --- Gemini Config ---
    def get_gemini_config(self) -> dict:
        self._ensure_loaded()
        cfg = self._cache.get("gemini_config", {})
        merged = dict(DEFAULT_GEMINI_CONFIG)
        merged.update(cfg)
        return merged

    def save_gemini_config(self, config: dict):
        self._ensure_loaded()
        self._cache["gemini_config"] = config
        self._save()

    # --- iMessage Config ---
    def get_imessage_config(self) -> dict:
        self._ensure_loaded()
        cfg = self._cache.get("imessage_config", {})
        merged = dict(DEFAULT_IMESSAGE_CONFIG)
        merged.update(cfg)
        return merged

    def save_imessage_config(self, config: dict):
        self._ensure_loaded()
        self._cache["imessage_config"] = config
        self._save()

    # --- App State ---
    def get_app_state(self) -> dict:
        self._ensure_loaded()
        state = self._cache.get("app_state", {})
        merged = dict(DEFAULT_APP_STATE)
        merged.update(state)
        return merged

    def save_app_state(self, state: dict):
        self._ensure_loaded()
        self._cache["app_state"] = state
        self._save()

    # --- Full settings ---
    def get_all(self) -> dict:
        self._ensure_loaded()
        return {
            "gemini_config": self.get_gemini_config(),
            "imessage_config": self.get_imessage_config(),
            "app_state": self.get_app_state(),
        }


settings_service = SettingsService()
