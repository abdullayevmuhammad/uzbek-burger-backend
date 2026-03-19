import re
from typing import Union

MoneyInput = Union[str, int, float]


def parse_uzs_amount(raw: MoneyInput) -> int:
    """
    Strictly parse UZS amounts into an integer number of so'm.
    - Accepts strings with spaces or commas as thousand separators.
    - Rejects decimals, negative numbers, or malformed inputs.
    """
    if raw is None:
        raise ValueError("Pul qiymati kiritilmagan.")

    # Short-circuit integers
    if isinstance(raw, bool):
        raise ValueError("Pul qiymati noto'g'ri.")
    if isinstance(raw, (int,)):
        if raw < 0:
            raise ValueError("Pul qiymati manfiy bo'la olmaydi.")
        return int(raw)
    if isinstance(raw, float):
        raise ValueError("Pul qiymati faqat butun son bo'lishi kerak.")

    text = str(raw).strip()
    if text == "":
        raise ValueError("Pul qiymati kiritilmagan.")

    # Accept either a plain integer or grouped thousands with spaces/commas.
    if not re.fullmatch(r"\d+", text) and not re.fullmatch(r"\d{1,3}(?P<sep>[ ,])\d{3}(?:(?P=sep)\d{3})*", text):
        raise ValueError("Pul qiymati faqat butun son bo'lishi kerak.")

    cleaned = re.sub(r"[ ,]", "", text)
    amount = int(cleaned)
    if amount < 0:
        raise ValueError("Pul qiymati manfiy bo'la olmaydi.")
    return amount
