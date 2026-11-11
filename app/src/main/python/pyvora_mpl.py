"""matplotlib backend: plt.show() displays the figures on the PYVORA GUI screen."""
import io, base64
from matplotlib.backend_bases import _Backend, FigureManagerBase
from matplotlib.backends.backend_agg import FigureCanvasAgg

@_Backend.export
class _BackendPyvora(_Backend):
    FigureCanvas = FigureCanvasAgg
    FigureManager = FigureManagerBase

    @staticmethod
    def show(*args, **kwargs):
        from matplotlib import _pylab_helpers
        import matplotlib.pyplot as plt
        import tkshim
        imgs = []
        for m in _pylab_helpers.Gcf.get_all_fig_managers():
            b = io.BytesIO()
            m.canvas.figure.savefig(b, format="png", dpi=100)
            imgs.append(base64.b64encode(b.getvalue()).decode())
        if imgs:
            tkshim._show_images(imgs)
        plt.close("all")
