import numpy as np
from hexrd.utils.decorators import numba_njit_if_available
from hexrd import constants
import numba

if constants.USE_NUMBA:
    from numba import prange
else:
    prange = range

@numba_njit_if_available(cache=True, nogil=True)
def _calc_dspacing(rmt, hkls):
    nhkls = hkls.shape[0]
    dsp = np.zeros(hkls.shape[0])

    for ii in np.arange(nhkls):
        g = hkls[ii,:]
        dsp[ii] = 1.0/np.sqrt(np.dot(g, 
            np.dot(rmt, g)))
    return dsp

@numba_njit_if_available(cache=True, nogil=True)
def _get_tth(dsp, wavelength):
    nn = dsp.shape[0]
    tth = np.zeros(dsp.shape[0])
    wavelength_allowed_hkls = np.zeros(dsp.shape[0])
    for ii in np.arange(nn):
        d = dsp[ii]
        glen = 1./d
        sth = glen*wavelength/2.
        if(np.abs(sth) <= 1.0):
            t = 2. * np.degrees(np.arcsin(sth))
            tth[ii] = t
            wavelength_allowed_hkls[ii] = 1
        else:
            tth[ii] = np.nan
            wavelength_allowed_hkls[ii] = 0

    return tth, wavelength_allowed_hkls

@numba_njit_if_available(cache=True, nogil=True)
def _calcanomalousformfactor(atom_type,
    wavelength,
    frel,
    f_anomalous_data,
    f_anomalous_data_sizes):

    f_anam = np.zeros(atom_type.shape,dtype=np.complex64)

    for i in range(atom_type.shape[0]):
        nd = f_anomalous_data_sizes[i]
        Z = atom_type[i]
        fr = frel[i]
        f_data = f_anomalous_data[i,:,:]
        xp = f_data[:nd,0]
        yp = f_data[:nd,1]
        ypp = f_data[:nd,2]

        f1 = np.interp(wavelength,xp,yp)
        f2 = np.interp(wavelength,xp,ypp)

        f_anam[i] = np.complex(f1+fr-Z,f2)
    return f_anam

@numba_njit_if_available(cache=True, nogil=True)
def _calcxrayformfactor(wavelength,
    s, 
    atom_type,
    scatfac, 
    fNT, 
    frel, 
    f_anomalous_data,
    f_anomalous_data_sizes):

    f_anomalous = _calcanomalousformfactor(atom_type,
                  wavelength,
                  frel,
                  f_anomalous_data,
                  f_anomalous_data_sizes)
    ff = np.zeros(atom_type.shape,dtype=np.complex64)
    for ii in range(atom_type.shape[0]):
        sfact = scatfac[ii,:]
        fe = sfact[5]
        for jj in range(5):
            fe += sfact[jj] * np.exp(-sfact[jj+6]*s)

        ff[ii] = fe+fNT[ii]+f_anomalous[ii]

    return ff


@numba_njit_if_available(cache=True, nogil=True, parallel=True)
def _calcxrsf(hkls,
              nref,
              multiplicity,
              w_int,
              wavelength,
              rmt,
              atom_type,
              atom_ntype,
              betaij,
              occ,
              asym_pos_arr,
              numat,
              scatfac,
              fNT,
              frel,
              f_anomalous_data,
              f_anomalous_data_sizes):

    struct_factors = np.zeros(multiplicity.shape,
        dtype=np.float64)

    struct_factors_raw = np.zeros(multiplicity.shape,
        dtype=np.float64)

    for ii in prange(nref):
        g = hkls[ii,:]
        mm = multiplicity[ii]
        glen = np.dot(g,np.dot(rmt,g))
        s = 0.25 * glen * 1E-2
        sf = np.complex(0., 0.)
        formfact = _calcxrayformfactor(wavelength,
             s, 
             atom_type,
             scatfac, 
             fNT, 
             frel, 
             f_anomalous_data,
             f_anomalous_data_sizes)

        for jj in range(atom_ntype):
            natom = numat[jj]
            apos = asym_pos_arr[:natom,jj,:]
            if betaij.ndim > 1:
                b = betaij[:,:,jj]
                arg = b[0,0]*g[0]**2+\
                b[1,1]*g[1]**2+\
                b[2,2]*g[2]**2+\
                2.0*(b[0,1]*g[0]*g[1]+\
                    b[0,2]*g[0]*g[2]+\
                    b[1,2]*g[1]*g[2])
                arg = -arg
            else:
                arg = -8.0*np.pi**2 * betaij[jj]*s

            T = np.exp(arg)
            ff = formfact[jj]*occ[jj]*T

            for kk in range(natom):
                r = apos[kk,:]
                arg = 2.0 * np.pi * np.sum(g*r)
                sf = sf + ff*np.complex(np.cos(arg), -np.sin(arg))

        struct_factors[ii] = w_int*mm*np.abs(sf)**2
        struct_factors_raw[ii] = np.abs(sf)**2

    ma = struct_factors.max()
    struct_factors = 100.0*struct_factors/ma

    # ma = struct_factors_raw.max()
    # struct_factors_raw = 100.0*struct_factors_raw/ma

    return struct_factors, struct_factors_raw

@numba_njit_if_available(cache=True, nogil=True)
def _calc_x_factor(K,
                   v_unitcell,
                   wavelength,
                   f_sqr,
                   D):
    return f_sqr*(K*wavelength*D/v_unitcell)**2

@numba_njit_if_available(cache=True, nogil=True)
def _calc_bragg_factor(x,tth):
    stth = np.sin(np.radians(tth*0.5))**2
    return stth/np.sqrt(1.+x)


@numba_njit_if_available(cache=True, nogil=True)
def _calc_laue_factor(x,tth):
    ctth = np.cos(np.radians(tth*0.5))**2
    if x <= 1.:
      El = (1.-0.5*x+0.25*x**2-(5./48.)*x**3+(7./192.)*x**4)
    elif x > 1.:
      El = (2./np.pi/x)**2 * (1.-0.125*x**2-(3./128.)*x**2-\
            (15./1024.)*x**3)
    return El*ctth

@numba_njit_if_available(cache=True, nogil=True, parallel=True)
def _calc_extinction_factor(hkls,
                            tth,
                            v_unitcell,
                            wavelength,
                            f_sqr,
                            K,
                            D):
    nref = np.min(np.array([hkls.shape[0],\
           tth.shape[0]]))

    extinction = np.zeros(nref)

    for ii in prange(nref):
      fs = f_sqr[ii]
      t = tth[ii]
      x = _calc_x_factor(K,v_unitcell,
                         wavelength,
                         fs,D)
      extinction[ii] = _calc_bragg_factor(x,t)+\
                   _calc_laue_factor(x,t)

    return extinction

@numba_njit_if_available(cache=True, nogil=True, parallel=True)
def _calc_absorption_factor(abs_fact,
                            tth,
                            phi,
                            wavelength):
    nref = tth.shape[0]
    absorption = np.zeros(nref)
    phir = np.radians(phi)

    abl = -abs_fact*wavelength
    for ii in prange(nref):
      t = np.radians(tth[ii])*0.5

      if(np.abs(phir)  > 1e-3):
        c1 = np.cos(t+phir)
        c2 = np.cos(t-phir)

        f1 = np.exp(abl/c1)
        f2 = np.exp(abl/c2)
        if np.abs(c2) > 1e-3:
          f3 = abl*(1. - c1/c2)
        else:
          f3 = np.inf

        absorption[ii] = (f1-f2)/f3
      else:
        c = np.cos(t)
        absorption[ii] = np.exp(abl/c)
    return absorption
    