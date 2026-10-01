import tkinter as tk
import threading
# from tkthread import tk, TkThread
tclsh=tk.Tcl()

lib_pathes=[
	'C:/Program Files/Spirent Communications/Spirent TestCenter 5.04/TCL/lib',
	'C:/Program Files/Spirent Communications/Spirent TestCenter 5.04/TCL/lib/tcl8.5'
]
#	'C:/Program Files (x86)/Spirent Communications/Spirent TestCenter 4.87/TCL/lib',
#	'C:/Program Files (x86)/Spirent Communications/Spirent TestCenter 4.87/TCL/lib/tcl8.4'

for path in lib_pathes:
	scripts='set auto_path [linsert $auto_path 0 "{}"]'.format(path)
	tclsh.eval(scripts)
# print(t.tk.exprstring('$tcl_library'))
# t.eval('puts $auto_path')
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
tool_tcl_path = os.path.join(current_dir, 'tool.tcl').replace('\\', '/')
tclsh.eval(f'source "{tool_tcl_path}"')
tclsh.eval('Init')

#############################
### Connect to the chassis
#############################
def Connect(chassisAddr):
	tclsh.eval('Connect %s' %chassisAddr)
#############################
### Disconnect to the chassis
#############################
def Disconnect(chassisAddr):
	tclsh.eval('Disconnect %s' %chassisAddr)
#############################
### Reserve PHYSICAL ports
#############################
def ReservePort(chassisAddr,slotPortlist):
	for port in slotPortlist:
		tclsh.eval('ReservePort {0} {1}'.format(chassisAddr, port))
#############################
### Set a Timer 
#############################
def Timer(testTime, port1, port2):
	tclsh.eval('SetTimer {0} {1} {2}'.format(testTime, port1, port2))
#############################
### Set ports type
#############################
def CreatePortType_Copper(port,dict):
	# for i in range(len(port)):
	copper=tclsh.eval('CreatePortType_Copper {0} {1} {2} {3} {4} {5}'.format(port, dict['Duplex'], 
		dict['AutoNegotiation'], dict['AutoNegotiationMasterSlave'], dict['LineSpeed'], dict['FlowControl']))
	return copper
def CreatePortType_Fiber(port):
	fiber = tclsh.eval('CreatePortType_Fiber {0}'.format(port))
	return fiber
#############################
### Create StreamBlock
#############################
def CreateStreamBlock(port, dict1, dict2) :
	streamblock = tclsh.eval('CreateStreamBlock {0} {1} {2} {3} {4} {5} {6} {7} {8} {9} {10} {11} {12}'
		.format(port, dict1['Active'], dict1['EnableFcsErrorInsertion'],dict1['FixedFrameLength'] , dict1['FrameLengthMode'], 
		dict1['MaxFrameLength'], dict1['MinFrameLength'], dict2['Ethernet_srcMac'], dict2['Ethernet_dstMAc'], dict2['Ipv4_sourceAddr'], dict2['Ipv4_dstAddr'], 
		dict2['Ipv4_destPrefixLength'], dict2['Ipv4_gateway']))
	return streamblock
#############################
### Create StreamBlock Headers
#############################
def addVlan(streamblock, dict):
	tclsh.eval('addVlan {0} {1} {2} {3} {4}'.format(streamblock, dict['type'], dict['cfi'], dict['id'], dict['pri']))
def addTcpHeader(streamblock):
	tclsh.eval('addTcp {0}'.format(streamblock))
def addIGMPv1Header(streamblock, dict):
	tclsh.eval('addIGMPv1 {0} {1} {2} {3}'.format(streamblock, dict['version'], dict['type'], dict['groupAddress']))
def addtosdiffServ(streamblock, reserved) :
	tclsh.eval('addtosdiffserv {0} {1}'.format(streamblock, reserved))
#############################
### Trafic Generator Config
#############################
def Generator(port, dict) :
	tclsh.eval('Generator {0} {1} {2} {3} {4} {5} {6}'.format(port, dict['BurstSize'], dict['Duration'], dict['DurationMode'], dict['FixedLoad'], dict['LoadUnit'], dict['SchedulingMode']))
#############################
### start Trafic Generator & Analyzer
#############################
def StartGenerator(*argv) :
	f = ""
	flag = 0
	for args in argv:
		if(isinstance(args, list)) :
			f = " ".join(str(x) for x in args)
			# print(f)
			break
		elif(isinstance(args, str)) :
			flag = 1
			break
	if flag == 1:
		f = " ".join(str(args) for args in argv)
	tclsh.eval('startGenerator {0}'.format(f))
###################################
### stop Trafic Generator & Analyzer
###################################
def StopGenerator(portlist):
	f = " ".join(str(x) for x in portlist)
	tclsh.eval('stopGenerator {0}'.format(f))
