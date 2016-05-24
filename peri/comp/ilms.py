import numpy as np
from numpy.polynomial.polynomial import polyval3d
from numpy.polynomial.legendre import legval
from numpy.polynomial.chebyshev import chebval
import scipy.optimize as opt

from operator import add, mul
from itertools import product, chain

from peri.comp import Component
from peri.util import Tile, cdd
from peri.interpolation import BarnesInterpolation1D

#=============================================================================
# Pure 3d functional representations of ILMs
#=============================================================================
class Polynomial3D(Component):
    category = 'ilm'

    def __init__(self, shape, order=(1,1,1), tileinfo=None, constval=None):
        """
        A polynomial 3D class for updating large fields of polys.

        Parameters:
        -----------
        shape : tuple
            shape of the field (z,y,x)

        order : tuple
            number of terms in each direction

        tileinfo : tuple of 2 `peri.util.Tile`
            These objects help in the transfer of fields from different
            sections of the same image to new fields. `tileinfo` is a tuple
            containing the Tile representing the entire image as well as the
            Tile representing this particular section of field. (typically
            given by `peri.rawimage.tile`)

        constval : float
            The initial value of the entire field, if a constant.
        """
        self.shape = shape
        self.order = order
        self.tileinfo = tileinfo

        # set up the parameter mappings and values
        params, values = [], []
        self.param_term = {}
        for order in product(*(xrange(o) for o in self.order)):
            p = 'ilm-%i-%i-%i' % order
            self.param_term[p] = order

            params.append(p)
            values.append(0.0)

        if constval:
            values[0] = constval

        super(Polynomial3D, self).__init__(params=params, values=values)
        self.initialize()

    def initialize(self):
        self.r = self.rvecs()
        self.set_tile(Tile(self.shape))
        self.field = np.zeros(self.shape)
        self.update(self.params, self.values)

    def rvecs(self):
        # normalize all sizes to a strict upper bound on image size
        # so we can transfer ILM between different images
        if self.tileinfo:
            img, inner = self.tileinfo
            vecs = img.coords(norm=img.shape)
            vecs = [v[inner.slicer] for v in vecs]
        else:
            vecs = Tile(self.shape).coords(norm=self.shape)
        return vecs

    def term_ijk(self, index):
        i,j,k = index
        return self.r[0]**i * self.r[1]**j * self.r[2]**k

    def term(self, index):
        if self.__dict__.get('_last_index') and index == self._last_index:
            return self._last_term
        else:
            term = self.term_ijk(index)
            self._last_term = term
            self._last_index = index
            return self._last_term

    def set_tile(self, tile):
        self.tile = tile

    def update(self, params, values):
        if len(params) < len(self.params)/2:
            for p,v1 in zip(params, values):
                v0 = self.get_values(p)

                self.field -= v0 * self.term(self.param_term[p])
                self.set_values(p, v1)
                self.field += v1 * self.term(self.param_term[p])
        else:
            self.field = np.zeros(self.shape)
            for p,v in zip(self.params, self.values):
                self.field += v * self.term(self.param_term[p])

    def get_field(self):
        return self.field[self.tile.slicer]

    def get_params(self):
        return self.params

    def get_update_tile(self, params, values):
        return Tile(self.shape)

    def __str__(self):
        return "{} [{} {}]".format(
            self.__class__.__name__, self.order
        )

    def __repr__(self):
        return self.__str__()

    def __getstate__(self):
        odict = self.__dict__.copy()
        cdd(odict, ['r', 'field', '_last_term', '_last_index'])
        return odict

    def __setstate__(self, idict):
        self.__dict__.update(idict)
        self.initialize()

class LegendrePoly3D(Polynomial3D):
    def __init__(self, shape, *args, **kwargs):
        """ Same arguments are Polynomial3D """
        super(LegendrePoly3D, self).__init__(shape, *args, **kwargs)

    def rvecs(self):
        vecs = super(LegendrePoly3D, self).rvecs()
        vecs = [2*v - 1 for v in vecs]
        return vecs

    def term_ijk(self, index):
        i,j,k = index
        ci = np.zeros(i+1)
        cj = np.zeros(j+1)
        ck = np.zeros(k+1)
        ci[-1] = cj[-1] = ck[-1] = 1
        return legval(self.r[0], ci) * legval(self.r[1], cj) * legval(self.r[2], ck)

