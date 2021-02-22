"""Support for Emotiva Receivers."""
import logging
import math
import socket
import xml.etree.ElementTree as ET

from custom_components.emotiva import pymotiva
import voluptuous as vol

from homeassistant.components.media_player import PLATFORM_SCHEMA, MediaPlayerEntity
from homeassistant.components.media_player.const import (
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
)
from homeassistant.const import (
    CONF_HOST,
    STATE_ON,
    STATE_OFF,
)
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util


_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "RMC-1"

SUPPORTED_FEATURES = (
    SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_SELECT_SOURCE
)

KNOWN_HOSTS_KEY = "data_emotiva"
CONTROL_PORT = 7002
NOTIFY_PORT = 7003
INFO_PORT = 7004
SETUP_PORT_TCP = 7100
MENU_NOTIFY_PORT = 7005


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional("control_port", default=CONTROL_PORT): cv.port,
        vol.Optional("notify_port", default=NOTIFY_PORT): cv.port,
        vol.Optional("info_port", default=INFO_PORT): cv.port,
        vol.Optional("setup_port_tcp", default=SETUP_PORT_TCP): cv.port,
        vol.Optional("menu_notify_port", default=MENU_NOTIFY_PORT): cv.port
    }
)

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Emotiva platform."""

    known_hosts = hass.data.get(KNOWN_HOSTS_KEY)
    if known_hosts is None:
        known_hosts = hass.data[KNOWN_HOSTS_KEY] = []
    _LOGGER.debug("known_hosts: %s", known_hosts)

    host = config.get(CONF_HOST)
    control_port = config.get("control_port")
    notify_port = config.get("notify_port")
    info_port = config.get("info_port")
    setup_port_tcp = config.get("setup_port_tcp")
    menu_notify_port = config.get("menu_notify_port")

    # Get IP of host to prevent duplicates
    try:
        ipaddr = socket.gethostbyname(host)
    except (OSError) as error:
        _LOGGER.error("Could not communicate with %s:%d: %s", host, error)
        return

    if [item for item in known_hosts if item[0] == ipaddr]:
        _LOGGER.warning("Host %s:%d already registered", host)
        return

    reg_host = (ipaddr, control_port)
    known_hosts.append(reg_host)

    try:
        builder = ET.TreeBuilder()
        builder.start('emotivaTransponder',{})
        builder.start('model',{})
        builder.data("RMC-1")
        builder.end('model')
        builder.start('name',{})
        builder.data("RMC-1")
        builder.end('name')
        builder.start('control',{})
        builder.start('controlPort',{})
        builder.data(control_port)
        builder.end('controlPort')
        builder.start('notifyPort',{})
        builder.data(notify_port)
        builder.end('notifyPort')
        builder.start('infoPort',{})
        builder.data(info_port)
        builder.end('infoPort')
        builder.start('setupPortTCPPort',{})
        builder.data(setup_port_tcp)
        builder.end('setupPortTCP')
        builder.start('menuNotifyPort',{})
        builder.data(menu_notify_port)
        builder.end('menuNotifyPort')
        builder.end('control')
        builder.end('emotivaTransponder')
        pkt = builder.close()
        receiver = pymotiva.Emotiva(ipaddr , pkt)
    except pymotiva.InvalidTransponderResponseError as err:
        _LOGGER.error(err)
        receiver = None

    if receiver:
            add_entities([EmotivaDevice(receiver)], True)
    else:
        known_hosts.remove(reg_host)

        
class EmotivaDevice(MediaPlayerEntity):
    """Representation of an Emotiva device."""

    def __init__(self, recv):
        """Initialize the Emotiva device."""
        self._recv = recv
        recv.connect()

    
    def update(self):
        """Get the latest details from the device."""
        recv = self._recv
        self._name = recv.name
        self._source = recv.source
        self._source_list = recv.sources
        self._pwstate = recv.power
        self._muted = recv.mute
        self._volume = recv.volume
        return True

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        if self._pwstate == False:
            return STATE_OFF
        if self._pwstate == True:
            return STATE_ON

        return None

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return math.pow(10,self._volume/40.0) 

    @property
    def is_volume_muted(self):
        """Return boolean if volume is currently muted."""
        return self._muted

    @property
    def source_list(self):
        """Return the list of available input sources."""
        return sorted(list(self._source_list))

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return SUPPORTED_FEATURES

    @property
    def source(self):
        """Return the current input source."""
        return self._source

    def turn_on(self):
        """Turn the media player on."""
        self._recv.power = True
        self._pwstate = True

    def turn_off(self):
        """Turn off media player."""
        self._recv.power = False
        self._pwstate = False

    def volume_up(self):
        """Volume up media player."""
        self._recv.volume_up()

    def volume_down(self):
        """Volume down media player."""
        self._recv.volume_down()

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        if volume == 0:
            self._recv.volume = -96
        else:
            self._recv.volume = 40.0 * math.log10(volume)

    def mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        self._recv.mute = mute



    def select_source(self, source):
        """Select input source."""
        self._recv.source = source
