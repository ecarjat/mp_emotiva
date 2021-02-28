"""Support for Emotiva Receivers."""
import logging
import math

from homeassistant.components.media_player import PLATFORM_SCHEMA, MediaPlayerEntity
from homeassistant.components.media_player.const import (
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP,
    SUPPORT_SELECT_SOUND_MODE
)
from homeassistant.const import (
    STATE_ON,
    STATE_OFF
)
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util


_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "RMC-1"

SUPPORT_EMOTIVA = (
    SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_SELECT_SOURCE
    | SUPPORT_VOLUME_STEP
    | SUPPORT_SELECT_SOUND_MODE
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Emotiva platform."""

    from custom_components.emotiva.pymotiva import Emotiva
    add_entities(EmotivaDevice(Emotiva(ip, info))
                for ip, info in Emotiva.discover())

        
class EmotivaDevice(MediaPlayerEntity):
    """Representation of an Emotiva device."""

    def __init__(self, emo):
        """Initialize the Emotiva Receiver."""
        self._emo = emo
        self._emo.connect()
        self._name = '%s %s' % (self._emo.name, self._emo.model)
        self._min_volume = -96.0
        self._max_volume = 11
        self._emo.set_update_cb(lambda: self.schedule_update_ha_state())

    def update(self):
        #self._emo.connect()
        return True

    @property
    def should_poll(self):
        return False

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return {True: STATE_ON, False: STATE_OFF}[self._emo.power]

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        if self._emo.volume is not None:
            return math.pow(10,self._emo.volume/40.0)
        else:
            return 0

    @property
    def is_volume_muted(self):
        """Return boolean if volume is currently muted."""
        return self._emo.mute

    @property
    def source(self):
        """Return the current input source."""
        return self._emo.source

    @property
    def source_list(self):
        """Return the list of available input sources."""
        return sorted(list(self._emo.sources))

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return SUPPORT_EMOTIVA

    def turn_off(self):
        """Turn off media player."""
        self._emo.power = False
    
    def mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        self._emo.mute = mute

    def volume_up(self):
        """Volume up media player."""
        self._emo.volume_up()

    def volume_down(self):
        """Volume down media player."""
        self._emo.volume_down()

    def turn_on(self):
        """Turn the media player on."""
        self._emo.power = True

    def select_source(self, source):
        """Select input source."""
        self._emo.source = source


    @property
    def sound_mode(self):
        """Name of the current sound mode."""
        return self._emo.mode

    @property
    def sound_mode_list(self):
        """List of available sound modes."""
        return sorted(list(self._emo.modes))

    def select_sound_mode(self, sound_mode):
        """Select sound mode."""
        self._emo.mode = sound_mode

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        if volume == 0:
            self._emo.volume = -96
        else:
            self._emo.volume = 40.0 * math.log10(volume)