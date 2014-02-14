from a7105 import *
import time
import logging
import random
import struct

def calc_checksum(packet):
  total = 0
  for char in packet:
    total += struct.unpack('B', char)[0]
  return (256 - (total % 256)) & 0xff

def lerp(t, min, max):
  return int(round(min + t * (max - min)))

log = logging.getLogger('hubsan')

class BindError(Exception):
  pass

class Hubsan:
  # not sure if byte order is correct
  ID = '\x55\x20\x10\x41' # doesn't respond without this
  CALIBRATION_MAX_CHECKS = 3
  # channels we can use, magic numbers from deviation
  ALLOWED_CHANNELS = [ 0x14, 0x1e, 0x28, 0x32, 0x3c, 0x46, 0x50, 0x5a, 0x64, 0x6e, 0x78, 0x82 ]
  # mystery packet constants
  MYSTERY_CONSTANTS = '\x08\xe4\xea\x9e\x50' # does respond without this?
  # mystery ID from deviation
  TX_ID = '\xdb\x04\x26\x79' # also reacts without this

  def __init__(self):
    self.a7105 = A7105()

    # generate a random session ID
    self.session_id = struct.pack('BBBB', *(random.randint(0, 255) for n in xrange(4)))

    # choose a random channel
    self.channel, = random.sample(Hubsan.ALLOWED_CHANNELS, 1)

  def init(self):
    self.a7105.init()

    self.a7105.write_id(Hubsan.ID)

  def build_bind_packet(self, state):
    packet = struct.pack('BB', state, self.channel) + self.session_id + Hubsan.MYSTERY_CONSTANTS + Hubsan.TX_ID

    return packet + pbyte(calc_checksum(packet))

  def send_packet(self, packet, channel):
    self.a7105.strobe(State.STANDBY)
    self.a7105.write_data(packet, channel)
    #time.sleep(0.003)

    # wait for send to complete
    for send_n in xrange(4):
      if send_n == 3:
        raise Exception("Sending did not complete.")
      elif self.a7105.read_reg(Reg.MODE) & 1 == 0:
        break
      time.sleep(0.001)

  def bind_stage(self, state):
    log.debug('bind stage %d' % state)

    a = self.a7105

    packet = self.build_bind_packet(state)

    self.send_packet(packet, self.channel)

    a.strobe(State.RX)
    # time.sleep(0.00045)

    for recv_n in xrange(100):
      if a.read_reg(Reg.MODE) & 1 == 0:
        packet = a.read_data(16)
        log.debug('got response: ' + format_packet(packet))
        return packet

    raise BindError()

  def bind(self):
    log.info('binding started')

    while True:
      try:
        self.bind_stage(1)
        #time.sleep(0.008)
        state4_response = self.bind_stage(3)
        #self.a7105.write_id(state4_response[2:6])
        self.a7105.write_id(state4_response[2:6])
        #time.sleep(0.008)
        self.bind_stage(1)
        #time.sleep(0.008)

        break
      except BindError:
        continue

    while True:
      try:
        phase2_response = self.bind_stage(9)
        if phase2_response[1] == '\x09':
          break
      except BindError:
        continue

    # enable CRC, id code length 4, preamble length 4
    self.a7105.write_reg(Reg.CODE_I, 0x0F)

    log.info('bind complete!')

  def control_raw(self, throttle, rudder, elevator, aileron):
    control_packet = '\x20'
    for chan in [ throttle, rudder, elevator, aileron ]:
      control_packet += '\x00' + pbyte(chan)
    control_packet += '\x02\x64' + Hubsan.TX_ID
    control_packet += pbyte(calc_checksum(control_packet))

    log.debug('sending control packet: %s' % format_packet(control_packet))

    for i in xrange(4):
      #self.send_packet(control_packet, self.channel)
      self.a7105.strobe(State.STANDBY)
      self.a7105.write_data(control_packet, self.channel)
      time.sleep(0.003)
    #self.send_packet(control_packet, self.channel + 0x23)
    self.a7105.strobe(State.STANDBY)
    self.a7105.write_data(control_packet, self.channel + 0x23)
    time.sleep(0.003)

  '''
    Send a control packet using floating point values.
    Throttle ranges from 0 to 1, all others range from -1 to 1.
  '''
  def control(self, throttle, rudder, elevator, aileron):
    throttle_raw = lerp(throttle, 0x00, 0xFF)
    rudder_raw = lerp((rudder + 1) / 2, 0x34, 0xCC)
    elevator_raw = lerp((elevator + 1) / 2, 0x3E, 0xBC)
    aileron_raw = lerp((-aileron + 1) / 2, 0x45, 0xC3)
    self.control_raw(throttle_raw, rudder_raw, elevator_raw, aileron_raw)

  '''
    As a safety measure, the Hubsan X4 will not accept control commands until
    the throttle has been set to 0 for a number of cycles. Calling this function
    will send the appropriate control signals.
  '''
  def safety(self):
    log.info('sending safety signals')
    for i in xrange(100):
      self.control(0, 0, 0, 0) # send 0 throttle for 100 cycles
    log.info('safety complete')