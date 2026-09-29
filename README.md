# cc-quota-tracker

English | [正體中文](README.zh-TW.md)

A small always-on-top desktop window (Windows) that shows how much quota each of your Claude accounts has left, all at once. Claude Code only shows the account you are logged into; this tool keeps the last reading of every other account you have set up, so you can see which one has room this week.

- **Compact mode**: the active account's session window and weekly window — progress bar, reset countdown, reading age, credential expiry countdown.
- **Expanded mode**: one card per managed account, the active one highlighted; standby accounts show their last observed reading and how old it is.
- Three layouts (card list, dense table / one-line strip, ring gauge), light / dark / follow-system theme, adjustable opacity.

**Everything comes from local files that Claude Code already maintains. The tool makes no network requests, never writes to Claude Code's files, and never changes Claude Code's settings (no statusLine, no hooks).**

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
python -m cc_quota_tracker check            # see "For hosts" below
python -m cc_quota_tracker gui              # open the window
```

### 2. Right-click menu

Right-click the window:

- **Add the currently logged-in account…** asks for a label and does the same as `add`.
- **Import a credential file…** picks a credential file and copies it into the managed directory; the label defaults to the file name without `.json`.

### 3. Drop a file in

Copy a credential file into the managed directory yourself (right-click → *Open managed directory* gets you there), named `<label>.json`. Renaming a file renames the account label; the identity binding is kept.

**Limitation of dropping a file in (and of *Import*):** the file carries no account identifier, so the tool cannot tell which account's readings belong to it. Until that account has been your active account once and Claude Code has written a reading for it, its card shows **Reading pending** and nothing else. With `add` this does not happen, because it binds the account at the moment you run it.

### Permissions

The managed directory holds long-lived credentials for every account. `add` and *Import* restrict it to your Windows user only (inheritance removed) and check the result afterwards; if the permissions were not as expected, the tool fixes them and tells you. Credential snapshots are **not encrypted** — the protection is the file permissions, so treat the directory like `~/.claude` itself.

## Two states that are not faults

| What you see | What it means |
|---|---|
| **Reading pending** (讀數待更新) | The active account has no reading of its own yet. Claude Code keeps only one account's reading at a time, so right after a switch the cached reading still belongs to the previous account, and the tool will not show it under the new one. It appears once Claude Code refreshes its cache (usually within seconds of logging in; otherwise on the next prompt or when its usage panel is open). |
| **Unmanaged account** (未納管帳號) | The account you are logged into has no credential snapshot here. The card tells you how to manage it. Nothing is wrong. |

Standby accounts show their **last observed** reading and how long ago that was (e.g. 3 天前). That reading is only accurate if the account has not been used since it was observed — if you used it on another machine, this machine cannot see that. Standby readings are never flagged as out of date just for being old. For the active account, an old reading is not flagged either unless there has been new conversation activity on this machine since the reading ("new conversation, quota not yet updated").

## Credentials expire

A credential snapshot's refresh token lives about 30 days. Each card shows the time left; when less than `expiryWarningDays` (default 7) remain, it warns you. To renew: log in to that account again in Claude Code, then run `add <label>` again. A card that says the credential snapshot is invalid means Claude Code rotated the token; renew it the same way. The tool never rewrites a credential snapshot on its own.

## Window and menu

Drag anywhere to move; double-click to switch between compact and expanded. Right-click for:

- **Layout**: card list (default) / dense table and one-line strip / ring gauge
- **Always on top** (default on), **Mode** (compact / expanded)
- **Theme**: follow system (default), light, dark
- **Opacity**: 100% (default), 85%, 70%
- **Start at login** (default off): writes one value to your user's `Run` registry key and removes it when turned off. It does not need administrator rights and touches nothing else. The checkbox always reflects the actual registry value. The registered command points at the Python and the folder it was turned on from; if you move the folder or change Python, the checkbox shows off until you turn it on again.
- **Add / Import / Open managed directory / Quit**

The window remembers its position; if that position is no longer on any screen (for example an unplugged monitor) it moves back to the primary screen.

## Settings file

Location: `%APPDATA%\cc-quota-tracker\settings.json`. It is written with every field at its default the first time the tool starts, and never replaced afterwards (changing a setting from the right-click menu updates only that one field). It is deliberately **not** inside the managed directory, because the managed directory's location is itself a setting.

You can edit it with a text editor. Settings are re-read every 5 seconds and take effect without a restart; the two path fields are read only at startup (the window tells you when a restart is needed).

| Field | Values | Default | Meaning |
|---|---|---|---|
| `layout` | `"cards"`, `"table"`, `"ring"` | `"cards"` | Card list / dense table and one-line strip / ring gauge |
| `alwaysOnTop` | `true`, `false` | `true` | Keep the window above others |
| `mode` | `"compact"`, `"expanded"` | `"compact"` | Active account only / all accounts |
| `language` | `"system"`, `"zh-TW"`, `"en"` | `"system"` | Interface language. **Not in effect yet:** the interface is currently Traditional Chinese only, so this field is accepted but changes nothing visible |
| `theme` | `"system"`, `"light"`, `"dark"` | `"system"` | `system` follows the Windows app light/dark setting |
| `opacity` | `100`, `85`, `70` | `100` | Window opacity in percent |
| `countdownFormat` | `"twoUnits"`, `"decimalDays"` | `"twoUnits"` | `twoUnits`: 6天23小時 / 2小時15分 / 40分 (days + hours, hours + minutes, minutes). `decimalDays`: 6.9天 when a day or more remains (shorter spans still show hours and minutes). Both truncate, never round up |
| `providers.claude.expiryWarningDays` | positive integer | `7` | Warn when the credential snapshot has *less than* this many days left |
| `providers.claude.warningPercent` | integer 1–100, less than `criticalPercent` | `60` | Yellow threshold, used only when Claude does not report a severity itself |
| `providers.claude.criticalPercent` | integer 1–100, greater than `warningPercent` | `85` | Red threshold, same condition |
| `claudeConfigDir` | absolute path or `null` | `null` | Where Claude Code keeps its files (see below) |
| `managedDir` | absolute path or `null` | `null` | Where credential snapshots are kept (see below) |

The window position is remembered separately and is not in this file.

**A bad value** falls back to the default for that one field only (the two percentage thresholds fall back together unless `warningPercent` is less than `criticalPercent`). The window names an invalid field among `layout` through `countdownFormat`; a bad value under `providers` quietly uses its default. If the whole file is not valid JSON, every default is used, the window says so, and the tool will not overwrite the file until you fix it (changes made from the right-click menu then last only until you quit).

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

The tool tolerates the expected kinds of trouble: a file caught mid-write (it keeps the last value quietly), a missing field (shown as "no reading yet", not an error), and unknown limit types (shown under their original names as "other limits"). If the structure genuinely changes, a banner appears — only after the problem persists for 3 consecutive polls — together with the last successful reading and its time, instead of a wall of 0%.

To check compatibility at any time:

```
python -m cc_quota_tracker check
```

It verifies that every field path the tool relies on still exists with the expected type, lists new unknown fields under `utilization`, and prints the Claude Code directory and managed directory actually in use, saying whether each came from the settings file, the environment variable, or the default. It prints field names and types only, never values.

The tool also appends a log of every account switch it observes (time and account identifier only, kept in the managed directory with restricted permissions and never shown on screen) and the time it last ran, so that future reporting can attribute usage to the right account.

## Out of scope for this version

Switching accounts from inside the tool, encrypting credential snapshots, token reports, other providers, macOS / Linux, packaging as an exe, any network access, and any automation triggered by quota level.
