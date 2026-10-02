# 測試腳本標準開發框架與寫法規範 (SKILL.md)

本文件定義此工作區中所有自動化測試腳本的**標準編寫框架**與**開發規範**。未來新增或重構測試腳本時，必須嚴格遵守此規範，以確保程式碼風格一致、資源妥善清理且日誌格式標準。

---

## 1. 共用庫動態審查原則 (Pre-Inspection & Zero-Guessing Rule)

> [!CAUTION]
> **程式碼即單一真實來源（Single Source of Truth），嚴格禁止盲猜未定義函式**：  
> 1. **先審後寫 (Inspect First)**：AI 在編寫任何測試腳本前，**必須先主動檢視 `utils/` 目錄下的實體檔案**（如 `utils/pythontool.py`、`utils/comm_helper.py`），以實體檔案中的函式宣告（`def`）與參數簽名為唯一依據。
> 2. **嚴禁臆測 API**：當需要流量控制、設備通訊或連線清理時，**必須 100% 依據 `utils/` 內實際存在的具體函式名稱與參數格式**進行調用。嚴禁憑經驗或通用語意臆測未定義的 API。
> 3. **輸出前自我 Code Review**：生成程式碼後，AI 必須進行自我靜態代碼走查（毋須執行腳本），逐項核驗每一個共用函式調用之參數數量與型態，確保 100% 吻合。

### 1.1 `utils.comm_helper` 核心 API 簽名規格表
| 函式名稱與宣告 | 參數個數與型態 | 正確調用範例 | 致命禁忌（絕對嚴禁） |
| :--- | :--- | :--- | :--- |
| `get_com_port() -> str` | **0 個參數** | `com_port = get_com_port()` | ❌ 傳入自定義 prompt 字串（如 `get_com_port("COM:")`） |
| `get_iteration_count() -> int` | **0 個參數** | `iteration = get_iteration_count()` | ❌ 傳入自定義 prompt 字串 |
| `get_delay_time() -> float` | **0 個參數** | `delay = get_delay_time()` | ❌ 傳入自定義 prompt 字串 |
| `get_boot_wait_time() -> float` | **0 個參數** | `boot_wait = get_boot_wait_time()` | ❌ 傳入自定義 prompt 字串 |
| `get_target_ip() -> str` | **0 個參數** | `target_ip = get_target_ip()` | ❌ 傳入自定義 prompt 字串 |
| `comm_CMD(ser, String: bytes)` | **2 個參數** (Serial 物件, `bytes`) | `comm_CMD(ser, b"tx\r")` | ❌ 指令傳入 `str`（如 `"tx"`，必須為 `bytes` 且帶 `\r`） |
| `comm_TELNET(tn, expect, cmd)` | **3 個參數** (Telnet 物件, `str`, `str`) | `comm_TELNET(tn, 'Enter', 're')` | ❌ 漏掉 expect 參數 |
| `check_ping(target_ip, times=1)` | **1~3 個參數** (`str`, `int`, `float`) | `is_alive = check_ping("10.0.1.1")` | - |
| `get_result_dir(script_file, sub_dir=None) -> str` | **1~2 個參數** (`str`, `str`) | `out_dir = get_result_dir(__file__, "captures")` | ❌ 寫死絕對路徑或直接在工作區根目錄建立資料夾；輸出一律自動建立於 `test result/<測試名稱>_result/` |
| `get_result_log_path(script_file, filename="result.txt", sub_dir=None) -> str` | **1~3 個參數** (`str`, `str`, `str`) | `log_file = get_result_log_path(__file__, "result.txt")` | ❌ 寫死 `log_filename = "result.txt"` 或隨處亂放；必須調用此 API 將日誌集中存於 `test result/<測試名稱>_result/` |

### 1.2 `utils.pythontool` 核心 API 簽名規格表
| 函式名稱與宣告 | 參數個數與型態 | 正確調用範例 | 致命禁忌（絕對嚴禁） |
| :--- | :--- | :--- | :--- |
| `StartGenerator(portlist)` | **1 個參數：List[port_obj]** | `StartGenerator([tx_port_obj])` | ❌ 臆測 API `StartTraffic()` 或 `analyzerStart()`；❌ 傳入非清單型別 |
| `StopGenerator(portlist)` | **1 個參數：List[port_obj]** | `StopGenerator([tx_port_obj])` | ❌ 臆測 API `StopTraffic()` 或 `analyzerStop()`；❌ 傳入非清單型別 |
| `getdata(portlist)` | **1 個參數：List[port_obj]** | `datalist = getdata(ports_pair)` | ❌ 傳入單一 Port 物件；回傳 `[[rx0,tx0,drop0],[rx1,tx1,drop1]]` |
| `unsubscribe(result)` | **1 個參數：result handle** | `unsubscribe(result1)` | ❌ 首字母大寫 `Unsubscribe()` |
| `Disconnect(chassisAddr)` | **1 個參數：str** | `Disconnect(chassisAddr)` | ❌ 臆測 API `ReleasePort()` |
| `stc::delete $handle` (Tcl) | **原生 Tcl 命令** | `tclsh.eval(f"stc::delete {project}")` | ❌ 臆測 API `DestroyProject()` |
| `stc::perform ResultsClearAll` | **原生 Tcl 命令** | `tclsh.eval("stc::perform ResultsClearAll")` | ❌ 使用 `ClearResults`（僅清埠級，造成丟包累加） |
| ⚠️ **Analyzer 啟停禁忌** | **無獨立封裝** | 僅調用 `StartGenerator` / `StopGenerator` | ❌ **嚴禁調用未定義的 `analyzerStart()` 或 `analyzerStop()`**（其功能已內建於 `StartGenerator` 與 `StopGenerator` 底層，Python 模組並無獨立導出） |

