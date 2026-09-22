const test = require('node:test');
const assert = require('node:assert');
const connect4 = require('../../games/connect4');

const ROWS = 6;
const COLS = 7;

function emptyBoard() {
  return Array.from({ length: ROWS }, () => Array(COLS).fill(null));
}

// Build a state with a hand-constructed board so win/draw scenarios don't
// depend on fragile move-by-move simulation. The board need not be reachable
// through legal alternating play; applyMove only reads state.board and
// state.turn, so this is a faithful way to test its win/draw logic directly.
function stateWithBoard(setup, turn) {
  const board = emptyBoard();
  setup(board);
  return { board, turn, over: false, result: null, winningCells: null, lastMove: null };
}

test('initialState has an empty 6x7 board and red to move', () => {
  const state = connect4.initialState();
  assert.strictEqual(state.board.length, 6);
  assert.strictEqual(state.board[0].length, 7);
  assert.ok(state.board.every((row) => row.every((cell) => cell === null)));
  assert.strictEqual(state.turn, 'red');
  assert.strictEqual(state.over, false);
  assert.strictEqual(state.result, null);
  assert.strictEqual(state.lastMove, null);
});

test('a disc stacks on top of the previous disc in that column', () => {
  const state = connect4.initialState();

  const first = connect4.applyMove(state, { col: 3 });
  assert.ok(!first.error, first.error);
  assert.strictEqual(first.state.board[5][3], 'red');
  assert.deepStrictEqual(first.state.lastMove, { row: 5, col: 3 });

  const second = connect4.applyMove(first.state, { col: 3 });
  assert.ok(!second.error, second.error);
  assert.strictEqual(second.state.board[4][3], 'yellow');
  assert.strictEqual(second.state.board[5][3], 'red');
  assert.deepStrictEqual(second.state.lastMove, { row: 4, col: 3 });
});

test('a full column is rejected', () => {
  const state = stateWithBoard((board) => {
    // Alternating colors top to bottom: no 4-in-a-row, column simply full.
    board[0][0] = 'yellow';
    board[1][0] = 'red';
    board[2][0] = 'yellow';
    board[3][0] = 'red';
    board[4][0] = 'yellow';
    board[5][0] = 'red';
  }, 'red');

  const result = connect4.applyMove(state, { col: 0 });
  assert.deepStrictEqual(result, { error: 'Column is full' });
});

test('an out-of-range column is rejected', () => {
  const state = connect4.initialState();

  assert.deepStrictEqual(connect4.applyMove(state, { col: -1 }), { error: 'Column out of range' });
  assert.deepStrictEqual(connect4.applyMove(state, { col: 7 }), { error: 'Column out of range' });
});

function redHorizontalWinState() {
  return stateWithBoard((board) => {
    board[5][0] = 'red';
    board[5][1] = 'red';
    board[5][2] = 'red';
    // col 3 bottom left empty; red's move drops there to complete the row.
  }, 'red');
}

