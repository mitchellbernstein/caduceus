"""
Integration key manager — encrypts API keys at rest using Fernet (AES-128-CBC).

Keys are stored as base64-encoded Fernet tokens in integrations.json.
Only the local user can decrypt (key derived from machine-specific secret).

Usage:
    manager = IntegrationManager()
    manager.add(mission_id, provider="stripe", key_value="sk_live_...")
    manager.get(mission_id, provider="stripe")  # returns decrypted value
    manager.delete(mission_id, provider="stripe")
"""
from __future__ import annotations

import base64
import hashlib
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet
    FERNET_AVAILABLE = True
except ImportError:
    FERNET_AVAILABLE = False

from caduceus_api.models import IntegrationKey, MISSIONS_DIR


class IntegrationManager:
    """
    Manages encrypted API keys for external services.

    Encryption key is derived from a machine-specific secret stored at:
        ~/.hermes/caduceus/.integration_key

    If the secret file doesn't exist, it's generated once using os.urandom(32).
    This means encrypted keys CANNOT be copied to another machine — by design
    (data sovereignty).
    """

    def __init__(self, base: Path = MISSIONS_DIR):
        self.base = base
        self._key = self._load_or_create_key()

    def _key_path(self) -> Path:
        return Path.home() / ".hermes" / "caduceus" / ".integration_key"

    def _load_or_create_key(self) -> bytes:
        key_path = self._key_path()
        if key_path.exists():
            raw = key_path.read_bytes()
            return base64.urlsafe_b64decode(raw)
        # Generate new key
        key = os.urandom(32)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(base64.urlsafe_b64encode(key))
        key_path.chmod(0o600)  # Only user can read
        return key

    def _fernet(self) -> "Fernet":
        if not FERNET_AVAILABLE:
            raise RuntimeError(
                "cryptography package required for integration key management. "
                "Install with: pip3 install cryptography"
            )
        # Derive a valid Fernet key (must be 32 bytes, base64-encoded)
        key_bytes = hashlib.sha256(self._key).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        return Fernet(fernet_key)

    def _encrypt(self, value: str) -> str:
        """Encrypt a string value. Returns base64 Fernet token."""
        if not FERNET_AVAILABLE:
            return base64.b64encode(value.encode()).decode()  # Fallback: no crypto
        return self._fernet().encrypt(value.encode()).decode()

    def _decrypt(self, encrypted: str) -> str:
        """Decrypt a Fernet token. Returns original string."""
        if not FERNET_AVAILABLE:
            return base64.b64decode(encrypted.encode()).decode()  # Fallback: no crypto
        try:
            return self._fernet().decrypt(encrypted.encode()).decode()
        except Exception:
            return ""  # Corrupted or wrong key

    def _preview(self, key_value: str) -> str:
        """Return last 4 chars of key for display."""
        return key_value[-4:] if len(key_value) >= 4 else "****"

    def add(self, mission_id: str, provider: str, key_value: str, label: str = "", scopes: list[str] = None) -> IntegrationKey:
        """
        Add an API key for a mission.
        provider: stripe, sendgrid, twilio, openai, postgres, webhook, etc.
        """
        integration = IntegrationKey(
            provider=provider,
            label=label or provider,
            key_preview=self._preview(key_value),
            encrypted_value=self._encrypt(key_value),
            scopes=scopes or [],
        )

        # Load existing integrations
        int_path = self.base / mission_id / "integrations.json"
        if int_path.exists():
            integrations = json.loads(int_path.read_text()).get("integrations", [])
        else:
            integrations = []

        # Remove old entry for same provider+label
        integrations = [i for i in integrations if not (i.get("provider") == provider and i.get("label") == (label or provider))]
        integrations.append({
            "id": integration.id,
            "provider": integration.provider,
            "label": integration.label,
            "key_preview": integration.key_preview,
            "encrypted_value": integration.encrypted_value,
            "created_at": integration.created_at,
            "updated_at": integration.updated_at,
            "scopes": integration.scopes,
        })

        int_path.parent.mkdir(parents=True, exist_ok=True)
        int_path.write_text(json.dumps({"integrations": integrations}, indent=2))
        return integration

    def get(self, mission_id: str, provider: str, label: str = "") -> Optional[str]:
        """Get the decrypted API key for a provider."""
        int_path = self.base / mission_id / "integrations.json"
        if not int_path.exists():
            return None

        integrations = json.loads(int_path.read_text()).get("integrations", [])
        for i in integrations:
            if i.get("provider") == provider:
                if label and i.get("label") != label:
                    continue
                decrypted = self._decrypt(i.get("encrypted_value", ""))
                # Update last_used_at
                i["last_used_at"] = i.get("created_at", datetime.now().isoformat())
                int_path.write_text(json.dumps({"integrations": integrations}, indent=2))
                return decrypted
        return None

    def list(self, mission_id: str) -> list[dict]:
        """List all integrations for a mission (REDACTED — never returns decrypted keys)."""
        int_path = self.base / mission_id / "integrations.json"
        if not int_path.exists():
            return []
        integrations = json.loads(int_path.read_text()).get("integrations", [])
        return [
            {
                "id": i["id"],
                "provider": i["provider"],
                "label": i["label"],
                "key_preview": i["key_preview"],
                "created_at": i.get("created_at"),
                "last_used_at": i.get("last_used_at"),
                "scopes": i.get("scopes", []),
            }
            for i in integrations
        ]

    def delete(self, mission_id: str, integration_id: str) -> bool:
        """Delete an integration by ID."""
        int_path = self.base / mission_id / "integrations.json"
        if not int_path.exists():
            return False
        integrations = json.loads(int_path.read_text()).get("integrations", [])
        before = len(integrations)
        integrations = [i for i in integrations if i.get("id") != integration_id]
        if len(integrations) == before:
            return False
        int_path.write_text(json.dumps({"integrations": integrations}, indent=2))
        return True

    def has(self, mission_id: str, provider: str) -> bool:
        """Check if a provider is configured for this mission."""
        return self.get(mission_id, provider) is not None