###################################
### subscribe results(write to csv) 
###################################
def ResultSubscribe_Rx(project, filename):
	result = tclsh.eval('ResultSubscribe_Rx {0} {1}'.format(project, filename))
	return result
def ResultSubscribe_Tx(project, filename):
	result = tclsh.eval('ResultSubscribe_Tx {0} {1}'.format(project, filename))
	return result
def ResultSubscribe_Rxstreams(project, filename):
	result = tclsh.eval('ResultSubscribe_Rxstreams {0} {1}'.format(project, filename))
	return result
###########################################
### unsubscribe results(stop writing to csv) 
###########################################
def unsubscribe(result):
	tclsh.eval('unsubscribe {0}'.format(result))
#############################
### get realtime data
#############################
def getdata(*argv):
	f = ""
	flag = 0
	for args in argv:
		if(isinstance(args, list)) :
			f = " ".join(str(x) for x in args)
			# print(f)
			break
		elif(isinstance(args, str)) :
			flag = 1
			break
	if flag == 1:
		f = " ".join(str(args) for args in argv)
	data = tclsh.eval('getdata {0}'.format(f))
	data = data.replace("{", "")
	data = data.replace("}", "")
	datalist = data.split()
	composite_list = [datalist[x:x+3] for x in range(0, len(datalist),3)]
	return composite_list
######################################
### Clear previous all traffic results
######################################
def ClearResults(*argv):
	f = ""
	flag = 0
	for args in argv:
		if(isinstance(args, list)) :
			f = " ".join(str(x) for x in args)
			# print(f)
			break
		elif(isinstance(args, str)) :
			flag = 1
			break
	if flag == 1:
		f = " ".join(str(args) for args in argv)
	tclsh.eval('ClearResults {0}'.format(f))
###################
### Capture packets
###################
def tcl_braced(value: str) -> str:
	"""將路徑或字串轉為單一 Tcl 參數，支援空白字元並標準化反斜線。"""
	normalized_value = str(value).replace("\\", "/")
	if "{" in normalized_value or "}" in normalized_value:
		raise ValueError(f"路徑不可包含大括號: {normalized_value}")
	return "{{{}}}".format(normalized_value)


def start_capture(port: str, buffer_mode: str = "STOP_ON_FULL") -> str:
	"""在指定 Spirent Port 啟動 RX Capture 並回傳 Capture Proxy Handle。
	
	Args:
		port: Spirent Port 物件 Handle。
		buffer_mode: 緩衝區模式，預設 "STOP_ON_FULL" 或可選 "CIRCULAR"。
		
	Returns:
		str: Capture 物件 Handle。
	"""
	capture = tclsh.eval(f"stc::get {port} -children-Capture").strip()
	if not capture:
		raise RuntimeError(f"Port {port} 找不到 Capture 物件")
	tclsh.eval(f"stc::config {capture} -BufferMode {buffer_mode}")
	tclsh.eval("stc::apply")
	tclsh.eval(f"stc::perform CaptureStart -CaptureProxyId {capture}")
	return capture


def stop_capture_and_save(capture_handle_or_port: str, filename: str) -> int:
	"""停止指定 Port 或 Capture 物件的封包擷取、保存為 PCAP 檔案，並回傳擷取封包數量。
	
	Args:
		capture_handle_or_port: Capture 物件 Handle 或是 Port 物件 Handle。
		filename: 欲儲存的 PCAP 完整路徑 (支援包含空格路徑)。
		
	Returns:
		int: 擷取到的封包總數。
	"""
	if "capture" in capture_handle_or_port.lower():
		capture = capture_handle_or_port
	else:
		capture = tclsh.eval(f"stc::get {capture_handle_or_port} -children-Capture").strip()
		if not capture:
			raise RuntimeError(f"Port {capture_handle_or_port} 找不到 Capture 物件")

	tclsh.eval(f"stc::perform CaptureStop -CaptureProxyId {capture}")
	tclsh.eval(
		"stc::perform CaptureDataSave "
		f"-CaptureProxyId {capture} "
		f"-FileName {tcl_braced(filename)} "
		"-FileNameFormat PCAP -IsScap FALSE"
	)
	pkt_count = int(tclsh.eval(f"stc::get {capture} -PktCount"))
	return pkt_count


def create_capture_output_dir(base_dir: str = None, prefix: str = "capture") -> str:
	"""建立帶有時間戳記的 PCAP 輸出目錄。"""
	from datetime import datetime
	timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
	if base_dir is None:
		base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "captures")
	output_dir = os.path.join(base_dir, f"{prefix}_{timestamp}")
	os.makedirs(output_dir, exist_ok=True)
	return os.path.abspath(output_dir)


def CaptureStart(port, buffermode="STOP_ON_FULL"):
	"""保留舊介面相容性"""
	return start_capture(port, buffermode)


def CaptureStop(port, filename):
	"""保留舊介面相容性"""
	return stop_capture_and_save(port, filename)

