"""
Basically I'm trying to cover 4 options, one of each:
    (Previously featured state,     No previously featured state)
    (using previous positions,      no previous positions)
    -----------------------------------------------------
    (no, no)    = get_initial_featuring
    (yes, no)   = get_particle_featuring
    (yes, yes)  = translate_featuring
    (no, yes)   = stupid, not doing. Or should I???

These do:
    (use globals to start,          start from nothing)
    (use positions to start,        start from trackpy)

Comments:
If you start from featured globals it seems that slab etc is off enough where
particles get added in regions they shouldn't be (e.g. below the slab).
So maybe you do a polish or a burn before an addsubtract?
"""
import os
import Tkinter as tk
import tkFileDialog as tkfd
import numpy as np
import peri
from peri import initializers, util, models, states, logger
from peri.comp import ilms, objs, psfs, exactpsf, comp

RLOG = logger.log.getChild('runner')

import peri.opt.optimize as opt
import peri.opt.addsubtract as addsub

def locate_spheres(image, radius, dofilter=True, order=(7,7,7), invert=False):
    """
    Get an initial featuring of sphere positions in an image.

    Parameters
    -----------
    image : :class:`peri.util.Image` object
        Image object which defines the image file as well as the region.

    radius : float
        Radius of objects to find, in pixels

    dofilter : boolean, optional
        Whether to remove the background before featuring. Doing so can often
        greatly increase the success of initial featuring and decrease later
        optimization time. Default is True.

    order : 3-element tuple, optional
        If `dofilter`, the 2+1D Leg Poly approximation to the background
        illumination field. Default is (7,7,7).

    invert : boolean, optional
        Whether to invert the image for featuring. Set to True if the
        image is bright particles on a dark background. Default is False

    Returns
    --------
    positions : np.ndarray [N,3]
        Positions of the particles in order (z,y,x) in pixel units of the image.

    Notes
    -----
        Optionally filters the image by fitting the image I(x,y,z) to a
    polynomial, then subtracts this fitted intensity variation and uses
    centroid methods to find the particles.
    """
    # We just want a smoothed field model of the image so that the residuals
    # are simply the particles without other complications
    m = models.SmoothFieldModel()

    I = ilms.LegendrePoly2P1D(order=order, constval=image.get_image().mean())
    s = states.ImageState(image, [I], pad=0, mdl=m)

    if dofilter:
        opt.do_levmarq(s, s.params)

    return addsub.feature_guess(s, radius, invert=not invert)[0]

def get_initial_featuring(feature_diam, actual_rad=None, im_name=None,
        tile=None, invert=True, use_full_path=False, minmass=100.0, **kwargs):
    """
    Completely optimizes a state from an image of roughly monodisperse
    particles.

    The user can interactively select the image. The state is periodically
    saved during optimization, with different filename for different stages
    of the optimization.

    Parameters
    ----------
        feature_diam : Int, odd
            The particle diameter for featuring, as passed to trackpy.locate
        actual_rad : Float, optional
            The actual radius of the particles. Default is 0.5 * feature_diam
        im_name : string, optional
            The file name of the image to load. If not set, it is selected
            interactively through Tk.
        tile : :class:`peri.util.Tile`, optional
            The tile of the raw image to be analyzed. Default is None, the
            entire image.
        invert : Bool, optional
            Whether to invert the image for featuring, as passed to trackpy.
            Default is True.
        use_full_path : Bool, optional
            Set to True to use the full path name for the image. Default
            is False.
        minmass : Float, optional
            minmass for featuring, as passed to trackpy. Default is 100.

        **kwargs Parameters
        -------------------
        slab : :class:`peri.comp.objs.Slab` or None, optional
            If not None, a slab corresponding to that in the image. Default
            is None.
        max_mem : Numeric
            The maximum additional memory to use for the optimizers, as
            passed to optimize.burn. Default is 1e9.
        desc : String, optional
            A description to be inserted in saved state. The save name will
            be, e.g., '0.tif-peri-' + desc + 'initial-burn.pkl'. Default is ''
        min_rad : Float, optional
            The minimum particle radius, as passed to addsubtract.add_subtract.
            Particles with a fitted radius smaller than this are identified
            as fake and removed. Default is 0.5 * actual_rad.
        max_rad : Float, optional
            The maximum particle radius, as passed to addsubtract.add_subtract.
            Particles with a fitted radius larger than this are identified
            as fake and removed. Default is 1.5 * actual_rad, however you
            may find better results if you make this more stringent.
        rz_order : int, optional
            If nonzero, the order of an additional augmented rscl(z)
            parameter for optimization. Default is 0; i.e. no rscl(z)
            optimization.
        zscale : Float, optional
            The zscale of the image. Default is 1.0
        mem_level : String, optional
            Set to one of 'hi', 'med-hi', 'med', 'med-lo', 'lo' to control
            the memory overhead of the state at the expense of accuracy.
            Default is 'hi'.

    Returns
    -------
        s : :class:`peri.states.ImageState`
            The optimized state.

    See Also
    --------
        feature_from_pos_rad    : Using a previous state's globals and
            user-provided positions and radii as an initial guess,
            completely optimizes a state.

        get_particle_featuring  : Using a previous state's globals and
            positions as an initial guess, completely optimizes a state.

        translate_featuring     : Use a previous state's globals and
            centroids methods for an initial particle guess, completely
            optimizes a state.

    Notes
    -----
        The **kwargs parameters are passed to _optimize_from_centroid.
    Proceeds by centroid-featuring the image for an initial guess of
    particle positions, then optimizing the globals + positions until
    termination as called in _optimize_from_centroid.
    """
    if actual_rad is None:
        actual_rad = feature_diam * 0.5

    _,  im_name = _pick_state_im_name('', im_name, use_full_path=use_full_path)
    im = util.RawImage(im_name, tile=tile)

    ###FIXME why isn't this using locate_spheres?
    f = peri.trackpy.locate(im.get_image()*255, feature_diam, invert=invert,
            minmass=minmass)
    npart = f['x'].size
    pos = np.zeros([npart,3])
    pos[:,0] = f['z']
    pos[:,1] = f['y']
    pos[:,2] = f['x']
    ####

    rad = np.ones(npart, dtype='float') * actual_rad
    s = _optimize_from_centroid(pos, rad, im, invert=invert, **kwargs)
    return s

