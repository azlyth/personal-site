/**
 * Go (9x9).
 *
 * Ported from the collaborative Go implementation that used to live directly
 * in server.js (the getNeighbors/getGroup/hasLiberties/checkAndRemoveCaptures
 * helpers and the go-make-move socket handler). This keeps the exact same
 * rules as that code: plain capture-by-surrounding-liberties plus a suicide
 * check. There is no ko rule here, because the old code never tracked board
 * history to detect one -- this is a straight port, not a redesign.
 *
 * One behaviour change from the old socket handler: the old code took the
 * stone colour from the client (`{ sessionId, row, col, color }`), which let
 * a client claim either colour on any move. This module takes the colour
 * from `state.turn` instead -- the move on the wire is just `{ row, col }`.
 */

const SIZE = 9;

function emptyBoard() {
  return Array.from({ length: SIZE }, () => Array(SIZE).fill(null));
}

function cloneBoard(board) {
  return board.map((row) => row.slice());
}

function initialState() {
  return {
    board: emptyBoard(),
    turn: 'black',
    // Go has no end condition in this implementation, same as the old code --
    // games just keep going. over/result are always false/null.
    over: false,
    result: null,
    captures: { black: 0, white: 0 },
    lastMove: null
  };
}

function getNeighbors(row, col) {
  const neighbors = [];
  if (row > 0) neighbors.push([row - 1, col]);
  if (row < SIZE - 1) neighbors.push([row + 1, col]);
  if (col > 0) neighbors.push([row, col - 1]);
  if (col < SIZE - 1) neighbors.push([row, col + 1]);
  return neighbors;
}

function getGroup(board, row, col, color, visited = new Set()) {
  const key = `${row},${col}`;
  if (visited.has(key) || board[row][col] !== color) {
    return [];
  }

  visited.add(key);
  const group = [[row, col]];

  for (const [nRow, nCol] of getNeighbors(row, col)) {
    if (board[nRow][nCol] === color) {
      group.push(...getGroup(board, nRow, nCol, color, visited));
    }
  }

  return group;
}

function hasLiberties(board, group) {
  for (const [row, col] of group) {
    for (const [nRow, nCol] of getNeighbors(row, col)) {
      if (board[nRow][nCol] === null) {
        return true; // Found an empty space (liberty)
      }
    }
  }
  return false; // No liberties found
}

// Removes any opponent groups adjacent to (lastRow, lastCol) that have no
// liberties left, mutating `board` (a working copy, never the caller's
// state) in place. Returns the list of captured [row, col] points.
function removeCapturedGroups(board, lastRow, lastCol, lastColor) {
  const capturedStones = [];
  const opponentColor = lastColor === 'black' ? 'white' : 'black';
  const processedGroups = new Set();

  for (const [nRow, nCol] of getNeighbors(lastRow, lastCol)) {
    if (board[nRow][nCol] === opponentColor) {
      const groupKey = `${nRow},${nCol}`;
      if (!processedGroups.has(groupKey)) {
        const group = getGroup(board, nRow, nCol, opponentColor);

        for (const [gRow, gCol] of group) {
          processedGroups.add(`${gRow},${gCol}`);
        }

        if (!hasLiberties(board, group)) {
          for (const [gRow, gCol] of group) {
            board[gRow][gCol] = null;
            capturedStones.push([gRow, gCol]);
          }
        }
      }
    }
  }

  return capturedStones;
}

function applyMove(state, move) {
  const row = move && move.row;
  const col = move && move.col;

  if (
    typeof row !== 'number' || !Number.isInteger(row) || row < 0 || row >= SIZE ||
    typeof col !== 'number' || !Number.isInteger(col) || col < 0 || col >= SIZE
  ) {
    return { error: 'Invalid position' };
  }

  if (state.board[row][col] !== null) {
    return { error: 'Position already occupied' };
  }

  const color = state.turn;
  const board = cloneBoard(state.board);
  board[row][col] = color;

  // Apply captures first, exactly like the old handler: a placed stone with
  // no liberties of its own can still be legal if it emptied an opponent
  // group's last liberty in the process.
  const capturedStones = removeCapturedGroups(board, row, col, color);

  const placedGroup = getGroup(board, row, col, color);
  if (capturedStones.length === 0 && !hasLiberties(board, placedGroup)) {
    return { error: 'Invalid move: suicide is not allowed' };
  }

  const opponent = color === 'black' ? 'white' : 'black';
  const captures = {
    ...state.captures,
    [color]: state.captures[color] + capturedStones.length
  };

  return {
    state: {
      board,
      turn: opponent,
      over: false,
      result: null,
      captures,
      lastMove: { row, col }
    }
  };
}

module.exports = {
  id: 'go',
  name: 'Go',
  blurb: 'Nine by nine. Captures count.',
  seats: [{ id: 'black', label: 'Black' }, { id: 'white', label: 'White' }],
  initialState,
  applyMove
};
