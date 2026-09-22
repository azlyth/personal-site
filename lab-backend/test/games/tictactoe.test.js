const test = require('node:test');
const assert = require('node:assert');
const tictactoe = require('../../games/tictactoe');

function emptyBoard() {
  return [
    [null, null, null],
    [null, null, null],
    [null, null, null]
  ];
}

function stateWithBoard(setup, turn) {
  const board = emptyBoard();
  setup(board);
  return { board, turn, over: false, result: null, winningCells: null, lastMove: null };
}

test('initialState has an empty 3x3 board and x to move', () => {
  const state = tictactoe.initialState();
  assert.strictEqual(state.board.length, 3);
  assert.ok(state.board.every((row) => row.length === 3 && row.every((c) => c === null)));
  assert.strictEqual(state.turn, 'x');
  assert.strictEqual(state.over, false);
  assert.strictEqual(state.result, null);
  assert.strictEqual(state.lastMove, null);
});

test('an occupied cell is rejected', () => {
  const first = tictactoe.applyMove(tictactoe.initialState(), { row: 0, col: 0 });
  assert.ok(!first.error, first.error);

  const second = tictactoe.applyMove(first.state, { row: 0, col: 0 });
  assert.deepStrictEqual(second, { error: 'Cell is occupied' });
});

test('an out-of-range cell is rejected', () => {
  const state = tictactoe.initialState();

  assert.deepStrictEqual(tictactoe.applyMove(state, { row: -1, col: 0 }), { error: 'Cell out of range' });
  assert.deepStrictEqual(tictactoe.applyMove(state, { row: 3, col: 0 }), { error: 'Cell out of range' });
  assert.deepStrictEqual(tictactoe.applyMove(state, { row: 0, col: -1 }), { error: 'Cell out of range' });
  assert.deepStrictEqual(tictactoe.applyMove(state, { row: 0, col: 3 }), { error: 'Cell out of range' });
});

test('a row win is detected', () => {
  const state = stateWithBoard((board) => {
    board[1][0] = 'x';
    board[1][1] = 'x';
    // (1, 2) empty; x's move completes the middle row.
    board[0][0] = 'o';
    board[0][1] = 'o';
  }, 'x');

  const result = tictactoe.applyMove(state, { row: 1, col: 2 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.over, true);
  assert.strictEqual(result.state.turn, null);
  assert.strictEqual(result.state.result, 'X wins');
  const cells = result.state.winningCells.map((c) => `${c.row},${c.col}`).sort();
  assert.deepStrictEqual(cells, ['1,0', '1,1', '1,2']);
});

test('a column win is detected', () => {
  const state = stateWithBoard((board) => {
    board[0][2] = 'o';
    board[1][2] = 'o';
    // (2, 2) empty; o's move completes the right column.
    board[0][0] = 'x';
    board[1][0] = 'x';
  }, 'o');

  const result = tictactoe.applyMove(state, { row: 2, col: 2 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.over, true);
  assert.strictEqual(result.state.turn, null);
  assert.strictEqual(result.state.result, 'O wins');
  const cells = result.state.winningCells.map((c) => `${c.row},${c.col}`).sort();
  assert.deepStrictEqual(cells, ['0,2', '1,2', '2,2']);
});

test('the top-left to bottom-right diagonal win is detected', () => {
  const state = stateWithBoard((board) => {
    board[0][0] = 'x';
    board[1][1] = 'x';
    // (2, 2) empty; x's move completes the diagonal.
    board[0][1] = 'o';
    board[0][2] = 'o';
  }, 'x');

  const result = tictactoe.applyMove(state, { row: 2, col: 2 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.result, 'X wins');
  const cells = result.state.winningCells.map((c) => `${c.row},${c.col}`).sort();
  assert.deepStrictEqual(cells, ['0,0', '1,1', '2,2']);
});

test('the top-right to bottom-left diagonal win is detected', () => {
  const state = stateWithBoard((board) => {
    board[0][2] = 'o';
    board[1][1] = 'o';
    // (2, 0) empty; o's move completes the diagonal.
    board[0][0] = 'x';
    board[0][1] = 'x';
  }, 'o');

  const result = tictactoe.applyMove(state, { row: 2, col: 0 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.result, 'O wins');
  const cells = result.state.winningCells.map((c) => `${c.row},${c.col}`).sort();
  assert.deepStrictEqual(cells, ['0,2', '1,1', '2,0']);
});

test('a full board with no winner is a draw', () => {
  // x o x
  // x o o
  // o x x
  // No row, column or diagonal is uniform; (2, 2) is left for the final move.
  const state = stateWithBoard((board) => {
    board[0][0] = 'x';
    board[0][1] = 'o';
    board[0][2] = 'x';
    board[1][0] = 'x';
    board[1][1] = 'o';
    board[1][2] = 'o';
    board[2][0] = 'o';
    board[2][1] = 'x';
    // (2, 2) left empty for the final move.
  }, 'x');

  const result = tictactoe.applyMove(state, { row: 2, col: 2 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.board[2][2], 'x');
  assert.strictEqual(result.state.over, true);
  assert.strictEqual(result.state.turn, null);
  assert.strictEqual(result.state.result, 'Draw');
  assert.strictEqual(result.state.winningCells, null);
});

test('moves after the game is over are rejected', () => {
  const state = stateWithBoard((board) => {
    board[1][0] = 'x';
    board[1][1] = 'x';
    board[0][0] = 'o';
    board[0][1] = 'o';
  }, 'x');

  const won = tictactoe.applyMove(state, { row: 1, col: 2 });
  assert.strictEqual(won.state.over, true);

  const result = tictactoe.applyMove(won.state, { row: 2, col: 2 });
  assert.deepStrictEqual(result, { error: 'Game is already over' });
});

test('applyMove does not mutate the state it was given', () => {
  const state = tictactoe.initialState();
  const boardSnapshot = JSON.parse(JSON.stringify(state.board));

  tictactoe.applyMove(state, { row: 1, col: 1 });

  assert.deepStrictEqual(state.board, boardSnapshot);
  assert.strictEqual(state.turn, 'x');
  assert.strictEqual(state.over, false);
  assert.strictEqual(state.lastMove, null);
});
