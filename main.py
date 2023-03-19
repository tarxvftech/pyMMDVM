import sys
import serial
import struct
import pathlib
import argparse
import logging
import time
import subprocess

import pprint
pp = pprint.pprint

import semver
#TODO ignores version for now but later we can use semver to check if we need to update
logging.basicConfig(level=logging.DEBUG)

class dattr(dict):
    def __getattr__(self,name):
        if type(self[name]) == type({}): 
            self[name] = dattr(self[name]) 
        return self[name]
    def __setattr__(self,name,value):
        self[name] = value

class DV4MINI:
    #not MMDVM compatible...
    #https://github.com/hcninja/dv4mini
    ...


class NAKExc(Exception):
    pass

class MMDVM:
    FRAME_START=0xE0

    #https://github.com/g4klx/MMDVMHost/blob/master/Modem.cpp
    GET_VERSION=0x00
    GET_STATUS=0x01
    SET_CONFIG=0x02
    SET_MODE=0x03
    SET_FREQ=0x04
    SEND_CWID=0x0A

    ACK=0x70
    NAK=0x7f

    MODES={#https://github.com/g4klx/MMDVMHost/blob/master/Defines.h
            0:"IDLE",
            1:"D-STAR",
            2:"DMR",
            3:"YSF",
            4:"P25",
            5:"NXDN",
            6:"POCSAG",
            7:"M17",
            10:"FM", #used for AX25 too
            98:"CW",
            99:"LOCKOUT",
            100:"ERROR",
            110:"QUIT",

            # 99:"calibration",
            }
    NAK_REASONS=["invalid command","wrong mode","command too long","data incorrect", "not enough buffer space"]
    def make_rMODES(self):
        self.rMODES = {v:k for k,v in self.MODES.items()}

    def __init__(self, port):
        self.port = port
        TAG = ["HEADER","DATA","LOST","EOT"]
        dstar = {
                "header":0x10,
                "data":0x11,
                "lost":0x12,
                "eot":0x13
                }
        dmr = {
                "slot1_data":0x18,
                "slot1_lost":0x19,
                "slot2_data":0x1A,
                "slot2_lost":0x1B,
                "set_CACH_short_LC_data":0x1C,
                "tx_ctl":0x1D,
                }
        ysf = {
                "data":0x20,
                "lost":0x21, #no EOT, so everything will end with lost even under normal conditions
                }
        calibration = {
                "data":0x08,
                }
        self.make_rMODES()
        self.log = logging.getLogger(self.__class__.__name__)
        self._config = {
                }
        self._rf_config = {
                "rx_freq": 433000000,
                "tx_freq": 433000000,
                "rf_level": 50, #0-100
                "pocsag_freq": 433000000,
                }
        unused_rf_config = {
                "rx_offset": 0,
                "tx_offset": 0,
                "tx_dc_offset":0,
                "rx_dc_offset":0,
                "pocsag_level": 433000000,
                }


    @classmethod
    def parse_description(cls, description_version_string):
        parts = description_version_string.split(" ")
        mmdvm_type = parts[0]
        mmdvm_version = ""
        if '-' in mmdvm_type:
            mmdvm_type, mmdvm_version = parts[0].split('-')
        datecompiled = parts[1]
        oscillator_f = parts[2]
        rf_chips = ["ADF7021N","ADF7021"]
        features = {}
        for each in ["dual"]:
            features[each] = each in description_version_string
        for chip in rf_chips:
            if chip in description_version_string:
                rf_chip = chip
        return {
                "modemtype": mmdvm_type,
                "version": mmdvm_version,
                "date": datecompiled,
                "oscillator": oscillator_f,
                "rf_chip": rf_chip,
                **features,
                }

    def send_mmdvm(self, bs:bytes):
        pkt = [
                MMDVM.FRAME_START,
                2+len(bs),
                bs
                ]
        self.log.debug("send: %s", bs)
        # self.log.debug("pkt %s", pkt)
        pkt = struct.pack(">BB%ss"%(len(bs)), *pkt)
        # self.log.debug("pkt %s", pkt)
        # self.log.debug("send %s",pkt)
        self.port.write(pkt)

    def recv_mmdvm(self):
        r0 = self.port.read()
        if r0:
            assert int.from_bytes(r0,'big') == MMDVM.FRAME_START
        else:
            #tiemout
            return ''
        r1 = self.port.read()
        pktlength = int.from_bytes(r1, 'big') -2
        reply = b''
        for i in range(pktlength):
            reply += self.port.read()
        self.log.debug("reply: %s", reply)
        return reply

    @staticmethod
    def parse_reply(bs:bytes):
        cmd_reply = bs[0]

    @staticmethod
    def parse_nak(bs:bytes):
        #don't include the frame start and length in bs
        #in other words, pass recv_mmdvm to this
        if bs[0] != MMDVM.NAK:
            return None
        return {"cmd":bs[1], "reason":MMDVM.NAK_REASONS[bs[2]-1]} #reasons start at 1 but are indexed from zero

    @staticmethod
    def pretty_print(bs:bytes):
        ...

    def version(self):
        print("version")
        self.send_mmdvm( MMDVM.GET_VERSION.to_bytes(1,'big') )
        reply = self.recv_mmdvm()
        nak = MMDVM.parse_nak( reply )
        if nak:
            raise(NAKExc(nak))
        cmd = reply[0]
        assert cmd == MMDVM.GET_VERSION
        mmdvm_protocol_version = reply[1]

        description = reply[2:].decode('utf-8')
        #type-version date oscillator rfchip don'tcareabouttherest
        v = {
                "protocol": mmdvm_protocol_version,
                "description": description,
                **MMDVM.parse_description(description)
                }
        return v

    def set_config(self, config:dict):
        self._config.update(config)
        success = self._send_config(self._config)

    def set_rf_config(self, config:dict):
        self._rf_config.update(config)
        success = self._send_rf_config(self._rf_config)
        

    def _send_config(self, config:dict):
        b0 = ["rx_invert","tx_invert","ptt_invert","ysflodev","debug","useCOSaslockout","simplex"]
        b1 = ["dstar","dmr","ysf","p25","nxdn","pocsag","m17"]
        txdelay = 20 # * 10 ms
        #temporary
        bs = MMDVM.SET_CONFIG.to_bytes(1,"big") +\
                b"\x80\x40" +\
                txdelay.to_bytes(1,"big") +\
                self.rMODES["IDLE"].to_bytes(1,"big") +\
                b"\x80\x80" +\
                b"\x00\x00" +\
                b"\x80" +\
                b"\x80"*7 +\
                b"\x00" +\
                b"\x80"*2 +\
                b"\x00"*2 +\
                b"\x80\x00"

        self.send_mmdvm(bs)
        reply = self.recv_mmdvm()
        nak = MMDVM.parse_nak( reply )
        if nak:
            raise(NAKExc(nak))
        else:
            assert( reply[0] == MMDVM.ACK )
        return True
    def _send_rf_config(self, config:dict):
        rf_level = int(config["rf_level"] * 2.55 + .5)
        bs = MMDVM.SET_FREQ.to_bytes(1,"big") + b"\x00"+ \
                config["rx_freq"].to_bytes(4, "little") +\
                config["tx_freq"].to_bytes(4, "little") +\
                rf_level.to_bytes(1, "big") +\
                config["pocsag_freq"].to_bytes(4, "little") 

        self.send_mmdvm(bs)
        reply = self.recv_mmdvm()
        nak = MMDVM.parse_nak( reply )
        if nak:
            raise(NAKExc(nak))
        else:
            assert( reply[0] == MMDVM.ACK )
        return True


    @property
    def status(self):
        #https://github.com/g4klx/MMDVMHost/blob/33143105e388e37c875692f1fc8909afa43c2340/Modem.cpp#L772
        #protocol 1 only implemented below currently
        bs = MMDVM.GET_STATUS.to_bytes(1,"big")
        self.send_mmdvm(bs)
        reply = self.recv_mmdvm()
        assert( reply[0] == MMDVM.GET_STATUS )
        status = {}
        status["raw"] = {}
        status["raw"]["modes"] = reply[1]
        status["raw"]["state"] = reply[2]
        status["raw"]["flags"] = reply[3]
        status["raw"]["buffer_sizes"] = {}
        status["raw"]["buffer_sizes"]["D-STAR"] = reply[4]
        status["raw"]["buffer_sizes"]["slot1_DMR"] = reply[5]
        status["raw"]["buffer_sizes"]["slot2_DMR"] = reply[6]
        status["raw"]["buffer_sizes"]["YSF"] = reply[7]
        try:
            status["raw"]["buffer_sizes"]["P25"] = reply[8]
            status["raw"]["buffer_sizes"]["NXDN"] = reply[9]
            status["raw"]["buffer_sizes"]["POCSAG"] = reply[10]
            status["raw"]["buffer_sizes"]["M17"] = reply[11]
        except IndexError:
            pass
        #in protocol 2 it looks the same except it's 
        # d*, dmr1, dmr2, ysf, p25, nxdn,  as normal
        # but then it's m17, FM, pocsag, ax25
        unhandled = reply[12:]
        if len(unhandled) > 0:
            print("unhandled status bytes:", unhandled)
        status["_modes"] = [v for k,v in MMDVM.MODES.items() if ((k-1>0) and reply[1] >> k-1) &1] #doesn't look like this is used, and buffer size (>0) is actually authoritative?
        status["modes"] = [k for k,v in status["raw"]["buffer_sizes"].items() if v > 0]
        status["modem_state"] = MMDVM.MODES[ reply[2] ]
        status["flags"] = []
        tx_is_on = reply[3] & 0x1
        if reply[3] & 0x02:
            #revisit the flags here at some point
            status["flags"].append("ADC level overflow occurred")
        if reply[3] & 0x04:
            status["flags"].append("RX Buffer overflow occurred")
        if reply[3] & 0x08:
            status["flags"].append("TX Buffer overflow occurred")
        lockout = reply[3] & 0x10
        if reply[3] & 0x20:
            status["flags"].append("DAC level overflow occurred")
        cd = reply[3] & 0x40 #carrier_detect?
        status["carrier_detected"] = bool(cd)
        status["txing"] = bool(tx_is_on)
        status["lockedout"] = bool(lockout)
        del status["raw"]
        del status["_modes"]
        return status

    def set_mode(self, mode):
        #mode can be either an int/index or the string value from MODES
        try:
            name = self.MODES[ mode ]
            idx = mode
        except KeyError as e:
            pass
        try:
            idx = self.rMODES[ mode.upper() ]
            name = mode
        except ValueError:
            pass
        bs = struct.pack(">BB", MMDVM.SET_MODE, idx)
        self.send_mmdvm(bs)
        reply = self.recv_mmdvm()
        if MMDVM.parse_nak(reply):
            pp(reply)
            raise(NAKExc(nak))
        else:
            assert( reply[0] == MMDVM.ACK )

    def tx_cw(self, callsign):
        self.send_mmdvm(MMDVM.SEND_CWID.to_bytes(1,"big") + callsign.upper().encode("ascii"))
        # reply = self.recv_mmdvm()
        # while not len(reply):
            # reply = self.recv_mmdvm()
        # if MMDVM.parse_nak(reply):
            # pp(reply)
            # raise(NAKExc(reply))
        # else:
            # assert( reply[0] == MMDVM.ACK )


def main():
    parser = argparse.ArgumentParser(
                    description = 'Example programs that communicate with MMDVM modems/hotspots over serial',
                    epilog = 'Good luck! ~tarxvf/W2FBI')
    parser.add_argument('-p','--port', type=str, help="Serial port where the modem can be found. Default at /dev/ttyACM0.", default="/dev/ttyACM0")
    # parser.add_argument('-b','--baud', type=str, help="Speed for the port (if necessary). 'auto' tries 115200 and 460800, the most common.", default="auto")
    ##commented until auto-trying actually works
    args = parser.parse_args()

    port = args.port
    # baud = args.baud
    baud = 115200
    ser = serial.Serial(port, baud, timeout=1)
    m = MMDVM(port=ser)
    # v = dattr(m.version())
    # print(v)
    pp(m.status)
    pp(m.status)
    f = 446000000
    m.set_config({})
    m.set_rf_config({"rx_freq":f, "tx_freq":f})
    m.set_mode("idle")
    pp(m.status)
    m.tx_cw("vvvv HELLO WORLD")
    # time.sleep(.1)
    # while m.status["txing"]:
        # time.sleep(.1)
    del m
    ser.close()


if __name__ == "__main__":
    main()

