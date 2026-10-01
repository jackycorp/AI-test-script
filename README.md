# AI 自動化測試框架 (AI Test Automation Framework)

本專案提供標準化、模組化的硬體與網路自動化測試框架（支援 Serial、Telnet、SNMP、Ping 以及 Spirent 流量測試）。專案具備環境隔離、路徑動態相容機制，兼顧「**純執行測試**」與「**二次開發**」兩大需求。

---

## 一、 專案目錄結構

```text
AI_test_framework/                          <-- 專案根目錄
│
├── .gitignore                              <-- [版控防線] 排除虛擬環境、測試結果、封包與個人自訂腳本
├── README.md                               <-- [主說明書] 快速上手、目錄架構與執行/開發指南
├── SKILL.md                                <-- [開發規範] 核心 API 簽名規格表與禁止事項
├── requirements.txt                        <-- 相依套件清單 (pyserial, icmplib, pysnmp 等)
├── pyproject.toml / setup.py               <-- 專案模組設定檔 (支援任意層級 import utils)
│
├── setup.bat                               <-- [一鍵環境安裝] 自動建立專屬 .venv 隔離環境
│
├── utils/                                  <-- [核心共用庫] 底層通訊與儀器封裝 (唯讀)
│   ├── __init__.py
│   ├── comm_helper.py                      <-- Serial, Telnet, Ping, 防呆參數輸入
│   ├── pythontool.py                       <-- Spirent TestCenter 控制介面
│   └── dictionary_parameters.py
│
├── example/                                <-- [官方測試範例庫] 保持純淨源碼，可自由建立多層子資料夾
│   ├── 1.Cold start Recovery Test/
│   ├── 2.Link_off_on_Recovery_Test/
│   ├── 8.Warm_start_Recovery_Test/
│   └── 11.ARCC Test/                       <-- (多層子目錄範例，保證正常執行)
│       └── Couple_decouple_looping_test.py
│
├── my_scripts/                             <-- [個人自訂開發區] (已設為 .gitignore，升級零衝突)
│   ├── templates/                          <-- [官方範本庫] (保留進 Git，就地參考複製)
│   │   ├── template.py                     <-- 腳本骨架樣板 (採用 1.1~3.6 清晰切分)
│   │   └── test_spec.txt                   <-- 需求填寫表 (採用 1.1~3.6 清晰切分)
│   ├── .gitkeep
│   └── (在此撰寫個人的客製化測試腳本)
│
└── test result/                            <-- [集中測試輸出區] (已設為 .gitignore，不污染 Git)
    ├── .gitkeep
    └── 1.Cold start Recovery Test_result/  <-- [案例專屬輸出目錄] (自動建立同名資料夾並加 _result)
        ├── result.txt                      <-- 本次測試結果日誌
        └── captures/                       <-- 抓包檔案集中存放於此子階層 (如 .pcap)
```

---

## 二、 快速上手：純執行測試 (Runner 指南)

若您僅需要執行現成的測試案例，無需具備 Python 開發經驗，也不用擔心電腦原有的 Python 套件衝突或版本問題：

### 💡 執行個別測試的「最小必要檔案清單」（免下載整包方案）
若其他測試電腦**只想執行特定測試**（例如僅跑 `8.Warm_start_Recovery_Test`），其實**無需下載所有案例**，只要保留以下 3 樣檔案即可獨立運行：

1. **環境啟動檔案 (專案根目錄)**：
   * `setup.bat`（首次雙擊自動建立隔離環境）
   * `requirements.txt`（相依套件清單）
   * `pyproject.toml` 或 `setup.py`（模組路徑設定）
2. **共用核心庫 (專案根目錄)**：
   * `utils/`（**核心必備！**包含 Ping、Telnet、Serial 與 Spirent 控制底層）
3. **欲執行的目標案例 (example 目錄下)**：
   * `example/<目標測試資料夾>/`（內含該測試的 `.py` 腳本與 `scenarios.csv` 參數表）

> *提示：其餘未用到的 `example/` 子目錄、`templates/` 範本與 `my_scripts/` 均為選用，不下載也 100% 不影響執行！*

---

### 步驟 1：下載專案
- **方法 A**：使用 Git 指令 `git clone <儲存庫網址>`。
- **方法 B**：至 GitLab 頁面點擊 **Code ➔ Download ZIP** 並解壓縮。
- **方法 C（進階，僅抓單一測試）**：使用 Git Sparse-checkout 只檢出 `utils` 與目標案例資料夾。

