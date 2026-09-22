const test = require('node:test');
const assert = require('node:assert');

const checkers = require('../../games/checkers');

// ---- helpers -------------------------------------------------------------

function emptyBoard() {
  return Array.from({ length: 8 }, () => Array(8).fill(null));
}

function makeState(pieces, { turn = 'red', mustContinueFrom = null } = {}) {
  const board = emptyBoard();
  for (const [row, col, color, king = false] of pieces) {
    board[row][col] = { color, king };
  }
  return {
    board,
    turn,
    over: false,
    result: null,
    mustContinueFrom,
    lastMove: null,
    legalMoves: [],
  };
}

function countAll(board, color) {
  let n = 0;
  for (const row of board) for (const cell of row) if (cell && cell.color === color) n += 1;
  return n;
}

// ---- initial layout --------------------------------------------------

test('initial state: 12 pieces a side, on dark squares, correct rows', () => {
  const state = checkers.initialState();
  assert.strictEqual(state.turn, 'red');
  assert.strictEqual(state.over, false);
  assert.strictEqual(state.result, null);
  assert.strictEqual(state.mustContinueFrom, null);

  let redCount = 0;
  let blackCount = 0;
  for (let row = 0; row < 8; row += 1) {
    for (let col = 0; col < 8; col += 1) {
      const cell = state.board[row][col];
      if (!cell) continue;
      assert.strictEqual((row + col) % 2, 1, `piece at (${row},${col}) is not on a dark square`);
      assert.strictEqual(cell.king, false);
      if (cell.color === 'red') {
        redCount += 1;
        assert.ok(row <= 2, 'red pieces start in rows 0-2');
      } else if (cell.color === 'black') {
        blackCount += 1;
        assert.ok(row >= 5, 'black pieces start in rows 5-7');
      }
    }
  }
  assert.strictEqual(redCount, 12);
  assert.strictEqual(blackCount, 12);

  // middle two rows are empty
  for (let col = 0; col < 8; col += 1) {
    assert.strictEqual(state.board[3][col], null);
    assert.strictEqual(state.board[4][col], null);
  }
});

// ---- basic move legality ----------------------------------------------

test('a legal opening man move succeeds and passes the turn', () => {
  const state = checkers.initialState();
  const { state: next, error } = checkers.applyMove(state, {
    from: { row: 2, col: 1 },
    to: { row: 3, col: 0 },
  });
  assert.strictEqual(error, undefined);
  assert.strictEqual(next.board[2][1], null);
  assert.deepStrictEqual(next.board[3][0], { color: 'red', king: false });
  assert.strictEqual(next.turn, 'black');
  assert.strictEqual(next.over, false);
  assert.strictEqual(next.mustContinueFrom, null);
});

test('a backwards man move is rejected', () => {
  const state = makeState([[3, 2, 'red']], { turn: 'red' });
  const result = checkers.applyMove(state, { from: { row: 3, col: 2 }, to: { row: 2, col: 1 } });
  assert.ok(result.error, 'expected an error');
  assert.match(result.error, /forward/i);
  // original state is untouched
  assert.deepStrictEqual(state.board[3][2], { color: 'red', king: false });
});

test('moving the wrong colour piece is rejected', () => {
  const state = makeState(
    [
      [2, 3, 'red'],
      [5, 4, 'black'],
    ],
    { turn: 'red' },
  );
  const result = checkers.applyMove(state, { from: { row: 5, col: 4 }, to: { row: 4, col: 3 } });
  assert.ok(result.error);
  assert.match(result.error, /turn/i);
});

// ---- captures ------------------------------------------------------------

test('a capture removes the jumped piece', () => {
  const state = makeState(
    [
      [2, 3, 'red'],
      [3, 4, 'black'],
      [6, 7, 'black'], // keeps black alive/mobile after the capture
    ],
    { turn: 'red' },
  );
  const { state: next, error } = checkers.applyMove(state, {
    from: { row: 2, col: 3 },
    to: { row: 4, col: 5 },
  });
  assert.strictEqual(error, undefined);
  assert.strictEqual(next.board[3][4], null, 'jumped piece removed');
  assert.strictEqual(next.board[2][3], null);
  assert.deepStrictEqual(next.board[4][5], { color: 'red', king: false });
  assert.strictEqual(next.turn, 'black');
  assert.strictEqual(next.over, false);
});

test('a plain move is rejected when a capture is available (compulsory capture)', () => {
  const state = makeState(
    [
      [2, 3, 'red'],
      [3, 4, 'black'],
      [0, 1, 'red'], // has an unrelated, otherwise-legal plain move
    ],
    { turn: 'red' },
  );
  const result = checkers.applyMove(state, { from: { row: 0, col: 1 }, to: { row: 1, col: 0 } });
  assert.ok(result.error);
  assert.match(result.error, /capture/i);
});

