/**
 * Game rule modules.
 *
 * A game module is pure: no sockets, no Redis, no timers, no clock. It is the
 * rules and nothing else, which is what makes it testable without standing a
 * server up.
 *
 *   id                      unique string; matches the filename and the id the
 *                           client sends on the wire
 *   name                    display name for the menu tile
 *   blurb                   one line of description for the menu tile
 *   initialState()          -> state (a JSON-serializable plain object; it is
 *                              written to Redis as-is)
 *   applyMove(state, move)  -> { state } on success
 *                              { error: 'human readable reason' } on rejection
 *
 * applyMove MUST NOT mutate the state it is handed. Return a new object.
 * Resetting a game is just initialState() again.
 *
 * Every state carries three common fields. The client renders these
 * generically, so a game that omits them will render wrong:
 *
 *   turn    string | null   whose move it is; null once the game is over
 *   over    boolean
 *   result  string | null   e.g. "Checkmate - White wins"; null while playing
 *
 * Everything else in a state is that game's own business.
 */

const chess = require('./chess');
const checkers = require('./checkers');
const connect4 = require('./connect4');
const tictactoe = require('./tictactoe');
const go = require('./go');

const GAMES = [chess, checkers, connect4, tictactoe, go];

const byId = new Map(GAMES.map((game) => [game.id, game]));

function getGame(id) {
  return byId.get(id) || null;
}

module.exports = { GAMES, getGame };
