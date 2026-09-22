/**
 * Checkers (standard English draughts).
 *
 * Board: 8x8, pieces live only on dark squares (row + col is odd). Red starts
 * on rows 0-2 and moves "forward" toward increasing row numbers; black starts
 * on rows 5-7 and moves forward toward decreasing row numbers. Red moves
 * first.
 *
 * Men move/capture diagonally forward only. Kings move/capture diagonally in
 * any of the four directions. Captures are compulsory: if the player to move
 * has ANY capture available anywhere on the board, a non-capturing move is
 * rejected. A capturing piece that lands with another capture available must
 * keep jumping (multi-jump); the turn does not pass and no other piece may
 * move until the chain ends. If a man is crowned (reaches the far back rank)
 * mid-chain, the chain ends immediately even if the newly-made king could
 * technically jump again.
 *
 * State shape:
 *   {
 *     board: 8x8 array of row arrays; each cell is null or
 *            { color: 'red' | 'black', king: boolean },
 *     turn: 'red' | 'black' | null,   // null once the game is over
 *     over: boolean,
 *     result: string | null,          // e.g. "Red wins - Black has no moves left"
 *     mustContinueFrom: { row, col } | null,  // set mid multi-jump; only this
 *                                              // piece may move until the chain ends
 *     lastMove: { from, to, captured: {row,col}|null, crowned: boolean } | null,
 *     legalMoves: [{ from: {row,col}, to: {row,col} }, ...]  // every legal
 *            move for the side to move, already filtered for compulsory
 *            capture and (if set) locked to mustContinueFrom
 *   }
 *
 * Move shape on the wire: { from: {row, col}, to: {row, col} }.
 *
 * Exports beyond the standard module contract:
 *   legalMovesFrom(state, {row, col}) -> [{row, col}, ...]
 *     Convenience helper for a client that wants "what squares can the piece
 *     at (row, col) move to right now", derived from state.legalMoves. Equally
 *     the client can just filter state.legalMoves itself; both are exposed.
 */

const SIZE = 8;

function inBounds(row, col) {
  return row >= 0 && row < SIZE && col >= 0 && col < SIZE;
}

function isDarkSquare(row, col) {
  return (row + col) % 2 === 1;
}

function opponent(color) {
  return color === 'red' ? 'black' : 'red';
}

function forwardDir(color) {
  return color === 'red' ? 1 : -1;
}

function backRankFor(color) {
  return color === 'red' ? SIZE - 1 : 0;
}

