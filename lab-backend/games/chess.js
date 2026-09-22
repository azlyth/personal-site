/**
 * Chess rules, backed by chess.js.
 *
 * This module is a thin, stateless wrapper: state is just a FEN string plus
 * some denormalized fields the client wants without re-parsing the FEN
 * itself (whose turn, is it check, move history in SAN, the last move's
 * squares). Every call reconstructs a chess.js `Chess` instance from the
 * given state's FEN, so nothing here holds mutable shared state between
 * calls and applyMove never touches the object it was handed.
 */

const { Chess } = require('chess.js');

const COLOR_NAMES = { w: 'white', b: 'black' };

function colorName(shortColor) {
  return COLOR_NAMES[shortColor] || null;
}

function describeResult(chess) {
  if (chess.isCheckmate()) {
    // The side to move is the side that got mated; the other side wins.
    const winner = colorName(chess.turn()) === 'white' ? 'Black' : 'White';
    return `Checkmate - ${winner} wins`;
  }
  if (chess.isStalemate()) {
    return 'Stalemate - draw';
  }
  if (chess.isThreefoldRepetition()) {
    return 'Draw - threefold repetition';
  }
  if (chess.isInsufficientMaterial()) {
    return 'Draw - insufficient material';
  }
  if (chess.isDrawByFiftyMoves()) {
    return 'Draw - fifty-move rule';
  }
  if (chess.isDraw()) {
    return 'Draw';
  }
  return null;
}

function buildState(chess, lastMove) {
  const over = chess.isGameOver();
  const result = over ? describeResult(chess) : null;
  return {
    fen: chess.fen(),
    turn: over ? null : colorName(chess.turn()),
    over,
    result,
    history: chess.history(),
    lastMove: lastMove ? { from: lastMove.from, to: lastMove.to } : null,
    check: chess.isCheck(),
  };
}

function initialState() {
  const chess = new Chess();
  return buildState(chess, null);
}

const SQUARE_RE = /^[a-h][1-8]$/;

function applyMove(state, move) {
  if (!state || typeof state.fen !== 'string') {
    return { error: 'Invalid game state' };
  }
  if (state.over) {
    return { error: 'Game is already over' };
  }
  if (!move || typeof move !== 'object') {
    return { error: 'Invalid move' };
  }

  const { from, to } = move;
  if (typeof from !== 'string' || typeof to !== 'string' || !SQUARE_RE.test(from) || !SQUARE_RE.test(to)) {
    return { error: 'Move must specify valid from/to squares' };
  }

  let chess;
  try {
    chess = new Chess(state.fen);
  } catch (err) {
    return { error: 'Invalid game state' };
  }

  const piece = chess.get(from);
  if (!piece) {
    return { error: `No piece on ${from}` };
  }
  if (piece.color !== chess.turn()) {
    return { error: 'Not your turn' };
  }

  let result;
  try {
    result = chess.move({ from, to, promotion: move.promotion || 'q' });
  } catch (err) {
    return { error: 'Illegal move' };
  }

  return { state: buildState(chess, result) };
}

module.exports = {
  id: 'chess',
  name: 'Chess',
  blurb: 'Full rules, including the ones you forget.',
  initialState,
  applyMove,
};
