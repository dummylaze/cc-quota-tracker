"""帳號標籤、倒數、絕對時間、讀數年齡、金額的格式：終端機與視窗兩個畫面層共用。"""
from datetime import datetime, timedelta
from typing import Optional

from .board import CountdownFormat, Money


def account_label(account_key: str) -> str:
    """畫面上只顯示帳號標籤：帳號鍵是「供應商:帳號標籤」。"""
    return account_key.split(":", 1)[1]


def until(when: datetime, now: datetime, fmt: CountdownFormat) -> str:
    """倒數＋絕對時間，例如「2小時15分後（14:00）」。"""
    return f"{countdown(when - now, fmt)}後（{absolute(when, now)}）"


def countdown(left: timedelta, fmt: CountdownFormat) -> str:
    """兩個單位，不足的部分一律捨去、不進位：剩一天以上是「天＋時」（或天數到小數第 1 位），不到一天是「時＋分」。"""
    seconds = int(left.total_seconds())
    days, rest = divmod(seconds, 86400)
    hours, minutes = rest // 3600, rest % 3600 // 60
    if days and fmt is CountdownFormat.DECIMAL_DAYS:
        tenths = seconds * 10 // 86400
        return f"{tenths // 10}.{tenths % 10}天"
    if days:
        return f"{days}天{hours}小時"
    return f"{hours}小時{minutes}分" if hours else f"{minutes}分"


def absolute(when: datetime, now: datetime) -> str:
    """24 小時內只顯示時刻，更遠的加上月日；不顯示年份。"""
    local = when.astimezone()
    return local.strftime("%H:%M" if abs(when - now) < timedelta(days=1) else "%m-%d %H:%M")


def age(value: timedelta) -> str:
    minutes = int(value.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} 分鐘前"
    if minutes < 60 * 24:
        return f"{minutes // 60} 小時前"
    return f"{minutes // (60 * 24)} 天前"


def money(value: Optional[Money]) -> str:
    if value is None:
        return "—"
    amount = value.minor / 10 ** value.exponent
    return f"{amount:.{value.exponent}f} {value.currency or ''}".rstrip()