---

## 2. 核心開發原則

1. **資源安全清理 (Resource Teardown)**：
   - 所有的 Spirent 連線（若有使用）、TCL 專案預約、Serial 串口與 Telnet 連線，都必須在 `try...finally` 結構中被安全釋放，避免因程式異常中斷導致設備埠口或硬體佔用。
2. **共用庫重用與唯讀原則 (Shared Library Reuse & Read-only Principle)**：
   - 必須導入與調用 `utils/` 目錄下的共用函式庫（如 `utils.pythontool`、`utils.comm_helper`），禁止直接操作底層 TCL 或重寫通訊接口。
   - **撰寫任何測試腳本時，絕對禁止更動或修改 `utils/` 資料夾內任何共用模組的檔案內容**。所有客製化測試邏輯應於個別測試腳本內自行實作，以確保共用庫的穩定性與向後相容性。
3. **分階段結構 (Three-Phase Structure)**：
   - 每個測試腳本都應包含獨立且清晰三個階段：
     - **Phase 1**：收集參數、讀取參數表與防呆輸入。
     - **Phase 2**：儀器預約（若有使用）與環境連線配置（如 Serial/Telnet 初始化）。
     - **Phase 3**：執行測試循環（步驟可根據具體測試邏輯自由編排，如 MAC 學習、指令下達、收斂等待、丟包計算或 Ping/狀態判定等）。
4. **程式碼區塊分割規範 (Code Block Separation)**：
   - 腳本內的程式結構必須清晰分隔。
   - 在**所有輔助函式與工具函式宣告上方**，必須加上 `#` 註解標記 `####################### 輔助函式 ###########################`。
   - 在 **`main()` 主程式入口宣告上方**，必須加上 `#` 註解標記 `####################### 主程式 ###########################`。
5. **工具箱按需裝配原則 (Toolbox On-Demand Assembly)**：
   - `utils/` 下的共用通訊與輸入功能（如 Spirent 預約、Serial 串口連線、Telnet 連線、Ping 檢測等）皆為「工具箱」中的選用積木。
   - 撰寫腳本時，應根據具體測試需求，**僅在程式中配置與開啟必要的通訊連線與控制功能**。無用到的功能（如純 Telnet 測試無用到 Serial 與 Spirent）應直接在腳本中移除，不留無用代碼。
   - 在 `finally` 資源清理區塊中，亦僅需針對程式中「實際有成功配置與開啟的連線與資源」進行安全關閉。
6. **全域結果清除原則 (Complete Results Clear Principle)**：
   - 為了防範串流級統計數據在 Iteration 之間持續累加，在清除統計結果時，**必須使用 `tclsh.eval("stc::perform ResultsClearAll")` 執行全域結果清除**。
   - 這樣做能同時將埠口（Port-level）與串流級（Stream-level）的歷史資料完全重置，避免因為僅清除埠級或僅清除串流級而導致數據不一致或受歷史數據污染。未來撰寫任何測試程式時，請務必採用此全域清除方式，避免使用僅清除埠級的 `ClearResults`。
7. **封包參數標準化引用原則 (Standard Packet Parameters Principle)**：
   - 所有測試腳本所使用的 StreamBlock 封包標頭（如來源/目的 MAC、IPv4 位址、Gateway 等），**必須強制引用 `utils.dictionary_parameters` 中已定義好的標準字典（如 `Frame`、`Frame1`、`Frame2`、`Frame3` 等）**。
   - **嚴禁在個別測試腳本內自行重複寫死（Hardcode）自定義封包字典**，以確保所有測試腳本的封包特徵一致且便於全域維護。
8. **封包擷取回歸與異常保護原則 (Packet Capture Integration & Safeguard Principle)**：
   - Spirent 封包擷取（PCAP Capture）相關函式已統一封裝回歸於 `utils.pythontool`（包含 `start_capture`、`stop_capture_and_save`、`create_capture_output_dir` 等），各腳本應直接調用共用函式。
   - 所有測試產生的 `.pcap` 檔案必須統一存放於工作區根目錄的 `captures/` 目錄下，嚴禁硬編碼絕對路徑。
   - 在 `finally` 資源清理區塊中，**必須加入未儲存 Capture 的緊急保存機制**，確保即使測試中途發生例外中斷，封包也不會遺失。
9. **流量控制與即時數據標準 API 原則 (Traffic Control & Real-time Stats API Principle)**：
   - 啟動流量發送時，**必須調用 `StartGenerator([port_obj])`**，傳入參數為 Port 物件之清單。嚴禁使用不存在的 `StartTraffic()`。
   - 停止流量發送時，**必須調用 `StopGenerator([port_obj])`**，傳入參數為 Port 物件之清單。嚴禁使用不存在的 `StopTraffic()`。
   - 獲取即時 TX/RX 數據並計算掉包時，**必須優先調用 `datalist = getdata(ports_pair)`**，解析回傳列表（例如 `datalist[0][2]` 為 Port0 Tx，`datalist[1][1]` 為 Port1 Rx），避免手動拼湊未經封裝之 Tcl 底層指令。
