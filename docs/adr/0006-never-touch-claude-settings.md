# 不修改 Claude Code 的設定、不掛 statusLine 或 hooks

本工具只讀 Claude Code 維護的檔案，自己的狀態一律寫在 `~/.claude-multi/`：不修改 `~/.claude/settings.json` 裡的任何項目，不註冊 statusLine 或 hooks，不碰 `~/.claude/cache/`，部署說明也不附 `settings.json` 範例。`statusLine` 在設定裡是單一值，不是陣列；只要文件附一份含 `statusLine` 的範例，照抄的人就會蓋掉自己原本的設定。額度資料本來就能從本機快取直接讀到（見 ADR-0001），所以不需要借用這些掛點。

切換功能是唯一的例外：它會寫入當前憑證，以及 `~/.claude.json` 裡的 `oauthAccount` 這一個鍵（ADR-0011）。設定、statusLine、hooks 仍然一律不碰。
