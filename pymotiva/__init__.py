#!/usr/bin/env python3

__author__ = "Dima Zavin"
__copyright__ = "Copyright 2016, Dima Zavin"

import logging
import select
import socket
import threading
import time
import xml.etree.ElementTree as ET

_LOGGER = logging.getLogger(__name__)

class Error(Exception):
  pass


class InvalidTransponderResponseError(Error):
  pass


class InvalidSourceError(Error):
  pass

class InvalidModeError(Error):
  pass

class EmotivaNotifier(threading.Thread):
  def __init__(self):
    threading.Thread.__init__(self)

    self._devs = {}
    self._socks_by_port = {}
    self._socks_by_fileno = {}
    self._lock = threading.Lock()
    self.setDaemon(True)
    self.start()

  def register(self, ip, port, callback):
    with self._lock:
      if port not in self._socks_by_port:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('', port))
        sock.setblocking(0)
        self._socks_by_port[port] = sock
        self._socks_by_fileno[sock.fileno()] = sock
      if ip not in self._devs:
        self._devs[ip] = callback

  def run(self):
    _LOGGER.debug("Connected")
    while True:
      if not self._socks_by_fileno:
        continue
      readable, writable, exceptional = select.select(self._socks_by_fileno,[] , [])
      print(readable)
      for s in readable:
        with self._lock:
          sock = self._socks_by_fileno[s]
        data, (ip, port) = sock.recvfrom(4096)
        _LOGGER.debug("Got data %s from %s:%d" % (data, ip, port))
        with self._lock:
          cb = self._devs[ip]
        cb(data)