10. **StreamBlock 生命週期管理與防呆清除原則 (StreamBlock Lifecycle & Cleanup Principle)**：
   - **場景結束清理**：每個 Scenario 測試結束時，**必須顯式調用 `tclsh.eval(f"stc::delete {sb}")` 刪除該場景建立的 StreamBlock**（如 `sb0` 與 `sb1`）。
   - **建立前防呆**：在建立新 StreamBlock 之前，**必須加入防呆清除機制**（遍歷清除 `stc::get $port -children-StreamBlock`），防止因先前異常中斷在同一個 Port 上殘留多個 StreamBlock。
   - **兩端必須剛好各配 1 個 StreamBlock（嚴防 invalid handle 兩大致命陷阱）**：
     1. **若 > 1 個 StreamBlock**：`utils/tool.tcl` 的 `getdata` 會取得空格串聯的多個 Handle（如 `"streamblock1 streamblock3"`），導致底層 `stc::get` 拋出 `invalid handle` 崩潰。
     2. **若 0 個 StreamBlock**：`getdata` 會遍歷傳入的所有 Port。若 RX 埠未配置 StreamBlock，底層會取得空字串 Handle `""`，導致 `stc::get ""` 拋出致命錯誤 `RuntimeError: in get: invalid handle ""`！
     - **黃金法則**：因此，無論單向或雙向流量測試，**Port0 與 Port1 兩端在場景開頭均必須各配置 1 個 StreamBlock（Port0 用 Frame，Port1 用 Frame1）**。單向測試時僅需調用 `StartGenerator([tx_port_obj])`，接收端未啟動 Generator 絕不會發包，且 `getdata` 能夠 100% 正常讀取！
11. **資源安全釋放 API 白名單與避坑指南 (Teardown API Whitelist & Pitfalls)**：
   - ⚠️ **取消訂閱**：必須使用**全小寫**的 `unsubscribe(res)`，嚴禁使用大寫 `Unsubscribe`。
   - ⚠️ **專案刪除**：必須使用 Tcl 原生指令 `tclsh.eval(f"stc::delete {project}")`，嚴禁調用未定義的 `DestroyProject`。
   - ⚠️ **釋放埠口與斷連**：直接調用 `Disconnect(chassisAddr)` 即可完全中斷連線並自動釋放機箱預約埠，嚴禁調用未定義的 `ReleasePort`。
12. **CSV 參數表防禦性解析規範 (Defensive CSV Parsing Principle)**：
   - ⚠️ **嚴防 NoneType.strip() 崩潰**：使用 `csv.DictReader` 讀取參數表時，若 CSV 資料列欄位數少於表頭，缺漏的欄位值會由 Python 補為 `None`；若欄位數多於表頭，多餘欄位鍵會被置於 `None`。因此，**絕對嚴禁**使用未經保護的 `{k.strip(): v.strip() for k, v in row.items()}`。
   - ⚠️ **防禦性清理標準寫法**：
     ```python
     clean_row = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items() if k is not None}
     if not clean_row or not clean_row.get("Scenario"):
         continue  # 跳過空行或無效資料列
     ```
13. **產出檔案隔離原則 (Workspace Output Isolation Principle)**：
   - ⚠️ **嚴禁污染 `utils/` 目錄**：`utils/` 為系統唯一共用核心庫，絕對禁止在 `utils/` 資料夾內建立、生成或寫入任何臨時檔、日誌檔（如 `result.txt`）或 PCAP 封包。
   - ⚠️ **命名空間污染防範**：動態載入 `utils.pythontool` 時，必須過濾掉其內部的路徑變數（如 `current_dir`），避免覆蓋主腳本的全域路徑。日誌檔名一律直接寫為工作區根目錄相對路徑 `log_filename = "result.txt"`。
14. **跨層級目錄相容原則 (Cross-Directory Compatibility Principle)**：
   - ⚠️ **跨層級動態向上搜尋 `utils` 原則 (全目錄相容)**：
     無論測試程式放置於工作區根目錄 `test script/`、次級目錄 `example/`、或 `example/` 更下層子資料夾（如 `example/1-1_Cold_Start_Recovery_Test/`），**嚴禁使用寫死固定階層的 `../..`**。所有腳本頭部必須統一採用「動態向上遞迴搜尋法」，自動定位包含 `utils/comm_helper.py` 的目錄並加入 `sys.path`，確保不論在哪一層目錄執行均可順利載入共用模組：
     ```python
     # 動態向上搜尋包含 utils 的根目錄，確保無論放置於哪一層子目錄均能正常引入 utils
     SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
     current_dir_check = SCRIPT_DIR
     while current_dir_check and os.path.dirname(current_dir_check) != current_dir_check:
         if os.path.exists(os.path.join(current_dir_check, "utils", "comm_helper.py")):
             if current_dir_check not in sys.path:
                 sys.path.insert(0, current_dir_check)
             break
         current_dir_check = os.path.dirname(current_dir_check)
     if SCRIPT_DIR not in sys.path:
         sys.path.insert(0, SCRIPT_DIR)
     ```
   - ⚠️ **參數表 (`scenarios.csv`) 候選路徑遍歷**：
     若腳本需要讀取 CSV 測試參數表，必須具備多路徑搜尋候選機制（優先搜尋腳本所在目錄 `SCRIPT_DIR`，次之為工作目錄 `cwd`、上層目錄或工作區根目錄），保證腳本移動到任何子目錄時均能自動找到參數表。
15. **虛擬環境自動跳轉原則 (Auto Virtual Environment Trampoline Principle)**：
   - ⚠️ **全自動偵測與重啟機制 (免手動 activate)**：
     為了讓測試人員無論在何種終端機或目錄下，只要直接輸入 `python 腳本.py` 均能 100% 成功執行，所有測試腳本在動態定位到專案根目錄後、匯入任何第三方套件之前，必須加入自動跳轉檢查。若當前直譯器非專案 `.venv` 且專案根目錄存在 `.venv\Scripts\python.exe`，應自動透過 `subprocess.run` 重新拉起自身並轉移 exit code：
     ```python
     # 虛擬環境自動跳轉防呆機制 (若以全域 Python 啟動，自動切換至專案 .venv 執行)
     _venv_py = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
     if os.path.exists(_venv_py) and os.path.normcase(sys.executable) != os.path.normcase(_venv_py):
         import subprocess
         sys.exit(subprocess.run([_venv_py] + sys.argv).returncode)
     ```