def feature_from_pos_rad(pos, rad, im_name, tile=None, **kwargs):
    """
    Gets a completely-optimized state from an image and an initial guess of
    particle positions and radii. The user can interactively select the image.

    The state is periodically saved during optimization, with different
    filename for different stages of the optimization.

    Parameters
    ----------
        pos : [N,3] element numpy.ndarray.
            The initial guess for the N particle positions.
        rad : N element numpy.ndarray.
            The initial guess for the N particle radii.
        im_name : string
            The filename of the image to feature.
        tile : :class:`peri.util.Tile`, optional
            A tile of the sub-region of the image to feature. Default is
            None, i.e. entire image.

    **kwargs Parameters
    -------------------
        slab : :class:`peri.comp.objs.Slab` or None, optional
            If not None, a slab corresponding to that in the image. Default
            is None.
        max_mem : Numeric
            The maximum additional memory to use for the optimizers, as
            passed to optimize.burn. Default is 1e9.
        desc : String, optional
            A description to be inserted in saved state. The save name will
            be, e.g., '0.tif-peri-' + desc + 'initial-burn.pkl'. Default is ''
        min_rad : Float, optional
            The minimum particle radius, as passed to addsubtract.add_subtract.
            Particles with a fitted radius smaller than this are identified
            as fake and removed. Default is 0.5 * actual_rad.
        max_rad : Float, optional
            The maximum particle radius, as passed to addsubtract.add_subtract.
            Particles with a fitted radius larger than this are identified
            as fake and removed. Default is 1.5 * actual_rad, however you
            may find better results if you make this more stringent.
        invert : Bool
            Whether to invert the image for featuring, as passed to
            addsubtract.add_subtract. Default is True.
        rz_order : int, optional
            If nonzero, the order of an additional augmented rscl(z)
            parameter for optimization. Default is 0; i.e. no rscl(z)
            optimization.
        zscale : Float, optional
            The zscale of the image. Default is 1.0
        mem_level : String, optional
            Set to one of 'hi', 'med-hi', 'med', 'med-lo', 'lo' to control
            the memory overhead of the state at the expense of accuracy.
            Default is 'hi'.

    Returns
    -------
        s : :class:`peri.states.ImageState`
            The optimized state.

    See Also
    --------
        get_initial_featuring   : Features an image from scratch, using
            centroid methods as initial particle locations.

        get_particle_featuring  : Using a previous state's globals and
            positions as an initial guess, completely optimizes a state.

        translate_featuring     : Use a previous state's globals and
            centroids methods for an initial particle guess, completely
            optimizes a state.

    Notes
    -----
        The **kwargs parameters are passed to _optimize_from_centroid.
    Proceeds by centroid-featuring the image for an initial guess of
    particle positions, then optimizing the globals + positions until
    termination as called in _optimize_from_centroid.
    """
    #FIXME the user cannot select the image right now
    im = util.RawImage(im_name, tile=tile)
    s = _optimize_from_centroid(pos, rad, im, **kwargs)
    return s

