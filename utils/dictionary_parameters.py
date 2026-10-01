##portType
PortType_1G_Full_AN = {
	'Duplex' : "FULL", 
	'AutoNegotiation' : "TRUE", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_1G", 
	'FlowControl' : "false"
}
PortType_1G_Full_AN_Pause = {
	'Duplex' : "FULL", 
	'AutoNegotiation' : "TRUE", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_1G", 
	'FlowControl' : "TRUE"
}
PortType_10M_Full = {
	'Duplex' : "FULL", 
	'AutoNegotiation' : "false", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_10M", 
	'FlowControl' : "false"
}
PortType_10M_Full_AN = {
	'Duplex' : "FULL", 
	'AutoNegotiation' : "TRUE", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_10M", 
	'FlowControl' : "false"
}
PortType_10M_Full_AN_Pause = {
	'Duplex' : "FULL", 
	'AutoNegotiation' : "TRUE", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_100M", 
	'FlowControl' : "TRUE"
}
PortType_10M_Half = {
	'Duplex' : "HALF", 
	'AutoNegotiation' : "false", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_10M", 
	'FlowControl' : "false"
}
PortType_10M_Half_AN = {
	'Duplex' : "HALF", 
	'AutoNegotiation' : "TRUE", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_10M", 
	'FlowControl' : "false"
}
PortType_100M_Full = {
	'Duplex' : "FULL", 
	'AutoNegotiation' : "false", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_100M", 
	'FlowControl' : "false"
}
PortType_100M_Full_AN = {
	'Duplex' : "FULL", 
	'AutoNegotiation' : "TRUE", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_100M", 
	'FlowControl' : "false"
}
PortType_100M_Full_AN_Pause = {
	'Duplex' : "FULL", 
	'AutoNegotiation' : "TRUE", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_100M", 
	'FlowControl' : "TRUE"
}
PortType_100M_Half = {
	'Duplex' : "HALF", 
	'AutoNegotiation' : "false", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_100M", 
	'FlowControl' : "false"
}
PortType_100M_Half_AN = {
	'Duplex' : "HALF", 
	'AutoNegotiation' : "TRUE", 
	'AutoNegotiationMasterSlave' : "MASTER",
	'LineSpeed' : "Speed_100M", 
	'FlowControl' : "false"
}

####StreamBlock Dictionary
StreamBlock = {
	'Active' : "TRUE", 
	'EnableFcsErrorInsertion' : "false", 
	'FixedFrameLength' :128,
	'FrameLengthMode' : "Fixed",
	'MaxFrameLength' : 256,
	'MinFrameLength' : 128,
}
###Streamblock frame header Dictionary
Frame = {
	'Ethernet_srcMac' : "00:10:94:00:00:01",
	'Ethernet_dstMAc' : "01:00:5e:0b:02:01", 
	'Ipv4_sourceAddr' : "10.1.255.11",
	'Ipv4_dstAddr': "225.11.2.1",
	'Ipv4_destPrefixLength': 24,
	'Ipv4_gateway': "10.1.255.1",
}
Frame1 = {
	'Ethernet_srcMac' : "00:10:94:00:00:02",
	'Ethernet_dstMAc' : "00:10:94:00:00:01",
	'Ipv4_sourceAddr' : "172.16.1.11",
	'Ipv4_dstAddr': "10.1.255.11",
	'Ipv4_destPrefixLength': 24,
	'Ipv4_gateway': "172.16.1.2",
}
Vlan = {
	'type': "8100",
    'cfi': "0",
    'id' : 2, 
   	'pri': "000",
}
Generatortype = {
	'BurstSize' : 1,
	'Duration' : 30,
	'DurationMode' : "CONTINUOUS",
	'FixedLoad' : 1000,
	'LoadUnit' : "FRAMES_PER_SECOND", # "PERCENT_LINE_RATE" or "FRAMES_PER_SECOND" 
	'SchedulingMode' : "PORT_BASED",
}
Igmpv1 = {
	'version' : 1,
	'type' : 2,
	'groupAddress' : "255.0.0.1",
}

Frame2 = {
	'Ethernet_srcMac' : "00:10:94:00:00:03",
	'Ethernet_dstMAc' : "00:00:01:00:00:02",
	'Ipv4_sourceAddr' : "192.85.1.2",
	'Ipv4_dstAddr': "192.0.0.1",
	'Ipv4_destPrefixLength': 24,
	'Ipv4_gateway': "192.85.1.1",
}
Frame3 = {
	'Ethernet_srcMac' : "00:00:01:00:00:02",
	'Ethernet_dstMAc' : "00:10:94:00:00:03",
	'Ipv4_sourceAddr' : "192.85.1.3",
	'Ipv4_dstAddr': "192.0.0.1",
	'Ipv4_destPrefixLength': 24,
	'Ipv4_gateway': "192.85.1.1",
}