---

## 2. 標準測試腳本寫法框架 (Template)

以下為標準腳本結構的骨架。開發新測試時請以此 Template 為基礎進行修改。

*註：若您的測試項目不需要使用 Spirent TestCenter 儀器（例如：純 Serial 狀態讀取或 Ping 斷連收斂測試），請直接在您的程式中移除 `pythontool` 的匯入與 `setup_spirent` 等儀器配置代碼，但分階段架構（Phase 1/2/3）與 try...finally 清理機制仍須嚴格保留。*

```python
# -*- coding: utf-8 -*-
"""
名稱: [測試腳本名稱]

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 輸入「COM 埠」、「執行次數」與「等待延遲時間」等。
  1.2 讀取測試參數表（如有多 Scenario 需求）。
[Phase 2] 儀器與環境配置 (Spirent & Serial/Telnet)
  2.1 配置 Spirent TestCenter 預約 Port 並建立 Stream。
  2.2 初始化 Serial 或 Telnet 連線並發送前置穩定指令。
[Phase 3] 自動化測試迴圈
  3.1 [進入測試迴圈]：依據測試邏輯編排步驟。
  （可包含：MAC 學習、清除統計、單/雙向打流量、下達控制指令、等待收斂、停止流量並統計丟包/判定狀態等）
  3.2 記錄結果至日誌，進入下一輪。
"""

import sys
import os
import time
from datetime import datetime
from typing import TYPE_CHECKING
# 視需要引入 serial, telnetlib 或 icmplib

# 動態向上搜尋包含 utils 的根目錄，確保無論放置於哪一層子目錄均能正常引入 utils
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
current_dir_check = SCRIPT_DIR
ROOT_DIR = SCRIPT_DIR
while current_dir_check and os.path.dirname(current_dir_check) != current_dir_check:
    if os.path.exists(os.path.join(current_dir_check, "utils", "comm_helper.py")):
        ROOT_DIR = current_dir_check
        if current_dir_check not in sys.path:
            sys.path.insert(0, current_dir_check)
        break
    current_dir_check = os.path.dirname(current_dir_check)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# 虛擬環境自動跳轉防呆機制 (若以全域 Python 啟動，自動切換至專案 .venv 執行)
_venv_py = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if os.path.exists(_venv_py) and os.path.normcase(sys.executable) != os.path.normcase(_venv_py):
    import subprocess
    sys.exit(subprocess.run([_venv_py] + sys.argv).returncode)

# 引入共用工具
try:
    from utils.dictionary_parameters import *
    from utils.comm_helper import *
except ImportError as e:
    print(f"無法載入 dictionary_parameters 或 comm_helper: {e}")
    sys.exit(1)

if TYPE_CHECKING:
    from utils.pythontool import *


####################### 輔助函式 ###########################
def load_utils():
    """動態載入 Spirent TestCenter API 核心，並注入全域命名空間"""
    print("\n正在載入 Spirent TestCenter API 與通訊工具，請稍候...")
    try:
        import utils.pythontool as pt
        # 排除模組內部私有或路徑變數，避免污染全域工作區命名空間
        excluded = {'current_dir', 'tool_tcl_path', 'lib_pathes', 'scripts', 'path'}
        for name in dir(pt):
            if not name.startswith('_') and name not in excluded:
                globals()[name] = getattr(pt, name)
    except ImportError as e:
        print(f"無法載入 pythontool: {e}")
        sys.exit(1)

def setup_spirent(chassisAddr: str, slotPortlist: list) -> tuple:
    """配置 Spirent TestCenter 預約 Port、建立 Stream，並訂閱流量結果"""
    Connect(chassisAddr)
    ReservePort(chassisAddr, slotPortlist)
    
    project = tclsh.eval('CreateProject')
    port = []
    for i in range(len(slotPortlist)):
        port.append(tclsh.eval('CreatePort {0} {1} {2}'.format(slotPortlist[i], project, chassisAddr)))

    # 設定 Port 屬性 (雙工、速率、流控)
    CreatePortType_Copper(port[0], PortType_1G_Full_AN)
    CreatePortType_Copper(port[1], PortType_1G_Full_AN)
    print(f"Ports initialized: {port}")

    tclsh.eval('Mapping')
    
    # 建立雙向 Stream Block
    Streamblocklist = []
    Streamblocklist.append(CreateStreamBlock(port[0], StreamBlock, Frame))
    Streamblocklist.append(CreateStreamBlock(port[1], StreamBlock, Frame1))

    # 設定 Generator
    Generator(port[0], Generatortype)
    Generator(port[1], Generatortype)
    
    # 訂閱統計結果
    now = datetime.now()
    filename = "generatorTx"+now.strftime("%m%d%y%H%M")
    filename2 = "analyzerRx"+now.strftime("%m%d%y%H%M")
    filename3 = "droppedRx"+now.strftime("%m%d%y%H%M")
    
    result1 = ResultSubscribe_Tx(project, filename)
    result2 = ResultSubscribe_Rx(project, filename2)
    result3 = ResultSubscribe_Rxstreams(project, filename3)
    
    return project, port, result1, result2, result3

def clear_results_and_streams(active_ports):
    """清除全域統計數據（包含埠與串流），防止 RxDrop 在 iteration 之間累加"""
    # 執行全域結果清除，會同時重置 Port 與 Stream 統計，避免僅清除 port-level 或 stream-level
    tclsh.eval("stc::perform ResultsClearAll")
####################### 主程式 ###########################
def main(com_port=None, iteration=None, delay_time=None):
    # --- [Phase 1] 參數蒐集與初始化 ---
    if com_port is None: com_port = get_com_port()
    if iteration is None: iteration = get_iteration_count()
    if delay_time is None: delay_time = get_delay_time()

    # 參數輸入完畢後，動態載入 Spirent API 核心工具 (避免啟動卡頓)
    load_utils()

    # 初始化連線參考，確保 finally 能安全清理
    ser = None
    result1, result2, result3 = None, None, None
    chassisAddr = "10.123.38.202"
    slotPortlist = ['1/12', '2/10']   # 依測試需求修改
    # 集中式日誌路徑：統一輸出至 test result/<測試名稱>_result/result.txt
    log_filename = get_result_log_path(__file__, "result.txt")

    try:
        # --- [Phase 2] 儀器與環境配置 ---
        project, port, result1, result2, result3 = setup_spirent(chassisAddr, slotPortlist)

        # 串口初始化 (若為 Telnet 則改用 telnet_login)
        try:
            ser = serial.Serial(port=com_port, baudrate=115200, timeout=0.5)
            print(f"已開啟串列埠 {com_port}")
            # 發送前置指令穩定環境
            comm_CMD(ser, b"t-\r")
            time.sleep(10)
        except Exception as e:
            print(f"串口初始化失敗: {e}")
            sys.exit(1)

        # 寫入日誌標頭
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*50}\n")
            f_log.write(f"開始測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"{'='*50}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for i in range(iteration):
            print(f"\n--- 第 {i+1}/{iteration} 次循環 ---")
            
            # 以下為常見操作步驟示範（請根據具體測試邏輯自行調整或增刪步驟）：
            
            # [步驟示範 A] 雙向流量學習 MAC (若有需要)
            print("開始雙向流量進行 MAC 學習...")
            clear_results_and_streams(port)
            StartGenerator([port[0], port[1]])
            time.sleep(2)
            StopGenerator([port[0], port[1]])
            time.sleep(1)
            clear_results_and_streams(port)
            time.sleep(1)
            
            # [步驟示範 B] 持續打流量 (單向或雙向，依測試而定)
            print("開始流量發送...")
            clear_results_and_streams(port)
            StartGenerator([port[0]])
            time.sleep(2)
            
            # [步驟示範 C] 下達設備控制指令 (Serial / Telnet / Power)
            print("發送測試指令...")
            comm_CMD(ser, b"tx\r")
            
            # [步驟示範 D] 等待收斂延遲
            time.sleep(delay_time)
            
            # [步驟示範 E] 停止流量並獲取數據
            print("停止流量並統計...")
            StopGenerator([port[0]])
            time.sleep(1)
            
            datalist = getdata(port)
            # 根據 datalist 進行數據分析與結果記錄

    except Exception as e:
        print(f"執行期間發生異常: {e}")
    finally:
        # 資源必定清理機制
        if ser is not None:
            try: ser.close()
            except: pass
        for res in [result1, result2, result3]:
            if res is not None:
                try: unsubscribe(res)
                except: pass
        try: Disconnect(chassisAddr)
        except: pass
        print(f"已完成測試。日誌已更新至 {log_filename}")


if __name__ == "__main__":
    main()
```