def _optimize_from_centroid(pos, rad, im, slab=None, max_mem=1e9, desc='',
        min_rad=None, max_rad=None, invert=True, rz_order=0, zscale=1.0,
        mem_level='hi'):
    """
    Workhorse for creating & optimizing states with an initial centroid
    guess.
    See get_initial_featuring's __doc__ for params.
    """
    if min_rad is None:
        min_rad = 0.5 * rad.mean()
    if max_rad is None:
        max_rad = 1.5 * rad.mean() #FIXME this could be a problem for bidisperse suspensions
    if slab is not None:
        o = comp.ComponentCollection(
                [
                    objs.PlatonicSpheresCollection(pos, rad, zscale=zscale),
                    slab
                ],
                category='obj'
            )
    else:
        o = objs.PlatonicSpheresCollection(pos, rad, zscale=zscale)

    p = exactpsf.FixedSSChebLinePSF()
    npts, iorder = _calc_ilm_order(im.get_image().shape)
    i = ilms.BarnesStreakLegPoly2P1D(npts=npts, zorder=iorder)
    b = ilms.LegendrePoly2P1D(order=(9,3,5), category='bkg') #FIXME order needs to be based on image size, slab
    c = comp.GlobalScalar('offset', 0.0)
    s = states.ImageState(im, [o, i, b, c, p])
    if mem_level != 'hi':
        s.set_mem_level(mem_level)
    RLOG.info('State Created.')

    opt.do_levmarq(s, ['ilm-scale'], max_iter=1, run_length=6, max_mem=max_mem)
    states.save(s, desc=desc+'initial')

    RLOG.info('Initial burn:')
    opt.burn(s, mode='burn', n_loop=6, fractol=0.1, desc=desc+'initial-burn',
            max_mem=max_mem)

    RLOG.info('Start add-subtract')
    addsub.add_subtract(s, tries=30, min_rad=min_rad, max_rad=max_rad,
            invert=invert)
    states.save(s, desc=desc+'initial-addsub')

    RLOG.info('Final polish:')
    opt.burn(s, mode='polish', n_loop=8, fractol=3e-4, desc=desc+
            'addsub-polish', max_mem=max_mem, rz_order=rz_order)
    return s

def _calc_ilm_order(imshape):
    """
    Calculates an ilm order based on the shape of an image. Bleeding-edge...
    """
    #FIXME this needs to be general, with loads from the config file
    # Right now I'm calculating as if imshape is the unpadded shape but
    # perhaps it should be the padded shape?
    zorder = int(imshape[0] / 6.25) + 1  #might be overkill for big z images
    l_npts = int(imshape[1] / 42.5)+1
    npts = ()
    for a in xrange(l_npts):
        if a < 5:
            npts += ( int(imshape[2] * [59,39,29,19,14][a]/512.) + 1,)
        else:
            npts += ( int(imshape[2] * 11/512.) + 1,)
    return npts, zorder

