from decimal import Decimal, ROUND_HALF_UP

exp = Decimal('1e-8')


def normalize_money(money):
    if money == money.to_integral_value():
        return money.quantize(Decimal(1))
    else:
        return money.quantize(exp, rounding=ROUND_HALF_UP).normalize()