---

## 3. 分階段詳細規範要求

### 3.1 [Phase 1] 參數與參數表規範
- 互動輸入防呆：必須使用 `comm_helper` 的防呆輸入函式，不可直接使用未包裝的 `input()`，以防輸入空白或非法字元。
- **常用防呆輸入函式速查表 (comm_helper)**（⚠️ **注意：以下函式簽名均為 0 個參數，嚴禁傳入自定義 prompt 字串**）：
  - `get_com_port()`：提示輸入有效 COM 埠（內部自帶提示 `請輸入 COM 埠 (例如 COM11): `，不可帶參數）。
  - `get_iteration_count()`：提示輸入執行次數（內部自帶提示 `請輸入執行次數 (正整數): `，不可帶參數）。
  - `get_delay_time()`：提示輸入等待/收斂延遲秒數（內部自帶提示 `請輸入等待時間 (秒，例如 30): `，不可帶參數）。
  - `get_boot_wait_time()`：提示輸入重啟開機等待秒數（內部自帶提示 `請輸入開機等待時間 (秒，例如 60 或 220): `，不可帶參數）。
  - `get_target_ip()`：提示輸入目標 IP 位址（內部自帶提示 `請輸入目標 IP 位址 (例如 192.168.127.253): `，不可帶參數）。
  - `get_telnet_username()` / `get_telnet_password()`：提示輸入 Telnet 登入帳號與密碼。
- 參數表設計：若測試涉及多個 Scenario，應將參數表以清單字典結構定義在代碼頂部，或建立外部 CSV 檔案（如 `link change scenarios.csv`、`power_scenarios.csv`）以利動態解析。外部 CSV 參數表示例如下：
  ```python
  SCENARIOS = [
      {"id": 1, "port0": "1/12", "port1": "2/10", "tx_port": 0, "path": "4"},
      # ...
  ]
  ```
  程式需提供使用者選擇特定 Scenario（1-8）或全部（all）執行的選單。

