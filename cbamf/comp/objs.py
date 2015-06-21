import numpy as np
from ..util import Tile

class SphereCollectionRealSpace(object):
    def __init__(self, pos, rad, shape):
        self.pos = pos
        self.rad = rad
        self.N = rad.shape[0]

        self.shape = shape
        self._setup()

    def _setup(self):
        z,y,x = np.meshgrid(*(xrange(i) for i in self.shape), indexing='ij')
        self.rvecs = np.rollaxis(np.array(np.broadcast_arrays(z,y,x)), 0, 4)
        self.particles = np.zeros(self.shape)

    def _particle(self, pos, rad, zscale, sign=1):
        p = np.round(pos)
        r = np.ceil(rad)+1

        tile = Tile(p-r, p+r)
        subr = self.rvecs[tile.slicer + (np.s_[:],)]
        rvec = (subr - pos)

        # apply the zscale and find the distances to make a ellipsoid
        rvec[...,0] *= zscale
        rdist = np.sqrt((rvec**2).sum(axis=-1))
        self.particles[tile.slicer] += sign/(1.0 + np.exp(5*(rdist - rad)))

    def _update_particle(self, n, p, r, zscale):
        self._particle(self.pos[n], self.rad[n], zscale, -1)

        self.pos[n] = p
        self.rad[n] = r

        self._particle(self.pos[n], self.rad[n], zscale, +1)

    def initialize(self, zscale):
        if len(self.pos.shape) != 2:
            raise AttributeError("Position array needs to be (-1,3) shaped, (z,y,x) order")

        self.particles = np.zeros(self.shape)
        for p0, r0 in zip(self.pos, self.rad):
            self._particle(p0, r0, zscale)

    def set_tile(self, tile):
        self.tile = tile

    def update(self, ns, pos, rad, zscale):
        for n, p, r in zip(ns, pos, rad):
            self._update_particle(n, p, r, zscale)

    def get_field(self):
        return self.particles[self.tile.slicer]

    def get_params(self):
        return np.hstack([self.pos.ravel(), self.rad])

    def get_params_pos(self):
        return self.pos.ravel()

    def get_params_rad(self):
        return self.rad