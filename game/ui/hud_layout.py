"""The dashboard's layout, in its own 1280 x 224 pixel space.

Shared by the art generator (game/tools/make_art.py), which cuts the wells
into the panel, and the HUD (game/ui/hud.py), which fills them each frame.
"""

DASH_W, DASH_H = 1280, 224
RADAR = (540, 30, 740, 214)          # radar window (screen centre)
SPEEDO = (40, 42, 210, 212)          # speedometer dial well
FLAGS_RIVAL = (238, 60, 510, 120)    # rival flags taken (tally window)
FLAGS_HOME = (238, 140, 510, 200)    # home flags still standing
SLOTS = (770, 60, 1060, 200)         # power-up slots
TIMER = (1080, 60, 1240, 120)        # LED clock
SHIELD = (1080, 140, 1240, 200)      # shield bar
GAUGE_SIZE = 160
