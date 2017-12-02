import pickle
import numpy as np
import scipy as sp
import matplotlib.pyplot as pl
from mpl_toolkits.axes_grid1 import ImageGrid

import common
from peri import const, runner, initializers
from peri.test import init, nbody

def diffusion(diffusion_constant=0.2, exposure_time=0.05, samples=200):
    """
    See `diffusion_correlated` for information related to units, etc
    """
    radius = 5
    psfsize = np.array([2.0, 1.0, 3.0])

    # create a base image of one particle
    s0 = init.create_single_particle_state(imsize=4*radius, 
            radius=radius, psfargs={'params': psfsize, 'error': 1e-6})

    # add up a bunch of trajectories
    finalimage = 0*s0.get_model_image()[s0.inner]
    position = 0*s0.obj.pos[0]

    for i in range(samples):
        offset = np.sqrt(6*diffusion_constant*exposure_time)*np.random.randn(3)
        s0.obj.pos[0] = np.array(s0.image.shape)/2 + offset
        s0.reset()

        finalimage += s0.get_model_image()[s0.inner]
        position += s0.obj.pos[0]

    finalimage /= float(samples)
    position /= float(samples)

    # place that into a new image at the expected parameters
    s = init.create_single_particle_state(imsize=4*radius, sigma=0.05,
            radius=radius, psfargs={'params': psfsize, 'error': 1e-6})
    s.reset()

    # measure the true inferred parameters
    return s, finalimage, position

def diffusion_correlated(diffusion_constant=0.2, exposure_time=0.05,
        samples=40, phi=0.25):
    """
    Calculate the (perhaps) correlated diffusion effect between particles
    during the exposure time of the confocal microscope. diffusion_constant is
    in terms of seconds and pixel sizes exposure_time is in seconds

    1 micron radius particle:
        D = kT / (6 a\pi\eta)
        for 80/20 g/w (60 mPas), 3600 nm^2/sec ~ 0.15 px^2/sec
        for 100 % w  (0.9 mPas),               ~ 10.1 px^2/sec
    a full 60 layer scan takes 0.1 sec, so a particle is 0.016 sec exposure
    """
    radius = 5
    psfsize = np.array([2.0, 1.0, 3.0])/2

    pos, rad, tile = nbody.initialize_particles(N=50, phi=phi, polydispersity=0.0)
    sim = nbody.BrownianHardSphereSimulation(
        pos, rad, tile, D=diffusion_constant, dt=exposure_time/samples
    )
    sim.dt = 1e-2
    sim.relax(2000)
    sim.dt = exposure_time/samples

    # move the center to index 0 for easier analysis later
    c = ((sim.pos - sim.tile.center())**2).sum(axis=-1).argmin()
    pc = sim.pos[c].copy()
    sim.pos[c] = sim.pos[0]
    sim.pos[0] = pc

    # which particles do we want to simulate motion for? particle
    # zero and its neighbors
    mask = np.zeros_like(sim.rad).astype('bool')
    neigh = sim.neighbors(3*radius, 0)
    for i in neigh+[0]:
        mask[i] = True

    img = np.zeros(sim.tile.shape)
    s0 = runner.create_state(img, sim.pos, sim.rad, ignoreimage=True)

    # add up a bunch of trajectories
    finalimage = 0*s0.get_model_image()[s0.inner]
    position = 0*s0.obj.pos

    for i in range(samples):
        sim.step(1, mask=mask)
        s0.obj.pos = sim.pos.copy() + s0.pad
        s0.reset()

        finalimage += s0.get_model_image()[s0.inner]
        position += s0.obj.pos

    finalimage /= float(samples)
    position /= float(samples)

    # place that into a new image at the expected parameters
    s = runner.create_state(img, sim.pos, sim.rad, ignoreimage=True)
    s.reset()

    # measure the true inferred parameters
    return s, finalimage, position

