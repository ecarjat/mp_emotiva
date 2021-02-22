"""Support for Emotiva Receivers."""
import logging

import pymotiva
import voluptuous as vol

from homeassistant.components.media_player import PLATFORM_SCHEMA, MediaPlayerEntity
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_MUSIC,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_STOP,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    STATE_IDLE,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNKNOWN,
)
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util


_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Music station"

SUPPORTED_FEATURES = (
    SUPPORT_PLAY
    | SUPPORT_PAUSE
    | SUPPORT_STOP
    | SUPPORT_PREVIOUS_TRACK
    | SUPPORT_NEXT_TRACK
    | SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_SELECT_SOURCE
)

KNOWN_HOSTS_KEY = "data_emotiva"
DEFAULT_PORT = 7002

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)




def setup_platform(hass, config, add_entities, discovery_info=None):
     """Set up the Emotiva platform."""

    known_hosts = hass.data.get(KNOWN_HOSTS_KEY)
    if known_hosts is None:
        known_hosts = hass.data[KNOWN_HOSTS_KEY] = []
    _LOGGER.debug("known_hosts: %s", known_hosts)

    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    interval = config.get(INTERVAL_SECONDS)

    # Get IP of host to prevent duplicates
    try:
        ipaddr = socket.gethostbyname(host)
    except (OSError) as error:
        _LOGGER.error("Could not communicate with %s:%d: %s", host, port, error)
        return

    if [item for item in known_hosts if item[0] == ipaddr]:
        _LOGGER.warning("Host %s:%d already registered", host, port)
        return

    if [item for item in known_hosts if item[1] == port]:
        _LOGGER.warning("Port %s:%d already registered", host, port)
        return

    reg_host = (ipaddr, port)
    known_hosts.append(reg_host)

    try:
        receiver = pymusiccast.McDevice(ipaddr, udp_port=port, mc_interval=interval)
    except pymusiccast.exceptions.YMCInitError as err:
        _LOGGER.error(err)
        receiver = None

    if receiver:
        for zone in receiver.zones:
            _LOGGER.debug("Receiver: %s / Port: %d / Zone: %s", receiver, port, zone)
            add_entities([YamahaDevice(receiver, receiver.zones[zone])], True)
    else:
        known_hosts.remove(reg_host)

        
