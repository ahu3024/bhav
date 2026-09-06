"""Build features + train the model from whatever is already in sqlite.

    python -m scripts.build
"""

from __future__ import annotations

from bhav.features import training_frame
from bhav.model import main as train_main


def main() -> None:
    frame = training_frame()
    print(f"training rows: {len(frame)}  "
          f"({frame.index.min().date()} .. {frame.index.max().date()})")
    print(f"drop-event base rate: {frame['target'].mean():.1%}")
    train_main()


if __name__ == "__main__":
    main()