#=============================================================================
# 2+1d functional representations of ILMs, p(x,y)+q(z)
#=============================================================================
class Polynomial2P1D(Polynomial3D):
    def __init__(self, shape, order=(1,1,1), tileinfo=None, constval=None,
            operation='*'):
        """
        A polynomial 2+1D class for updating large fields of polys.  The form
        of these polynomials if P(x,y) () Q(z), separated in the z-direction.

        Parameters:
        -----------
        shape : tuple
            shape of the field (z,y,x)

        order : tuple
            number of terms in each direction

        tileinfo : tuple of 2 `peri.util.Tile`
            These objects help in the transfer of fields from different
            sections of the same image to new fields. `tileinfo` is a tuple
            containing the Tile representing the entire image as well as the
            Tile representing this particular section of field. (typically
            given by `peri.rawimage.tile`)

        constval : float
            The initial value of the entire field, if a constant.

        operation : string
            Type of joining operation between the (x,y) and (z) poly. Can be
            either '*' or '+'
        """

        self.shape = shape
        self.operation = operation
        self.order = order
        self.tileinfo = tileinfo

        # set up the parameter mappings and values
        params, values = [], []
        self.xy_param = {}
        self.z_param = {}

        for order in product(*(xrange(o) for o in self.order[1::-1])):
            p = 'ilm-xy-%i-%i' % order
            self.xy_param[p] = order

            params.append(p)
            values.append(0.0)

        for order in xrange(self.order[0]):
            p = 'ilm-z-%i' % order
            self.z_param[p] = (order,)

            params.append(p)
            values.append(0.0)

        # setup the basics of the component now
        Component.__init__(self, params, values)

        # set up the appropriate zero terms for the supplied constant value
        # parameter if there.
        if constval:
            if operation == '*':
                self.set_values('ilm-xy-0-0', constval)
                self.set_values('ilm-z-0', 1.0)
            else:
                self.set_values('ilm-xy-0-0', constval)

        self.initialize()

    def initialize(self):
        self.r = self.rvecs()
        self.field_xy = 0*self.term_xy((0,0))
        self.field_z = 0*self.term_z((0,))
        super(Polynomial2P1D, self).initialize()

    def calc_field(self):
        self.field_xy = 0*self.term_xy((0,0))
        self.field_z = 0*self.term_z((0,))

        for p,v in zip(self.params, self.values):
            if p in self.xy_param:
                order = self.xy_param[p]
                term = self.field_xy
            else:
                order = self.z_param[p]
                term = self.field_z

            term += v * self.term(order)

        op = {'*': mul, '+': add}[self.operation]
        self.field = op(self.field_xy, self.field_z)
        return self.field

    def term_xy(self, index):
        i,j = index
        return self.r[2]**i * self.r[1]**j

    def term_z(self, index):
        k = index[0]
        return self.r[0]**k

    def term(self, index):
        # per index cache, so if called multiple times in a row, keep the answer
        if self.__dict__.get('_last_index') and self._last_index == index:
            return self._last_term

        # otherwise, just calculate this one term
        self._last_index = index
        if len(index) == 2:
            self._last_term = self.term_xy(index)
        if len(index) == 1:
            self._last_term = self.term_z(index)
        return self._last_term

    def update(self, params, values):
        if len(params) < len(self.params)/2:
            for p,v1 in zip(params, values):
                if p in self.xy_param:
                    order = self.xy_param[p]
                    term = self.field_xy
                else:
                    order = self.z_param[p]
                    term = self.field_z

                v0 = self.get_values(p)
                term -= v0 * self.term(order)
                self.set_values(p,v1)
                term += v1 * self.term(order)

            op = {'*': mul, '+': add}[self.operation]
            self.field = op(self.field_xy, self.field_z)
        else:
            self.set_values(params, values)
            self.field = self.calc_field()

    def get_field(self):
        return self.field[self.tile.slicer]

    def __getstate__(self):
        odict = self.__dict__.copy()
        cdd(odict, ['r', 'field', 'field_xy', 'field_z'])
        cdd(odict, ['_last_term', '_last_index'])
        return odict

    def __setstate__(self, idict):
        self.__dict__.update(idict)
        self.initialize()

class LegendrePoly2P1D(Polynomial2P1D):
    def __init__(self, shape, order=(1,1,1), tileinfo=None, constval=None,
            operation='*'):
        super(LegendrePoly2P1D, self).__init__(shape=shape, order=order, **kwargs)

    def _setup_rvecs(self):
        o = self.shape
        self.rz, self.ry, self.rx = [np.linspace(-1, 1, i) for i in o]
        self.rz = self.rz[:,None,None]
        self.ry = self.ry[None,:,None]
        self.rx = self.rx[None,None,:]

    def term_xy(self, index):
        i,j = index
        ci = np.zeros(i+1)
        cj = np.zeros(j+1)
        ci[-1], cj[-1] = 1, 1
        return legval(self.rx, ci) * legval(self.ry, cj)

    def term_z(self, index):
        k = index[0]
        ck = np.zeros(k+1)
        ck[-1] = 1
        return legval(self.rz, ck)

