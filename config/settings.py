"""Cấu hình Django cho OSS Radar.

Đây là nơi DUY NHẤT được đọc biến môi trường (CLAUDE.md mục 3; ruff TID251 chặn ở nơi khác).
Code khác đọc cấu hình qua `django.conf.settings`.
"""

import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# .env chỉ bổ sung biến còn thiếu; biến môi trường thật (CI, terminal) được ưu tiên hơn.
load_dotenv(BASE_DIR / ".env", override=False)


def _env_str(name: str, *, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def parse_bool(raw: str, *, name: str, default: bool) -> bool:
    """Đọc true/false từ chuỗi cấu hình: trống thì dùng mặc định, viết sai thì báo lỗi."""
    value = raw.strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} phải là true hoặc false, đang là {raw!r}.")


def resolve_secret_key(raw: str, *, debug: bool) -> str:
    """Khoá bí mật của Django: bắt buộc khi tắt DEBUG; khi DEBUG thì để trống được."""
    if raw.strip():
        return raw.strip()
    if not debug:
        raise ImproperlyConfigured(
            "Thiếu DJANGO_SECRET_KEY trong .env (bắt buộc khi DJANGO_DEBUG=false)."
        )
    # App không dùng session hay đăng nhập → khoá ngẫu nhiên mỗi lần chạy là đủ khi phát triển.
    return secrets.token_urlsafe(50)


# DEBT(D-001): DEBUG bật mặc định — chỉ an toàn khi app chỉ nghe 127.0.0.1.
DEBUG = parse_bool(_env_str("DJANGO_DEBUG"), name="DJANGO_DEBUG", default=True)
SECRET_KEY = resolve_secret_key(_env_str("DJANGO_SECRET_KEY"), debug=DEBUG)

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]


# Ứng dụng — mỗi tính năng là một thư mục trong features/ (xem FEATURE_MAP.md).
INSTALLED_APPS = [
    # Đứng trước staticfiles để lệnh `runserver` của dự án (bật bộ nhịp) được dùng thay lệnh gốc.
    "core",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "features.catalog",
    "features.discovery",
    "features.rising",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Cơ sở dữ liệu: một file SQLite trong data/ (QĐ-04).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "oss_radar.sqlite3",
        "OPTIONS": {
            # WAL: trang web vẫn đọc được trong lúc lệnh quét đang ghi.
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            # Giành khoá ghi ngay khi mở transaction → tránh lỗi "database is locked" giữa chừng.
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Ngôn ngữ và thời gian
LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True
# Định dạng tiếng Việt của Django có dấu ngăn nghìn "." nhưng thiếu cỡ nhóm → tự khai (255.793).
NUMBER_GROUPING = 3


# File tĩnh (CSS)
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]


# GitHub (integrations/github). Token để trống vẫn chạy nhưng GitHub chỉ cho 10 lần tìm kiếm/phút.
GITHUB_TOKEN = _env_str("GITHUB_TOKEN")
GITHUB_API_URL = "https://api.github.com"
GITHUB_TIMEOUT_SECONDS = 20.0


# Việc định kỳ (QĐ-15): bộ nhịp `core/scheduler.py` gọi lần lượt các hàm này trên luồng nền, đúng
# thứ tự khai. Nhìn danh sách này là biết app tự làm những gì.
SCHEDULED_JOBS: list[str] = [
    "features.discovery.services.resume_interrupted_scan",
    "features.rising.services.run_daily_if_due",
]


# Log ra màn hình console; code dùng logging.getLogger(__name__), không dùng print().
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
