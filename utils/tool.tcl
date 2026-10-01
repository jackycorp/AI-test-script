package require SpirentTestCenter

proc Init {} {
    # Retrieve and display the current API version.
    puts "SpirentTestCenter version:\
          [stc::get system1 -Version]"
}

proc ListTestModuleInfo {mgrHandleList} {
    # Get the handle to the physical chassis
    set chassisHandle [stc::get system1 -children-PhysicalChassisManager]
    set mgrHandleList [stc::get $chassisHandle -children-PhysicalChassis]
    foreach mgrHandle $mgrHandleList {
        puts $mgrHandle
        set modHandleList [stc::get $mgrHandle \
        -children-PhysicalTestModule]
        foreach modHandle $modHandleList {
            puts $modHandle
            array set mEntry [stc::get $modHandle ]
            puts "Card($mEntry(-Index)) $mEntry(-ProductId):$mEntry(-SerialNum):\
                $mEntry(-FirmwareVersion):$mEntry(-Status):$mEntry(-Description)"
            set pgroupList [stc::get $modHandle -children-physicalportgroup ]
            foreach pg $pgroupList {
                array set pgEntry [stc::get $pg]
                puts "\t$pgEntry(-Name) $pgEntry(-OwnershipState) $pgEntry(-Status)\
                    Reserved:$pgEntry(-ReservedByUser) $pgEntry(-OwnerUserId) $pgEntry(-OwnerHostname)"
                set portList [stc::get $pg -children-physicalport]
                foreach ptEntry $portList {
                    array set pEntry [stc::get $ptEntry]
                    puts "\t\t$pEntry(-Name) $pEntry(-Location)"
                }
            }
        }
    }
}
#####################
## Connect to chassis
#####################
proc Connect {chassisAddr} {
    # puts $chassisAddr
    if {[catch { stc::connect $chassisAddr } error]} {
        puts "Connection to chassis failed: $error"
        exit
    } else {
        puts "Connecting to chassis $chassisAddr"
        set chassis [ stc::connect $chassisAddr ]
    }
}
########################
## Disconnect to chassis
########################
proc Disconnect {chassisAddr} {
    puts "Disconnecting from chassis $chassisAddr"
    array set cmdResp [ stc::perform ChassisDisconnectAll ]
}
#################
## Reserve ports
#################
proc ReservePort {chassisAddr slotPort} {
    stc::reserve "//$chassisAddr/$slotPort"
    puts "\tPort($slotPort) reservation complete"
}
##################################
## No need to change variable here
##################################
proc CreateProject {} {
    puts "Creating project..."
    set project [stc::create project]
    puts "\tProject($project) created."
    return $project
}
proc CreatePort {slotport project chassisAddr} {
    puts "Creating the ports"
    set port [stc::create Project.Port -under $project]
    set portReturn [stc::config $port \
                    -location "$chassisAddr/$slotport"]

    puts "\tPort($port) configuration complete"
    return $port
}
proc Mapping {} {
    puts "Logical to physical port mappings started..."
    set resultReturn [stc::perform setupPortMappings]
    stc::apply
    puts "Logical to physical port mapping complete"
    return $resultReturn
}
################################################
#### Create the port type under the port object.
################################################
proc CreatePortType_Copper {port duplex an anms speed fc} {
    set ethernetCopper [stc::create EthernetCopper \
        -under $port \
        -Duplex $duplex \
        -AutoNegotiation $an \
        -AutoNegotiationMasterSlave $anms \
        -LineSpeed $speed \
        -FlowControl $fc \
        -Name  "ethernetCopper"]
    # stc::apply
    return $ethernetCopper
}
proc CreatePortType_Fiber {port} {
    set ethernetFiber [stc::create EthernetFiber \
        -under $port\
        -Name "ethernetFiber"]
    set result [stc::get $ethernetFiber]
    # puts$result
    return $ethernetFiber
}
#####################
###Create StreamBlock 
#####################
proc CreateStreamBlock {port active fcs fixed framelengthmode maxframe minframe srcMac dstMac sourceAddr destAddr dstPrefixlength gateway } {
    puts "Creating the StreamBlock"
    set StreamBlock [stc::create "StreamBlock" \
    -under $port \
    -Active $active \
    -FixedFrameLength $fixed \
    -FrameLengthMode $framelengthmode \
    -MaxFrameLength $maxframe\
    -MinFrameLength $minframe]
    set result [stc::get $StreamBlock]
    puts "\tStreamblock($StreamBlock) creation completed"
    set StreamBlockConfig [stc::config $StreamBlock -frameconfig ""]
    set strBlkEthII [stc::create ethernet:EthernetII \
                            -under $StreamBlock \
                            -name "eth_sb1" \
                            -srcMac $srcMac \
                            -dstMac $dstMac]
    set strBlkIpv4 [stc::create ipv4:IPv4 \
                            -under $StreamBlock \
                            -name "ipv4_sb1" \
                            -sourceAddr $sourceAddr \
                            -destAddr $destAddr \
                            -destPrefixLength $dstPrefixlength \
                            -gateway $gateway]
    stc::apply
    puts $StreamBlock
    return $StreamBlock
}
#############################
### Create StreamBlock Headers
#############################
proc addVlan {StreamBlock type cfi id pri} {
    set strBlkchildren [stc::get $StreamBlock -children]
    set strBlkEthII [lindex $strBlkchildren 0]
    set strBlkEthIIVlans [stc::create Vlans \
                                    -under $strBlkEthII]
    puts "Create Vlan Information.........."
    set vlans [stc::get $strBlkEthIIVlans]
    puts $vlans
    puts "Vlan children............"
    set strBlkEthIIVlan [stc::create Vlan -under $strBlkEthIIVlans]

    puts $strBlkEthIIVlan
    stc::config $strBlkEthIIVlan \
                -type $type \
                -cfi $cfi \
                -id $id \
                -pri $pri
    set vlanresult [stc::get $strBlkEthIIVlan]
    stc::apply
}

