import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.money import parse_amount, to_cents, to_decimal
from app.order import ALLOWED_TRANSITIONS
from app.security import hash_password, sign, unsign, verify_password

STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"


def read_frontend_status_map():
    """อ่านตาราง NEXT_STATUS ออกจาก app/static/app.js"""
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    block = re.search(r"const NEXT_STATUS = \{(.*?)\n\};", source, re.S)
    assert block, "ไม่พบ NEXT_STATUS ใน app/static/app.js"
    return {
        match.group(1): [
            item.strip().strip('"') for item in match.group(2).split(",") if item.strip()
        ]
        for match in re.finditer(r"(\w+):\s*\[(.*?)\]", block.group(1))
    }


class TestFrontendBackendContract:
    def test_next_status_matches_backend_transitions(self):
        """กันไม่ให้ dropdown ในหน้าเว็บหลุดจากกฎของ backend"""
        frontend = read_frontend_status_map()
        backend = {
            status.value: sorted(next_values)
            for status, next_values in ALLOWED_TRANSITIONS.items()
        }
        for status_value, allowed in backend.items():
            assert set(frontend.get(status_value, [])) == set(allowed), status_value

    def test_frontend_labels_cover_every_status(self):
        source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        for status_value in ALLOWED_TRANSITIONS:
            assert f'{status_value}: "' in source, f"ไม่มี label สำหรับสถานะ {status_value}"


class TestSettingsLoading:
    def test_blank_secret_key_is_treated_as_unset(self):
        """คัดลอก .env.example มาเป็น .env ต้องรันได้ แม้ SECRET_KEY ว่าง"""
        from app.config import Settings

        assert Settings(_env_file=None, secret_key="").secret_key is None
        assert Settings(_env_file=None, secret_key="   ").secret_key is None

    def test_short_secret_key_is_rejected(self):
        from pydantic import ValidationError

        from app.config import Settings

        with pytest.raises(ValidationError):
            Settings(_env_file=None, secret_key="too-short")


class TestPasswordHashing:
    def test_roundtrip(self):
        encoded = hash_password("s3cret!", rounds=1_000)
        assert verify_password("s3cret!", encoded) is True
        assert verify_password("wrong", encoded) is False

    def test_salt_is_random_per_hash(self):
        a = hash_password("same-password", rounds=1_000)
        b = hash_password("same-password", rounds=1_000)
        assert a != b, "hash ต้องต่างกันเพราะใช้ salt สุ่มใหม่"

    def test_encoded_format(self):
        algorithm, rounds, salt, digest = hash_password("x", rounds=1_000).split("$")
        assert algorithm == "pbkdf2_sha256"
        assert int(rounds) == 1_000
        assert salt and digest

    @pytest.mark.parametrize("bad", ["", "not-a-hash", "md5$1$2$3", None, 123])
    def test_verify_rejects_garbage_without_raising(self, bad):
        assert verify_password("x", bad) is False


class TestSigning:
    def test_roundtrip(self):
        assert unsign(sign("hello")) == "hello"

    def test_tampered_value_is_rejected(self):
        signed = sign("hello")
        assert unsign(signed.replace("hello", "hell0")) is None


class TestMoney:
    @pytest.mark.parametrize(
        ("amount", "expected"),
        [("10.50", 1050), ("0.01", 1), ("0.10", 10), ("0", 0)],
    )
    def test_to_cents(self, amount, expected):
        assert to_cents(Decimal(amount)) == expected

    def test_to_decimal(self):
        assert to_decimal(1050) == Decimal("10.50")
        assert to_decimal(1) == Decimal("0.01")

    def test_roundtrip_avoids_float_error(self):
        assert to_cents(parse_amount("0.30")) == 30
        assert to_decimal(to_cents(Decimal("0.30"))) == Decimal("0.30")

    def test_parse_amount_quantizes_to_two_places(self):
        assert parse_amount("10.567") == Decimal("10.57")

    def test_parse_amount_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_amount("not-a-number")