### 3.2 [Phase 2] 儀器預約與前置穩定配置
- Spirent Port 預約（僅適用於儀器測試場景）：應動態傳入 `slotPortlist`。
- 多連接埠預約策略（僅適用於儀器測試場景）：若「測試參數表」多個 Scenario 中使用到不同的連接埠組合（例如部分場景用 2/10，部分場景用 8/15），必須在 Phase 1 蒐集所有被選中場景使用埠的聯集，並在 Phase 2 一次性預約（Reserve）所有可能用到的 Port，避免在迴圈內部頻繁連線與中斷 Spirent。
- 動態 Stream 建立與清除（僅適用於儀器測試場景）：為了避免單一實體 Port 因為同時綁定多個 Stream Block 造成 Spirent `getdata` 統計函式崩潰（`invalid handle` 錯誤），在 Phase 2 全局預約時應僅建立 Port 物件而不建立 Stream Block，並在 Phase 3 各場景開頭動態建立該場景的 Stream Block，於場景結束後隨即刪除。
- 穩定時間（通用）：在發送環境初始化或設備狀態切換命令後，必須等待充足的時間（如開機重啟 60~220 秒、 Couple 狀態切換 10 秒）以確保網路拓撲或 DUT 狀態收斂穩定，才開始執行測試迴圈。
- 環境連線（通用）：在此階段完成 Serial 串口（透過 `serial.Serial`）或 Telnet（透過 `telnetlib`）的連線初始化。

### 3.3 [Phase 3] 迴圈內常見操作實作指南

Phase 3 的具體步驟應保留高度彈性，不強制要求固定順序。以下為常見操作的建議寫法：

- **MAC 學習（僅適用於儀器測試場景）**：若測試需要環境先學習 MAC 地址，可先開啟雙向流量，等待 2 秒後停止，並在正式開始測試前呼叫 `clear_results_and_streams(port)` 清除該背景包數據。
- **單向與雙向流量控制（僅適用於儀器測試場景）**：
  - `StartGenerator` / `StopGenerator` 傳入需要發送流量的 Port 清單。
  - 對於單向流量測試，僅在發送端配置 StreamBlock，發送端與接收端的對應關係應與參數表中 `Port[TX]` 和 `Port[RX]` 一致。直接調用 `StartGenerator([tx_port_obj])` 與 `StopGenerator([tx_port_obj])` 即可，底層已自動處理關聯埠的 Generator 與 Analyzer，**切勿調用未定義的 `analyzerStart`**。
- **動態 Stream 控制與防崩潰示範（僅適用於儀器測試場景）**：
  - 為了防止 `getdata` 多埠統計崩潰，必須限制單一實體 Port 同時只綁定一個 Stream Block。應在各場景迴圈開頭與結尾動態配置與刪除 Stream，範例程式碼如下：
    ```python
    def setup_scenario_streams(port_0, port_1):
        sb0 = CreateStreamBlock(port_0, StreamBlock, Frame)
        sb1 = CreateStreamBlock(port_1, StreamBlock, Frame1)
        Generator(port_0, Generatortype)
        Generator(port_1, Generatortype)
        return sb0, sb1

    def cleanup_scenario_streams(sb0, sb1):
        try: tclsh.eval(f"stc::delete {sb0}")
        except: pass
        try: tclsh.eval(f"stc::delete {sb1}")
        except: pass
    ```
- **重置全域與串流統計防止統計殘留累加（僅適用於儀器測試場景）**：
  - 由於共用庫 `ClearResults` 僅清除埠級（Port-level）統計，無法清除串流級（Stream-level）的丟包累計（`droppedFrameCount`），會導致 Spirent 儀器內部統計在 Iteration 之間持續累加。
  - 解決方案是定義一個輔助函式，使用不帶參數的 Spirent 原生全域指令 `ResultsClearAll`（即 `tclsh.eval("stc::perform ResultsClearAll")`）進行清除，從而同時重置 Port 與 Stream 統計，範例程式碼如下：
    ```python
    def clear_results_and_streams(active_ports):
        """清除全域統計數據（包含埠與串流），防止丟包統計在 iteration 之間累加"""
        # 執行全域結果清除，會同時重置 Port 與 Stream 統計，避免僅清除 port-level 或 stream-level
        tclsh.eval("stc::perform ResultsClearAll")
    ```
  - 在迴圈內所有需要重置統計的步驟，均應呼叫此函式（例如 `# 3.1`、`# 3.2` 等，代替原本僅清除埠級的 `ClearResults`）。
- **設備控制（通用）**：
  - Serial 指令使用 `comm_CMD(ser, b"command\r")`。
  - Telnet 指令使用 `comm_TELNET(tn, 'expect_prompt', 'command')`。
- **丟包計算與狀態檢測**：
  - **有儀器場景**：丟包應精確計算發送端發送數與接收端接收數的差值：
    $$\text{丟包數} = \text{Port[TX]}\text{\_Tx} - \text{Port[RX]}\text{\_Rx}$$
    建議在統計前預留 1 秒的發送引擎停止時間（`time.sleep(1)`），確保所有在途封包已被計數。
  - **無儀器場景**：可使用 `comm_helper` 中封裝好的 Ping 檢測（如 `comm_PING`）或讀取控制埠的回應狀態文字，作為收斂與判定依據。
- **步驟註解強制要求**：
  - 為了讓程式碼具有清晰的可讀性，並能與檔案開頭 docstring 中的「測試流程說明」嚴格對應，**在 Phase 3 的自動化測試迴圈中，每一個步驟的前方都必須使用單行註解 `#` 明文標記步驟編號與其功能描述**（例如：`# 3.13 記錄至日誌檔` 或 `# 3.14 清除統計數據，準備進入下一輪`）。