proc addTcp {StreamBlock} {
    set strTCP [stc::create tcp:Tcp \
                            -under $StreamBlock \
                            -name "tcp_sb1"]
    stc::apply
    
}
proc addIGMPv1 {StreamBlock version type groupAddress} {
    set strBlkchildren [stc::get $StreamBlock -children]
    set strBlkIPv4 [lindex $strBlkchildren 1]
    set Options [stc::create options -under $strBlkIPv4]
    set IPv4HeaderOption [stc::create IPv4HeaderOption -under $Options]
    set rtrAlert [stc::create rtrAlert -under $IPv4HeaderOption]
    
    set status [::stc::create igmp:Igmpv1 -under $StreamBlock -version $version -type $type -groupAddress $groupAddress]
    stc::apply
}
###
proc addIGMPv2Query {StreamBlock checksum type groupAddress maxRespTime} {
    set strBlkchildren [stc::get $StreamBlock -children]
    set strBlkIPv4 [lindex $strBlkchildren 1]
    set Options [stc::create options -under $strBlkIPv4]
    set IPv4HeaderOption [stc::create IPv4HeaderOption -under $Options]
    set rtrAlert [stc::create rtrAlert -under $IPv4HeaderOption]
    
    set status [::stc::create igmp:Igmpv2Query -under $StreamBlock -checksum $checksum -type $type -groupAddress $groupAddress -maxRespTime $maxRespTime]
    stc::apply
}
proc addIGMPv2Report {StreamBlock checksum type groupAddress maxRespTime} {
    set strBlkchildren [stc::get $StreamBlock -children]
    set strBlkIPv4 [lindex $strBlkchildren 1]
    set Options [stc::create options -under $strBlkIPv4]
    set IPv4HeaderOption [stc::create IPv4HeaderOption -under $Options]
    set rtrAlert [stc::create rtrAlert -under $IPv4HeaderOption]
    
    set status [::stc::create igmp:Igmpv2Report -under $StreamBlock -checksum $checksum -type $type -groupAddress $groupAddress -maxRespTime $maxRespTime]
    stc::apply
}
###
proc addtosdiffserv {StreamBlock reserved} {
    set strBlkchildren [stc::get $StreamBlock -children]
    set strBlkIPv4 [lindex $strBlkchildren 1]
    set tosDiffserv [stc::create tosDiffserv -under $strBlkIPv4]
    set diffServ [stc::create diffServ -under $tosDiffserv]
    stc::config $diffServ \
                -reserved $reserved
    stc::apply
}

