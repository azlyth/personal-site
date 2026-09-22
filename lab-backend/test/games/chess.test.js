const test = require('node:test');
const assert = require('node:assert');

const chess = require('../../games/chess');

function play(state, moves) {
  let current = state;
  for (const move of moves) {
    const outcome = chess.applyMove(current, move);
    assert.ok(!outcome.error, `expected move ${JSON.stringify(move)} to succeed, got error: ${outcome.error}`);
    current = outcome.state;
  }
  return current;
}

test('module shape', () => {
  assert.strictEqual(chess.id, 'chess');
  assert.strictEqual(typeof chess.name, 'string');
  assert.strictEqual(typeof chess.blurb, 'string');
  assert.strictEqual(typeof chess.initialState, 'function');
  assert.strictEqual(typeof chess.applyMove, 'function');
});

test('initialState carries the common fields and starting position', () => {
  const state = chess.initialState();
  assert.strictEqual(state.turn, 'white');
  assert.strictEqual(state.over, false);
  assert.strictEqual(state.result, null);
  assert.strictEqual(state.check, false);
  assert.deepStrictEqual(state.history, []);
  assert.strictEqual(state.lastMove, null);
  assert.strictEqual(state.fen, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1');
});

test('opening move works and flips turn', () => {
  const state = chess.initialState();
  const outcome = chess.applyMove(state, { from: 'e2', to: 'e4' });
  assert.ok(!outcome.error);
  assert.strictEqual(outcome.state.turn, 'black');
  assert.strictEqual(outcome.state.over, false);
  assert.deepStrictEqual(outcome.state.lastMove, { from: 'e2', to: 'e4' });
  assert.deepStrictEqual(outcome.state.history, ['e4']);
});

test('illegal move is rejected with an error and unchanged state is implied', () => {
  const state = chess.initialState();
  // Knight can't jump straight ahead like a rook.
  const outcome = chess.applyMove(state, { from: 'b1', to: 'b3' });
  assert.ok(outcome.error);
  assert.strictEqual(outcome.state, undefined);
});

test('illegal move: moving to a square that is not reachable at all', () => {
  const state = chess.initialState();
  const outcome = chess.applyMove(state, { from: 'e2', to: 'e5' });
  assert.ok(outcome.error);
});

test('moving from an empty square is rejected', () => {
  const state = chess.initialState();
  const outcome = chess.applyMove(state, { from: 'e4', to: 'e5' });
  assert.ok(outcome.error);
});

test('out-of-turn move is rejected', () => {
  const state = chess.initialState();
  // It's white's move; trying to move a black pawn should fail.
  const outcome = chess.applyMove(state, { from: 'e7', to: 'e5' });
  assert.ok(outcome.error);
  assert.match(outcome.error, /turn/i);
});

test('out-of-turn move is rejected after a move has been made', () => {
  const state = play(chess.initialState(), [{ from: 'e2', to: 'e4' }]);
  // Now it's black's turn; white tries to move again.
  const outcome = chess.applyMove(state, { from: 'd2', to: 'd4' });
  assert.ok(outcome.error);
});

test('promotion with an explicit piece works', () => {
  // White pawn one step from promoting on a8.
  let state = {
    fen: '8/P6k/8/8/8/8/7K/8 w - - 0 1',
    turn: 'white',
    over: false,
    result: null,
    history: [],
    lastMove: null,
    check: false,
  };
  const outcome = chess.applyMove(state, { from: 'a7', to: 'a8', promotion: 'r' });
  assert.ok(!outcome.error);
  assert.match(outcome.state.history[0], /=R/);
  assert.strictEqual(outcome.state.fen.startsWith('R7'), true);
});

test('promotion defaults to queen when omitted', () => {
  const state = {
    fen: '8/P6k/8/8/8/8/7K/8 w - - 0 1',
    turn: 'white',
    over: false,
    result: null,
    history: [],
    lastMove: null,
    check: false,
  };
  const outcome = chess.applyMove(state, { from: 'a7', to: 'a8' });
  assert.ok(!outcome.error);
  assert.match(outcome.state.history[0], /=Q/);
  assert.strictEqual(outcome.state.fen.startsWith('Q7'), true);
});

test('en passant capture is allowed', () => {
  const state = play(chess.initialState(), [
    { from: 'e2', to: 'e4' },
    { from: 'a7', to: 'a6' },
    { from: 'e4', to: 'e5' },
    { from: 'd7', to: 'd5' },
  ]);
  const outcome = chess.applyMove(state, { from: 'e5', to: 'd6' });
  assert.ok(!outcome.error);
  assert.strictEqual(outcome.state.history[outcome.state.history.length - 1], 'exd6');
  // The captured black pawn on d5 should be gone.
  assert.ok(!outcome.state.fen.includes('3pP3'));
});

test('castling kingside is allowed once the path is clear', () => {
  const state = play(chess.initialState(), [
    { from: 'g1', to: 'f3' },
    { from: 'g8', to: 'f6' },
    { from: 'g2', to: 'g3' },
    { from: 'g7', to: 'g6' },
    { from: 'f1', to: 'g2' },
    { from: 'f8', to: 'g7' },
  ]);
  const outcome = chess.applyMove(state, { from: 'e1', to: 'g1' });
  assert.ok(!outcome.error);
  assert.strictEqual(outcome.state.history[outcome.state.history.length - 1], 'O-O');
});

test("fool's mate ends the game with white delivering checkmate", () => {
  const state = play(chess.initialState(), [
    { from: 'f2', to: 'f3' },
    { from: 'e7', to: 'e5' },
    { from: 'g2', to: 'g4' },
  ]);
  const outcome = chess.applyMove(state, { from: 'd8', to: 'h4' });
  assert.ok(!outcome.error);
  assert.strictEqual(outcome.state.over, true);
  assert.strictEqual(outcome.state.turn, null);
  assert.strictEqual(outcome.state.check, true);
  assert.strictEqual(outcome.state.result, 'Checkmate - Black wins');
});

test('stalemate ends the game as a draw', () => {
  // Black king on h8 with no legal moves; white to move delivers stalemate.
  const state = {
    fen: '7k/8/6K1/6Q1/8/8/8/8 w - - 0 1',
    turn: 'white',
    over: false,
    result: null,
    history: [],
    lastMove: null,
    check: false,
  };
  const outcome = chess.applyMove(state, { from: 'g5', to: 'd5' });
  assert.ok(!outcome.error);
  assert.strictEqual(outcome.state.over, true);
  assert.strictEqual(outcome.state.turn, null);
  assert.strictEqual(outcome.state.result, 'Stalemate - draw');
});

test('moves are rejected once the game is over', () => {
  const state = play(chess.initialState(), [
    { from: 'f2', to: 'f3' },
    { from: 'e7', to: 'e5' },
    { from: 'g2', to: 'g4' },
    { from: 'd8', to: 'h4' },
  ]);
  assert.strictEqual(state.over, true);
  const outcome = chess.applyMove(state, { from: 'a2', to: 'a3' });
  assert.ok(outcome.error);
  assert.strictEqual(outcome.state, undefined);
});

test('applyMove does not mutate the state it is given', () => {
  const state = chess.initialState();
  const snapshot = JSON.parse(JSON.stringify(state));
  const outcome = chess.applyMove(state, { from: 'e2', to: 'e4' });
  assert.ok(!outcome.error);
  assert.deepStrictEqual(state, snapshot, 'input state object must be unchanged after applyMove');
  assert.notStrictEqual(outcome.state, state);
});

test('applyMove does not mutate state even when the move is illegal', () => {
  const state = chess.initialState();
  const snapshot = JSON.parse(JSON.stringify(state));
  const outcome = chess.applyMove(state, { from: 'b1', to: 'b3' });
  assert.ok(outcome.error);
  assert.deepStrictEqual(state, snapshot);
});

test('applyMove rejects malformed move payloads', () => {
  const state = chess.initialState();
  assert.ok(chess.applyMove(state, {}).error);
  assert.ok(chess.applyMove(state, { from: 'e2' }).error);
  assert.ok(chess.applyMove(state, { from: 'z9', to: 'e4' }).error);
  assert.ok(chess.applyMove(state, null).error);
});

test('check is flagged without ending the game', () => {
  // White rook swings onto the open e-file, checking the black king, which
  // still has escape squares (not mate).
  const state = {
    fen: '4k3/8/8/8/8/8/8/R5K1 w - - 0 1',
    turn: 'white',
    over: false,
    result: null,
    history: [],
    lastMove: null,
    check: false,
  };
  const outcome = chess.applyMove(state, { from: 'a1', to: 'e1' });
  assert.ok(!outcome.error);
  assert.strictEqual(outcome.state.check, true);
  assert.strictEqual(outcome.state.over, false);
  assert.strictEqual(outcome.state.result, null);
  assert.strictEqual(outcome.state.turn, 'black');
});

test('the move list accumulates instead of holding only the last move', () => {
  // Regression: applyMove rebuilds a Chess from the FEN alone, so
  // chess.history() reports just the move it was handed. Reading it directly
  // left the move list permanently one move long, which looked fine in every
  // single-move test.
  let state = chess.initialState();
  for (const move of [
    { from: 'e2', to: 'e4' },
    { from: 'e7', to: 'e5' },
    { from: 'g1', to: 'f3' },
    { from: 'b8', to: 'c6' }
  ]) {
    const result = chess.applyMove(state, move);
    assert.ok(!result.error, `unexpected rejection: ${result.error}`);
    state = result.state;
  }

  assert.deepEqual(state.history, ['e4', 'e5', 'Nf3', 'Nc6']);
});