def translate_featuring(state_name=None, im_name=None, use_full_path=False,
        **kwargs):
    """
    Translates one optimized state into another image where the particles
    have moved by a small amount (~1 particle radius).

    Returns a completely-optimized state. The user can interactively
    selects the initial state and the second raw image. The state is
    periodically saved during optimization, with different filename for
    different stages of the optimization.

    Parameters
    ----------
        state_name : String or None, optional
            The name of the initially-optimized state. Default is None,
            which prompts the user to select the name interactively
            through a Tk window.
        im_name : String or None, optional
            The name of the new image to optimize. Default is None,
            which prompts the user to select the name interactively
            through a Tk window.
        use_full_path : Bool, optional
            Set to True to use the full path of the state instead of
            partial path names (e.g. C:\Users\Me\Desktop\state.pkl vs
            state.pkl). Default is False

    **kwargs Parameters
    -------------------
        max_mem : Numeric
            The maximum additional memory to use for the optimizers, as
            passed to optimize.burn. Default is 1e9.
        desc : String, optional
            A description to be inserted in saved state. The save name will
            be, e.g., '0.tif-peri-' + desc + 'initial-burn.pkl'. Default is ''
        min_rad : Float, optional
            The minimum particle radius, as passed to addsubtract.add_subtract.
            Particles with a fitted radius smaller than this are identified
            as fake and removed. Default is 0.5 * actual_rad.
        max_rad : Float, optional
            The maximum particle radius, as passed to addsubtract.add_subtract.
            Particles with a fitted radius larger than this are identified
            as fake and removed. Default is 1.5 * actual_rad, however you
            may find better results if you make this more stringent.
        invert : Bool
            Whether to invert the image for featuring, as passed to
            addsubtract.add_subtract. Default is True.
        rz_order : int, optional
            If nonzero, the order of an additional augmented rscl(z)
            parameter for optimization. Default is 0; i.e. no rscl(z)
            optimization.
        do_polish : Bool, optional
            Set to False to only optimize the particles and add-subtract.
            Default is True, which then runs a polish afterwards.
        mem_level : String, optional
            Set to one of 'hi', 'med-hi', 'med', 'med-lo', 'lo' to control
            the memory overhead of the state at the expense of accuracy.
            Default is 'hi'.
    Returns
    -------
        s : :class:`peri.states.ImageState`
            The optimized state.

    See Also
    --------
        get_initial_featuring   : Features an image from scratch, using
            centroid methods as initial particle locations.

        feature_from_pos_rad    : Using a previous state's globals and
            user-provided positions and radii as an initial guess,
            completely optimizes a state.

        get_particle_featuring  : Using a previous state's globals and
            positions as an initial guess, completely optimizes a state.

    Notes
    -----
        The **kwargs parameters are passed to _translate_particles.
    Proceeds by:
        1. Optimize particle positions only.
        2. Optimize particle positions and radii only.
        3. Add-subtract missing and bad particles.
        4. If polish, optimize the illumination, background, and particles.
        5. If polish, optimize everything.
    """
    state_name, im_name = _pick_state_im_name(state_name, im_name,
                use_full_path=use_full_path)

    s = states.load(state_name)
    im = util.RawImage(im_name, tile=s.image.tile)  #should have get_scale? FIXME

    s.set_image(im)
    _translate_particles(s, **kwargs)
    return s

