import numpy as np
import matplotlib as mpl
import matplotlib.pylab as pl
from matplotlib.gridspec import GridSpec

"""
TODO -- plans for web-based GUI
    - bokeh graphs from matplotlib
    - tornado backend
"""
class OrthoManipulator(object):
    def __init__(self, state, cmap_abs='bone', cmap_diff='RdBu', vmin=0.0, vmax=1.0, incsize=18.0):
        self.incsize = incsize
        self.mode = 'view'
        self.inset = 'none'
        self.views = ['field', 'diff', 'cropped']
        self.insets = ['exposure']
        self.view = self.views[0]

        self.state = state
        self.cmap_abs = cmap_abs
        self.cmap_diff = cmap_diff

        sh = self.state.image.shape
        q = float(sh[1]) / (sh[0]+sh[1])

        self.fig = pl.figure(figsize=(16,8))

        h = 0.5
        self.gl = {}
        self.gl['xy'] = self.fig.add_axes((h*0.0, 1-q, h*q,     q))
        self.gl['yz'] = self.fig.add_axes((h*q,   1-q, h*(1-q), q))
        self.gl['xz'] = self.fig.add_axes((h*0.0, 0.0, h*q,     1-q))
        self.gl['in'] = self.fig.add_axes((h*q,   0.0, h*(1-q), 1-q))

        self.gr = {}
        self.gr['xy'] = self.fig.add_axes((h+h*0.0, 1-q, h*q,     q))
        self.gr['yz'] = self.fig.add_axes((h+h*q,   1-q, h*(1-q), q))
        self.gr['xz'] = self.fig.add_axes((h+h*0.0, 0.0, h*q,     1-q))
        self.gr['in'] = self.fig.add_axes((h+h*q,   0.0, h*(1-q), 1-q))

        self.slices = (np.array(self.state.image.shape)/2).astype('int')

        #self.vmin = min([self.state.image.min(), self.state.get_model_image().min()])
        #self.vmax = max([self.state.image.max(), self.state.get_model_image().max()])
        self._grab = None
        self.vmin = vmin
        self.vmax = vmax
        self.draw()
        self.register_events()

    def _format_ax(self, ax):
        ax.set_xticks([])
        ax.set_yticks([])

    def draw(self):
        self.draw_ortho(self.state.image, self.gl, cmap=self.cmap_abs,
                vmin=self.vmin, vmax=self.vmax)

        if self.view == 'field':
            self.draw_ortho(self.state.model_image, self.gr,
                cmap=self.cmap_abs, vmin=self.vmin, vmax=self.vmax)
        if self.view == 'diff':
            self.draw_ortho(self.state.image - self.state.get_model_image(),
                self.gr, cmap=self.cmap_diff, vmin=-self.vmax/5, vmax=self.vmax/5)
        if self.view == 'cropped':
            self.draw_ortho(self.state.get_model_image(),
                self.gr, cmap=self.cmap_abs, vmin=self.vmin, vmax=self.vmax)

    def draw_ortho(self, im, g, cmap=None, vmin=0, vmax=1):
        slices = self.slices

        g['xy'].cla()
        g['yz'].cla()
        g['xz'].cla()
        g['in'].cla()

        g['xy'].imshow(im[slices[0],:,:], vmin=vmin, vmax=vmax, cmap=cmap)
        g['xy'].hlines(slices[1], 0, im.shape[2], colors='y', linestyles='dashed', lw=1)
        g['xy'].vlines(slices[2], 0, im.shape[1], colors='y', linestyles='dashed', lw=1)
        self._format_ax(g['xy'])

        g['yz'].imshow(im[:,:,slices[2]].T, vmin=vmin, vmax=vmax, cmap=cmap)
        g['yz'].hlines(slices[1], 0, im.shape[0], colors='y', linestyles='dashed', lw=1)
        g['yz'].vlines(slices[0], 0, im.shape[1], colors='y', linestyles='dashed', lw=1)
        self._format_ax(g['yz'])

        g['xz'].imshow(im[:,slices[1],:], vmin=vmin, vmax=vmax, cmap=cmap)
        g['xz'].hlines(slices[0], 0, im.shape[2], colors='y', linestyles='dashed', lw=1)
        g['xz'].vlines(slices[2], 0, im.shape[0], colors='y', linestyles='dashed', lw=1)
        self._format_ax(g['xz'])

        if self.inset == 'exposure':
            m = im*self.state.image_mask
            self.pix = np.r_[m[slices[0],:,:], m[:,:,slices[2]], m[:,slices[1],:]].ravel()
            self.pix = self.pix[self.pix != 0.]
            g['in'].hist(self.pix, bins=300, histtype='step')
            g['in'].semilogy()

            g['in'].set_xlim(0, 1)
            g['in'].set_ylim(9e-1, 1e3)

            if self.view == 'diff' and g == self.gr:
                g['in'].set_xlim(-0.3, 0.3)

        self._format_ax(g['in'])
        pl.draw()

    def register_events(self):
        self._calls = []

        self._calls.append(self.fig.canvas.mpl_connect('key_press_event', self.key_press_event))

        if self.mode == 'view':
            self._calls.append(self.fig.canvas.mpl_connect('button_press_event', self.mouse_press_view))
        if self.mode == 'add':
            self._calls.append(self.fig.canvas.mpl_connect('button_press_event', self.mouse_press_add))
        if self.mode == 'remove':
            self._calls.append(self.fig.canvas.mpl_connect('button_press_event', self.mouse_press_remove))
        if self.mode == 'grab':
            self._calls.append(self.fig.canvas.mpl_connect('button_press_event', self.mouse_press_grab))
            self._calls.append(self.fig.canvas.mpl_connect('motion_notify_event', self.mouse_move_grab))
            self._calls.append(self.fig.canvas.mpl_connect('button_release_event', self.mouse_release_grab))
            self._calls.append(self.fig.canvas.mpl_connect('scroll_event', self.mouse_scroll_grab))

    def mouse_press_grab(self, event):
        self.event = event
        p = self._pt_xyz(event)

        if p is not None:
            self._grab = self.state.closest_particle(p)
            self._pos = self.state.obj.pos[self._grab]
        else:
            self._grab = None

    def mouse_release_grab(self, event):
        self.event = event
        self._grab = None

    def mouse_move_grab(self, event):
        self.event = event
        p = self._pt_xyz(event)

        if p is not None and self._grab is not None:
            b = self.state.block_particle_pos(self._grab)
            self.state.update(b, p)
            self.draw()

    def mouse_scroll_grab(self, event):
        self.event = event
        p = self._pt_xyz(event)

        if p is not None:
            n = self.state.closest_particle(p)
            b = self.state.block_particle_rad(n)
            self.state.update(b, self.state.obj.rad[n]+event.step/self.incsize)
            self.draw()

    def _pt_xyz(self, event):
        x0 = event.xdata
        y0 = event.ydata

        f = False
        for g in [self.gl, self.gr]:
            if event.inaxes == g['xy']:
                z = self.slices[0]
                x = x0
                y = y0
                f = True
            if event.inaxes == g['yz']:
                z = x0
                x = self.slices[2]
                y = y0
                f = True
            if event.inaxes == g['xz']:
                y = self.slices[1]
                z = y0
                x = x0
                f = True

        if f:
            return np.array((z,y,x))
        return None

    def mouse_press_view(self, event):
        self.event = event

        p = self._pt_xyz(event)
        if p is not None:
            self.slices = p
        self.draw()

    def mouse_press_add(self, event):
        self.event = event

        p = self._pt_xyz(event)
        if p is not None:
            print "Adding particle at", p
            self.state.add_particle(p, self.state.obj.rad.mean())
        self.draw()

    def mouse_press_remove(self, event):
        self.event = event

        p = self._pt_xyz(event)
        if p is not None:
            print "Removing particle near", p
            self.state.remove_closest_particle(p)
        self.draw()

    def key_press_event(self, event):
        self.event = event

        if event.key == 'v':
            self.mode = 'view'
        if event.key == 'a':
            self.mode = 'add'
        if event.key == 'r':
            self.mode = 'remove'
        if event.key == 'g':
            self.mode = 'grab'
        if event.key == 'q':
            self.view = self.views[(self.views.index(self.view)+1) % len(self.views)]
            self.draw()
            return

        print "Switching mode to", self.mode

        for c in self._calls:
            self.fig.canvas.mpl_disconnect(c)

        self.register_events()