class Emotiva(object):
  XML_HEADER = '<?xml version="1.0" encoding="utf-8"?>'.encode('utf-8')
  DISCOVER_REQ_PORT = 7000
  DISCOVER_RESP_PORT = 7001
  NOTIFY_EVENTS = set([
      'power', 'zone2_power', 'source', 'mode', 'volume', 'audio_input',
      'audio_bitstream', 'video_input', 'video_format',
  ]).union(set(['input_%d' % d for d in range(1, 9)]))
  __notifier = EmotivaNotifier()

  def __init__(self, ip, transp_xml, events = NOTIFY_EVENTS):
    self._ip = ip
    self._name = 'Unknown'
    self._model = 'Unknown'
    self._proto_ver = None
    self._ctrl_port = None
    self._notify_port = None
    self._info_port = None
    self._setup_port_tcp = None
    self._ctrl_sock = None
    self._update_cb = None
    self._modes = ('stereo', 'direct', 'dolby', 'dts', 'all_stereo', 'auto', 'reference_stereo', 'surround_mode')
    self._events = events

    # current state
    self._current_state = dict(((ev, None) for ev in self._events))
    self._sources = {}
    self._muted = False

    self.__parse_transponder(transp_xml)
    if not self._ctrl_port or not self._notify_port:
      raise InvalidTransponderResponseError("Coulnd't find ctrl/notify ports")

  def connect(self):
    self._ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self._ctrl_sock.bind(('', self._ctrl_port))
    self._ctrl_sock.settimeout(0.5)
    self.__notifier.register(self._ip, self._notify_port, self._notify_handler)
    self._subscribe_events(self._events)

  def _send_request(self, req, ack=False):
    self._ctrl_sock.sendto(req, (self._ip, self._ctrl_port))

    while ack:
      try:
        _resp_data, (ip, port) = self._ctrl_sock.recvfrom(4096)
        _LOGGER.debug(_resp_data)
        resp = self._parse_response(_resp_data)
        self._handle_status(resp)
      except socket.timeout:
        break

  def _notify_handler(self, data):
    resp = self._parse_response(data)
    self._handle_status(resp)

  def _subscribe_events(self, events):
    msg = self.format_request('emotivaSubscription',
                              [(ev, {}) for ev in events],
                              {'protocol':"3.0"} if self._proto_ver == 3 else {})
    self._send_request(msg, ack=True)

  def __parse_transponder(self, transp_xml):
    elem = transp_xml.find('name')
    if elem is not None: self._name = elem.text.strip()
    elem = transp_xml.find('model')
    if elem is not None: self._model = elem.text.strip()

    ctrl = transp_xml.find('control')
    elem = ctrl.find('version')
    if elem is not None: self._proto_ver = elem.text
    elem = ctrl.find('controlPort')
    if elem is not None: self._ctrl_port = int(elem.text)
    elem = ctrl.find('notifyPort')
    if elem is not None: self._notify_port = int(elem.text)
    elem = ctrl.find('infoPort')
    if elem is not None: self._info_port = int(elem.text)
    elem = ctrl.find('setupPortTCP')
    if elem is not None: self._setup_port_tcp = int(elem.text)

  def _handle_status(self, resp):
    for elem in resp:
      if elem.tag not in self._current_state:
        _LOGGER.debug('Unknown element: %s' % elem.tag)
        continue
      val = (elem.get('value') or '').strip()
      visible = (elem.get('visible') or '').strip()
      if ((elem.tag.startswith('input_') or elem.tag.startswith('mode_'))
          and visible != "true"):
        continue
      if elem.tag == 'volume':
        if val == 'Mute':
          self._muted = True
          continue
        self._muted = False
        # fall through
      if val:
        self._current_state[elem.tag] = val
        _LOGGER.debug("Updated '%s' <- '%s'" % (elem.tag, val))
      if elem.tag.startswith('input_'):
        num = elem.tag[6:]
        self._sources[val] = int(num)
    if self._update_cb:
      self._update_cb()

  def set_update_cb(self, cb):
    self._update_cb = cb

  @classmethod
  def discover(cls, version = 2):
    resp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    resp_sock.bind(('', cls.DISCOVER_RESP_PORT))
    resp_sock.settimeout(0.5)

    req_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    req_sock.bind(('', 0))
    req_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if version == 3:
      req = cls.format_request('emotivaPing', {}, {'protocol': "3.0"})
    else:
      req = cls.format_request('emotivaPing')
    req_sock.sendto(req, ('<broadcast>', cls.DISCOVER_REQ_PORT))

    devices = []
    while True:
      try:
        _resp_data, (ip, port) = resp_sock.recvfrom(4096)
        resp = cls._parse_response(_resp_data)
        devices.append((ip, resp))
      except socket.timeout:
        break
    return devices

  @classmethod
  def _parse_response(cls, data):
    _LOGGER.debug(data)
    data_lines = data.decode('utf-8').split('\n')
    data_joined = ''.join([x.strip() for x in data_lines])
    root = ET.fromstring(data_joined)
    return root

  @classmethod
  def format_request(cls, pkt_type, req = {}, pkt_attrs = {}):
    """
    req is a list of 2-element tuples with first element being the command,
    and second being a dict of parameters. E.g.
    ('power_on', {'value': "0"})

    pkt_attrs is a dictionary containing element attributes. E.g.
    {'protocol': "3.0"}
    """
    output = cls.XML_HEADER
    builder = ET.TreeBuilder()
    builder.start(pkt_type,pkt_attrs)
    for cmd, params in req:
      builder.start(cmd, params)
      builder.end(cmd)
    builder.end(pkt_type)
    pkt = builder.close()
    return output + ET.tostring(pkt)

  @property
  def name(self):
    return self._name

  @property
  def model(self):
    return self._model

  @property
  def address(self):
    return self._ip

  @property
  def power(self):
    if self._current_state['power'] == 'On':
      return True
    return False

  @power.setter
  def power(self, onoff):
    cmd = {True: 'power_on', False: 'power_off'}[onoff]
    msg = self.format_request('emotivaControl', [(cmd, {'value': '0'})])
    self._send_request(msg)

  @property
  def volume(self):
    if self._current_state['volume'] != None:
      return float(self._current_state['volume'].replace(" ", ""))
    return None

  @volume.setter
  def volume(self, value):
    msg = self.format_request('emotivaControl', [('set_volume', {'value': str(value)})])
    self._send_request(msg)

  def _volume_step(self, incr):
    # The XMC-1 with firmware version <= 3.1a will not change the volume unless
    # the volume overlay is up. So, we first send a noop command for volume step
    # with value 0, and then send the real step.
    noop = self.format_request('emotivaControl', [('volume', {'value': '0'})])
    msg = self.format_request('emotivaControl', [('volume', {'value': str(incr)})])
    self._send_request(noop)
    self._send_request(msg)

  def volume_up(self):
    self._volume_step(1)

  def volume_down(self):
    self._volume_step(-1)

  @property
  def mute(self):
    return self._muted

  @mute.setter
  def mute(self, enable):
    mute_cmd = {True: 'mute_on', False: 'mute_off'}[enable]
    msg = self.format_request('emotivaControl', [(mute_cmd, {'value': '0'})])
    self._send_request(msg)

  @property
  def sources(self):
    return tuple(self._sources.keys())

  @property
  def source(self):
    return self._current_state['source']

  @source.setter
  def source(self, val):
    if val not in self._sources:
      raise InvalidSourceError('Source "%s" is not a valid input' % val)
    elif self._sources[val] is None:
      raise InvalidSourceError('Source "%s" has bad value (%s)' % (
          val, self._sources[val]))
    msg = self.format_request('emotivaControl',
        [('source_%d' % self._sources[val], {'value': '0'})])
    self._send_request(msg)

  
  @property
  def modes(self):
    return self._modes
  
  @property
  def mode(self):
    return self._current_state['mode']

  @mode.setter
  def mode(self, val):
    if val not in self._modes:
      raise InvalidModeError('Mode "%s" does not exist' % val)
    msg = self.format_request('emotivaControl',[(val,  {'value': '0'})])
    self._send_request(msg)