test('horizontal win is detected', () => {
  const state = redHorizontalWinState();
  const result = connect4.applyMove(state, { col: 3 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.over, true);
  assert.strictEqual(result.state.turn, null);
  assert.strictEqual(result.state.result, 'Red wins');
  assert.ok(result.state.winningCells);
  assert.strictEqual(result.state.winningCells.length, 4);
  const cols = result.state.winningCells.map((c) => c.col).sort();
  assert.deepStrictEqual(cols, [0, 1, 2, 3]);
});

test('vertical win is detected', () => {
  const state = stateWithBoard((board) => {
    board[5][0] = 'red';
    board[4][0] = 'red';
    board[3][0] = 'red';
    // row 2, col 0 empty; red's move drops there to complete the column.
  }, 'red');

  const result = connect4.applyMove(state, { col: 0 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.over, true);
  assert.strictEqual(result.state.turn, null);
  assert.strictEqual(result.state.result, 'Red wins');
  assert.ok(result.state.winningCells);
  assert.strictEqual(result.state.winningCells.length, 4);
  const rows = result.state.winningCells.map((c) => c.row).sort();
  assert.deepStrictEqual(rows, [2, 3, 4, 5]);
  result.state.winningCells.forEach((c) => assert.strictEqual(c.col, 0));
});

test('diagonal win is detected (top-left to bottom-right)', () => {
  const state = stateWithBoard((board) => {
    // Filler so column 0's lowest empty cell is row 2.
    board[5][0] = 'yellow';
    board[4][0] = 'yellow';
    board[3][0] = 'yellow';
    // Diagonal partners for the new red disc at (2, 0).
    board[3][1] = 'red';
    board[4][2] = 'red';
    board[5][3] = 'red';
  }, 'red');

  const result = connect4.applyMove(state, { col: 0 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.over, true);
  assert.strictEqual(result.state.result, 'Red wins');
  const cells = result.state.winningCells.map((c) => `${c.row},${c.col}`).sort();
  assert.deepStrictEqual(cells, ['2,0', '3,1', '4,2', '5,3']);
});

test('diagonal win is detected (top-right to bottom-left)', () => {
  const state = stateWithBoard((board) => {
    // Filler so column 3's lowest empty cell is row 2.
    board[5][3] = 'yellow';
    board[4][3] = 'yellow';
    board[3][3] = 'yellow';
    // Diagonal partners for the new red disc at (2, 3).
    board[3][2] = 'red';
    board[4][1] = 'red';
    board[5][0] = 'red';
  }, 'red');

  const result = connect4.applyMove(state, { col: 3 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.over, true);
  assert.strictEqual(result.state.result, 'Red wins');
  const cells = result.state.winningCells.map((c) => `${c.row},${c.col}`).sort();
  assert.deepStrictEqual(cells, ['2,3', '3,2', '4,1', '5,0']);
});

test('a full board with no winner is a draw', () => {
  // A board with no 4-in-a-row in any of the 4 directions (verified by
  // exhaustive check), with the top-left cell left open for the final move.
  const FULL_BOARD = [
    ['red', 'yellow', 'red', 'red', 'yellow', 'yellow', 'yellow'],
    ['red', 'red', 'red', 'yellow', 'red', 'red', 'yellow'],
    ['red', 'yellow', 'yellow', 'yellow', 'red', 'red', 'red'],
    ['yellow', 'red', 'red', 'yellow', 'red', 'yellow', 'yellow'],
    ['red', 'red', 'yellow', 'red', 'yellow', 'red', 'yellow'],
    ['yellow', 'yellow', 'yellow', 'red', 'red', 'red', 'yellow']
  ];

  const state = stateWithBoard((board) => {
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        board[r][c] = FULL_BOARD[r][c];
      }
    }
    board[0][0] = null; // left for the final move
  }, 'red'); // FULL_BOARD[0][0] === 'red' completes the pattern

  const result = connect4.applyMove(state, { col: 0 });

  assert.ok(!result.error, result.error);
  assert.strictEqual(result.state.board[0][0], 'red');
  assert.strictEqual(result.state.over, true);
  assert.strictEqual(result.state.turn, null);
  assert.strictEqual(result.state.result, 'Draw - board full');
  assert.strictEqual(result.state.winningCells, null);
  assert.ok(result.state.board.every((row) => row.every((cell) => cell !== null)));
});

test('moves after the game is over are rejected', () => {
  const state = redHorizontalWinState();
  const won = connect4.applyMove(state, { col: 3 });
  assert.strictEqual(won.state.over, true);

  const result = connect4.applyMove(won.state, { col: 4 });
  assert.deepStrictEqual(result, { error: 'Game is already over' });
});

test('applyMove does not mutate the state it was given', () => {
  const state = connect4.initialState();
  const boardSnapshot = JSON.parse(JSON.stringify(state.board));

  connect4.applyMove(state, { col: 2 });

  assert.deepStrictEqual(state.board, boardSnapshot);
  assert.strictEqual(state.turn, 'red');
  assert.strictEqual(state.over, false);
  assert.strictEqual(state.lastMove, null);
});