class EmotivaDevice(MediaPlayerEntity):
    """Representation of an Emotiva device."""

    def __init__(self, name, host):
        """Initialize the Emotiva device."""
        self._name = name
        self._host = host
        self._pwstate = "PWSTANDBY"
        self._volume = 0
        # Initial value 60dB, changed if we get a MVMAX
        self._volume_max = 60
        self._source_list = NORMAL_INPUTS.copy()
        self._source_list.update(MEDIA_MODES)
        self._muted = False
        self._mediasource = ""
        self._mediainfo = ""

        self._should_setup_sources = True

    def _setup_sources(self, telnet):
        # NSFRN - Network name
        nsfrn = self.telnet_request(telnet, "NSFRN ?")[len("NSFRN ") :]
        if nsfrn:
            self._name = nsfrn

        # SSFUN - Configured sources with (optional) names
        self._source_list = {}
        for line in self.telnet_request(telnet, "SSFUN ?", all_lines=True):
            ssfun = line[len("SSFUN") :].split(" ", 1)

            source = ssfun[0]
            if len(ssfun) == 2 and ssfun[1]:
                configured_name = ssfun[1]
            else:
                # No name configured, reusing the source name
                configured_name = source

            self._source_list[configured_name] = source

        # SSSOD - Deleted sources
        for line in self.telnet_request(telnet, "SSSOD ?", all_lines=True):
            source, status = line[len("SSSOD") :].split(" ", 1)
            if status == "DEL":
                for pretty_name, name in self._source_list.items():
                    if source == name:
                        del self._source_list[pretty_name]
                        break

    @classmethod
    def telnet_request(cls, telnet, command, all_lines=False):
        """Execute `command` and return the response."""
        _LOGGER.debug("Sending: %s", command)
        telnet.write(command.encode("ASCII") + b"\r")
        lines = []
        while True:
            line = telnet.read_until(b"\r", timeout=0.2)
            if not line:
                break
            lines.append(line.decode("ASCII").strip())
            _LOGGER.debug("Received: %s", line)

        if all_lines:
            return lines
        return lines[0] if lines else ""

    def telnet_command(self, command):
        """Establish a telnet connection and sends `command`."""
        telnet = telnetlib.Telnet(self._host)
        _LOGGER.debug("Sending: %s", command)
        telnet.write(command.encode("ASCII") + b"\r")
        telnet.read_very_eager()  # skip response
        telnet.close()

    def update(self):
        """Get the latest details from the device."""
        try:
            telnet = telnetlib.Telnet(self._host)
        except OSError:
            return False

        if self._should_setup_sources:
            self._setup_sources(telnet)
            self._should_setup_sources = False

        self._pwstate = self.telnet_request(telnet, "PW?")
        for line in self.telnet_request(telnet, "MV?", all_lines=True):
            if line.startswith("MVMAX "):
                # only grab two digit max, don't care about any half digit
                self._volume_max = int(line[len("MVMAX ") : len("MVMAX XX")])
                continue
            if line.startswith("MV"):
                self._volume = int(line[len("MV") :])
        self._muted = self.telnet_request(telnet, "MU?") == "MUON"
        self._mediasource = self.telnet_request(telnet, "SI?")[len("SI") :]

        if self._mediasource in MEDIA_MODES.values():
            self._mediainfo = ""
            answer_codes = [
                "NSE0",
                "NSE1X",
                "NSE2X",
                "NSE3X",
                "NSE4",
                "NSE5",
                "NSE6",
                "NSE7",
                "NSE8",
            ]
            for line in self.telnet_request(telnet, "NSE", all_lines=True):
                self._mediainfo += f"{line[len(answer_codes.pop(0)) :]}\n"
        else:
            self._mediainfo = self.source

        telnet.close()
        return True

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        if self._pwstate == "PWSTANDBY":
            return STATE_OFF
        if self._pwstate == "PWON":
            return STATE_ON

        return None

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._volume / self._volume_max

    @property
    def is_volume_muted(self):
        """Return boolean if volume is currently muted."""
        return self._muted

    @property
    def source_list(self):
        """Return the list of available input sources."""
        return sorted(list(self._source_list))

    @property
    def media_title(self):
        """Return the current media info."""
        return self._mediainfo

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        if self._mediasource in MEDIA_MODES.values():
            return SUPPORT_DENON | SUPPORT_MEDIA_MODES
        return SUPPORT_DENON

    @property
    def source(self):
        """Return the current input source."""
        for pretty_name, name in self._source_list.items():
            if self._mediasource == name:
                return pretty_name

    def turn_off(self):
        """Turn off media player."""
        self.telnet_command("PWSTANDBY")

    def volume_up(self):
        """Volume up media player."""
        self.telnet_command("MVUP")

    def volume_down(self):
        """Volume down media player."""
        self.telnet_command("MVDOWN")

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        self.telnet_command(f"MV{round(volume * self._volume_max):02}")

    def mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        mute_status = "ON" if mute else "OFF"
        self.telnet_command(f"MU{mute_status})")

    def media_play(self):
        """Play media player."""
        self.telnet_command("NS9A")

    def media_pause(self):
        """Pause media player."""
        self.telnet_command("NS9B")

    def media_stop(self):
        """Pause media player."""
        self.telnet_command("NS9C")

    def media_next_track(self):
        """Send the next track command."""
        self.telnet_command("NS9D")

    def media_previous_track(self):
        """Send the previous track command."""
        self.telnet_command("NS9E")

    def turn_on(self):
        """Turn the media player on."""
        self.telnet_command("PWON")

    def select_source(self, source):
        """Select input source."""
        self.telnet_command(f"SI{self._source_list.get(source)}")