test('multi-jump: same piece must continue, turn stays, unrelated piece is locked out', () => {
  const state = makeState(
    [
      [2, 3, 'red'],
      [3, 4, 'black'],
      [5, 6, 'black'],
      [7, 6, 'black'], // keeps black mobile throughout, out of the chain's path
      [0, 1, 'red'], // unrelated piece with an otherwise-legal plain move
    ],
    { turn: 'red' },
  );

  // first jump: (2,3) -> (4,5), capturing (3,4); another capture is available
  // from (4,5) over (5,6) landing on (6,7), so the chain must continue.
  const first = checkers.applyMove(state, { from: { row: 2, col: 3 }, to: { row: 4, col: 5 } });
  assert.strictEqual(first.error, undefined);
  assert.strictEqual(first.state.turn, 'red', 'turn stays with the jumping side');
  assert.deepStrictEqual(first.state.mustContinueFrom, { row: 4, col: 5 });
  assert.strictEqual(first.state.board[3][4], null);

  // the unrelated piece may not move mid-chain
  const wrongPiece = checkers.applyMove(first.state, {
    from: { row: 0, col: 1 },
    to: { row: 1, col: 0 },
  });
  assert.ok(wrongPiece.error);
  assert.match(wrongPiece.error, /continue/i);

  // the same piece finishes the chain
  const second = checkers.applyMove(first.state, {
    from: { row: 4, col: 5 },
    to: { row: 6, col: 7 },
  });
  assert.strictEqual(second.error, undefined);
  assert.strictEqual(second.state.board[5][6], null, 'second jumped piece removed');
  assert.deepStrictEqual(second.state.board[6][7], { color: 'red', king: false });
  assert.strictEqual(second.state.mustContinueFrom, null);
  assert.strictEqual(second.state.turn, 'black', 'turn passes once the chain ends');
});

// ---- kinging ---------------------------------------------------------

test('a man is crowned on reaching the back rank', () => {
  const state = makeState(
    [
      [6, 3, 'red'],
      [2, 5, 'black'], // keeps black mobile (away from any board edge)
    ],
    { turn: 'red' },
  );
  const { state: next, error } = checkers.applyMove(state, {
    from: { row: 6, col: 3 },
    to: { row: 7, col: 4 },
  });
  assert.strictEqual(error, undefined);
  assert.deepStrictEqual(next.board[7][4], { color: 'red', king: true });
  assert.strictEqual(next.turn, 'black');
});

test('kinging mid-jump ends the chain even if another capture would be available', () => {
  const state = makeState(
    [
      [5, 2, 'red'],
      [6, 3, 'black'], // jumped to land on the back rank
      [6, 5, 'black'], // would offer a further capture for a king, but chain must end
    ],
    { turn: 'red' },
  );
  const { state: next, error } = checkers.applyMove(state, {
    from: { row: 5, col: 2 },
    to: { row: 7, col: 4 },
  });
  assert.strictEqual(error, undefined);
  assert.deepStrictEqual(next.board[7][4], { color: 'red', king: true });
  assert.strictEqual(next.board[6][3], null, 'captured piece removed');
  assert.deepStrictEqual(next.board[6][5], { color: 'black', king: false }, 'untouched piece remains');
  assert.strictEqual(next.mustContinueFrom, null, 'chain ends at kinging');
  assert.strictEqual(next.turn, 'black', 'turn passes even though the new king could jump again');
});

test('a king may move backwards', () => {
  const state = makeState([[4, 3, 'red', true]], { turn: 'red' });
  const { state: next, error } = checkers.applyMove(state, {
    from: { row: 4, col: 3 },
    to: { row: 3, col: 2 },
  });
  assert.strictEqual(error, undefined);
  assert.deepStrictEqual(next.board[3][2], { color: 'red', king: true });
});

// ---- win detection ---------------------------------------------------

test('a side with no pieces left loses', () => {
  const state = makeState(
    [
      [2, 3, 'red'],
      [3, 4, 'black'], // black's only piece
    ],
    { turn: 'red' },
  );
  const { state: next, error } = checkers.applyMove(state, {
    from: { row: 2, col: 3 },
    to: { row: 4, col: 5 },
  });
  assert.strictEqual(error, undefined);
  assert.strictEqual(countAll(next.board, 'black'), 0);
  assert.strictEqual(next.over, true);
  assert.strictEqual(next.turn, null);
  assert.match(next.result, /red wins/i);
  assert.match(next.result, /no pieces left/i);
});

test('a side with no legal moves loses', () => {
  // black's only piece is boxed into the corner: its one diagonal forward
  // step is occupied, and the square beyond for a jump is also occupied.
  const state = makeState(
    [
      [7, 0, 'black'],
      [6, 1, 'red'],
      [5, 2, 'red'],
      [0, 1, 'red'], // red's piece that actually makes the move
    ],
    { turn: 'red' },
  );
  const { state: next, error } = checkers.applyMove(state, {
    from: { row: 0, col: 1 },
    to: { row: 1, col: 0 },
  });
  assert.strictEqual(error, undefined);
  assert.strictEqual(next.over, true);
  assert.strictEqual(next.turn, null);
  assert.match(next.result, /red wins/i);
  assert.match(next.result, /no moves left/i);
});

// ---- purity ------------------------------------------------------------

test('applyMove does not mutate the state it is given', () => {
  const state = checkers.initialState();
  const snapshot = JSON.stringify(state);
  const boardRef = state.board;

  const { state: next, error } = checkers.applyMove(state, {
    from: { row: 2, col: 1 },
    to: { row: 3, col: 0 },
  });

  assert.strictEqual(error, undefined);
  assert.strictEqual(JSON.stringify(state), snapshot, 'input state was not mutated');
  assert.strictEqual(state.board, boardRef, 'input board reference unchanged');
  assert.notStrictEqual(next.board, state.board, 'a new board object was returned');
  assert.notStrictEqual(next, state, 'a new state object was returned');
});

// ---- legalMovesFrom helper --------------------------------------------

test('legalMovesFrom reports the right destinations for a piece', () => {
  const state = checkers.initialState();
  const dests = checkers.legalMovesFrom(state, { row: 2, col: 1 });
  const sorted = dests.slice().sort((a, b) => a.col - b.col);
  assert.deepStrictEqual(sorted, [
    { row: 3, col: 0 },
    { row: 3, col: 2 },
  ]);

  // an empty square has no legal moves
  assert.deepStrictEqual(checkers.legalMovesFrom(state, { row: 3, col: 0 }), []);
});