### 步驟 2：一鍵建立專屬環境
- 在專案根目錄找到 **`setup.bat`**，**滑鼠點擊兩下執行**。
- 此程式會自動在專案內建立名為 `.venv` 的獨立沙盒環境，並自動安裝測試所需的必要套件。
- *註：本步驟僅需在首次下載或套件更新時執行一次。*

### 步驟 3：命令列執行測試
在專案根目錄開啟終端機（CMD 或 PowerShell），使用專案專屬的虛擬環境直譯器執行目標腳本：

```cmd
.venv\Scripts\python.exe "example\8.Warm_start_Recovery_Test\Warm_start_Recovery_Test.py"
```

*(或者也可以先啟動環境再執行)*：
```cmd
call .venv\Scripts\activate
python "example\8.Warm_start_Recovery_Test\Warm_start_Recovery_Test.py"
```

> **提示**：無論腳本位於 `example/` 底下多深層的子資料夾（如 `example\11.ARCC Test\...`），均可直接使用上述指令順暢執行。

### 步驟 4：查看測試結果 (集中與分階層管理)
- 測試過程中產生的日誌與結果報告統一集中輸出至根目錄的 **`test result/<測試案例名稱>_result/result.txt`**。
- 若測試有執行封包擷取（Wireshark 抓包），檔案會自動分階層存放於 **`test result/<測試案例名稱>_result/captures/`**。
- **優勢**：原始碼與執行產出徹底解耦，`example/` 資料夾永遠維持純淨，歷史報告與封包要打包或一鍵刪除只需操作 `test result/`。
- *註：`test result/` 資料夾與封包檔均已在 `.gitignore` 中設定排除，絕不會污染 Git 儲存庫。*

---

## 三、 開發者指南：依需求自訂測試腳本 (Developer 指南)

若您需要根據特定產品或需求撰寫新的測試腳本：

### 步驟 1：初始化開發環境
- 同樣先雙擊執行 **`setup.bat`**。
- `setup.bat` 會以可編輯模式（`pip install -e .`）將 `utils/` 註冊進環境中。這意味著您在專案的**任何子目錄下**撰寫程式碼，都能直接引用：
  ```python
  from utils.comm_helper import get_com_port, comm_CMD, check_ping
  ```

### 步驟 2：閱讀開發規範與 API 規格 (`SKILL.md`)
- 在撰寫前，請務必詳細閱讀專案根目錄下的 **`SKILL.md`**。
- 裡面定義了所有 `utils/` 模組的完整函式簽名、禁止盲猜的調用禁忌與三階段開發原則。

### 步驟 3：建立並撰寫新腳本
- 直接從 **`my_scripts/templates/template.py`** 複製一份到 **`my_scripts/`** 目錄下。
- 將其重命名（例如 `my_scripts/my_arcc_test.py`）。
- 若需定義新測試需求請 AI 編寫，可複製並參考 **`my_scripts/templates/test_spec.txt`**。
- 依據 `template.py` 的標準三階段骨架撰寫邏輯：
  1. **Phase 1**：讀取參數表與防呆輸入。
  2. **Phase 2**：環境與連線配置（Serial / Telnet / 儀器），初始化集中輸出路徑。
  3. **Phase 3**：自動化測試迴圈與 `try...finally` 資源妥善釋放。

### 步驟 4：執行與驗證
在終端機中執行您自訂的腳本：
```cmd
.venv\Scripts\python.exe "my_scripts\my_arcc_test.py"
```
測試結果將自動存於 `test result/my_scripts/result.txt`。

### 步驟 5：未來同步核心更新 (升級零衝突)
- 當專案擁有者更新了 `utils/` 底層功能或發布了新版官方 example 時，您只需在專案根目錄執行：
  ```cmd
  git pull
  ```
- **為什麼安全？** 因為 `my_scripts/` 與 `test result/` 均已被 `.gitignore` 排除，`git pull` 只會同步官方核心與範例，**絕對不會覆蓋或衝突您自訂的測試腳本與測試結果**！

---

## 四、 核心原則提醒

1. **`utils/` 唯讀原則**：請勿直接修改 `utils/` 中的實體檔案，以確保團隊所有人共享的基礎通訊庫維持穩定與向後相容。
2. **多層資料夾支援**：所有官方 `example/` 及新架構腳本均已內建模組定位邏輯，即使未來在 `example/` 下細分多層資料夾（例如 `example/Subgroup/TestA/test.py`），均可直接被正確載入執行。
