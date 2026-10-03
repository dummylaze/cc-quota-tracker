# cc-quota-tracker

English | [正體中文](README.zh-TW.md)

A small always-on-top desktop window (Windows) that shows how much quota each of your Claude accounts has left, all at once. Claude Code only shows the account you are logged into; this tool keeps the last reading of every other account you have set up, so you can see which one has room this week.

- **Compact mode**: the active account's session window and weekly window — progress bar and reading age; the reset countdown and credential expiry countdown depend on the layout (the card list shows both, the one-line strip shows the reset countdown, the ring gauge shows neither until expanded).
- **Expanded mode**: one card per managed account, the active one highlighted; standby accounts show their last observed reading and how old it is.
- **Query usage** (on request): when the active account's reading has fallen behind, one click asks Claude Code to look up the latest usage. See [Query usage](#query-usage).
- Three layouts (card list, dense table / one-line strip, ring gauge), light / dark / follow-system theme, adjustable opacity, Traditional Chinese or English interface.

**Everything comes from local files that Claude Code already maintains. By default the tool sends no requests and never changes Claude Code's settings (no statusLine, no hooks); it never writes to Claude Code's files itself. Only when you press the button, or turn on auto-query, does it ask Claude Code to look the usage up on its behalf.**

## Requirements

- Windows 10 or later
- Python 3.9 or later with `tkinter` (the standard python.org installer includes it). Standard library only — nothing to `pip install`.
- Claude Code, logged in at least once

This version is deployed from source. It is not packaged as an exe.

## Setup in three steps