class ChebyshevPoly2P1D(Polynomial2P1D):
    def __init__(self, shape, coeffs=None, order=(1,1,1), *args, **kwargs):
        super(ChebyshevPoly2P1D, self).__init__(*args,
                shape=shape, order=order, **kwargs)

    def term_xy(self, index):
        i,j = index
        ci = np.zeros(i+1)
        cj = np.zeros(j+1)
        ci[-1], cj[-1] = 1, 1
        return chebval(self.rx, ci) * chebval(self.ry, cj)

    def term_z(self, index):
        k = index[0]
        ck = np.zeros(k+1)
        ck[-1] = 1
        return chebval(self.rz, ck)

#=============================================================================
# a complex hidden variable representation of the ILM
# something like (p(x,y)+m(x,y))*q(z) where m is determined by local models
#=============================================================================
class BarnesStreakLegPoly2P1D(object):
    category = 'ilm'

    def __init__(self, shape, order=(1,1,1), nstreakpoints=40, barnes_dist=2.0):
        """
        An illumination field of the form (b(e) + p(x,y))*q(z) where
        e is the axis of the 1d streak, be in x or y.

        Parameters:
        -----------
        shape : iterable
            size of the field in pixels, needs to be padded shape

        order : list, tuple
            number of orders for each polynomial, (order[0], order[1])
            correspond to size of p(x,y) and order[2] is the q(z) poly

        nstreakpoints : int
            number of points to include in the approximation of the barnes streak

        barnes_dist : float
            fractional distance to use for the barnes interpolator
        """
        self.shape = shape
        self.barnes_dist = barnes_dist
        self.xyorder = order[:2]
        self.zorder = order[-1]

        self.order = order

        npoly = len(list(self._poly_orders()))
        self.nparams = npoly + nstreakpoints

        # set some parameters for the streak
        self.nstreakpoints = nstreakpoints
        self.streak_slicer = np.s_[npoly:npoly+self.nstreakpoints]

        self.params = np.zeros(self.nparams, dtype='float')
        self.params[0] = 1
        self.params[len(list(self._poly_orders_xy()))] = 1

        self._setup()
        self.tile = Tile(self.shape)
        self.set_tile(Tile(self.shape))

        self.block = np.ones(self.nparams).astype('bool')
        self.initialize()

    def _poly_orders_xy(self):
        return product(*(xrange(o) for o in self.order[:2]))

    def _poly_orders_z(self):
        return product(xrange(self.order[-1]))

    def _poly_orders(self):
        return chain(self._poly_orders_xy(), self._poly_orders_z())

    def _setup_rvecs(self):
        o = self.shape
        self.rz, self.ry, self.rx = [np.linspace(-1, 1, i) for i in o]
        self.rz = self.rz[:,None,None]
        self.ry = self.ry[None,:,None]
        self.rx = self.rx[None,None,:]

        self.b_out = np.squeeze(self.rx)
        self.b_in = np.linspace(self.b_out.min(), self.b_out.max(), self.nstreakpoints)

    def _setup(self):
        self._setup_rvecs()
        self._last_index = None
        self._indices = list(self._poly_orders())
        self._indices_xy = list(self._poly_orders_xy())
        self._indices_z = list(self._poly_orders_z())

    def _barnes(self, y):
        bdist = self.__dict__.get('barnes_dist', 2.0)
        b = BarnesInterpolation1D(
                self.b_in, self.params[self.streak_slicer],
                filter_size=(self.b_in[1]-self.b_in[0])*1.0/bdist, damp=0.9, iterations=3
        )
        return b(y)

    def _barnes_val(self):
        return self._barnes(self.b_out)[None,None,:]

    def _bkg(self):
        self.bkg = np.zeros(self.shape)
        self._polyxy = 0*self.bkg
        self._polyz = 0*self.bkg

        for order in self._poly_orders_xy():
            ind = self._indices.index(order)
            self._polyxy += self.params[ind] * self._term(order)

        for order in self._poly_orders_z():
            ind = self._indices.index(order)
            self._polyz += self.params[ind] * self._term(order)

        self.bkg = (self._barnes_val() + self._polyxy) * self._polyz
        return self.bkg

    def from_ilm(self, ilm):
        orders = list(self._poly_orders())

        for i,o in enumerate(ilm._poly_orders()):
            try:
                ind = orders.index(o)
                self.params[ind] = ilm.params[i]
            except ValueError as e:
                continue

    def from_data(self, f, mask=None, dopriors=False, multiplier=1, maxcalls=200):
        if mask is None:
            mask = np.s_[:]
        res = opt.leastsq(self._score, x0=self.params, args=(f, mask), maxfev=maxcalls*(self.nparams+1))
        self.update(self.block, res[0])

    def from_ilm_tile(self, ilm, tile):
        """
        Be able to interpolate a second ILM into a new one of a different
        shape exactly due to Legendre orthogonality and the Barnes interps
        """
        fieldxy = ilm._polyxy[tile.slicer]
        fieldz = ilm._polyz[tile.slicer]

        for i,ind in enumerate(self._indices):
            if ind in self._indices_xy:
                self.params[i] = (fieldxy[0]*self._term_xy(ind)).sum()
            else:
                self.params[i] = (fieldz[:,0,0]*self._term_z(ind)).sum()

        self.params[self.streak_slicer] = ilm._barnes(self.b_in)
        self.initialize()

    def _score(self, coeffs, f, mask):
        self.params = coeffs
        test = self._bkg()
        out = (f[mask] - test[mask]).flatten()
        #print np.abs(out).mean()
        return out

    def _term_xy(self, index):
        i,j = index
        ci = np.zeros(i+1)
        cj = np.zeros(j+1)
        ci[-1], cj[-1] = 1, 1
        return legval(self.rx, ci) * legval(self.ry, cj)

    def _term_z(self, index):
        k = index[0]
        ck = np.zeros(k+1)
        ck[-1] = 1
        return legval(self.rz, ck)

    def _term(self, index):
        # per index cache, so if called multiple times in a row, keep the answer
        if self._last_index == index:
            return self._last_term

        # otherwise, just calculate this one term
        self._last_index = index
        if len(index) == 2:
            self._last_term = self._term_xy(index)
        if len(index) == 1:
            self._last_term = self._term_z(index)
        return self._last_term

    def initialize(self):
        self.update(self.block, self.params)

    def set_tile(self, tile):
        self.tile = tile

    def update(self, blocks, params):
        if blocks.sum() < self.block.sum()/2:
            for b in np.arange(len(blocks))[blocks]:
                if b < len(self._indices):
                    order = self._indices[b]

                    if order in self._indices:
                        if order in self._indices_xy:
                            _term = self._polyxy
                        else:
                            _term = self._polyz

                        _term -= self.params[b] * self._term(order)
                        self.params[b] = params[b]
                        _term += self.params[b] * self._term(order)

                self.params[b] = params[b]
                self.bkg = (self._barnes_val() + self._polyxy) * self._polyz
        else:
            self.params = params
            self._bkg()

    def get_field(self):
        return self.bkg[self.tile.slicer]

    def get_params(self):
        return self.params

    def __getstate__(self):
        odict = self.__dict__.copy()
        cdd(odict, ['_poly', 'b_in', 'b_out', 'rx', 'ry', 'rz', 'bkg', '_last_term', '_last_index'])
        cdd(odict, ['_polyxy', '_polyz'])
        return odict

    def __setstate__(self, idict):
        self.__dict__.update(idict)
        self._setup()
        self.tile = Tile(self.shape)
        self.set_tile(Tile(self.shape))
        self.initialize()

