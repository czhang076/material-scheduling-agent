"""Explicit local configuration; credentials never enter public model metadata."""

from dataclasses import dataclass, field
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from material_scheduler.domain.validation import DomainError


def _invalid():
    return DomainError("MODEL_CONFIGURATION_ERROR", "Check model endpoint, name, key and supported local options; values are not echoed")


def _boolean(value):
    if value not in {"true", "false"}:
        raise _invalid()
    return value == "true"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    base_url: str
    model_name: str
    api_key: str = field(repr=False)
    provider: str = "compatible"
    max_output_tokens: int = 1024
    token_parameter: str = "max_completion_tokens"
    strict_tools: bool = False
    max_request_bytes: int = 2_097_152
    max_response_bytes: int = 1_048_576

    def __post_init__(self):
        if type(self.base_url) is not str:
            raise _invalid()
        try:
            url = urlsplit(self.base_url)
            host = url.hostname
            port = url.port
            local = host == "localhost" or (host is not None and ipaddress.ip_address(host).is_loopback)
        except ValueError:
            try:
                url = urlsplit(self.base_url)
                host, port, local = url.hostname, url.port, False
            except ValueError:
                raise _invalid() from None
        if (not host or url.scheme not in {"https", "http"} or (url.scheme == "http" and not local)
                or url.username is not None or url.password is not None or url.query or url.fragment
                or any(char.isspace() or ord(char) < 32 for char in self.base_url)
                or any(char in self.base_url for char in "\\") or (port is not None and not 1 <= port <= 65535)):
            raise _invalid()
        if (type(self.model_name) is not str or not 1 <= len(self.model_name) <= 128 or self.model_name != self.model_name.strip()
                or any(ord(char) < 32 for char in self.model_name)
                or type(self.api_key) is not str or not 1 <= len(self.api_key) <= 512
                or any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in self.api_key)
                or self.api_key in self.base_url or self.api_key in self.model_name):
            raise _invalid()
        if self.provider not in {"compatible", "deepseek"} or self.token_parameter not in {"max_tokens", "max_completion_tokens"}:
            raise _invalid()
        if type(self.strict_tools) is not bool:
            raise _invalid()
        for value, maximum in [(self.max_output_tokens, 4096), (self.max_request_bytes, 8_388_608), (self.max_response_bytes, 2_097_152)]:
            if type(value) is not int or not 1 <= value <= maximum:
                raise _invalid()

    @property
    def endpoint(self):
        return self.base_url.rstrip("/") + "/chat/completions"

    def public_info(self):
        return {"protocol": "chat_completions", "endpoint": self.endpoint, "configured_model": self.model_name,
                "provider": self.provider, "max_output_tokens": self.max_output_tokens,
                "token_parameter": self.token_parameter, "strict_tools": self.strict_tools,
                "thinking": "disabled" if self.provider == "deepseek" else "provider_default",
                "parallel_parameter": "omitted" if self.provider == "deepseek" else False,
                "max_request_bytes": self.max_request_bytes, "max_response_bytes": self.max_response_bytes}


_FIELDS = {"MODEL_BASE_URL", "MODEL_NAME", "MODEL_API_KEY", "MODEL_PROVIDER", "MODEL_MAX_OUTPUT_TOKENS",
           "MODEL_TOKEN_PARAMETER", "MODEL_STRICT_TOOLS", "MODEL_MAX_REQUEST_BYTES", "MODEL_MAX_RESPONSE_BYTES"}


def load_model_config(env_file: Path | None = None, *, environ=None):
    values = {}
    if env_file is not None:
        try:
            if env_file.stat().st_size > 16384:
                raise _invalid()
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, separator, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if not separator or key not in _FIELDS or key in values:
                    raise _invalid()
                if value.startswith(("'", '"')):
                    if len(value) < 2 or value[-1] != value[0]:
                        raise _invalid()
                    value = value[1:-1]
                values[key] = value
        except (OSError, UnicodeError):
            raise _invalid() from None
    process = os.environ if environ is None else environ
    values.update({key: process[key] for key in _FIELDS if key in process})
    try:
        provider = values.get("MODEL_PROVIDER", "compatible")
        return ModelConfig(
            values["MODEL_BASE_URL"], values["MODEL_NAME"], values["MODEL_API_KEY"], provider,
            int(values.get("MODEL_MAX_OUTPUT_TOKENS", "1024")),
            values.get("MODEL_TOKEN_PARAMETER", "max_tokens" if provider == "deepseek" else "max_completion_tokens"),
            _boolean(values.get("MODEL_STRICT_TOOLS", "false")),
            int(values.get("MODEL_MAX_REQUEST_BYTES", "2097152")),
            int(values.get("MODEL_MAX_RESPONSE_BYTES", "1048576")),
        )
    except (KeyError, ValueError, TypeError):
        raise _invalid() from None
