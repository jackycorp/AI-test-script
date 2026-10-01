# -*- coding: utf-8 -*-
"""
自動化測試通用輔助模組 (Common Helper & Communication Module)

本模組整合並分類了原多個自動化測試腳本中的重複輔助函式，區分為兩大類別：
1. 設備連線、串口/Telnet通訊與網路檢測 (Device Connection, Communication & Network Checks)
   - 包含串列埠指令傳送、Telnet連線與指令交互、Telnet登入以及 Ping 檢測等。
2. 使用者互動輸入與參數獲取 (CLI User Inputs)
   - 包含獲取 COM 埠、執行次數、等待時間、IP位址以及各種自定義指令前綴與插座範疇的CLI互動輸入防呆函式。

使用說明：
在各測試腳本中導入此模組即可直接使用所有封裝函式：
    from comm_helper import *
"""

import sys
import os
import time
import re
import telnetlib
from typing import List, Tuple, Optional

# 嘗試載入專案所需之外部通訊套件
try:
    import serial
except ImportError:
    print("[WARNING] 無法載入 pyserial 套件，串口功能將無法正常使用。")

try:
    from icmplib import ping
except ImportError:
    print("[WARNING] 無法載入 icmplib 套件，Ping 檢測功能將無法正常使用。")


# =====================================================================
# 類別 1: 設備連線、串口/Telnet通訊與網路檢測 (Connection, Communication & Network Checks)
# =====================================================================

def comm_CMD(ser, String: bytes) -> List[str]:
    """
    傳送 Serial 指令至待測設備 (DUT)，並即時顯示及收集回傳內容。
    
    Args:
        ser: 已開啟的 serial.Serial 物件。
        String (bytes): 欲發送的二進位指令（通常以 \\r 結尾）。
        
    Returns:
        List[str]: 包含所有接收到之設備回應文字行的清單。
    """
    feedback_lines = []
    try:
        ser.flushInput()
        ser.flushOutput()
        ser.write(String)
        time.sleep(0.5)
        while ser.in_waiting:
            feedback = ser.readline().decode(errors='ignore')
            feedback_lines.append(feedback)
            print(f'DUT Respond: {feedback.strip()}')
    except Exception as e:
        print(f"串口通訊異常: {e}")
    return feedback_lines


def comm_TELNET(tn: telnetlib.Telnet, expectstring: str = "Enter", CMD: str = "\n", timeout: float = 3.0) -> bool:
    """
    透過 Telnet 發送指令，並在指定超時內等待特定的預期應答字串。
    
    Args:
        tn (telnetlib.Telnet): 已建立的 Telnet 連線物件。
        expectstring (str): 預期等待的字串，若為 "Enter" 則不進行關鍵字匹配，直接發送。
        CMD (str): 欲發送的指令文字。
        timeout (float): 等待回應的超時時間（秒）。
        
    Returns:
        bool: 是否成功偵測到預期字串並發送指令。
    """
    start_time = time.time()
    all_responses = b""
    while (time.time() - start_time) < timeout:
        raw_feedback = tn.read_very_eager()
        if raw_feedback:
            all_responses += raw_feedback
            try:
                decoded = raw_feedback.decode(errors='ignore')
                if decoded.strip():
                    print(f"[DUT Output]: {decoded.strip()}")
            except:
                pass

        decoded_total = all_responses.decode(errors='ignore')
        if expectstring == "Enter" or (expectstring.lower() in decoded_total.lower()):
            time.sleep(0.5)
            tn.write(CMD.encode('ascii') + b"\n")
            print(f"[Action] 發送指令: '{CMD}'")
            time.sleep(0.5)
            return True
        time.sleep(0.5)
    print(f"[WARNING] 逾時未偵測到預期字串 '{expectstring}'")
    return False


def telnet_login(target_ip: str, username: str = "admin", password: str = "moxa") -> Optional[telnetlib.Telnet]:
    """
    嘗試 Telnet 登入設備，並執行使用者自訂或 admin/moxa 預設帳密之登入交握。
    
    Args:
        target_ip (str): 設備目標 IP 位址。
        username (str): 登入帳號，預設為 'admin'。
        password (str): 登入密碼，預設為 'moxa'。
        
    Returns:
        Optional[telnetlib.Telnet]: 登入成功回傳 Telnet 連線物件，失敗則回傳 None。
    """
    print(f"正在嘗試登入設備: {target_ip} (帳號: {username}) ...")
    try:
        tn = telnetlib.Telnet(target_ip, timeout=10)
        time.sleep(2)
        comm_TELNET(tn, 'login', username)
        time.sleep(2)
        comm_TELNET(tn, 'Password', password)
        time.sleep(2)
        comm_TELNET(tn)  # 發送 Enter 鍵確認
        print(f"Telnet 登入成功 ({target_ip})。")
        return tn
    except Exception as e:
        print(f"Telnet 登入失敗 ({target_ip}): {e}")
        return None