def get_particles_featuring(feature_diam, state_name=None, im_name=None,
        use_full_path=False, actual_rad=None, minmass=100, invert=True,
        **kwargs):
    """
    Runs trackpy.locate on an image, sets the globals from a previous state,
    calls _translate_particles
    Parameters
    ----------
        feature_diam : Int
            The diameters of the features in the new image, sent to
            trackpy.locate.

        state_name : String or None, optional
            The name of the initially-optimized state. Default is None,
            which prompts the user to select the name interactively
            through a Tk window.
        im_name : String or None, optional
            The name of the new image to optimize. Default is None,
            which prompts the user to select the name interactively
            through a Tk window.
        use_full_path : Bool, optional
            Set to True to use the full path of the state instead of
            partial path names (e.g. C:\Users\Me\Desktop\state.pkl vs
            state.pkl). Default is False
        actual_rad : Float or None
            The initial guess for the particle radii, which can be distinct
            from feature_diam/2. If None, then defaults to feature_diam/2.
        minmass : Float
            The minimum mass, as pased to trackpy.locate. Default is 100.
        invert : Bool
            Whether to invert the image for featuring, as passed to
            addsubtract.add_subtract. Default is True.

    **kwargs Parameters
    -------------------
        max_mem : Numeric
            The maximum additional memory to use for the optimizers, as
            passed to optimize.burn. Default is 1e9.
        desc : String, optional
            A description to be inserted in saved state. The save name will
            be, e.g., '0.tif-peri-' + desc + 'initial-burn.pkl'. Default is ''
        min_rad : Float, optional
            The minimum particle radius, as passed to addsubtract.add_subtract.
            Particles with a fitted radius smaller than this are identified
            as fake and removed. Default is 0.5 * actual_rad.
        max_rad : Float, optional
            The maximum particle radius, as passed to addsubtract.add_subtract.
            Particles with a fitted radius larger than this are identified
            as fake and removed. Default is 1.5 * actual_rad, however you
            may find better results if you make this more stringent.
        invert : Bool
            Whether to invert the image for featuring, as passed to
            addsubtract.add_subtract. Default is True.
        rz_order : int, optional
            If nonzero, the order of an additional augmented rscl(z)
            parameter for optimization. Default is 0; i.e. no rscl(z)
            optimization.
        do_polish : Bool, optional
            Set to False to only optimize the particles and add-subtract.
            Default is True, which then runs a polish afterwards.
        mem_level : String, optional
            Set to one of 'hi', 'med-hi', 'med', 'med-lo', 'lo' to control
            the memory overhead of the state at the expense of accuracy.
            Default is 'hi'.
    Returns
    -------
        s : :class:`peri.states.ImageState`
            The optimized state.

    See Also
    --------
        get_initial_featuring   : Features an image from scratch, using
            centroid methods as initial particle locations.

        feature_from_pos_rad    : Using a previous state's globals and
            user-provided positions and radii as an initial guess,
            completely optimizes a state.

        translate_featuring     : Use a previous state's globals and
            centroids methods for an initial particle guess, completely
            optimizes a state.

    Notes
    -----
        The **kwargs parameters are passed to _translate_particles.
    Proceeds by:
        1. Find a guess of the particle positions through centroid methods.
        2. Optimize particle positions only.
        3. Optimize particle positions and radii only.
        4. Add-subtract missing and bad particles.
        5. If polish, optimize the illumination, background, and particles.
        6. If polish, optimize everything.
    """
    state_name, im_name = _pick_state_im_name(state_name, im_name,
            use_full_path=use_full_path)
    s = states.load(state_name)

    if actual_rad == None:
        actual_rad = np.median(s.obj_get_radii())  #or 2 x feature_diam?
    im = util.RawImage(im_name, tile=s.image.tile)  #should have get_scale? FIXME
    f = peri.trackpy.locate(im.get_image()*255, feature_diam, invert=invert,
            minmass=minmass)
    npart = f['x'].size
    pos = np.zeros([npart,3])
    pos[:,0] = f['z']
    pos[:,1] = f['y']
    pos[:,2] = f['x']

    _ = s.obj_remove_particle(np.arange(s.obj_get_radii().size))
    s.obj_add_particle(pos, np.ones(pos.shape[0])*actual_rad)

    s.set_image(im)
    _translate_particles(s, invert=invert, **kwargs)
    return s

def _pick_state_im_name(state_name, im_name, use_full_path=False):
    """
    If state_name or im_name is None, picks them interactively through Tk,
    and then sets with or without the full path.
    """
    initial_dir = os.getcwd()
    if (state_name is None) or (im_name is None):
        wid = tk.Tk()
        wid.withdraw()
    if state_name is None:
        state_name = tkfd.askopenfilename(initialdir=initial_dir, title=
                'Select pre-featured state')
        os.chdir(os.path.dirname(state_name))

    if im_name is None:
        im_name = tkfd.askopenfilename(initialdir=initial_dir, title=
                'Select new image')

    if (not use_full_path) and (os.path.dirname(im_name) != ''):
        im_path = os.path.dirname(im_name)
        os.chdir(im_path)
        im_name = os.path.basename(im_name)
    else:
        os.chdir(initial_dir)
    return state_name, im_name

def _translate_particles(s, max_mem=1e9, desc='', min_rad='calc',
        max_rad='calc', invert=True, rz_order=0, do_polish=True,
        mem_level='hi'):
    """
    Workhorse for translating particles. See get_particles_featuring for docs.
    """
    s.set_mem_level(mem_level)  #overkill because always sets mem, but w/e
    RLOG.info('Translate Particles:')
    opt.burn(s, mode='do-particles', n_loop=4, fractol=0.1, desc=desc+
            'translate-particles', max_mem=max_mem, include_rad=False)
    opt.burn(s, mode='do-particles', n_loop=4, fractol=0.05, desc=desc+
            'translate-particles', max_mem=max_mem, include_rad=True)

    RLOG.info('Start add-subtract')
    addsub.add_subtract(s, tries=30, min_rad=min_rad, max_rad=max_rad,
        invert=invert)
    states.save(s, desc=desc+'translate-addsub')

    if do_polish:
        RLOG.info('Final Burn:')
        opt.burn(s, mode='burn', n_loop=3, fractol=3e-4, desc=desc+
            'addsub-burn', max_mem=max_mem, rz_order=rz_order)
        RLOG.info('Final Polish:')
        opt.burn(s, mode='polish', n_loop=4, fractol=3e-4, desc=desc+
            'addsub-polish', max_mem=max_mem, rz_order=rz_order)
