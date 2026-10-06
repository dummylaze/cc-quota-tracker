"""帳號標籤、倒數、絕對時間、讀數年齡、金額的格式：終端機與視窗兩個畫面層共用。"""
from datetime import datetime, timedelta
from typing import Optional

from .board import (WRITEBACK_ATTEMPTS, Board, CountdownFormat, Money, Role, SwitchRefusal, SwitchResult, SwitchStep,
                    WatchOnlyReason)
from .i18n import text


_WATCH_ONLY_REASONS = {WatchOnlyReason.EXPIRED: "watch_only.reason.expired",
                       WatchOnlyReason.INVALID: "watch_only.reason.invalid",
                       WatchOnlyReason.WRITEBACK_RETRYING: "watch_only.reason.writeback_retrying",
                       WatchOnlyReason.WRITEBACK_STOPPED: "watch_only.reason.writeback_stopped",
                       WatchOnlyReason.NO_ACCOUNT_INFO: "watch_only.reason.no_account_info"}


def watch_only_reason(reason: WatchOnlyReason, lang: str, failures: Optional[int] = None) -> str:
    """僅監看帳號不能切換的原因：卡片與 list 共用同一組字樣。failures 是寫回重試中已失敗的次數。"""
    return text(lang, _WATCH_ONLY_REASONS[reason], failures=failures, attempts=WRITEBACK_ATTEMPTS)


def snapshot_expiry(expires: datetime, now: datetime, fmt: CountdownFormat, lang: str) -> str:
    """只是告知的到期資訊：「憑證快照已過期（…）」或「憑證快照 n 後到期（…）」，不帶補救。"""
    when = absolute(expires, now)
    if expires <= now:
        return text(lang, "snapshot.expired", when=when)
    return text(lang, "snapshot.expires_in", left=countdown(expires - now, fmt, lang), when=when)


def account_label(account_key: str) -> str:
    """畫面上只顯示帳號標籤：帳號鍵是「供應商:帳號標籤」。"""
    return account_key.split(":", 1)[1]


def switch_confirmation(board: Board, label: str, lang: str) -> str:
    """切換前要使用者確認的內容，段落以空行隔開：目標標籤、目標憑證快照的到期倒數、後果說明（當前憑證帳號是監看帳號
    或未監看帳號），當前憑證帳號的快照已失效時多一段。只依看板的帳號狀態，不帶任何額度數字。"""
    assert board.as_of is not None  # 核心的看板一定帶這一輪的時間
    paragraphs = [text(lang, "dialog.switch_confirm", label=label)]
    target = next((c for c in board.cards if c.account_key and account_label(c.account_key) == label), None)
    if target is not None and target.snapshot_expires_at is not None:
        paragraphs.append(snapshot_expiry(target.snapshot_expires_at, board.as_of, board.countdown_format, lang))
    current = board.cards[0]
    if current.role is Role.UNWATCHED:
        paragraphs.append(text(lang, "dialog.switch_unwatched"))
    else:
        assert current.account_key is not None  # 當前憑證帳號是監看帳號才有帳號鍵
        paragraphs.append(text(lang, "dialog.switch_watched", label=account_label(current.account_key)))
    if current.snapshot_invalid:
        paragraphs.append(text(lang, "dialog.switch_invalid"))
    return "\n\n".join(paragraphs)


_SWITCH_REFUSALS = {
    SwitchRefusal.ALREADY_ACTIVE: "switch.refused.already_active",
    SwitchRefusal.SYNC_FAILED: "switch.refused.sync_failed",
    SwitchRefusal.UNREADABLE: "switch.refused.unreadable",
    SwitchRefusal.UNWRITABLE: "switch.refused.unwritable",
}


def switch_refusal(result: SwitchResult, label: str, lang: str) -> str:
    """切換被拒絕的原因（沒寫任何檔）：視窗與命令列共用同一組字樣。"""
    assert result.refusal is not None  # 拒絕一定帶原因
    if result.refusal is SwitchRefusal.UNKNOWN_LABEL:
        return text(lang, "error.unknown_label", label=label)
    if result.watch_only_reason is not None:
        reason = watch_only_reason(result.watch_only_reason, lang, result.writeback_failures)
        return text(lang, "switch.refused.watch_only", label=label, reason=reason)
    return text(lang, _SWITCH_REFUSALS[result.refusal], label=label)


_SWITCH_STEPS = {SwitchStep.SYNC: "switch.step.sync", SwitchStep.QUERY_OLD: "switch.step.query_old",
                 SwitchStep.WRITE: "switch.step.write", SwitchStep.QUERY_NEW: "switch.step.query_new"}


def switch_step(step: SwitchStep, label: str, lang: str) -> str:
    """切換中的圖層顯示的步驟；label 是切換的目標帳號標籤，只有寫入那一步用到。"""
    return text(lang, _SWITCH_STEPS[step], label=label)


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
