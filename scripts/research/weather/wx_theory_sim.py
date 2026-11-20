"""wx_theory_sim.py -- what exponent does trajectory physics predict?

RESEARCH ONLY. Integrates a pitch with Alan Nathan's published drag and
Magnus (lift) model at two air densities, fits the constant-acceleration
(9-parameter) form Statcast reports, and reads the density elasticity of
the induced break. No tuning: coefficients are Nathan's trajectory
calculator values (cd0 0.3008, cdspin 0.0292, CL = 1.12 S / (0.583 + 2.333 S)).
"""
import numpy as np
G = 32.174
K0 = 5.383e-3          # 0.5 * rho * A / m in 1/ft at rho = 1.197 kg/m^3
R_BALL = 0.121         # ft


def fly(v_mph, rpm, axis_deg, rho, vz_deg=-2.0, active=1.0):
    """axis_deg: direction of the Magnus force in the x-z plane (90 = pure up)."""
    K = K0 * rho / 1.197
    w = rpm * 2 * np.pi / 60.0
    v = v_mph * 1.46667
    pos = np.array([-2.0, 55.0, 6.0])
    vel = np.array([v * 0.03, -v * np.cos(np.radians(vz_deg)), v * np.sin(np.radians(vz_deg))])
    # spin vector fixed in space, perpendicular to the Magnus direction and to y
    md = np.array([np.cos(np.radians(axis_deg)), 0.0, np.sin(np.radians(axis_deg))])
    spin_dir = np.cross(np.array([0.0, -1.0, 0.0]), md)          # w x v gives md
    dt = 0.0005
    ts, ps = [], []
    t = 0.0
    while pos[1] > 17.0 / 12.0:
        if pos[1] <= 50.0:
            ts.append(t); ps.append(pos.copy())
        sp = np.linalg.norm(vel)
        S = R_BALL * w * active / sp
        cd = 0.3008 + 0.0292 * rpm / 1000.0
        cl = 1.12 * S / (0.583 + 2.333 * S)
        wxv = np.cross(spin_dir, vel / sp)
        acc = -K * cd * sp * vel + K * cl * sp * sp * wxv / max(np.linalg.norm(wxv), 1e-9)
        acc[2] -= G
        vel = vel + acc * dt
        pos = pos + vel * dt
        t += dt
    ts = np.array(ts) - ts[0]; ps = np.array(ps)
    cx = np.polyfit(ts, ps[:, 0], 2); cz = np.polyfit(ts, ps[:, 2], 2); cy = np.polyfit(ts, ps[:, 1], 2)
    ax, az, ay = 2 * cx[0], 2 * cz[0], 2 * cy[0]
    T = ts[-1]
    return 12 * 0.5 * ax * T * T, 12 * 0.5 * (az + G) * T * T, -ay, T


if __name__ == '__main__':
    r_sea, r_coors = 1.195, 0.985
    print('pitch                 sea x   sea z  coors x coors z   e_x    e_z   e_drag')
    for name, v, rpm, ax_, act in (('FF 94 2300', 94, 2300, 100, 0.9), ('SI 93 2150', 93, 2150, 150, 0.85),
                                   ('CH 85 1750', 85, 1750, 150, 0.9), ('SL 85 2400', 85, 2400, -20, 0.35),
                                   ('CU 79 2550', 79, 2550, -110, 0.7), ('ST 82 2600', 82, 2600, 0, 0.6)):
        a = fly(v, rpm, ax_, r_sea, active=act); b = fly(v, rpm, ax_, r_coors, active=act)
        L = np.log(r_coors / r_sea)
        ex = np.log(b[0] / a[0]) / L if a[0] * b[0] > 0 else float('nan')
        ez = np.log(b[1] / a[1]) / L if a[1] * b[1] > 0 else float('nan')
        print(f'{name:20s} {a[0]:6.2f} {a[1]:6.2f}  {b[0]:6.2f} {b[1]:6.2f}  {ex:5.3f}  {ez:5.3f}  '
              f'{np.log(b[2]/a[2])/L:5.3f}')