### 3.4 封包參數定義與引用規範 (utils.dictionary_parameters)

為了避免各測試腳本自行宣告封包格式導致 MAC/IP 位址混亂或配置不一致，所有腳本必須統一引用 `utils.dictionary_parameters` 中的標準定義字典：

- **常用標準封包字典說明**：
  - `StreamBlock`：基礎封包長度與模式（預設長度 128 bytes，Fixed 模式）。
  - `Generatortype`：標準流量發送配置（預設 1000 fps，PORT_BASED 排程，CONTINUOUS 發流）。
  - `Frame` (Port0 端)：
    ```python
    {
        'Ethernet_srcMac': "00:10:94:00:00:01",
        'Ethernet_dstMAc': "01:00:5e:0b:02:01",
        'Ipv4_sourceAddr': "10.1.255.11",
        'Ipv4_dstAddr': "225.11.2.1",
        'Ipv4_destPrefixLength': 24,
        'Ipv4_gateway': "10.1.255.1",
    }
    ```
  - `Frame1` (Port1 端)：
    ```python
    {
        'Ethernet_srcMac': "00:10:94:00:00:02",
        'Ethernet_dstMAc': "00:10:94:00:00:01",
        'Ipv4_sourceAddr': "172.16.1.11",
        'Ipv4_dstAddr': "10.1.255.11",
        'Ipv4_destPrefixLength': 24,
        'Ipv4_gateway': "172.16.1.2",
    }
    ```
  - `Frame2` 與 `Frame3`：專用於純對稱單播互打對組（互換來源與目的 MAC/IP）。
- **呼叫範例**：
  ```python
  from utils.dictionary_parameters import StreamBlock, Generatortype, Frame, Frame1

  # 建立 StreamBlock 時直接帶入
  sb0 = CreateStreamBlock(port_objs[0], StreamBlock, Frame)
  sb1 = CreateStreamBlock(port_objs[1], StreamBlock, Frame1)
  ```
- **禁止事項**：嚴禁在個別測試腳本內自行定義 `FRAME_PORT0 = {...}` 這類重複字典。若有全新專案級封包格式需求，應在經評估後統一擴充於 `utils/dictionary_parameters.py` 中。

### 3.5 封包擷取 (PCAP Capture) 開發與使用規範 (utils.pythontool)

針對需要儲存 Wireshark 封包（`.pcap`）分析丟包或恢復收斂的測試場景，封包擷取功能已整合回歸至 `utils.pythontool`，編寫規範如下：

1. **共用 Capture API 速查**：
   - `create_capture_output_dir(base_dir=None, prefix="capture") -> str`：
     自動在工作區 `captures/` 目錄下建立帶時間戳記的專用子資料夾（例如 `captures/warm_start_round_robin_20260914_180000/`）。
   - `start_capture(port, buffer_mode="STOP_ON_FULL") -> str`：
     在指定 Port 啟動 RX Capture，並回傳 Capture Proxy Handle。
   - `stop_capture_and_save(capture_handle_or_port, filename) -> int`：
     停止 Capture、將封包寫入 `.pcap` 檔案（自動處理含空格路徑防護 `tcl_braced`），並回傳實際擷取到的封包總數。
2. **關鍵原則與防呆機制**：
   - **Capture 對象連接埠判定 (RX vs TX)**：
     - Spirent 的 Capture 機制是**擷取該連接埠「接收端 (RX)」進來的封包**。
     - 若測試是單向流量（Port TX -> DUT -> Port RX），為了觀察 DUT 轉發中斷與恢復過程，**必須對接收端 `port_rx` 啟動 Capture**。若誤開在發送端 `port_tx`，將無法錄到發出的 Generator 流量。
     - 若為雙向互打測試，則兩邊 Port 均應各自啟動 Capture。
   - **例外安全儲存機制 (Emergency Teardown)**：
     在測試迴圈外宣告 `active_captures = []`，每當啟動 Capture 即將 `(cap_handle, save_path)` 存入。在 `finally` 區塊中務必遍歷 `active_captures` 進行未儲存檔案的緊急存檔，確保測試異常中斷時封包不遺失：
     ```python
     finally:
         for cap_handle, save_path in active_captures:
             try:
                 emergency_pkts = stop_capture_and_save(cap_handle, save_path)
                 print(f"異常終止已保存 Capture: {save_path} ({emergency_pkts} pkts)")
             except Exception:
                 pass
     ```
   - **檔案儲存位置**：PCAP 封包檔案一律存放於集中式輸出目錄，呼叫 `get_result_dir(__file__, "captures")` 自動存放於 `test result/<當前測試目錄>_result/captures/`，嚴禁寫入硬編碼絕對路徑或直接放根目錄。

---

## 4. 日誌記錄規範

所有腳本產生的日誌必須統一收納於專案根目錄的 `test result/<當前測試目錄>_result/result.txt`。**宣告日誌檔案路徑時，必須調用共用函式 `get_result_log_path(__file__, "result.txt")`**，嚴禁在程式碼中寫入任何硬編碼絕對路徑，也不得隨意直接在工作區根目錄或腳本同層就地產生日誌，確保原始程式碼與測試產出完全解耦。

