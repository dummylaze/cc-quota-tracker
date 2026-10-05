"""帳號標籤、倒數、絕對時間、讀數年齡、金額的格式：終端機與視窗兩個畫面層共用。"""
from datetime import datetime, timedelta
from typing import Optional

from .board import CountdownFormat, Money, WatchOnlyReason
from .i18n import text


_WATCH_ONLY_REASONS = {WatchOnlyReason.EXPIRED: "watch_only.reason.expired",
                       WatchOnlyReason.INVALID: "watch_only.reason.invalid",
                       WatchOnlyReason.NO_ACCOUNT_INFO: "watch_only.reason.no_account_info"}


def watch_only_reason(reason: WatchOnlyReason, lang: str) -> str:
    """僅監看帳號不能切換的原因：卡片與 list 共用同一組字樣。"""
    return text(lang, _WATCH_ONLY_REASONS[reason])


def snapshot_expiry(expires: datetime, now: datetime, fmt: CountdownFormat, lang: str) -> str:
    """只是告知的到期資訊：「憑證快照已過期（…）」或「憑證快照 n 後到期（…）」，不帶補救。"""
    when = absolute(expires, now)
    if expires <= now:
        return text(lang, "snapshot.expired", when=when)
    return text(lang, "snapshot.expires_in", left=countdown(expires - now, fmt, lang), when=when)


def account_label(account_key: str) -> str:
    """畫面上只顯示帳號標籤：帳號鍵是「供應商:帳號標籤」。"""
    return account_key.split(":", 1)[1]


def until(when: datetime, now: datetime, fmt: CountdownFormat, lang: str, short: bool = False) -> str:
    """倒數＋絕對時間，例如「2小時15分後（14:00）」。short 是窄欄位用的寫法（中文不帶「後」）。"""
    return text(lang, "until.short" if short else "until", countdown=countdown(when - now, fmt, lang), when=absolute(when, now))


def countdown(left: timedelta, fmt: CountdownFormat, lang: str) -> str:
    """兩個單位，不足的部分一律捨去、不進位：剩一天以上是「天＋時」（或天數到小數第 1 位），不到一天是「時＋分」。"""
    seconds = int(left.total_seconds())
    days, rest = divmod(seconds, 86400)
    hours, minutes = rest // 3600, rest % 3600 // 60
    if days and fmt is CountdownFormat.DECIMAL_DAYS:
        tenths = seconds * 10 // 86400
        return text(lang, "countdown.decimal_days", value=f"{tenths // 10}.{tenths % 10}")
    if days:
        return text(lang, "countdown.days_hours", days=days, hours=hours)
    if hours:
        return text(lang, "countdown.hours_minutes", hours=hours, minutes=minutes)
    return text(lang, "countdown.minutes", minutes=minutes)


def absolute(when: datetime, now: datetime) -> str:
    """24 小時內只顯示時刻，更遠的加上月日；不顯示年份。"""
    local = when.astimezone()
    return local.strftime("%H:%M" if abs(when - now) < timedelta(days=1) else "%m-%d %H:%M")


def date_time(value: Optional[datetime], lang: str) -> str:
    """完整的本地日期時間（含年份）；沒有值就是「未知」。"""
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else text(lang, "common.unknown")


def age(value: timedelta, lang: str) -> str:
    minutes = int(value.total_seconds() // 60)
    if minutes < 60:
        return text(lang, "age.minutes", n=minutes)
    if minutes < 60 * 24:
        return text(lang, "age.hours", n=minutes // 60)
    return text(lang, "age.days", n=minutes // (60 * 24))


def money(value: Optional[Money]) -> str:
    if value is None:
        return "—"
    amount = value.minor / 10 ** value.exponent
    return f"{amount:.{value.exponent}f} {value.currency or ''}".rstrip()