######################################
### Configure the generator attributes
######################################
proc Generator {port BurstSize Duration DurationMode FixedLoad LoadUnit SchedulingMode } {
    puts "Configuring the generator on port"
    set generator1 [stc::get $port -children-Generator]
    stc::config $generator1 -Name "Generator 1"

    set generatorConfig1 [stc::get $generator1 -children-GeneratorConfig]
    stc::config $generatorConfig1 \
                -BurstSize $BurstSize \
                -Duration $Duration \
                -DurationMode $DurationMode \
                -LoadUnit $LoadUnit \
                -FixedLoad $FixedLoad \
                -SchedulingMode $SchedulingMode 
    stc::apply
    set result [stc::get $generatorConfig1]
    puts $result
    puts "\tGenerator($generator1) configuration completed"
}
######################################
###subscirbe results to Excel file
######################################
proc ResultSubscribe_Rx {project filename} {
    puts "Subscribing to results..."
    set sbResultRx [stc::subscribe -Parent $project \
                        -ConfigType Analyzer \
                        -resulttype AnalyzerPortResults \
                        -filenameprefix $filename]
    puts "\tResults($sbResultRx) subscription complete"
    stc::apply
    # puts "Configuration applied successfully"
    return $sbResultRx
}
proc ResultSubscribe_Tx {project filename} {
     set sbResultTx [stc::subscribe -Parent $project \
                    -ConfigType Generator \
                    -ResultType GeneratorPortResults \
                    -FilenamePrefix $filename \
                    -Interval 1]
    puts "\tResults($sbResultTx) subscription complete"
    stc::apply
    return $sbResultTx
}
proc ResultSubscribe_Rxstreams {project filename} {
     set sbDetailedRx [stc::subscribe -Parent $project \
                    -ConfigType StreamBlock \
                    -ResultType RxStreamSummaryResults \
                    -FilenamePrefix $filename \
                    -Interval 1]
    puts "\tResults($sbDetailedRx) subscription complete"
    stc::apply
    return $sbDetailedRx
}
###############################################
###unsubscirbe results(stop writing excel files)
###############################################
proc unsubscribe {result} {
    stc::unsubscribe $result
}
############################
###clear all traffic results
############################
proc ClearResults {args} {
    puts "Clearing results..."
    stc::perform ResultsClearAll -portList $args
    # stc::delete $object
    puts "Results Cleared"
    stc::apply
}
######################################
### Start Generator and Analyzer
######################################
proc startGenerator {args} {
    foreach arg $args {
        # puts $arg
        lappend generatorCurrent [stc::get $arg -children-generator]
        lappend analyzerCurrent [stc::get $arg -children-analyzer]
    }
    # puts $generatorCurrent
    puts "Analyzer started..."
    stc::perform analyzerStart -analyzerList $analyzerCurrent
    
    puts "Traffic generation started..."
    stc::perform generatorStart -generatorList $generatorCurrent
    
}
######################################
### Stop Generator and Analyzer
######################################
proc stopGenerator {args} {
    foreach arg $args {
        # puts $arg
        lappend generatorCurrent [stc::get $arg -children-generator]
        lappend analyzerCurrent [stc::get $arg -children-analyzer]
    }
    # puts $generatorCurrent
    puts "Traffic generator stop..."
    stc::perform generatorStop -generatorList $generatorCurrent
    stc::perform analyzerStop -analyzerList $analyzerCurrent
}

###############################################
###get realtime data(for error callback)
###############################################
proc getdata {args} {
    foreach arg $args {
        # puts $arg
        lappend generatorCurrent [stc::get $arg -children-generator]
        lappend analyzerCurrent [stc::get $arg -children-analyzer]
        lappend RxStreamblock [stc::get $arg -children-StreamBlock]
    }
    set len [llength $generatorCurrent]
    # puts $len
    for {set i 1} {$i <= $len} {incr i} {
        lappend TxGeneratorResults [stc::get [lindex $generatorCurrent [expr $i - 1]] -children-GeneratorPortResults] 
        lappend RxAnalyzerResults [stc::get [lindex $analyzerCurrent [expr $i - 1]] -children-AnalyzerPortResults] 
        lappend RxStreamblockResults [stc::get [lindex $RxStreamblock [expr $i -1]] -children-RxStreamSummaryResults]
        # puts $RxAnalyzerResults
    }
    for {set i 1} {$i <= $len} {incr i} {
        lappend data_($i) [stc::get [lindex $RxStreamblockResults [expr $i - 1]] -DroppedFrameCount] 
        lappend data_($i) [stc::get [lindex $RxAnalyzerResults [expr $i - 1]] -SigFrameCount] 
        lappend data_($i) [stc::get [lindex $TxGeneratorResults [expr $i - 1]] -GeneratorSigFrameCount]
        lappend datalist $data_($i)
    } 
    return $datalist
}
###############################################
###start / stop capture (for error callback)
###############################################
proc CaptureStart {port buffermode} {
    set Capture [stc::get $port -children-capture]
    stc::config $Capture -BufferMode $buffermode
    puts [stc::get $Capture]
    stc::perform CaptureStart -CaptureProxyId $Capture
}
proc CaptureStop {port filename} {
    set Capture [stc::get $port -children-capture]
    
    stc::perform CaptureStop -captureProxyId $Capture
    stc::perform CaptureDataSave -captureProxyId $Capture -FileName $filename
    puts [stc::get $Capture -PktCount]
}