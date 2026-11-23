"""Levitate! multiplayer: friends race together against the rival craft.

Choose **MULTIPLAYER** in the launcher: host a race and send friends its
friend code, or paste one to join; everyone meets in a lobby, readies up and
the host starts. Human craft are all on the home team; the rival craft
(game/bots.py) fill the seats left over, and give theirs up when a human
joins a full race.

* :mod:`.friend_code`, :mod:`.udp`, :mod:`.upnp`, :mod:`.transport`,
  :mod:`.delta` -- the network, ported from MiniWind: friend codes that are
  the address, a UDP channel that gets through home routers, TCP and LAN
  discovery, world frames sent as changes;
* :mod:`.lobby` -- the lobby: who is in, ready, the maze and the rivals,
  and handing the race to the game;
* :mod:`.session` -- the race itself: the host runs the match, each player
  flies their own craft.

Importing this package opens no network resources.
"""

#: Seats in a race, human craft and rival craft together (game.bots.MAX_CRAFT).
MAX_PLAYERS = 8
PROTOCOL_VERSION = 1