每一輪測試日誌與檔案標頭必須包含：
1. **測試啟動時間**：每次測試大批次啟動時，於標頭記錄起始日期與時間（精確至秒，格式：`YYYY-MM-DD HH:MM:SS`）。
2. **回合寫入時間與識別**：每一輪結果寫入時的時間戳記，以及當前的 Scenario 與 Iteration 資訊。
3. **操作指令發送精確時間**：下達狀態切換指令（例如：Link Down `t4x`、Link Up `t4-`、Couple `t-`、Decouple `tx`）**瞬間**的精確時間戳記（精確至毫秒 ms，格式：`HH:MM:SS.fff`），以利比對封包丟失與網路恢復的精確收斂點。
4. **精確的測試數據**：
   - **有儀器場景**：必須清楚記錄 Port[0] 與 Port[1] 的詳細統計 `[RxCount, TxCount]`。
     - *註：嚴禁在日誌中記錄 `RxDrop` (DroppedFrameCount) 欄位。因為當設備斷電或完全斷連 (Blackout) 時，接收端無任何封包，Spirent 的 sequence gap 偵測會因此不準確（無法即時統計斷線期間的丟包，只會在重新收包後累加或殘留歷史值），極易造成誤解。真實丟包請一律透過 `TxCount - RxCount` 計算得出。*
   - **無儀器場景**：記錄 Ping 丟失率（%）、重連時間或 Serial 回應的狀態判定文字。
5. **判定結果與丟包數**：
   - 如：`Link Down: X pkts`、`Link Up: Y pkts`（非儀器測試則寫入如 `PING Loss: X %` 或 `Recovery: PASS/FAIL`）。
6. **分界線**：每次大批次測試開始前，需寫入明顯的等號分隔線（如 `{'='*50}` 或 `{'='*60}`）。

---

## 5. 交付前靜態程式碼走查規範 (Pre-Delivery Static Code Review Checklist)

> [!IMPORTANT]
> **靜態走查，嚴禁未審交付；毋須實際執行 script**：  
> AI 在完成任何測試腳本編寫後、回覆使用者之前，**必須逐行靜態審查自身代碼 (Self Code Review)**。**不需要且不應執行測試腳本**，但必須依據以下 5 大核心查核點嚴格進行自我比對確認，確保無任何參數違規或命名臆測後，方可交付：

1. **查核點 1：互動輸入函式簽名審查 (comm_helper Signature Review)**
   - 審查腳本中所有來自 `utils.comm_helper` 的輸入函式呼叫（如 `get_com_port()`、`get_iteration_count()`、`get_delay_time()`、`get_target_ip()`、`get_boot_wait_time()` 等）。
   - **審查標準**：確認所有上述函式調用均為 **0 個參數**（如 `get_com_port()`），**嚴格確認未帶入任何自定義 prompt 字串或多餘參數**。

2. **查核點 2：儀器控制 API 簽名與大小寫審查 (pythontool Signature Review)**
   - 審查流量控制：必須是 `StartGenerator([port])` 與 `StopGenerator([port])`，傳入值必須為 **List[port_obj]**；**絕對禁止調用不存在的 `StartTraffic()` 或 `StopTraffic()`**。
   - 審查數據讀取：必須是 `getdata(ports_pair)`，傳入值必須為包含埠對的 **List[port_obj]**。
   - 審查資源釋放：必須使用全小寫 `unsubscribe(res)`（**絕對禁止大寫 `Unsubscribe`**）；中斷連線必須調用 `Disconnect(chassisAddr)`（**絕對禁止 `ReleasePort`**）；專案刪除必須調用原生 `tclsh.eval(f"stc::delete {project}")`（**絕對禁止 `DestroyProject`**）。

3. **查核點 3：外部參數表防禦性解析審查 (CSV Defensive Parsing Review)**
   - 審查 `load_scenarios_from_csv`：確認字典推導式使用 `(str(v).strip() if v is not None else "")`，且鍵過濾為 `if k is not None`。
   - **審查標準**：確認包含 `if not clean_row or not clean_row.get("Scenario"): continue`，排除尾隨空行或無效資料列，**絕對嚴禁直接對 `v` 呼叫 `v.strip()`**。

4. **查核點 4：工作區路徑與集中式產出審查 (Path & Centralized Output Review)**
   - 審查日誌與封包路徑：確認呼叫 `log_filename = get_result_log_path(__file__, "result.txt")`，封包資料夾呼叫 `get_result_dir(__file__, "captures")`。**嚴禁在工作區根目錄隨意生成日誌，且絕對不可寫入 `utils/` 資料夾**。所有產出必須統一集中在 `test result/<測試案例資料夾>_result/` 階層底下。
   - 審查腳本目錄變數：確認使用大寫 `SCRIPT_DIR`（而非易受覆蓋的 `current_dir`）。
   - 審查 `load_utils()`：確認包含 `excluded = {'current_dir', 'tool_tcl_path', 'lib_pathes', 'scripts', 'path'}`，防止 `utils` 內部路徑變數污染主腳本。

5. **查核點 5：資源安全清理完整性審查 (Teardown Integrity Review)**
   - 審查主流程是否包含完整的 `try...except...finally` 結構。
   - 確認在 `finally` 區塊中，對所有在 Phase 2 成功開啟的資源（`ser.close()`、`unsubscribe()`、`stc::delete {project}`、`Disconnect()`）都有在獨立 `try...except` 保護下進行安全釋放。

6. **查核點 6：跨目錄相容性審查 (Cross-Directory Compatibility Review)**
   - 審查動態路徑引入：確認腳本頂部使用動態向上遞迴搜尋 `utils/comm_helper.py`，嚴禁寫死 `../..` 等固定層級路徑，確保腳本置於 `test script/`、`example/` 或更深層子目錄均能順利執行。
   - 審查參數表載入：確認參數表讀取具備多層候選路徑遍歷，確保在不同目錄下均能正確讀取 `scenarios.csv`。
