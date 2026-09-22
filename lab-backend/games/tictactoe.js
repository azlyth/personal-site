/**
 * Tic-Tac-Toe.
 *
 * Board is a 3x3 grid, stored as board[row][col].
 */

const SIZE = 3;

function displayName(player) {
  return player === 'x' ? 'X' : 'O';
}

function otherPlayer(player) {
  return player === 'x' ? 'o' : 'x';
}

function emptyBoard() {
  return Array.from({ length: SIZE }, () => Array(SIZE).fill(null));
}

function initialState() {
  return {
    board: emptyBoard(),
    turn: 'x',
    over: false,
    result: null,
    winningCells: null,
    lastMove: null
  };
}

function cloneBoard(board) {
  return board.map((row) => row.slice());
}

function lineCells(board) {
  const lines = [];

  for (let r = 0; r < SIZE; r++) {
    lines.push([{ row: r, col: 0 }, { row: r, col: 1 }, { row: r, col: 2 }]);
  }

  for (let c = 0; c < SIZE; c++) {
    lines.push([{ row: 0, col: c }, { row: 1, col: c }, { row: 2, col: c }]);
  }

  lines.push([{ row: 0, col: 0 }, { row: 1, col: 1 }, { row: 2, col: 2 }]);
  lines.push([{ row: 0, col: 2 }, { row: 1, col: 1 }, { row: 2, col: 0 }]);

  return lines;
}

function findWinningCells(board) {
  for (const line of lineCells(board)) {
    const values = line.map(({ row, col }) => board[row][col]);
    if (values[0] !== null && values[0] === values[1] && values[1] === values[2]) {
      return line;
    }
  }
  return null;
}

function boardIsFull(board) {
  return board.every((row) => row.every((cell) => cell !== null));
}

function applyMove(state, move) {
  if (state.over) {
    return { error: 'Game is already over' };
  }

  const row = move && move.row;
  const col = move && move.col;

  if (
    typeof row !== 'number' || !Number.isInteger(row) || row < 0 || row >= SIZE ||
    typeof col !== 'number' || !Number.isInteger(col) || col < 0 || col >= SIZE
  ) {
    return { error: 'Cell out of range' };
  }

  if (state.board[row][col] !== null) {
    return { error: 'Cell is occupied' };
  }

  const board = cloneBoard(state.board);
  const player = state.turn;
  board[row][col] = player;

  const winningCells = findWinningCells(board);

  let turn = otherPlayer(player);
  let over = false;
  let result = null;

  if (winningCells) {
    over = true;
    turn = null;
    result = `${displayName(player)} wins`;
  } else if (boardIsFull(board)) {
    over = true;
    turn = null;
    result = 'Draw';
  }

  return {
    state: {
      board,
      turn,
      over,
      result,
      winningCells: winningCells || null,
      lastMove: { row, col }
    }
  };
}

module.exports = {
  id: 'tictactoe',
  name: 'Tic-Tac-Toe',
  blurb: 'It ends in a draw. Play anyway.',
  initialState,
  applyMove
};
