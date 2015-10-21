"""
Plot the average positional / radius error vs fraction of self-diffusion time
"""
import sys
import pickle
import numpy as np
import scipy as sp
import scipy.ndimage as nd
from IPython.core.debugger import Tracer
#Tracer()() / %debug after stacktrace

import matplotlib.pyplot as pl

from cbamf import const, runner, initializers
from cbamf.test import init
from cbamf.states import prepare_image
from cbamf.viz.util import COLORS

RADIUS = 5.0

def set_image(state, cg, sigma):
    image = cg + np.random.randn(*cg.shape)*sigma
    image = np.pad(image, const.PAD, mode='constant', constant_values=const.PADVAL)
    state.set_image(image)
    state.sigma = sigma
    state.reset()

def missing_particle(separation=0.0, radius=RADIUS, SNR=20):
    """ create a two particle state and compare it to featuring using a single particle guess """
    # create a base image of one particle
    s = init.create_two_particle_state(imsize=6*radius+4, axis='x', sigma=1.0/SNR,
            delta=separation, radius=radius, stateargs={'varyn': True}, psfargs={'error': 1e-6})
    s.obj.typ[1] = 0.
    s.reset()

    return s, s.obj.pos.copy()

def crb(state):
    crb = []

    blocks = state.explode(state.block_all())
    for block in blocks:
        tc = np.sqrt(1.0/np.abs(state.fisher_information(blocks=[block])))
        crb.append(tc)

    return np.squeeze(np.array(crb))

def sample(state, N=15, burn=15, sweeps=20):
    bl = state.blocks_particle(0)
    h = runner.sample_state(state, bl, stepout=0.1, N=sweeps)
    h = h.get_histogram()[burn:]

    return h.mean(axis=0), h.std(axis=0)

def dorun(SNR=20, separations=20, noise_samples=12, sweeps=30, burn=15):
    seps = np.logspace(-2, np.log10(2*RADIUS), separations)
    crbs, vals, errs, poss = [], [], [], []

    np.random.seed(10)
    for i,t in enumerate(seps):
        print 'sep', i, t, '|', 

        s,pos = missing_particle(separation=t, SNR=SNR)
        crbs.append(crb(s))
        poss.append(pos)

        for j in xrange(noise_samples):
            print j,
            sys.stdout.flush()

            s,pos = missing_particle(separation=t, SNR=SNR)
            val, err = sample(s, N=noise_samples, sweeps=sweeps, burn=burn)
            vals.append(val)
            errs.append(err)

        print ''
    shape0 = (separations,  -1)
    shape1 = (separations, noise_samples, -1)

    crbs = np.array(crbs).reshape(shape0)
    vals = np.array(vals).reshape(shape1)
    errs = np.array(errs).reshape(shape1)
    poss = np.array(poss).reshape(shape0)

    return  [crbs, vals, errs, poss, seps]

def dist(a):
    return np.sqrt((a[...,:3]**2).sum(axis=-1))

def errs(val, pos):
    v,p = val, pos
    return np.sqrt(((v[:,:,:3] - p[:,None,:3])**2).sum(axis=-1)).mean(axis=1)

def doplot(prefix='/media/scratch/peri/missing-particle', snrs=[20,50,200]):
    fig = pl.figure()

    symbols = ['o', '^', 'D', '>']
    for i, snr in enumerate(snrs):
        c = COLORS[i]
        fn = prefix+'-snr-'+str(snr)+'.pkl'
        crb, val, err, pos, time = pickle.load(open(fn))

        if i == 0:
            label0 = r"$\rm{SNR} = %i$ CRB" % snr
            label1 = r"$\rm{SNR} = %i$ Error" % snr
        else:
            label0 = r"$%i$, CRB" % snr
            label1 = r"$%i$, Error" % snr

        pl.plot(time, dist(crb), '-', c=c, lw=3, label=label0)
        pl.plot(time, errs(val, pos), symbols[i], ls='--', lw=2, c=c, label=label1, ms=12)

    pl.loglog()
    pl.ylim(5e-3, 1e0)
    pl.xlim(0, time[-1])
    pl.legend(loc='best', ncol=2, prop={'size': 18}, numpoints=1)
    pl.xlabel(r"Particle $x$-separation")
    pl.ylabel(r"Position CRB, Error")
    pl.grid(False, which='minor', axis='both')
    pl.title(r"Missing particle effects")