function capitalize(word) {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function cloneBoard(board) {
  return board.map((row) => row.map((cell) => (cell ? { ...cell } : null)));
}

function directionsFor(piece) {
  if (piece.king) {
    return [
      [1, 1],
      [1, -1],
      [-1, 1],
      [-1, -1],
    ];
  }
  const dir = forwardDir(piece.color);
  return [
    [dir, 1],
    [dir, -1],
  ];
}

/** Single-jump capture options for the piece at (row, col). */
function pieceCaptureMoves(board, row, col) {
  const piece = board[row][col];
  if (!piece) return [];
  const moves = [];
  for (const [dr, dc] of directionsFor(piece)) {
    const midRow = row + dr;
    const midCol = col + dc;
    const toRow = row + 2 * dr;
    const toCol = col + 2 * dc;
    if (!inBounds(toRow, toCol)) continue;
    const midPiece = board[midRow][midCol];
    if (midPiece && midPiece.color !== piece.color && board[toRow][toCol] === null) {
      moves.push({ to: { row: toRow, col: toCol }, captured: { row: midRow, col: midCol } });
    }
  }
  return moves;
}

/** Non-capturing single-step diagonal moves for the piece at (row, col). */
function pieceSimpleMoves(board, row, col) {
  const piece = board[row][col];
  if (!piece) return [];
  const moves = [];
  for (const [dr, dc] of directionsFor(piece)) {
    const toRow = row + dr;
    const toCol = col + dc;
    if (!inBounds(toRow, toCol)) continue;
    if (board[toRow][toCol] === null) moves.push({ to: { row: toRow, col: toCol } });
  }
  return moves;
}

/**
 * Whether `color` has at least one capture available. If `restrictTo` is
 * given, only that square's piece is considered (used mid multi-jump, where
 * only the continuing piece may move).
 */
function anyCaptureAvailable(board, color, restrictTo) {
  if (restrictTo) {
    return pieceCaptureMoves(board, restrictTo.row, restrictTo.col).length > 0;
  }
  for (let row = 0; row < SIZE; row += 1) {
    for (let col = 0; col < SIZE; col += 1) {
      const piece = board[row][col];
      if (piece && piece.color === color && pieceCaptureMoves(board, row, col).length > 0) {
        return true;
      }
    }
  }
  return false;
}

function anySimpleMoveAvailable(board, color) {
  for (let row = 0; row < SIZE; row += 1) {
    for (let col = 0; col < SIZE; col += 1) {
      const piece = board[row][col];
      if (piece && piece.color === color && pieceSimpleMoves(board, row, col).length > 0) {
        return true;
      }
    }
  }
  return false;
}

function countPieces(board, color) {
  let count = 0;
  for (let row = 0; row < SIZE; row += 1) {
    for (let col = 0; col < SIZE; col += 1) {
      if (board[row][col] && board[row][col].color === color) count += 1;
    }
  }
  return count;
}

/** All legal moves for `turn`, honoring compulsory capture and a mid-chain lock. */
function computeLegalMoves(board, turn, mustContinueFrom) {
  if (!turn) return [];

  if (mustContinueFrom) {
    return pieceCaptureMoves(board, mustContinueFrom.row, mustContinueFrom.col).map((m) => ({
      from: { row: mustContinueFrom.row, col: mustContinueFrom.col },
      to: m.to,
    }));
  }

  const captures = [];
  for (let row = 0; row < SIZE; row += 1) {
    for (let col = 0; col < SIZE; col += 1) {
      const piece = board[row][col];
      if (piece && piece.color === turn) {
        for (const m of pieceCaptureMoves(board, row, col)) {
          captures.push({ from: { row, col }, to: m.to });
        }
      }
    }
  }
  if (captures.length > 0) return captures;

  const simples = [];
  for (let row = 0; row < SIZE; row += 1) {
    for (let col = 0; col < SIZE; col += 1) {
      const piece = board[row][col];
      if (piece && piece.color === turn) {
        for (const m of pieceSimpleMoves(board, row, col)) {
          simples.push({ from: { row, col }, to: m.to });
        }
      }
    }
  }
  return simples;
}

/**
 * Convenience helper: legal destination squares for the piece at `square`,
 * given the already-computed state.legalMoves. Returns [] if that square has
 * no legal moves right now (wrong turn, locked out by a mid-chain capture,
 * compulsory capture elsewhere, etc).
 */
function legalMovesFrom(state, square) {
  if (!square || !Array.isArray(state.legalMoves)) return [];
  return state.legalMoves
    .filter((m) => m.from.row === square.row && m.from.col === square.col)
    .map((m) => ({ row: m.to.row, col: m.to.col }));
}

function checkGameOver(board, colorToMove) {
  if (countPieces(board, colorToMove) === 0) {
    const winner = opponent(colorToMove);
    return `${capitalize(winner)} wins - ${capitalize(colorToMove)} has no pieces left`;
  }
  if (!anyCaptureAvailable(board, colorToMove) && !anySimpleMoveAvailable(board, colorToMove)) {
    const winner = opponent(colorToMove);
    return `${capitalize(winner)} wins - ${capitalize(colorToMove)} has no moves left`;
  }
  return null;
}

function createInitialBoard() {
  const board = Array.from({ length: SIZE }, () => Array(SIZE).fill(null));
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < SIZE; col += 1) {
      if (isDarkSquare(row, col)) board[row][col] = { color: 'red', king: false };
    }
  }
  for (let row = SIZE - 3; row < SIZE; row += 1) {
    for (let col = 0; col < SIZE; col += 1) {
      if (isDarkSquare(row, col)) board[row][col] = { color: 'black', king: false };
    }
  }
  return board;
}

