"""Grid calibration and conservative, probability-aware classification."""
import hashlib
import time

import cv2
import numpy as np

from app.chess.checker import PositionChecker
from app.chess.vision_guard import screenshot_to_bgr


def calibrate_grid(image, xs, ys):
    """Fit visible grid segments near expected positions, not specific pieces.

    Missing lines (river/pieces) are allowed. Never fit to a single palace line.
    Coordinates are in the normalized 800-pixel-wide crop.
    """
    h, w = image.shape[:2]
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    if len(xs) != 9 or len(ys) != 10:
        raise ValueError("棋盘需要9列10行坐标")
    xs = xs * w / 800.0
    ys = ys * h / (ys[-1] + np.median(np.diff(ys)) / 2)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Long directional edges suppress characters, circular pieces and wood grain.
    edges = cv2.Canny(gray, 35, 105)
    vertical = cv2.morphologyEx(edges, cv2.MORPH_OPEN,
                              np.ones((max(20, h // 18), 1), np.uint8))
    horizontal = cv2.morphologyEx(edges, cv2.MORPH_OPEN,
                                np.ones((1, max(20, w // 18)), np.uint8))

    def fit(expected, scores, minimum):
        spacing = float(np.median(np.diff(expected)))
        radius = max(3, int(spacing * .22))
        indices, values = [], []
        for i, target in enumerate(expected):
            lo, hi = max(0, int(target) - radius), min(len(scores), int(target) + radius + 1)
            if hi <= lo:
                continue
            peak = lo + int(np.argmax(scores[lo:hi]))
            if scores[peak] >= .09:
                indices.append(i)
                values.append(peak)
        if len(indices) < minimum or max(indices) - min(indices) < len(expected) - 3:
            return np.rint(expected).astype(int).tolist(), False
        slope, intercept = np.polyfit(indices, values, 1)
        residual = np.abs(np.asarray(values) - (intercept + slope * np.asarray(indices)))
        good = residual < spacing * .10
        if good.sum() < minimum:
            return np.rint(expected).astype(int).tolist(), False
        slope, intercept = np.polyfit(np.asarray(indices)[good], np.asarray(values)[good], 1)
        fitted = intercept + slope * np.arange(len(expected))
        if abs(slope / spacing - 1) > .10 or np.max(np.abs(fitted - expected)) > radius:
            return np.rint(expected).astype(int).tolist(), False
        return np.rint(fitted).astype(int).tolist(), True

    xs, x_ok = fit(xs, (vertical > 0).mean(axis=0), 4)
    ys, y_ok = fit(ys, (horizontal > 0).mean(axis=1), 5)
    return xs, ys, x_ok and y_ok


def centered_crop(image, x, y, radius):
    """Pad boundary squares; shifting the center cuts edge elephants in half."""
    h, w = image.shape[:2]
    left, top, right, bottom = x - radius, y - radius, x + radius, y + radius
    crop = image[max(0, top):min(h, bottom), max(0, left):min(w, right)]
    # Copy only this square, not the entire 800px board 180 times per frame.
    return cv2.copyMakeBorder(crop, max(0, -top), max(0, bottom - h),
                             max(0, -left), max(0, right - w), cv2.BORDER_REPLICATE)


def grid_visibility(image, xs, ys):
    """Local grid support catches opaque panels that the CNN calls empty squares.

    Require some line evidence in each quarter, not all 9x10 lines. Scores are
    fractions of expected line length, tolerant of pieces and river breaks.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 35, 105)
    length = max(16, int(min(np.median(np.diff(xs)), np.median(np.diff(ys))) * .45))
    v = cv2.morphologyEx(edges, cv2.MORPH_OPEN, np.ones((length, 1), np.uint8))
    h = cv2.morphologyEx(edges, cv2.MORPH_OPEN, np.ones((1, length), np.uint8))
    scores = []
    for rows in (range(0, 5), range(5, 10)):
        for cols in (range(0, 4), range(5, 9)):
            top, bottom = max(0, ys[rows.start]), min(image.shape[0], ys[rows.stop - 1])
            left, right = max(0, xs[cols.start]), min(image.shape[1], xs[cols.stop - 1])
            vertical = [np.any(v[top:bottom, max(0, xs[c] - 4):xs[c] + 5] > 0, axis=1).mean()
                        for c in cols if bottom > top]
            horizontal = [np.any(h[max(0, ys[r] - 4):ys[r] + 5, left:right] > 0, axis=0).mean()
                          for r in rows if right > left]
            scores.append(float(max(np.mean(vertical) if vertical else 0.,
                                    np.mean(horizontal) if horizontal else 0.)))
    return scores


def distribution(result):
    if result is None:
        return {}
    return result.get('probabilities', {result['class_name']: result['confidence']})


def decode_square(probabilities, row, col, red_bottom=None):
    """Rules disambiguate plausible candidates; never invent a missing king."""
    if not probabilities:
        return '-', 0., True
    probabilities = dict(probabilities)
    probabilities['-'] = probabilities.get('-', 0.) + probabilities.pop('.', 0.)
    validator = PositionChecker()
    def allowed(piece):
        if piece in ('-', '.'):
            return True
        if piece not in validator.START_COUNTS:
            return False
        orientations = (True, False) if red_bottom is None else (red_bottom,)
        return any(validator.is_position_valid(piece, col, row, orientation)
                   for orientation in orientations)
    ordered = sorted(probabilities.items(), key=lambda pair: pair[1], reverse=True)
    raw, raw_conf = ordered[0]
    legal = [(piece, prob) for piece, prob in ordered if allowed(piece)]
    if not legal:
        return '-', 0., True
    piece, confidence = legal[0]
    # Illegal advisor -> plausible pawn is allowed only with substantial visual evidence.
    corrected = piece != raw
    next_conf = legal[1][1] if len(legal) > 1 else 0.
    uncertain = (confidence < (.25 if corrected else .65) or
                 confidence - next_conf < .12 or
                 (corrected and raw_conf > confidence * 3))
    return ('-' if piece == '.' else piece), confidence, uncertain


class GridClassifier:
    def __init__(self):
        self.reset()

    def reset(self):
        self.cache = {}
        self.geometry = None
        self.coords = None
        self.grid_supported = False
        self.last_report = {}

    def recognize(self, frame, xs, ys, model, platform):
        raw = screenshot_to_bgr(frame)
        # Strong Lanczos ringing around tiny strokes hurts the 80px classifier.
        # Keep the existing path for normal boards; use cubic for small boards.
        interpolation = cv2.INTER_CUBIC if raw.shape[1] < 360 else cv2.INTER_LANCZOS4
        image = cv2.resize(raw, (800, round(raw.shape[0] * 800 / raw.shape[1])),
                           interpolation=interpolation)
        key = (platform, raw.shape, tuple(xs), tuple(ys))
        if key != self.geometry:
            self.reset()
            self.geometry = key
        # Refit each frame; retry after animations instead of locking in a bad fit.
        xx, yy, supported = calibrate_grid(image, xs, ys)
        if supported and self.coords != (xx, yy):
            self.cache.clear()
            self.coords = xx, yy
        if self.coords is None:
            self.coords = xx, yy
        xx, yy = self.coords
        self.grid_supported = supported
        visibility = grid_visibility(image, xx, yy)
        radius = int(min(np.median(np.diff(xx)), np.median(np.diff(yy))) * .475)
        now = time.monotonic()
        distributions, hashes = {}, [[None] * 9 for _ in range(10)]
        crops, positions = [], []
        for r, y in enumerate(yy):
            for c, x in enumerate(xx):
                crop = centered_crop(image, x, y, radius)
                # Exact content hash: dHash can collide on differently colored characters.
                digest = hashlib.blake2b(crop.tobytes(), digest_size=8).digest()
                hashes[r][c] = digest.hex()
                cached = self.cache.get((r, c))
                if cached and cached[0] == digest and now - cached[1] < 1.5:
                    distributions[r, c] = cached[2]
                    continue
                # Two scales handle crop offset/shadow without assuming the piece identity.
                crops.extend((crop, centered_crop(image, x, y, int(radius * 1.13))))
                positions.append((r, c, digest))
        if crops:
            results = model.recognize_batch(crops)
            for i, (r, c, digest) in enumerate(positions):
                a, b = distribution(results[2 * i]), distribution(results[2 * i + 1])
                probs = {p: (a.get(p, 0.) + b.get(p, 0.)) / 2 for p in a.keys() | b.keys()}
                distributions[r, c] = probs
                self.cache[r, c] = digest, now, probs

        # Infer orientation before choosing retries: a confident pawn on the
        # wrong home rank can otherwise hide an uncertain advisor candidate.
        votes = []
        for (r, c), probs in distributions.items():
            for piece in ('k', 'K'):
                if probs.get(piece, 0.) > .75 and 3 <= c <= 5 and (r <= 2 or r >= 7):
                    votes.append((piece == 'k') == (r <= 2))
        red_bottom = votes[0] if votes and all(v == votes[0] for v in votes) else None

        # At small resolutions, one source pixel shifts a character by several
        # normalized pixels. Retry only ambiguous, freshly inferred squares;
        # require agreement across crops rather than picking the highest score.
        retry_positions = [(r, c, digest) for r, c, digest in positions
                           if decode_square(distributions[r, c], r, c, red_bottom)[2]]
        refined = 0
        if raw.shape[1] < 360 and 0 < len(retry_positions) <= 16:
            retry_crops = []
            offset = max(2, round(radius * .08))
            offsets = ((0, 0), (-offset, 0), (offset, 0), (0, -offset), (0, offset))
            for r, c, _ in retry_positions:
                retry_crops.extend(centered_crop(image, xx[c] + dx, yy[r] + dy,
                                                 max(2, round(radius * .85)))
                                   for dx, dy in offsets)
            retries = model.recognize_batch(retry_crops)
            for i, (r, c, digest) in enumerate(retry_positions):
                votes = [distribution(result) for result in retries[i*5:i*5+5]]
                if len(votes) != 5 or not all(votes):
                    continue
                labels = set().union(*(vote.keys() for vote in votes))
                mean = {p: sum(vote.get(p, 0.) for vote in votes) / 5 for p in labels}
                piece, _, unsure = decode_square(mean, r, c, red_bottom)
                agreement = sum(max(vote, key=vote.get) == piece and vote.get(piece, 0.) >= .75
                                for vote in votes)
                if not unsure and piece != '-' and agreement >= 3:
                    distributions[r, c] = mean
                    self.cache[r, c] = digest, now, mean
                    refined += 1

        # Infer orientation only from unambiguous king evidence anywhere inside either palace.
        votes = []
        for (r, c), probs in distributions.items():
            for piece in ('k', 'K'):
                if probs.get(piece, 0.) > .75 and 3 <= c <= 5 and (r <= 2 or r >= 7):
                    votes.append((piece == 'k') == (r <= 2))
        red_bottom = votes[0] if votes and all(v == votes[0] for v in votes) else None
        board, uncertain, cells = [['-'] * 9 for _ in range(10)], [], []
        for (r, c), probs in distributions.items():
            piece, conf, unsure = decode_square(probs, r, c, red_bottom)
            board[r][c] = piece
            if unsure:
                uncertain.append((r, c, piece, conf))
            cells.append({'row': r, 'col': c, 'piece': piece, 'confidence': conf,
                          'uncertain': unsure, 'candidates': sorted(probs.items(), key=lambda p: -p[1])[:3]})
        # A panel can confidently classify as empty. Only reject strong LOCAL
        # asymmetry; uniformly faint skins are not automatically called occluded.
        frame_reliable = not (min(visibility) < .25 and min(visibility) < max(visibility) * .32)
        if not frame_reliable:
            uncertain.append((-1, -1, '?', 0.))
        self.last_report = {'x': xx, 'y': yy, 'grid_supported': supported,
                            'source_size': [raw.shape[1], raw.shape[0]],
                            'source_cell_pixels': round(float(min(
                                np.median(np.diff(xx)) * raw.shape[1] / image.shape[1],
                                np.median(np.diff(yy)) * raw.shape[0] / image.shape[0])), 2),
                            'visibility': visibility,
                            'frame_reliable': frame_reliable,
                            'red_bottom': red_bottom, 'cells': cells,
                            'refined_squares': refined,
                            'inferred_squares': len(positions), 'board': board}
        return board, hashes, uncertain
