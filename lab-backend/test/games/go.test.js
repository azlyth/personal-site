const test = require('node:test');
const assert = require('node:assert');
const go = require('../../games/go');

function emptyBoard() {
  return Array.from({ length: 9 }, () => Array(9).fill(null));
}

function deepFreeze(value) {
  if (Array.isArray(value)) {
    value.forEach(deepFreeze);
    return Object.freeze(value);
  }
  if (value && typeof value === 'object') {
    Object.values(value).forEach(deepFreeze);
    return Object.freeze(value);
  }
  return value;
}

test('initial state is an empty 9x9 board with black to move', () => {
  const state = go.initialState();

  assert.strictEqual(state.board.length, 9);
  state.board.forEach((row) => {
    assert.strictEqual(row.length, 9);
    row.forEach((cell) => assert.strictEqual(cell, null));
  });

  assert.strictEqual(state.turn, 'black');
  assert.strictEqual(state.over, false);
  assert.strictEqual(state.result, null);
  assert.deepStrictEqual(state.captures, { black: 0, white: 0 });
  assert.strictEqual(state.lastMove, null);
});

test('a stone is placed and the turn alternates', () => {
  const state = go.initialState();

  const { state: next, error } = go.applyMove(state, { row: 2, col: 3 });

  assert.strictEqual(error, undefined);
  assert.strictEqual(next.board[2][3], 'black');
  assert.strictEqual(next.turn, 'white');
  assert.deepStrictEqual(next.lastMove, { row: 2, col: 3 });

  const { state: afterWhite } = go.applyMove(next, { row: 4, col: 4 });
  assert.strictEqual(afterWhite.board[4][4], 'white');
  assert.strictEqual(afterWhite.turn, 'black');
});

test('placing on an occupied point is rejected', () => {
  const state = go.initialState();
  const { state: next } = go.applyMove(state, { row: 0, col: 0 });

  const result = go.applyMove(next, { row: 0, col: 0 });

  assert.strictEqual(result.state, undefined);
  assert.ok(result.error);
  // Board and turn are unaffected by a rejected move.
  assert.strictEqual(next.board[0][0], 'black');
});

test('out-of-range coordinates are rejected', () => {
  const state = go.initialState();

  for (const move of [
    { row: -1, col: 0 },
    { row: 0, col: -1 },
    { row: 9, col: 0 },
    { row: 0, col: 9 },
    { row: 1.5, col: 0 }
  ]) {
    const result = go.applyMove(state, move);
    assert.strictEqual(result.state, undefined, `expected rejection for ${JSON.stringify(move)}`);
    assert.ok(result.error);
  }
});

test('a single stone with its last liberty filled is captured', () => {
  const board = emptyBoard();
  board[4][4] = 'white';
  board[3][4] = 'black';
  board[5][4] = 'black';
  board[4][3] = 'black';
  // (4,5) is white's last liberty.

  const state = {
    board,
    turn: 'black',
    over: false,
    result: null,
    captures: { black: 0, white: 0 },
    lastMove: null
  };

  const { state: next, error } = go.applyMove(state, { row: 4, col: 5 });

  assert.strictEqual(error, undefined);
  assert.strictEqual(next.board[4][4], null, 'captured stone is removed');
  assert.strictEqual(next.board[4][5], 'black', 'capturing stone is placed');
  assert.deepStrictEqual(next.captures, { black: 1, white: 0 });
});

test('a multi-stone group is captured together', () => {
  const board = emptyBoard();
  board[4][4] = 'white';
  board[4][5] = 'white';
  board[3][4] = 'black';
  board[3][5] = 'black';
  board[5][4] = 'black';
  board[5][5] = 'black';
  board[4][3] = 'black';
  // (4,6) is the group's last liberty.

  const state = {
    board,
    turn: 'black',
    over: false,
    result: null,
    captures: { black: 0, white: 0 },
    lastMove: null
  };

  const { state: next, error } = go.applyMove(state, { row: 4, col: 6 });

  assert.strictEqual(error, undefined);
  assert.strictEqual(next.board[4][4], null);
  assert.strictEqual(next.board[4][5], null);
  assert.strictEqual(next.board[4][6], 'black');
  assert.deepStrictEqual(next.captures, { black: 2, white: 0 });
});

test('a stone with remaining liberties is not captured', () => {
  const board = emptyBoard();
  board[4][4] = 'white';

  const state = {
    board,
    turn: 'black',
    over: false,
    result: null,
    captures: { black: 0, white: 0 },
    lastMove: null
  };

  const { state: next, error } = go.applyMove(state, { row: 3, col: 4 });

  assert.strictEqual(error, undefined);
  assert.strictEqual(next.board[4][4], 'white', 'white stone survives with liberties left');
  assert.deepStrictEqual(next.captures, { black: 0, white: 0 });
});

test('a capture works in a corner', () => {
  const board = emptyBoard();
  board[0][0] = 'white';
  board[0][1] = 'black';
  // (1,0) is white's last liberty.

  const state = {
    board,
    turn: 'black',
    over: false,
    result: null,
    captures: { black: 0, white: 0 },
    lastMove: null
  };

  const { state: next, error } = go.applyMove(state, { row: 1, col: 0 });

  assert.strictEqual(error, undefined);
  assert.strictEqual(next.board[0][0], null);
  assert.strictEqual(next.board[1][0], 'black');
  assert.deepStrictEqual(next.captures, { black: 1, white: 0 });
});

test('applyMove does not mutate its input state', () => {
  const board = emptyBoard();
  board[4][4] = 'white';
  board[3][4] = 'black';
  board[5][4] = 'black';
  board[4][3] = 'black';

  const state = deepFreeze({
    board,
    turn: 'black',
    over: false,
    result: null,
    captures: { black: 0, white: 0 },
    lastMove: null
  });

  // A frozen state throws (in strict mode, which modules are under by
  // default) if applyMove tries to write through it anywhere.
  assert.doesNotThrow(() => go.applyMove(state, { row: 4, col: 5 }));

  assert.strictEqual(state.board[4][4], 'white');
  assert.deepStrictEqual(state.captures, { black: 0, white: 0 });
  assert.strictEqual(state.lastMove, null);
});