function initialState() {
  const board = createInitialBoard();
  const turn = 'red';
  return {
    board,
    turn,
    over: false,
    result: null,
    mustContinueFrom: null,
    lastMove: null,
    legalMoves: computeLegalMoves(board, turn, null),
  };
}

function applyMove(state, move) {
  if (state.over) return { error: 'the game is already over' };
  if (!move || !move.from || !move.to) return { error: 'move must include from and to squares' };

  const { from, to } = move;
  if (!inBounds(from.row, from.col) || !inBounds(to.row, to.col)) {
    return { error: 'square is off the board' };
  }
  if (!isDarkSquare(from.row, from.col) || !isDarkSquare(to.row, to.col)) {
    return { error: 'pieces only occupy dark squares' };
  }

  const { board } = state;
  const piece = board[from.row][from.col];
  if (!piece) return { error: 'there is no piece on the from square' };
  if (piece.color !== state.turn) return { error: `it is ${state.turn}'s turn to move` };

  if (
    state.mustContinueFrom &&
    (state.mustContinueFrom.row !== from.row || state.mustContinueFrom.col !== from.col)
  ) {
    return { error: 'must continue capturing with the piece that just captured' };
  }

  if (board[to.row][to.col] !== null) return { error: 'destination square is occupied' };

  const dr = to.row - from.row;
  const dc = to.col - from.col;
  const isSimpleShape = Math.abs(dr) === 1 && Math.abs(dc) === 1;
  const isCaptureShape = Math.abs(dr) === 2 && Math.abs(dc) === 2;
  if (!isSimpleShape && !isCaptureShape) {
    return { error: 'pieces move one square diagonally, or two squares when capturing' };
  }

  if (!piece.king) {
    const requiredDir = forwardDir(piece.color);
    const moveDir = isSimpleShape ? dr : dr / 2;
    if (moveDir !== requiredDir) return { error: 'men can only move diagonally forward' };
  }

  let capturedSquare = null;
  if (isCaptureShape) {
    const midRow = from.row + dr / 2;
    const midCol = from.col + dc / 2;
    const midPiece = board[midRow][midCol];
    if (!midPiece || midPiece.color === piece.color) {
      return { error: 'there is no piece to capture there' };
    }
    capturedSquare = { row: midRow, col: midCol };
  } else if (anyCaptureAvailable(board, piece.color, state.mustContinueFrom)) {
    return { error: 'a capture is available and must be taken' };
  }

  const newBoard = cloneBoard(board);
  newBoard[from.row][from.col] = null;
  const movedPiece = { ...piece };
  if (capturedSquare) newBoard[capturedSquare.row][capturedSquare.col] = null;

  let crowned = false;
  if (!movedPiece.king && to.row === backRankFor(movedPiece.color)) {
    movedPiece.king = true;
    crowned = true;
  }
  newBoard[to.row][to.col] = movedPiece;

  let nextTurn;
  let nextMustContinue;
  if (capturedSquare && !crowned && anyCaptureAvailable(newBoard, movedPiece.color, { row: to.row, col: to.col })) {
    nextTurn = movedPiece.color;
    nextMustContinue = { row: to.row, col: to.col };
  } else {
    nextTurn = opponent(movedPiece.color);
    nextMustContinue = null;
  }

  const lastMove = {
    from: { row: from.row, col: from.col },
    to: { row: to.row, col: to.col },
    captured: capturedSquare,
    crowned,
  };

  let over = false;
  let result = null;
  if (!nextMustContinue) {
    const message = checkGameOver(newBoard, nextTurn);
    if (message) {
      over = true;
      result = message;
      nextTurn = null;
    }
  }

  const newState = {
    board: newBoard,
    turn: nextTurn,
    over,
    result,
    mustContinueFrom: nextMustContinue,
    lastMove,
    legalMoves: over ? [] : computeLegalMoves(newBoard, nextTurn, nextMustContinue),
  };

  return { state: newState };
}

module.exports = {
  id: 'checkers',
  name: 'Checkers',
  blurb: 'Jumps are compulsory. Sorry.',
  seats: [{ id: 'red', label: 'Red' }, { id: 'black', label: 'Black' }],
  initialState,
  applyMove,
  legalMovesFrom,
};