def dorun(SNR=20, ntimes=20, samples=10, noise_samples=10, sweeps=20, burn=10,
        correlated=False):
    """
    we want to display the errors introduced by pixelation so we plot:
        * CRB, sampled error vs exposure time

    a = dorun(ntimes=10, samples=5, noise_samples=5, sweeps=20, burn=8)
    """
    if not correlated:
        times = np.logspace(-3, 0, ntimes)
    else:
        times = np.logspace(np.log10(0.05), np.log10(30), ntimes)

    crbs, vals, errs, poss = [], [], [], []

    for i,t in enumerate(times):
        print('###### time', i, t)

        for j in range(samples):
            print('image', j, '|', end=' ') 
            if not correlated:
                s,im,pos = diffusion(diffusion_constant=0.2, exposure_time=t)
            else:
                s,im,pos = diffusion_correlated(diffusion_constant=0.2, exposure_time=t)

            # typical image
            common.set_image(s, im, 1.0/SNR)
            crbs.append(common.crb(s))

            val, err = common.sample(s, im, 1.0/SNR, N=noise_samples, sweeps=sweeps, burn=burn)
            poss.append(pos)
            vals.append(val)
            errs.append(err)


    shape0 = (ntimes, samples, -1)
    shape1 = (ntimes, samples, noise_samples, -1)

    crbs = np.array(crbs).reshape(shape0)
    vals = np.array(vals).reshape(shape1)
    errs = np.array(errs).reshape(shape1)
    poss = np.array(poss).reshape(shape0)

    return  [crbs, vals, errs, poss, times]

def doplot(prefix='/media/scratch/peri/does_matter/brownian-motion', snrs=[20,50,200,500]):
    fig = pl.figure(figsize=(14,7))

    ax = fig.add_axes([0.43, 0.15, 0.52, 0.75])
    gs = ImageGrid(fig, rect=[0.05, 0.05, 0.25, 0.90], nrows_ncols=(2,1), axes_pad=0.25,
            cbar_location='right', cbar_mode='each', cbar_size='10%', cbar_pad=0.04)

    s,im,pos = diffusion(1.0, 0.1, samples=200)
    h,l = runner.do_samples(s, 30,0, quiet=True)
    nn = np.s_[:,:,im.shape[2]/2]

    figlbl, labels = ['A', 'B'], ['Reference', 'Difference']
    diff = (im - s.get_model_image()[s.inner])[nn]
    diffm = 0.1#np.abs(diff).max()
    im0 = gs[0].imshow(im[nn], vmin=0, vmax=1, cmap='bone_r')
    im1 = gs[1].imshow(diff, vmin=-diffm, vmax=diffm, cmap='RdBu')
    cb0 = pl.colorbar(im0, cax=gs[0].cax, ticks=[0,1])
    cb1 = pl.colorbar(im1, cax=gs[1].cax, ticks=[-diffm,diffm]) 
    cb0.ax.set_yticklabels(['0', '1'])
    cb1.ax.set_yticklabels(['-%0.1f' % diffm, '%0.1f' % diffm])

    for i in range(2):
        gs[i].set_xticks([])
        gs[i].set_yticks([])
        gs[i].set_ylabel(labels[i])
        #lbl(gs[i], figlbl[i])

    aD = 1.0/(25./0.15)

    symbols = ['o', '^', 'D', '>']
    for i, snr in enumerate(snrs):
        c = common.COLORS[i]
        fn = prefix+'-snr-'+str(snr)+'.pkl'
        crb, val, err, pos, time = pickle.load(open(fn))

        if i == 0:
            label0 = r"$\rm{SNR} = %i$ CRB" % snr
            label1 = r"$\rm{SNR} = %i$ Error" % snr
        else:
            label0 = r"$%i$, CRB" % snr
            label1 = r"$%i$, Error" % snr

        time *= aD # a^2/D, where D=1, and a=5 (see first function)
        ax.plot(time, common.dist(crb), '-', c=c, lw=3, label=label0)
        ax.plot(time, common.errs(val, pos), symbols[i], ls='--', lw=2, c=c, label=label1, ms=12)

    # 80% glycerol value
    ax.vlines(0.100*aD, 1e-6, 100, linestyle='-', lw=40, alpha=0.2, color='k')
    #pl.text(0.116*aD*1.45, 3e-4, 'G/W')

    # 100% water value
    ax.vlines(0.100*aD*60, 1e-6, 100, linestyle='-', lw=40, alpha=0.2, color='b')
    #ax.text(0.116*aD*75*2, 0.5, 'W')

    ax.loglog()
    ax.set_ylim(5e-4, 2e0)
    ax.set_xlim(time[0], time[-1])
    ax.legend(loc='best', ncol=2, prop={'size': 18}, numpoints=1)
    ax.set_xlabel(r"$\tau_{\rm{exposure}} / (a^2/D)$")
    ax.set_ylabel(r"Position CRB, Error")
    ax.grid(False, which='both', axis='both')
    ax.set_title("Brownian motion")
