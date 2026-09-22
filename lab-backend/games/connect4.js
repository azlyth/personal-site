/**
 * Connect Four.
 *
 * Board is 7 columns x 6 rows, stored as board[row][col] with row 0 at the
 * top and row (ROWS - 1) at the bottom. A disc dropped into a column comes
 * to rest in the lowest empty cell.
 */

const COLS = 7;
const ROWS = 6;

function displayName(player) {
  return player === 'red' ? 'Red' : 'Yellow';
}

function otherPlayer(player) {
  return player === 'red' ? 'yellow' : 'red';
}

function emptyBoard() {
  return Array.from({ length: ROWS }, () => Array(COLS).fill(null));
}

function initialState() {
  return {
    board: emptyBoard(),
    turn: 'red',
    over: false,
    result: null,
    winningCells: null,
    lastMove: null
  };
}

function cloneBoard(board) {
  return board.map((row) => row.slice());
}

const DIRECTIONS = [
  { dr: 0, dc: 1 }, // horizontal
  { dr: 1, dc: 0 }, // vertical
  { dr: 1, dc: 1 }, // diagonal down-right
  { dr: 1, dc: -1 } // diagonal down-left
];

function findWinningCells(board, row, col) {
  const player = board[row][col];
  if (!player) return null;

  for (const { dr, dc } of DIRECTIONS) {
    const cells = [{ row, col }];

    // Walk forward.
    let r = row + dr;
    let c = col + dc;
    while (r >= 0 && r < ROWS && c >= 0 && c < COLS && board[r][c] === player) {
      cells.push({ row: r, col: c });
      r += dr;
      c += dc;
    }

    // Walk backward.
    r = row - dr;
    c = col - dc;
    while (r >= 0 && r < ROWS && c >= 0 && c < COLS && board[r][c] === player) {
      cells.push({ row: r, col: c });
      r -= dr;
      c -= dc;
    }

    if (cells.length >= 4) {
      return cells;
    }
  }

  return null;
}

function boardIsFull(board) {
  return board[0].every((cell) => cell !== null);
}

function applyMove(state, move) {
  if (state.over) {
    return { error: 'Game is already over' };
  }

  const col = move && move.col;
  if (typeof col !== 'number' || !Number.isInteger(col) || col < 0 || col >= COLS) {
    return { error: 'Column out of range' };
  }

  const board = cloneBoard(state.board);

  let row = -1;
  for (let r = ROWS - 1; r >= 0; r--) {
    if (board[r][col] === null) {
      row = r;
      break;
    }
  }

  if (row === -1) {
    return { error: 'Column is full' };
  }

  const player = state.turn;
  board[row][col] = player;

  const winningCells = findWinningCells(board, row, col);

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
    result = 'Draw - board full';
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
  id: 'connect4',
  name: 'Connect Four',
  blurb: 'Drop a disc, get four in a row.',
  seats: [{ id: 'red', label: 'Red' }, { id: 'yellow', label: 'Yellow' }],
  initialState,
  applyMove
};
