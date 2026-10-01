# AI Agent 行為準則與開發規範 (AGENTS.md)

本專案適用於 Google Antigravity、Gemini CLI 及所有相容之 AI 輔助開發工具。所有在此專案工作的 AI Agent 必須嚴格遵守以下條款：

---

## 🚨 核心鋼鐵禁令：Git Push 自主權限制 (Strict Git Push Prohibition)

1. **嚴禁主動執行 `git push`**：
   - 任何情況下，**絕對禁止**自主執行 `git push` 指令。
   - 即便使用者的指令為「請修復」、「請更新」、「請幫我弄好」，AI 的工作範圍**嚴格僅限於**：
     1. 分析問題與程式碼編修。
     2. 於本地環境執行測試與驗證。
     3. 產出修改報告並展示清楚的 `git diff` 與檔案連結。
     4. **立即停下動作，等待使用者確認與回覆。**

2. **推送觸發條件 (Release Condition)**：
   - 唯有在使用者於**該對話輪次中明確下達「push」、「請push」、「確認推送」等授權詞彙**時，AI 方得執行 `git commit` 與 `git push`。
   - 執行推送前，必須向使用者條列即將推送的檔案清單。

---

## 📦 專案核心相依性規範 (Dependency Constraints)

為確保跨 Python 版本（例如 Python 3.7、3.8、3.11 等）之硬體通訊相容性，修改相依性時必須恪遵以下版本限制：

1. **`pysnmp` 版本鎖定**：
   - 必須維持 `pysnmp>=4.4.12,<5.0.0`。
   - 說明：PySNMP 5.x/6.x/7.x 重構移除了同步 `hlapi` 與 `SnmpEngine` 匯入路徑，與本專案既有測試案例不相容，嚴禁升級至 5.0.0 以上。

2. **`pyasn1` 版本鎖定**：
   - 必須維持 `pyasn1>=0.4.8,<0.5.0`。
   - 說明：PyASN1 0.5.0 以上版本移除了 `pyasn1.compat.octets`，會直接導致 `pysnmp 4.4.12` 崩潰，嚴禁放寬至 0.5.0 以上。

3. **三方設定檔同步性**：
   - 若有任何套件調整，必須同時維持 `requirements.txt`、`setup.py` 與 `pyproject.toml` 三者 100% 同步。

---

## 🛠️ Windows 環境與批次檔相容規範 (Platform Compatibility)

1. **批次檔語法安全 (`setup.bat`)**：
   - 嚴禁在未引號包裹的 `if (...)` 括號區塊中使用半形括號文字，避免 Windows `cmd.exe` 提早閉合括號引發語法崩潰。
   - 邏輯分支優先採用 `goto :LABEL` 架構。
2. **換行與編碼**：
   - 所有批次檔及設定檔均採用標準 Windows CRLF (`\r\n`) 換行。
   - `requirements.txt` 內一律使用純 ASCII 英文註解，避免繁體中文 Windows 預設 CP950 編碼解碼異常。