def Pingfunc(host: str, times: int = 1, interval: float = 1.0) -> bool:
    """
    執行 Ping 檢測，判定目標主機是否在線。
    
    Args:
        host (str): 目標 IP 或主機名稱。
        times (int): 連續檢測的次數。
        interval (float): 每次檢測的間隔時間（秒）。
        
    Returns:
        bool: 若其中一次 Ping 成功在線則回傳 True，否則回傳 False。
    """
    is_alive = False
    for i in range(times):
        try:
            PingTest = ping(host, count=1)
            if PingTest.is_alive:
                print(f"ping {host} success")
                is_alive = True
            else:
                print(f"ping {host} fail")
                is_alive = False
        except Exception as e:
            print(f"ping 檢測異常: {e}")
            is_alive = False
        if times > 1:
            time.sleep(interval)
    return is_alive


# =====================================================================
# 類別 2: 使用者互動輸入與參數獲取 (CLI User Inputs)
# =====================================================================

def get_com_port() -> str:
    """
    提示使用者在命令列輸入有效的 COM 埠名稱（防呆不可為空）。
    
    Returns:
        str: 使用者輸入的埠名（例如 'COM11'）。
    """
    while True:
        port = input("請輸入 COM 埠 (例如 COM11): ").strip()
        if port:
            return port
        print("輸入不可為空。")


def get_iteration_count() -> int:
    """
    提示使用者輸入執行次數（防呆必須為正整數）。
    
    Returns:
        int: 使用者輸入之正整數次數。
    """
    while True:
        try:
            count = int(input("請輸入執行次數 (正整數): ").strip())
            if count > 0:
                return count
        except ValueError:
            print("請輸入有效的整數。")


def get_delay_time() -> float:
    """
    提示使用者輸入收斂/等待延遲時間（防呆必須為非負浮點數）。
    
    Returns:
        float: 輸入的秒數。
    """
    while True:
        try:
            delay = float(input("請輸入等待時間 (秒，例如 30): ").strip())
            if delay >= 0:
                return delay
        except ValueError:
            print("請輸入有效的數字。")


def get_boot_wait_time() -> float:
    """
    提示使用者輸入開機/重啟等待時間（防呆必須為正數）。
    
    Returns:
        float: 輸入的秒數。
    """
    while True:
        try:
            delay = float(input("請輸入開機等待時間 (秒，例如 60 或 220): ").strip())
            if delay > 0:
                return delay
        except ValueError:
            print("請輸入有效的數字。")


def get_target_ip() -> str:
    """
    提示使用者輸入目標 IP 位址（防呆不可為空）。
    
    Returns:
        str: 目標 IP 位址。
    """
    while True:
        ip = input("請輸入目標 IP 位址 (例如 192.168.127.253): ").strip()
        if ip:
            return ip
        print("輸入不可為空。")


def get_link_down_up_commands() -> Tuple[str, str]:
    """
    提示使用者輸入 Link 指令前綴，並自動組合生成 Link Down 與 Link Up 指令對。
    
    Returns:
        Tuple[str, str]: (Link Down 指令, Link Up 指令)
    """
    prefix = input("請輸入指令前綴 (例如輸入 t 會自動生成 tx/t-; 輸入 t1生成 t1x/t1-): ").strip()
    if not prefix:
        prefix = "t"  # 預設為 t
    
    down_cmd = f"{prefix}x"
    up_cmd = f"{prefix}-"
    print(f"-> 已設定 Link Down 指令: {down_cmd}")
    print(f"-> 已設定 Link Up 指令: {up_cmd}")
    return down_cmd, up_cmd


def get_power_on_off_commands() -> Tuple[str, str]:
    """
    提示使用者輸入電源指令前綴，並自動組合生成 Power On 與 Power Off 指令對。
    
    Returns:
        Tuple[str, str]: (Power On 指令, Power Off 指令)
    """
    prefix = input("請輸入電源指令前綴 (例如輸入 p1 會自動生成 p1 on/p1 off): ").strip()
    if not prefix:
        prefix = "p1"  # 預設為 p1
    
    on_cmd = f"{prefix} on"
    off_cmd = f"{prefix} off"
    print(f"-> 已設定 Power On 指令: {on_cmd}")
    print(f"-> 已設定 Power Off 指令: {off_cmd}")
    return on_cmd, off_cmd


