"""把看板渲染成終端機文字；所有文案都在這一層套用，語系由呼叫端指定（i18n）。"""
from . import COMMAND
from .board import Board, Card, Limit, ReadingState, Role
from .core import AddWarning
from .fmt import absolute, account_label, age, countdown, date_time, money, until
from .i18n import ZH_TW, text

_WINDOW_NAMES = {"session": "window.session", "weekly_all": "window.weekly_all", "weekly_scoped": "window.weekly_scoped"}
_ROLES = {Role.ACTIVE: "role.active", Role.STANDBY: "role.standby"}
_ADD_WARNINGS = {AddWarning.LABEL_LOOKS_LIKE_EMAIL: "add_warning.label_looks_like_email",
                 AddWarning.PERMISSIONS_FIXED: "add_warning.permissions_fixed"}
# 讀不到帳號識別碼的說明依入口不同：命令列、右鍵選單的納管、匯入憑證檔
_NOT_BOUND = {"cli": "add_warning.not_bound.cli", "menu": "add_warning.not_bound.menu",
              "import": "add_warning.not_bound.import"}


def add_warning(lang: str, warning: AddWarning, via: str) -> str:
    """納管帳號的提醒：命令列與視窗共用。via 是入口（cli、menu、import），只有 NOT_BOUND 的說明依入口而異。"""
    return text(lang, _NOT_BOUND[via]) if warning is AddWarning.NOT_BOUND else text(lang, _ADD_WARNINGS[warning])


def render(board: Board, lang: str = ZH_TW) -> str:
    """lang 的預設值只給不在意語系的呼叫端（測試）；命令列一律明確傳入。"""
    lines = [_render_card(c, board, lang) for c in board.cards]
    if board.schema_changed:
        key = "list.schema_changed" if board.last_reading_at else "list.schema_changed_none"
        lines.insert(0, text(lang, "notice", text=text(lang, key, time=date_time(board.last_reading_at, lang))))
    if board.wrong_location_suspected:
        lines.insert(0, text(lang, "notice", text=text(lang, "board.wrong_location")))
    if board.invalid_settings:
        fields = text(lang, "sep.item").join(board.invalid_settings)
        lines.insert(0, text(lang, "notice", text=text(lang, "settings.invalid", fields=fields)))
    if board.settings_unreadable:
        lines.insert(0, text(lang, "notice", text=text(lang, "settings.unreadable")))
    if any(c.lagging or c.reading_state is ReadingState.PENDING for c in board.cards):
        lines.append(text(lang, "list.query_hint", command=COMMAND))
    labels = [account_label(key) for key in board.managed_accounts]
    lines.append(text(lang, "list.managed", labels=text(lang, "sep.item").join(labels)) if labels
                 else text(lang, "list.none_managed"))
    return "\n".join(lines)


def _render_card(card: Card, board: Board, lang: str) -> str:
    body = _body(card, board, lang)
    expires = card.snapshot_expires_at
    label = account_label(card.account_key) if card.account_key else None
    if expires is not None:
        when = absolute(expires, board.as_of)
        if expires <= board.as_of:
            when = text(lang, "snapshot.expired", when=when)
        else:
            left = countdown(expires - board.as_of, board.countdown_format, lang)
            when = text(lang, "snapshot.expires_in", left=left, when=when)
        if card.snapshot_expiring:
            body.insert(0, text(lang, "snapshot.relogin", when=when, command=COMMAND, label=label))
        else:
            body.append(when)
    if card.snapshot_invalid:
        body.insert(0, text(lang, "list.snapshot_invalid", command=COMMAND, label=label))
    return "\n".join([_header(card, lang)] + ["  " + line for line in body])


def _header(card: Card, lang: str) -> str:
    if card.role is Role.UNMANAGED:
        return text(lang, "list.header_unmanaged", command=COMMAND)
    return text(lang, "list.header", role=text(lang, _ROLES[card.role]), label=account_label(card.account_key))


def _body(card: Card, board: Board, lang: str) -> list:
    if card.reading_state is ReadingState.NO_READING:
        return [text(lang, "reading.none" if card.role is Role.STANDBY else "reading.none_soon")]
    if card.reading_state is ReadingState.PENDING:
        return [text(lang, "reading.pending")]
    if card.role is Role.STANDBY:
        lines = [text(lang, "list.observed", age=age(card.reading_age, lang))]
    else:
        lines = [text(lang, "list.reading_age", age=age(card.reading_age, lang))]
        if card.lagging:
            lines.append(text(lang, "reading.lagging"))
    if card.locked_reason:
        lines.append(text(lang, "reading.locked", reason=card.locked_reason))
    lines += [_limit_line(lim, board, lang) for lim in card.limits + card.scoped_limits]
    if card.other_limits:
        lines.append(text(lang, "list.other_limits"))
        lines += ["  " + _limit_line(lim, board, lang) for lim in card.other_limits]
    if card.weekly_breakdown:
        b = card.weekly_breakdown
        lines.append(text(lang, "list.breakdown", start=date_time(b.started_at, lang), end=date_time(b.ends_at, lang)))
        lines += [f"  {row.label}  {row.percent}%" for row in b.rows]
    if card.extra_usage:
        e = card.extra_usage
        lines.append("  ".join((text(lang, "extra_usage"), f"{money(e.used)} / {money(e.limit)}")))
    if card.spend:
        s = card.spend
        lines.append("  ".join((text(lang, "spend"), f"{money(s.used)} / {money(s.limit)}")))
    return lines


def _limit_line(lim: Limit, board: Board, lang: str) -> str:
    name = text(lang, _WINDOW_NAMES[lim.kind]) if lim.kind in _WINDOW_NAMES else lim.kind  # 不認得的種類用供應商的原始名稱
    if lim.scope:
        name = text(lang, "limit.scoped", name=name, scope=lim.scope)
    if lim.reset:
        return "  ".join((name, text(lang, "limit.reset")))
    value = text(lang, "limit.no_open_window") if lim.percent is None else f"{lim.percent}%"
    when = until(lim.resets_at, board.as_of, board.countdown_format, lang) if lim.resets_at else text(lang, "common.unknown")
    line = "  ".join((name, value, text(lang, "limit.resets", when=when)))
    if lim.dollars and lim.dollars.used is not None:
        line += "  " + text(lang, "limit.dollars_used", used=f"{lim.dollars.used:g}")
    return line
