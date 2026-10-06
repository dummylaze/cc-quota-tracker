"""English locale file. Keys and placeholders must match zh_tw.py."""
STRINGS = {
    # Time: countdown, reading age
    "countdown.days_hours": "{days}d {hours}h",
    "countdown.decimal_days": "{value}d",
    "countdown.hours_minutes": "{hours}h {minutes}m",
    "countdown.minutes": "{minutes}m",
    "until": "in {countdown} ({when})",
    "until.short": "in {countdown} ({when})",
    "age.minutes": "{n} min ago",
    "age.hours": "{n} h ago",
    "age.days": "{n} d ago",
    "age.observed": "Observed {age}",
    "age.reading": "Reading {age}",
    "common.unknown": "unknown",
    "sep.item": ", ",
    "sep.clause": ", ",

    # Accounts and roles
    "role.active": "Active",
    "role.standby": "Standby",
    "account.unwatched": "Unwatched account",
    "account.added": "Managed \"{label}\"",
    "account.removed": "Removed \"{label}\"",
    "account.imported": "Imported \"{label}\"",

    # Limits and windows
    "window.session": "Session window",
    "window.weekly_all": "Weekly window",
    "window.weekly_scoped": "Weekly limit",
    "window.session_short": "Session",
    "window.weekly_all_short": "Week",
    "limit.scoped": "{name} ({scope})",
    "limit.reset": "Reset, next reset time unknown",
    "limit.reset_short": "Reset",
    "limit.next_reset_unknown": "Next reset time unknown",
    "limit.no_open_window": "No open window",
    "limit.resets": "Resets: {when}",
    "limit.dollars_used": "Used ${used}",
    "week.span": "Week {start} – {end}",
    "week.passed": "{percent}% elapsed",
    "breakdown.title": "Where this week's usage went",
    "extra_usage": "Extra usage",
    "spend": "Spend",
    "others.title": "{arrow} Other limits ({count})",
    "table.account": "Account",
    "table.reading": "Reading",
    "table.credential_expiry": "Snapshot expires",
    "expiry.invalid": "Invalid",
    "expiry.expired": "Expired ({when})",
    "notes.count": "Notes: {count}",

    # Notes on a card
    "reading.none": "No reading yet",
    "reading.none_soon": "No reading yet; it will appear once Claude Code updates its usage cache",
    "reading.pending": "Reading pending; it will appear once Claude Code updates its usage cache",
    "reading.pending_short": "Reading pending",  # used when the Update entry sits beside it, so it stays on one line
    "reading.lagging": "New activity; usage not updated",
    "reading.lagging_before_switch": "Lagging before the switch",  # standby account: this reading was already lagging when it was switched away from
    "reading.locked": "Usage locked: {reason}",
    "note.observed": "Observed value: only accurate if this account hasn't been used since; "
                     "use on another machine isn't visible here",
    "note.how_to_manage": "This account isn't managed yet: after signing in to it in Claude Code, run "
                          "{command} add <label>, or right-click the window and choose "
                          "\"Manage the signed-in account…\"",
    "note.named": "{label}: {text}",
    "note.watch_only": "Watch-only account ({reason}): sign in to this account in Claude Code, then manage it again",  # reason is watch_only.reason.*
    "note.writeback_retrying": "Couldn't write back the credential snapshot, retrying automatically {failures}/{attempts}",
    "note.writeback_stopped": "couldn't write back the credential snapshot, stopped retrying",  # reason of note.watch_only on cards
    "snapshot.expired": "Credential snapshot expired ({when})",
    "snapshot.expires_in": "Credential snapshot expires in {left} ({when})",
    "snapshot.relogin": "{when}: sign in to this account again in Claude Code, then run {command} add {label}",
    "snapshot.renew": "{when}; renew it",

    # Banner
    "settings.invalid": "The values of {fields} in the settings file are invalid, so defaults are used for them; "
                        "see the field descriptions in the README to fix them.",
    "settings.unreadable": "The settings file can't be read (it isn't valid JSON), so everything in it is treated as "
                           "unset; this tool won't overwrite it — fix it and try again.",
    "font.missing": "The font \"{font}\" set in the settings file isn't installed on this computer; "
                    "the system default font is used instead.",
    "banner.restart_required": "A path field in the settings file changed; paths are only read at startup, "
                               "so restart this tool for it to take effect.",
    "banner.permissions_untightened": "The managed directory's permissions can't be restricted. Move it to an NTFS "
                                      "drive (the usual C: or D: drive) to clear this.",
    "board.wrong_location": "Claude Code's usage cache wasn't found at the default location, so it may be reading the "
                            "wrong place. If the Claude Code directory isn't under home (for example "
                            "CLAUDE_CONFIG_DIR is set), specify it in claudeConfigDir in the settings file.",
    "banner.schema_changed": "The usage cache structure has changed and this tool can't read the new structure; "
                             "below is the last successful reading ({when}, {age})",
    "banner.schema_changed_none": "The usage cache structure has changed and this tool can't read the new structure; "
                                  "there is no successful reading yet",
    "banner.stalled": "Board stopped updating: an error occurred while reading; last successful reading: ({when}, {age})",
    "banner.stalled_none": "Board stopped updating: an error occurred while reading; there is no successful reading yet",

    # Text output of list
    "notice": "Note: {text}",
    "list.header": "[{role}] {label}",
    "list.header_unwatched": "[Active] Unwatched account (to manage it: sign in to this account in Claude Code, "
                             "then run {command} add <label>)",
    "list.reading_age": "Reading age: {age}",
    "list.observed": "Last observed: {age} (observed value: only accurate if this account hasn't been used since)",
    "list.other_limits": "Other limits:",
    "list.breakdown": "Where this week's usage went ({start} – {end}):",
    "list.watched": "Watched accounts: {labels}",
    "list.none_watched": "No accounts managed yet",
    "list.watch_only": "Watch-only account: {reason}",
    "list.watch_only_remedy": "To manage it again: sign in to this account in Claude Code, then run {command} add {label}",
    "watch_only.reason.expired": "expired",
    "watch_only.reason.invalid": "no longer valid",
    "watch_only.reason.no_account_info": "no account info",
    "watch_only.reason.writeback_retrying": "write-back failed (retrying {failures}/{attempts})",
    "watch_only.reason.writeback_stopped": "write-back failed (stopped retrying)",
    "list.schema_changed": "The usage cache structure has changed and this tool can't read the new structure; "
                           "the last successful reading follows ({time})",
    "list.schema_changed_none": "The usage cache structure has changed and this tool can't read the new structure; "
                                "there is no successful reading yet",
    "list.query_hint": "Reading is lagging or pending: run {command} query to ask Claude Code for the latest usage, "
                       "or run /usage in Claude Code.",

    # Results and errors of managing accounts: shared by the command line and the window
    "add_warning.label_looks_like_email": "Note: this account label looks like an email address, and it is shown "
                                          "on screen. If you'd rather not show it, manage the account again with "
                                          "another label, or rename the credential snapshot file.",
    "add_warning.permissions_fixed": "Warning: the permissions of the managed directory or a file in it were not as "
                                     "expected (accessible to others, or inherited from the parent directory); "
                                     "they have been fixed so only the current user can access them.",
    "add_warning.permissions_untightened": "Warning: the managed directory's permissions can't be restricted. Move it "
                                           "to an NTFS drive (the usual C: or D: drive) to clear this.",
    "add_warning.not_bound.cli": "Warning: couldn't read the ID of the account Claude Code is signed in to, so this "
                                 "credential snapshot isn't bound to an account yet; until that account becomes the "
                                 "active account it only shows \"Reading pending\". You can run add again later.",
    "add_warning.not_bound.menu": "Couldn't read the ID of the account Claude Code is signed in to, so this credential "
                                  "snapshot isn't bound to an account yet; until that account becomes the active "
                                  "account it only shows \"Reading pending\". You can try again later from the "
                                  "right-click menu \"Manage the signed-in account…\".",
    "add_warning.not_bound.import": "This credential snapshot isn't bound to an account yet: once you sign in to this "
                                    "account in Claude Code and it becomes the active account, this tool binds it "
                                    "automatically; until then it only shows \"Reading pending\".",
    "error.invalid_label": "The account label \"{label}\" can't be used as a file name: it can't be blank, can't start "
                           "or end with a dot, and can't contain < > : \" / \\ | ? * or a device name "
                           "(such as CON or NUL)",
    "error.no_credential": "Couldn't read the current sign-in credential. Sign in to the account you want to manage "
                           "in Claude Code first, then run this again.",
    "error.not_a_credential_file": "This file isn't a Claude Code credential file (no refreshToken under "
                                   "claudeAiOauth); nothing was imported.",
    "error.unknown_label": "There is no watched account with the label \"{label}\".",
    "error.bindings_unreadable": "Couldn't read the bindings file ({path}) right now; another program (such as "
                                 "antivirus software) may have it locked. No credential snapshot was changed. "
                                 "Try again in a moment.",

    # Right-click menu and dialogs
    "menu.layout": "Layout",
    "menu.topmost": "Always on top",
    "menu.mode": "Mode",
    "menu.language": "Language",
    "menu.theme": "Theme",
    "menu.opacity": "Opacity",
    "menu.autostart": "Start at login",
    "menu.query": "Query usage",
    "menu.auto_query": "Auto-query usage",
    "menu.add": "Manage the signed-in account…",
    "menu.import": "Import credential file…",
    "menu.open_folder": "Open folder",
    "menu.open_managed_dir": "Managed directory",
    "menu.open_settings_dir": "Settings directory",
    "menu.dismiss_untightened": "Stop warning about unrestricted permissions",
    "menu.quit": "Quit",
    "menu.switch": "Switch account",
    "menu.switch_none": "(No account to switch to)",
    "layout.cards": "Card list",
    "layout.table": "Dense table / one-line strip",
    "layout.ring": "Ring gauge",
    "mode.compact": "Compact",
    "mode.expanded": "Expanded",
    "theme.system": "Follow system",
    "theme.light": "Light",
    "theme.dark": "Dark",
    "language.system": "Follow system",
    "dialog.switch_title": "Switch account",
    "dialog.switch_confirm": "Switch to \"{label}\"?",
    "dialog.switch_watched": "The current account \"{label}\" is a watched account: its credential is synced to its "
                             "snapshot before switching.",
    "dialog.switch_unwatched": "The current account is an unwatched account: its credential is only saved as the "
                               "pre-switch credential, and only the latest copy is kept.",
    "dialog.switch_invalid": "The current account's snapshot is invalid; use \"Restore previous switch\", or sign in "
                             "again in Claude Code and then re-manage it.",
    "dialog.switch_failed": "The switch hit an error and did not complete: {error}",
    "dialog.label_prompt": "Account label (shown on screen, and also the credential snapshot's file name):",
    "dialog.import_title": "Import credential file",
    "dialog.all_files": "All files",
    "dialog.confirm_replace": "There is already an account labeled \"{label}\". "
                              "Replace its credential snapshot with this file?",
    "dialog.managed_dir_missing": "The managed directory doesn't exist yet: {directory}\n"
                                  "It is created when you manage the first account.",
    "dialog.settings_dir_missing": "The settings directory doesn't exist yet: {directory}\n"
                                   "It is created the first time the tool starts.",
    "dialog.autostart_failed": "Couldn't change start at login: {error}",
    "dialog.auto_query_unreadable": "The settings file can't be read, or its content isn't valid settings.\n"
                                    "The auto-query switch is unchanged.",
    "dialog.auto_query_malformed": "providers or providers.claude in the settings file isn't an object.\n"
                                   "The auto-query switch is unchanged.",
    "dialog.auto_query_write_failed": "Couldn't write the settings file: {error}\nThe auto-query switch is unchanged.",

    # Command line
    "cli.usage": "Usage:\n"
                 "  {command} add <label>     manage the account Claude Code is signed in to; "
                 "re-manage if the label exists\n"
                 "  {command} remove <label>  remove a watched account\n"
                 "  {command} list            print the board\n"
                 "  {command} check           check that Claude Code's usage cache structure is still compatible "
                 "with this tool, and list the directories actually used\n"
                 "  {command} query           ask Claude Code for the latest usage once and wait for it; "
                 "exit code 0 on success, 1 on failure\n"
                 "  {command} gui             open the floating window; run with pythonw to avoid a console window\n"
                 "  {command} switch <label> --yes\n"
                 "                            switch to this managed account; --yes switches without asking again.\n"
                 "                            Exit code 0 on success, 1 if refused (nothing written), 3 if written but "
                 "the usage check failed or only partly written, 2 without --yes",
    "switch.done": "Switched to \"{label}\"",
    "switch.step.sync": "Syncing the current credential…",
    "switch.step.query_old": "Querying usage for the old account…",
    "switch.step.write": "Writing the credential of \"{label}\"…",
    "switch.step.query_new": "Querying usage for the new account…",
    "switch.refused.watch_only": "\"{label}\" is a watch-only account ({reason}) and can't be switched to: sign in to "
                                 "this account in Claude Code, then manage it again",
    "switch.refused.already_active": "\"{label}\" is already the active account.",
    "switch.refused.sync_failed": "Couldn't sync the current account's credential back to its snapshot, so nothing "
                                  "was switched. Try again later.",
    "switch.refused.unreadable": "Couldn't read the current credential or Claude Code's account info, so nothing was "
                                 "switched. Try again later.",
    "switch.refused.unwritable": "Couldn't write the current credential or the pre-switch credential (another "
                                 "program may have it locked), so nothing was switched. Try again later.",
    "switch.write_failed": "Wrote the credential of \"{label}\", but couldn't update Claude Code's account info, so "
                           "the two don't match: sign in again in Claude Code.",
    "switch.verify_failed": "Switched to \"{label}\", but the usage query for it failed, so the switch couldn't be "
                            "confirmed: {reason}",
    "query.success": "Usage updated. Latest observed time: {time}",
    "query.failed": "Usage query failed: {reason}\nYou can run /usage in Claude Code instead.",
    "query.reason.command_not_found": "Couldn't find the claude executable. Make sure it is on PATH, or set the full "
                                      "path in providers.claude.claudeCommand in the settings file.",
    "query.reason.timeout": "Claude Code timed out before finishing the query.",
    "query.reason.reported_error": "Claude Code reported an error: {message}",  # the original message, never translated
    "query.reason.reported_error_no_message": "Claude Code reported an error without a message.",
    "query.reason.not_written": "Claude Code finished, but the usage cache wasn't updated.",
    # Usage query on a card: the entry and its status
    "query.entry": "Update",
    "query.entry_busy": "Updating…",
    "query.note.failed": "Update failed: {reason}. Try /usage in Claude Code instead",
    "query.note.command_not_found": "claude command not found",
    "query.note.timeout": "Claude Code timed out",
    "query.note.reported_error": "Claude Code reported \"{message}\"",  # the original message, never translated
    "query.note.reported_error_no_message": "Claude Code reported an error",
    "query.note.not_written": "Claude Code didn't update the usage cache",
    "query.note.auto_paused": "Auto-query paused: {reason}. A successful manual update resumes it",
    "banner.auto_query_floor": "providers.claude.autoUsageQueryMinutes is below the minimum; running every {minutes} minutes",
    "cli.settings_file_location": "Settings file: {path}",
    "path.not_absolute": "{field} in the settings file must be a full absolute path; write null to leave it unset.",
    "path.not_a_directory": "The directory {field} in the settings file points to doesn't exist. This tool won't "
                            "fall back to the default location, so it can't read another set of accounts by mistake.",
    "path.inside_claude_dir": "The managed directory can't be inside Claude Code's directory (this tool never writes "
                              "there); set {field} in the settings file to another location.",

    # The check command
    "check.claude_dir": "Claude Code directory: {path} ({source})",
    "check.usage_cache": "Usage cache: {path}",
    "check.managed_dir": "Managed directory: {path} ({source})",
    "check.managed_permissions": "Managed directory permissions: {state}",
    "check.permissions.tightened": "restricted",
    "check.permissions.untightened": "not restricted",
    "check.permissions.not_created": "not created yet",
    "check.settings_file": "Settings file: {path}",
    "check.source.settings_file": "{field} in the settings file",
    "check.source.env": "environment variable {name}",
    "check.source.default": "default",
    "check.not_found": "Couldn't find {path}, so nothing can be checked. Make sure the Claude Code directory is "
                       "right, and that you've signed in with Claude Code at least once.",
    "check.unreadable": "Couldn't read {path}: {reason}",
    "check.no_reading": "No reading yet: the usage cache doesn't exist, so nothing can be checked. Use Claude Code "
                        "once, wait for it to write the usage cache, then run this again.",
    "check.incomplete": "The file is being written by Claude Code and is incomplete. Please run this again shortly.",
    "check.fields_header": "Fields depended on:",
    "check.field_line": "  [{status}] {path} ({expected})",
    "check.optional": "{type}, optional",
    "check.wrong_type": "{status}: actually {actual}",
    "check.new_fields_header": "New fields (under utilization, appeared after the measured baseline):",
    "check.limit_shaped": " (limit-shaped; the board shows it as an other limit)",
    "check.no_new_fields": "none",
    "check.unparseable": "The parser can't parse this usage cache: dependencies not in the list above also don't "
                         "match, and the board treats it as a schema mismatch.",
    "check.result_compatible": "Result: compatible",
    "check.result_failures": "Result: incompatible, {count} fields don't match",
    "check.result_unparseable": "Result: incompatible, the parser can't parse it",
    "type.object": "object",
    "type.list": "list",
    "type.string": "string",
    "type.number": "number",
    "type.boolean": "boolean",
    "type.null": "null",
    "status.ok": "ok",
    "status.missing": "missing",
    "status.wrong_type": "wrong type",
    "status.absent": "optional, absent",
    "status.no_items": "list is empty, nothing to check",
    "status.unreachable": "parent doesn't match, nothing to check",
    "status.parent_absent": "parent absent, no check needed",
}