def get_power_outlets() -> List[str]:
    """
    提示使用者輸入電源指令範圍，可解析 'p1 to p4' 及 'p1, p2' 格式並生成插座清單。
    
    Returns:
        List[str]: 插座名稱清單（如 ['p1', 'p2', 'p3', 'p4']）。
    """
    while True:
        user_input = input("請輸入電源指令範圍 (例如 p1 to p4): ").strip()
        if not user_input:
            print("輸入不可為空。預設為 p1。")
            return ["p1"]
        
        # 嘗試解析 "p1 to p4" 格式
        match = re.match(r"^([a-zA-Z]+)(\d+)\s+to\s+([a-zA-Z]+)(\d+)$", user_input, re.IGNORECASE)
        if match:
            prefix1, start_str, prefix2, end_str = match.groups()
            if prefix1.lower() == prefix2.lower():
                start = int(start_str)
                end = int(end_str)
                step = 1 if start <= end else -1
                return [f"{prefix1}{i}" for i in range(start, end + step, step)]
        
        # 嘗試以逗號分隔解析
        parts = [p.strip() for p in user_input.split(",") if p.strip()]
        if parts:
            return parts
            
        print("無法解析輸入格式，請使用例如 'p1 to p4' 或 'p1, p2' 的格式。")


def get_telnet_credentials(default_user: str = "admin", default_pwd: str = "moxa") -> Tuple[str, str]:
    """
    提示使用者輸入 DUT 登入帳號與密碼 (支援直接 Enter 套用預設值)。
    
    Args:
        default_user (str): 預設使用者帳號，預設為 'admin'。
        default_pwd (str): 預設密碼，預設為 'moxa'。
        
    Returns:
        Tuple[str, str]: (username, password)
    """
    user_input = input(f"請輸入 DUT 登入帳號 (直接 Enter 預設 '{default_user}'): ").strip()
    username = user_input if user_input else default_user

    pwd_input = input(f"請輸入 DUT 登入密碼 (直接 Enter 預設 '{default_pwd}'): ").strip()
    password = pwd_input if pwd_input else default_pwd

    print(f"-> 已設定 Telnet 登入帳號: '{username}'")
    return username, password


# ========================================================
# 測試產出目錄與日誌路徑共通定位函式 (Test Result Centralized Path)
# ========================================================

def get_result_dir(script_file: str, sub_dir: str = None) -> str:
    """
    自動定位專案根目錄，並建立 test result/<當前測試目錄>_result/ 目錄。
    
    Args:
        script_file (str): 呼叫此函式之腳本檔案路徑 (通常傳入 __file__)。
        sub_dir (str, optional): 若需在 _result/ 資料夾下建立子目錄 (如 'captures' 或 'log') 可指定。
        
    Returns:
        str: 建立後之目標目錄絕對路徑字串。
    """
    script_path = os.path.abspath(script_file)
    script_dir = os.path.dirname(script_path)
    base_name = os.path.basename(script_dir)

    # 向上搜尋帶有 utils 的專案根目錄
    cur = script_dir
    root_dir = script_dir
    while cur and os.path.dirname(cur) != cur:
        if os.path.exists(os.path.join(cur, "utils", "comm_helper.py")):
            root_dir = cur
            break
        cur = os.path.dirname(cur)

    # 規範命名：test result/<測試資料夾名稱>_result/
    target_dir = os.path.join(root_dir, "test result", f"{base_name}_result")
    if sub_dir:
        target_dir = os.path.join(target_dir, sub_dir)

    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def get_result_log_path(script_file: str, filename: str = "result.txt", sub_dir: str = None) -> str:
    """
    自動定位專案根目錄，並在 test result/<當前測試目錄>_result/ 下建立輸出檔案路徑。
    
    Args:
        script_file (str): 呼叫此函式之腳本檔案路徑 (傳入 __file__)。
        filename (str): 日誌或報表檔案名稱，預設為 'result.txt'。
        sub_dir (str, optional): 若需指定子資料夾 (如 'captures' 或 'log') 可傳入。
        
    Returns:
        str: 輸出的日誌或結果檔案完整路徑字串。
    """
    target_dir = get_result_dir(script_file, sub_dir=sub_dir)
    return os.path.join(target_dir, filename)