1. **Put the code somewhere.** Clone or copy this repository to any folder. All commands below are run from that folder.
2. **Manage your accounts.** For each account: log in with Claude Code, then run

   ```
   python -m cc_quota_tracker add <label>
   ```

   See [Managing accounts](#managing-accounts).
3. **Start it.**

   ```
   pythonw -m cc_quota_tracker gui
   ```

   `pythonw` starts it without a console window. (`python -m cc_quota_tracker gui` works too, but keeps a console open.)

To have the window start when you log into Windows, use *Start at login* in the right-click menu (see [Window and menu](#window-and-menu)).

## Managing accounts

A managed account is one whose login credential you have handed over to this tool as a **credential snapshot**. The snapshots live in the managed directory (`~/.claude-multi/` by default), one file per account; the file name without `.json` is the **account label** shown on screen.

> The label is the only account name the tool ever displays. It never reads or shows your email address. If you pick a label that looks like an email, the tool warns you, because it will appear on screen (and in screenshots).

There are three ways in:

### 1. Command line

Log in to the account in Claude Code first, then:

```
python -m cc_quota_tracker add <label>
```

This copies the current credential into the managed directory and binds it to the account currently logged in, so the account is recognised immediately. Running `add` again with an existing label overwrites it — this is how you renew a credential snapshot that is about to expire or has become invalid.

Other commands:

```
python -m cc_quota_tracker remove <label>   # remove a managed account (its leftover data too)
python -m cc_quota_tracker list             # print the same information as the window, as text
python -m cc_quota_tracker query            # ask Claude Code for the latest usage (see "Query usage")
python -m cc_quota_tracker check            # see "For hosts" below
python -m cc_quota_tracker gui              # open the window
```

### 2. Right-click menu

Right-click the window:

- **Add the currently logged-in account…** asks for a label and does the same as `add`.
- **Import a credential file…** picks a credential file and copies it into the managed directory; the label defaults to the file name without `.json`.

### 3. Drop a file in

Copy a credential file into the managed directory yourself (right-click → *Open folder* → *Managed directory* gets you there), named `<label>.json`. Renaming a file renames the account label; the identity binding is kept.

**Limitation of dropping a file in (and of *Import*):** the file carries no account identifier, so the tool cannot tell which account's readings belong to it. Until that account has been your active account once and Claude Code has written a reading for it, its card shows **Reading pending** and nothing else. With `add` this does not happen, because it binds the account at the moment you run it.

### Permissions

The managed directory holds long-lived credentials for every account. `add` and *Import* restrict it to your Windows user only (inheritance removed) and check the result afterwards; if the permissions were not as expected, the tool fixes them and tells you. Credential snapshots are **not encrypted** — the protection is the file permissions, so treat the directory like `~/.claude` itself.

Some locations cannot restrict permissions at all — FAT32 and exFAT drives, common on USB sticks. If the managed directory is on one, the tool keeps working as usual and keeps warning you: a banner on the board, and a warning from `add` and *Import*. To silence the board banner, right-click → *Stop warning about unrestricted permissions*; it comes back if you switch to another managed directory, or if the permissions are once restricted successfully and later can't be again. The `add` and *Import* warnings are not affected. If you see the warning while the directory is already on NTFS, check that you are the owner of the directory.

## Two states that are not faults

| What you see | What it means |
|---|---|
| **Reading pending** (讀數待更新) | The active account has no reading of its own yet. Claude Code keeps only one account's reading at a time, so right after a switch the cached reading still belongs to the previous account, and the tool will not show it under the new one. It appears once Claude Code updates its cache (usually within seconds of logging in; otherwise on the next prompt or when its usage panel is open), or as soon as you press **Update** (see [Query usage](#query-usage)). |
| **Unmanaged account** (未納管帳號) | The account you are logged into has no credential snapshot here. The card tells you how to manage it. Nothing is wrong. |

Standby accounts show their **last observed** reading and how long ago that was (e.g. 3 天前). That reading is only accurate if the account has not been used since it was observed — if you used it on another machine, this machine cannot see that. Standby readings are never flagged as out of date just for being old. For the active account, an old reading is not flagged either unless there has been new conversation activity on this machine since the reading ("New activity; usage not updated"). If a reading was already flagged that way when you switched away from the account, its standby card keeps saying **Lagging before the switch** until a new reading for that account appears.

## Query usage

Every number comes from Claude Code's usage cache, and Claude Code only updates it at certain moments (when you run `/usage`, when you log in, …). While you keep chatting, the active account's reading falls behind — an hour or more is common — and the card says "New activity; usage not updated". **Query usage** asks Claude Code to look up the active account's latest usage and write it back to its cache; the tool then reads the cache as usual. The tool itself sends no request, never touches your token, and does not use the response to the query as a data source: success is judged only by whether the cache moved forward.

**Ways to start one**

- **The *Update* button** on the active account's card, next to the "New activity; usage not updated" or "Reading pending" note, in all three layouts. It appears only then. While the query runs it reads "Updating…", and for 30 seconds after a manual query (successful or not) it cannot be clicked, so you cannot hammer it. The right-click menu item shares that cooldown.
- **Right-click → Query usage**, any time except while a query is running or cooling down — for example when the reading is not flagged but you know you used the account somewhere else.
- **Command line**: `python -m cc_quota_tracker query` runs one query and waits for it. On success it prints the new observation time and exits with 0; on failure it prints the reason and exits with 1, so a script can tell. It has no cooldown (it is a separate process from the window). When a reading is lagging or pending, `list` also prints a line pointing to `query` and to `/usage`.
- **Auto-query**, off by default. Turn it on with right-click → *Auto-query usage* (kept after a restart). While on, the tool queries only when the active account's reading is lagging or pending, and never twice within one interval (`providers.claude.autoUsageQueryMinutes`, default 15 minutes, minimum 5). The interval counts from the later of the tool's last query and the reading's observation time, so a `/usage` you ran yourself counts as one. When you walk away and no new conversation appears, the reading stops being lagging, so auto-query makes at most one more query and then stops by itself; if a long task, a background sub-agent or a schedule is still running, it keeps going at the interval, because quota really is being used. After 3 failed auto-queries in a row it pauses, and the card shows "Auto-query paused" with the last reason; one successful manual update resumes it. After a single failure it waits a full interval before trying again. The pause state is kept in memory only, so restarting the tool starts it afresh.

**What it does.** The tool starts `claude` as a child process in print mode and sends the same request that Claude Code's own usage panel sends. The child always runs with `--settings '{"disableAllHooks":true}'`, so none of your Claude Code hooks (sounds, backups, reminders) fire. It runs no model, creates no conversation record and changes none of Claude Code's settings files. It usually takes a few seconds; the tool gives up after 20 seconds. It counts as successful only if the cache's observation time moved forward. If you relocated the Claude Code directory (see [Where the tool looks for files](#where-the-tool-looks-for-files)), the child is pointed at the same directory, so what it updates is the cache the tool is reading. No console window opens and focus is not taken.

**Cost and risk.** The request goes to the same endpoint as `/usage`, and counts against your account like any other request. Asking too often can get you rate-limited, and **while you are rate-limited even your own `/usage` fails**. That is why auto-query is off by default, has a minimum interval and pauses after repeated failures. The 5-minute minimum is a cautious guess: the provider does not publish a limit for this endpoint. Manual queries are only held back by the 30-second cooldown, so use them with the same care.

**When it fails**, the card shows a short reason next to the Update button and suggests running `/usage` in Claude Code instead. The reading you had stays exactly as it was. There are four kinds of reason:

- the `claude` executable was not found;
- the query timed out;
- Claude Code reported an error — its own message is shown untranslated (for example that you are not logged in); on the card, line breaks are collapsed and a long message is cut off at 60 characters;
- Claude Code finished but did not update the usage cache.

**Finding `claude`.** The tool looks for `claude` on `PATH`. If it is somewhere else, put its full path in `providers.claude.claudeCommand` in the settings file; that takes effect without a restart. A filled-in path that is not absolute or does not point to an existing file makes the query fail — the tool does **not** fall back to `PATH`, because that would silently run a different `claude` than the one you chose. (Unlike the path fields below, a bad `claudeCommand` does not stop the tool; only the query fails.) As with `CLAUDE_CONFIG_DIR`, a tool started at login only sees *user-level* `PATH` entries; if Update says it cannot find `claude` although it works in your terminal, set `claudeCommand`.

## Credentials expire

A credential snapshot's refresh token lives about 30 days. Each card shows the time left; when less than `expiryWarningDays` (default 7) remain, it warns you. To renew (the card just says "renew it"): log in to that account again in Claude Code, then either right-click the window and choose *Manage the signed-in account…* with the same label, or run `add <label>` again. A card that says the credential snapshot is invalid means Claude Code rotated the token; renew it the same way. The tool never rewrites a credential snapshot on its own.

## Window and menu

Drag anywhere to move; double-click to switch between compact and expanded. Right-click for:

- **Layout**: card list (default) / dense table and one-line strip / ring gauge
- **Query usage** and **Auto-query usage** (default off): see [Query usage](#query-usage)
- **Always on top** (default on), **Mode** (compact / expanded)
- **Language**: follow system (default), 正體中文, English. Follow system uses the Windows display language and falls back to English when it is neither Traditional Chinese nor English. Switching takes effect at once; the command line (`list`, `add`, `check`, …) follows the same setting. Values Claude reports itself (a lock reason, the name of a limit this tool doesn't recognise) are shown as reported, not translated
- **Theme**: follow system (default), light, dark
- **Opacity**: 100% (default), 85%, 70%
- **Start at login** (default off): writes one value to your user's `Run` registry key and removes it when turned off. It does not need administrator rights and touches nothing else. The checkbox always reflects the actual registry value. The registered command points at the Python and the folder it was turned on from; if you move the folder or change Python, the checkbox shows off until you turn it on again.
- **Add / Import / Open folder / Quit**: *Open folder* has two entries, *Managed directory* and *Settings directory*

The window remembers its position; if that position is no longer on any screen (for example an unplugged monitor) it moves back to the primary screen.

## Error log

Started with `pythonw`, the tool has no console, so an error leaves no trace on screen. Whenever a round does not complete, the error (time and full traceback) is appended to `%APPDATA%\cc-quota-tracker\errors.log`, next to `settings.json` and deliberately not in the managed directory, since the managed directory may be what is failing. To open it, right-click → *Open folder* → *Settings directory*.

An entry is written when a round fails after a completed one, or when the error changes while rounds keep failing; the same error repeating is written once. Past 1 MB the file is renamed to `errors.log.1` (replacing the previous one) and a new `errors.log` starts, so at most about 2 MB are kept. If the log itself cannot be written, the tool carries on without it and without any dialog.

## Settings file

Location: `%APPDATA%\cc-quota-tracker\settings.json`. It is written with every field at its default the first time the tool starts, and never replaced afterwards (changing a setting from the right-click menu updates only that one field). It is deliberately **not** inside the managed directory, because the managed directory's location is itself a setting.

You can edit it with a text editor. Settings are re-read every 5 seconds and take effect without a restart; the two path fields are read only at startup (the window tells you when a restart is needed).

| Field | Values | Default | Meaning |
|---|---|---|---|
| `layout` | `"cards"`, `"table"`, `"ring"` | `"cards"` | Card list / dense table and one-line strip / ring gauge |
| `alwaysOnTop` | `true`, `false` | `true` | Keep the window above others |
| `mode` | `"compact"`, `"expanded"` | `"compact"` | Active account only / all accounts |
| `language` | `"system"`, `"zh-TW"`, `"en"` | `"system"` | Interface language, for the window and the command line. `system` follows the Windows display language: Traditional Chinese (zh-TW, zh-HK, zh-MO) gives `zh-TW`, English gives `en`, anything else falls back to `en` |
| `theme` | `"system"`, `"light"`, `"dark"` | `"system"` | `system` follows the Windows app light/dark setting |
| `opacity` | `100`, `85`, `70` | `100` | Window opacity in percent |
| `countdownFormat` | `"twoUnits"`, `"decimalDays"` | `"twoUnits"` | `twoUnits`: 6d 23h / 2h 15m / 40m (days + hours, hours + minutes, minutes; the Traditional Chinese interface writes 6天23小時 / 2小時15分 / 40分). `decimalDays`: 6.9d (6.9天) when a day or more remains (shorter spans still show hours and minutes). Both truncate, never round up |
| `font` | font family name or `null` | `null` | Font for all text. `null` uses the built-in fonts (Microsoft JhengHei UI, and Segoe UI Semibold for the big percentages). Sizes and weights stay as designed. A font that is not installed on this computer is replaced by the system default font, and for a name you typed the window says so. Settings file only, not in the right-click menu |
| `providers.claude.expiryWarningDays` | positive integer | `7` | Warn when the credential snapshot has *less than* this many days left |
| `providers.claude.warningPercent` | integer 1–100, less than `criticalPercent` | `60` | Yellow threshold, used only when Claude does not report a severity itself |
| `providers.claude.criticalPercent` | integer 1–100, greater than `warningPercent` | `85` | Red threshold, same condition |
| `providers.claude.claudeCommand` | absolute path to the `claude` executable, or `null` | `null` | Which `claude` [Query usage](#query-usage) starts. `null` searches `PATH`. A filled-in path that is not absolute or not an existing file makes the query fail (no fallback to `PATH`). Takes effect without a restart |
| `providers.claude.autoUsageQuery` | `true`, `false` | `false` | Auto-query on or off. Also switched by right-click → *Auto-query usage*, which rewrites only this field |
| `providers.claude.autoUsageQueryMinutes` | positive integer | `15` | Minimum minutes between auto-queries. **Lower limit 5**: a smaller value runs as 5, the window says so (while auto-query is on), and the file is not rewritten. Manual queries are not affected |
| `claudeConfigDir` | absolute path or `null` | `null` | Where Claude Code keeps its files (see below) |
| `managedDir` | absolute path or `null` | `null` | Where credential snapshots are kept (see below) |

The window position is remembered separately and is not in this file.

**A bad value** falls back to the default for that one field only (the two percentage thresholds fall back together unless `warningPercent` is less than `criticalPercent`). The window names the invalid field (a bad value under `providers` is named by its path, e.g. `providers.claude.warningPercent`; when the two thresholds are not in increasing order, both are named, even the one you did not write). If the whole file is not valid JSON, every default is used, the window says so, and the tool will not overwrite the file until you fix it (changes made from the right-click menu then last only until you quit).

Progress bar colours follow the severity Claude itself reports (`normal` / `warning` / `critical`); the percentage thresholds above are only a fallback when it reports none.

### Where the tool looks for files

**Claude Code directory** (where the usage cache and the current credential live) — the first one that is set wins:

1. `claudeConfigDir` in the settings file
2. the `CLAUDE_CONFIG_DIR` environment variable (empty counts as unset)
3. the default: `~/.claude.json` and `~/.claude/`

With 1 or 2, both `.claude.json` and `.credentials.json` are looked for **inside** that directory, not next to it. (This is different from the default, where `.claude.json` sits in your home directory and the credential in `~/.claude/`.)

**Managed directory**: `managedDir` in the settings file, otherwise `~/.claude-multi/`. It may be on another drive. It must not be inside the Claude Code directory, because the tool never writes there.

A path field that is filled in must be an **absolute path to an existing directory**. If it is not, the tool **stops with an error naming the field** rather than falling back — falling back would silently read a different set of accounts while everything looked normal. Relative paths are rejected because they would resolve against a different working directory when started at login.

> **Start at login and `CLAUDE_CONFIG_DIR`:** a program started at login only inherits *user-level* Windows environment variables. If you set `CLAUDE_CONFIG_DIR` only in a shell profile, the tool started at login will not see it and will read the default location instead. Put the directory in `claudeConfigDir` in the settings file (or set the variable at user level in Windows).

If none of the three levels is set and `~/.claude.json` cannot be found, the window shows a "may be reading the wrong location" notice instead of quietly showing "no reading".

## For hosts: what the tool depends on

All usage numbers come from the `cachedUsageUtilization` field in Claude Code's `.claude.json`. **This is an internal, undocumented field. Claude Code makes no compatibility promise about it, and a Claude Code update can change or remove it.**

The tool tolerates the expected kinds of trouble: a file caught mid-write (it keeps the last value quietly), a missing field (shown as "no reading yet", not an error), and unknown limit types (shown under their original names as "other limits"). If the structure genuinely changes, a banner appears — only after the problem persists for 3 consecutive polls — together with the last successful reading and its time, instead of a wall of 0%. A different banner, "Board stopped updating", means the tool itself could not finish a poll for about a minute (12 polls in a row): the board stays on the last successful reading, shown with its time, and the banner clears as soon as a poll succeeds again.

To check compatibility at any time:

```
python -m cc_quota_tracker check
```

It verifies that every field path the tool relies on still exists with the expected type, lists new unknown fields under `utilization`, and prints the Claude Code directory and managed directory actually in use, saying whether each came from the settings file, the environment variable, or the default. It prints field names and types only, never values.

The tool also appends a log of every account switch it observes (time and account identifier only, kept in the managed directory with restricted permissions and never shown on screen) and the time it last ran, so that future reporting can attribute usage to the right account.

## Intended setup and known limitations

The tool was designed and tested for one setup: **Windows, Claude Code on a subscription plan, conversations mostly in the Claude Code panel of VS Code, several accounts used in turn on the same computer.** Other setups — using only the terminal, several computers, one account shared by several people — have not been tested. They may work partly, or not at all.

Known limitations:

- Querying, and the live judgement of whether a reading is lagging, work for the **active account only**. A standby account shows its last observed reading (flagged *Lagging before the switch* if it already was when you switched away).
- Quota used on another device, or on the claude.ai website, leaves no conversation record on this computer. A lagging reading cannot be detected there, and auto-query will not be triggered by it. Use right-click → *Query usage* when you know that happened.
- The *Update* button on the card appears only while the reading is lagging or pending. At other times use the right-click menu.
- The tool depends on things Claude Code does not document: the `cachedUsageUtilization` field (see below) and the experimental interface that Query usage uses. A Claude Code update can break either. If the interface changes, Query usage fails with a reason, everything else keeps working from the cache, and `/usage` in Claude Code remains the fallback.

## Out of scope for this version

Switching accounts from inside the tool, encrypting credential snapshots, token reports, other providers, macOS / Linux, packaging as an exe, network requests made by the tool itself (Query usage goes through Claude Code), querying standby accounts, and any automation triggered by quota level.
