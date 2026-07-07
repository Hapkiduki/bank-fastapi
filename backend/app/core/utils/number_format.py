from decimal import Decimal


def format_currency(amount: Decimal | float | str | int) -> str:
    try:
        decimal_amount = Decimal(str(amount))
        return f"{decimal_amount:,.2f}"
    except (ValueError, TypeError, AttributeError):
        return str(amount)


def parse_decimal(amount: str | float | int) -> Decimal:
    try:
        if isinstance(amount, str):
            amount = amount.replace(",", "")
        return Decimal(str(amount))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"Could not convert {amount} to Decimal") from None
