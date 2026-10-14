# Recognition fixtures

Board-only crops from user-supplied TT screenshots, with desktop/window chrome,
avatar and account information excluded:

- `tt_endgame_309.png`: stage 309, 15 pieces; two red elephants, off-center red king.
- `tt_endgame_310.png`: stage 310, 15 pieces; red king at row 8 / column 3 (zero-based), black king at row 2 / column 5.
- `tt_menu_occluded.png`: board debug capture, lower-left game menu obscures squares. Negative example: do not accept as a complete board.
- `tt_spectator.png`: 391x433 board-only crop from the 2026-10-14 user screenshot; red at top, 14 pieces. Desktop, spectator names, avatars and chat are excluded. Ground truth and synthetic sidebar regression are in `test_small_board.py`.

Ground truth for the two positive cases is enumerated in `test_replay_and_turns.py`.
The tests use the shipped TT ONNX model, not mocked recognition output.
These images cover the supplied skin only; they are not a claim about all TT/JJ skins.