class BarnesStreakLegPoly2P1D(BarnesStreakLegPoly2P1D):
    def __init__(self, shape, order=(1,1,1), npts=(40,20), barnes_dist=1.75):
        """
        Yet another Barnes interpolant. This one is of the form

            I = ((\sum b_k(x) * L_k(y)) + p(x,y))*q(z)

        where b_k are independent barnes interpolants and L_k are legendre
        polynomials. p and q are the same as previous ILMs.
        """
        self.shape = shape
        self.barnes_dist = barnes_dist
        self.xyorder = order[:2]
        self.zorder = order[-1]

        self.order = order

        npoly = len(list(self._poly_orders()))
        self.nparams = npoly + sum(npts)

        # set some parameters for the streak
        self.npts = npts
        self.slicers = []
        for i in xrange(len(npts)):
            self.slicers.append(np.s_[npoly+sum(npts[:i]):npoly+sum(npts[:i+1])])

        self.params = np.zeros(self.nparams, dtype='float')
        self.params[0] = 1
        self.params[len(list(self._poly_orders_xy()))] = 1

        self._setup()
        self.tile = Tile(self.shape)
        self.set_tile(Tile(self.shape))

        self.block = np.ones(self.nparams).astype('bool')
        self.initialize()

    def _barnes_poly(self, n=0):
        weights = np.diag(np.ones(n+1))[n]
        return legval(np.squeeze(self.ry), weights)[:,None]

    def _barnes(self, y, n=0):
        bdist = self.__dict__.get('barnes_dist', 2.0)
        b_in = self.b_in[n]
        b = BarnesInterpolation1D(
                b_in, self.params[self.slicers[n]],
                filter_size=(b_in[1]-b_in[0])*1.0/bdist, damp=0.9, iterations=3
        )
        return b(y)

    def _barnes_val(self, n=0):
        return self._barnes(self.b_out, n=n)[None,:]

    def _barnes_full(self):
        barnes = np.array([
            self._barnes_val(i)*self._barnes_poly(i) for i in xrange(len(self.npts))
        ])
        return barnes.sum(axis=0)[None,:,:]

    def _bkg(self):
        self.bkg = np.zeros(self.shape)
        self._polyxy = 0*self.bkg
        self._polyz = 0*self.bkg

        for order in self._poly_orders_xy():
            ind = self._indices.index(order)
            self._polyxy += self.params[ind] * self._term(order)

        for order in self._poly_orders_z():
            ind = self._indices.index(order)
            self._polyz += self.params[ind] * self._term(order)

        self.bkg = (self._barnes_full() + self._polyxy) * self._polyz
        return self.bkg

    def update(self, blocks, params):
        if blocks.sum() < self.block.sum()/2:
            for b in np.arange(len(blocks))[blocks]:
                if b < len(self._indices):
                    order = self._indices[b]

                    if order in self._indices:
                        if order in self._indices_xy:
                            _term = self._polyxy
                        else:
                            _term = self._polyz

                        _term -= self.params[b] * self._term(order)
                        self.params[b] = params[b]
                        _term += self.params[b] * self._term(order)

                self.params[b] = params[b]
                self.bkg = (self._barnes_full() + self._polyxy) * self._polyz
        else:
            self.params = params
            self._bkg()

    def _setup_rvecs(self):
        o = self.shape
        self.rz, self.ry, self.rx = [np.linspace(-1, 1, i) for i in o]
        self.rz = self.rz[:,None,None]
        self.ry = self.ry[None,:,None]
        self.rx = self.rx[None,None,:]

        self.b_out = np.squeeze(self.rx)
        self.b_in = [
            np.linspace(self.b_out.min(), self.b_out.max(), q)
            for q in self.npts
        ]

    def randomize_parameters(self, ptp=0.2, fourier=False, vmin=None, vmax=None):
        """
        Create random parameters for this ILM that mimic experiments
        as closely as possible without real assumptions.
        """
        if vmin is not None and vmax is not None:
            ptp = vmax - vmin
            print "Warning: vmin and vmax set, using those for ptp"

        for i, o in enumerate(self._indices_xy[1:]):
            self.params[i] = ptp*(np.random.rand() - 0.5) / (np.prod(o)+1) / 2

        off = len(self._indices_xy)
        for i, o in enumerate(self._indices_z[1:]):
            self.params[i+off+1] = ptp*(np.random.rand() - 0.5) / (np.prod(o)+1) / 2

        for i, s in enumerate(self.slicers):
            N = self.params[s].shape[0]
            if fourier:
                t = ((np.random.rand(N)-0.5) + 1.j*(np.random.rand(N)-0.5))/(np.arange(N)+1)
                q = np.real(np.fft.ifftn(t)) / (i+1)
            else:
                t = ptp*np.sqrt(N)*(np.random.rand(N)-0.5)
                q = np.cumsum(t) / (i+1)

            q = ptp * q / q.ptp() / len(self.slicers)
            q -= q.mean()
            self.params[s] = 1.0*(i==0) + q

        self.initialize()
        if vmin:
            diff = self.get_field().min() - vmin
            self.params[0] -= diff * (diff < 0)
        if vmax:
            diff = self.get_field().max() - vmax
            self.params[0] -= diff * (diff > 0)
        self.initialize()

    def __str__(self):
        return "{} [{} {}]".format(
            self.__class__.__name__, self.order, self.npts
        )

    def __repr__(self):
        return self.__str__()


