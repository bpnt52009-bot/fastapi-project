"""เงิน: เก็บเป็นจำนวนเต็ม (สตางค์) และคำนวณด้วย Decimal เพื่อไม่ให้เพี้ยนทศนิยม"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO_PLACES = Decimal("0.01")


def to_cents(amount: Decimal) -> int:
    """แปลง Decimal เป็นสตางค์ (int) โดยปัดทศนิยมครึ่งขึ้น"""
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal(cents: int) -> Decimal:
    """แปลงสตางค์กลับเป็น Decimal ที่มีทศนิยม 2 ตำแหน่ง"""
    return (Decimal(cents) / 100).quantize(TWO_PLACES)


def parse_amount(raw: object) -> Decimal:
    """อ่านค่าจำนวนเงินจาก string/Decimal แล้วบังคับให้มีทศนิยมไม่เกิน 2 ตำแหน่ง"""
    try:
        amount = Decimal(str(raw)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"ราคาไม่ถูกต้อง: {raw!r}") from exc
    return amount