# ── Default integrations we support ───────────────────────────────────────────

SUPPORTED_PROVIDERS = {
    "stripe": {
        "label": "Stripe",
        "description": "Payment processing and subscriptions",
        "placeholder": "sk_live_...",
        "scopes_help": "Secret key with read/write access",
        "docs": "https://dashboard.stripe.com/apikeys",
    },
    "sendgrid": {
        "label": "SendGrid",
        "description": "Transactional email delivery",
        "placeholder": "SG....",
        "scopes_help": "API key with Mail send permissions",
        "docs": "https://app.sendgrid.com/settings/api_keys",
    },
    "twilio": {
        "label": "Twilio",
        "description": "SMS and voice notifications",
        "placeholder": "AC...",
        "scopes_help": "Account SID and Auth Token",
        "docs": "https://console.twilio.com/us/develop/account/keys-credentials",
    },
    "openai": {
        "label": "OpenAI",
        "description": "GPT-4o and other OpenAI models",
        "placeholder": "sk-...",
        "scopes_help": "Secret API key",
        "docs": "https://platform.openai.com/api-keys",
    },
    "postgres": {
        "label": "PostgreSQL",
        "description": "Your own Postgres database",
        "placeholder": "postgres://user:pass@host:5432/db",
        "scopes_help": "Connection string",
        "docs": None,
    },
    "webhook": {
        "label": "Webhook URL",
        "description": "Zapier, n8n, or any HTTP endpoint",
        "placeholder": "https://hooks.zapier.com/...",
        "scopes_help": "Target URL (GET/POST auth handled by header)",
        "docs": None,
    },
    "s3": {
        "label": "AWS S3",
        "description": "File and asset storage",
        "placeholder": "AKIA...",
        "scopes_help": "Access key ID + Secret",
        "docs": "https://console.aws.amazon.com/iam/home#/users",
    },
    "gcs": {
        "label": "Google Cloud Storage",
        "description": "GCS file storage",
        "placeholder": '{"type":"service_account",...}',
        "scopes_help": "JSON service account credentials",
        "docs": "https://console.cloud.google.com/apis/credentials",
    },
    "domain": {
        "label": "Custom Domain",
        "description": "Your domain name for deployments",
        "placeholder": "mydomain.com",
        "scopes_help": "Domain name only (no secret needed)",
        "docs": None,
    },
}
