"""Figure factory: a plain Figure for saving, a pyplot figure when a window is wanted."""
from __future__ import annotations

from matplotlib.figure import Figure


def new_figure(interactive: bool, **kwargs) -> Figure:
    if interactive:
        import matplotlib.pyplot as plt
        return plt.figure(**kwargs)
    return Figure(**kwargs)


def show() -> None:
    import matplotlib.pyplot as plt
    plt.show()
