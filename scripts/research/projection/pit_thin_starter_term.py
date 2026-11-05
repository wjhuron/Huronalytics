"""pit_thin_starter_term.py: a thin-season starter term, read the way production prints (stated role).

pit_thin_prior_test.py found arms with a base season under 30 IP and a start share >= .5 running +.25 RA9 (SE .10) above their stated-role
projection. Arms here all train on the BASE season's stated role, not gs_T, and all score on stated role:
  stated    train gs_T (shipped), score stated role: the reference
  gsStated  train stated role
  spThin    gsStated + (stated SP) / (1 + BF_(T-1) / k), k swept
Replicates: T 2022-2026 with Stuff+, T 2020-2026 without it (2020 and 2021 were not used to find the gap). Placebo shuffles the stated-SP label
within base-IP bin and season. Effect on 2027 for the two arms and the starter list, from the shipped design with the term.

Usage: python3 scripts/research/projection/pit_thin_starter_term.py
Output: console + data/_proj/_pit_thin_starter_term.json
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pit_horizon_backtest as ph
import pit_rate_backtest as pr
import pit_thin_prior_test as t

P = pr.P
GRID_K = [10, 20, 40, 80, 160, 320, 640, 1280, 2560]
BINS = [0, 10, 30, 80, 150, 10 ** 6]


def setup(B, Ts, use_stuff):
    D = {}
    for T in Ts:
        R = B.rows(T)
        feats = ph.feats(R, 1, *B.par)
        ipB = np.array([h[0]['ip'] if h[0] else 0.0 for _, _, h in R]); bfB = np.array([h[0]['bf'] if h[0] else 0.0 for _, _, h in R])
        gsB = np.array([h[0]['gs'] if h[0] else next(x for x in h if x)['gs'] for _, _, h in R])
        D[T] = dict(actual=B.design(R, T, 'actual', use_stuff), stated=B.design(R, T, 'stated', use_stuff), y=feats[1], w=feats[2], ipB=ipB, bfB=bfB, sp=(gsB >= .5).astype(float))
    return D


def term(z, k, sp=None):
    return ((z['sp'] if sp is None else sp) / (1 + z['bfB'] / k))[:, None]


def run(D, Ts, key, k=None, labels=None):
    pred = {}
    for T in Ts:
        tr = [s for s in Ts if s != T]
        mk = lambda s: t.add(D[s][key], term(D[s], k, labels[s] if labels else None)) if k else D[s][key]
        Xp = t.add(D[T]['stated'], term(D[T], k, labels[T] if labels else None)) if k else D[T]['stated']
        pred[T], _ = pr.fit_predict(np.vstack([mk(s) for s in tr]), np.concatenate([D[s]['y'] for s in tr]), np.concatenate([D[s]['w'] for s in tr]), Xp)
    return pred


def mse(p, z, m=None):
    m = np.ones(len(p), bool) if m is None else m
    return float((z['w'][m] * (p[m] - z['y'][m]) ** 2).sum() / z['w'][m].sum())


def compare(lab, p, p0, D, Ts, n=2000):
    d = [mse(p[T], D[T]) - mse(p0[T], D[T]) for T in Ts]
    rng = np.random.default_rng(0); B = []
    for _ in range(n):
        b = []
        for T in Ts:
            z = D[T]; i = rng.integers(0, len(z['y']), len(z['y']))
            b.append((z['w'][i] * ((p[T][i] - z['y'][i]) ** 2 - (p0[T][i] - z['y'][i]) ** 2)).sum() / z['w'][i].sum())
        B.append(np.mean(b))
    base = np.mean([mse(p0[T], D[T]) for T in Ts])
    th = [mse(p[T], D[T], D[T]['ipB'] < 30) - mse(p0[T], D[T], D[T]['ipB'] < 30) for T in Ts]
    print(f'{lab:30s} dMSE {np.mean(d):+.4f} (se {np.std(B):.4f}, {100*np.mean(d)/base:+.2f}%) wins {sum(x < 0 for x in d)}/{len(Ts)}  ' + ' '.join(f'{T}:{x:+.3f}' for T, x in zip(Ts, d)) + f'  thin {np.mean(th):+.3f} ({sum(x < 0 for x in th)}/{len(Ts)})')
    return dict(d=d, se=float(np.std(B)), wins=int(sum(x < 0 for x in d)))


def calib(p, D, Ts, lab):
    c = {k: np.concatenate([D[T][k] for T in Ts]) for k in ('y', 'w', 'ipB', 'sp')}
    q = np.concatenate([p[T] for T in Ts])
    print(f'  calibration {lab}: ' + '  '.join(f'{n}: {np.average(c["y"][m] - q[m], weights=c["w"][m]):+.2f} (IP {c["w"][m].sum():.0f})' for n, m in (
        ('SP IP<10', (c['sp'] == 1) & (c['ipB'] < 10)), ('SP IP 10-30', (c['sp'] == 1) & (c['ipB'] >= 10) & (c['ipB'] < 30)), ('SP 30-80', (c['sp'] == 1) & (c['ipB'] >= 30) & (c['ipB'] < 80)),
        ('SP 80-150', (c['sp'] == 1) & (c['ipB'] >= 80) & (c['ipB'] < 150)), ('SP 150+', (c['sp'] == 1) & (c['ipB'] >= 150)), ('RP IP<30', (c['sp'] == 0) & (c['ipB'] < 30)), ('RP 30+', (c['sp'] == 0) & (c['ipB'] >= 30)))))


def main():
    B = t.Base()
    res = {}
    for lab, Ts, us in (('with Stuff+, T 2022-2026', list(range(2022, 2027)), True), ('no Stuff+, T 2020-2026', list(range(2020, 2027)), False)):
        print('\n==', lab)
        D = setup(B, Ts, us)
        p0 = run(D, Ts, 'actual')
        print('  stated reference MSE', round(np.mean([mse(p0[T], D[T]) for T in Ts]), 4))
        calib(p0, D, Ts, 'reference')
        pg = run(D, Ts, 'stated')
        res[lab + '|gsStated'] = compare('gsStated vs reference', pg, p0, D, Ts)
        cur = {}
        for k in GRID_K:
            q = run(D, Ts, 'stated', k)
            cur[k] = float(np.mean([mse(q[T], D[T]) - mse(p0[T], D[T]) for T in Ts]))
        print('  k curve vs reference: ' + '  '.join(f'{k}:{v:+.4f}' for k, v in cur.items()))
        bk = min(cur, key=cur.get)
        # k chosen inside each fold
        q = {}
        for T in Ts:
            tr = [s for s in Ts if s != T]
            inner = {}
            for k in GRID_K:
                pi = run({s: D[s] for s in tr}, tr, 'stated', k)
                inner[k] = np.mean([mse(pi[s], D[s]) for s in tr])
            kk = min(inner, key=inner.get)
            q[T] = run(D, Ts, 'stated', kk)[T]
        res[lab + '|spThin'] = compare(f'spThin, k chosen in fold', q, p0, D, Ts)
        res[lab + '|spThin_vs_gsStated'] = compare('spThin vs gsStated', q, pg, D, Ts)
        calib(q, D, Ts, 'spThin')
        res[lab + '|curve'] = {str(k): v for k, v in cur.items()}
        res[lab + '|bk'] = bk
        if us:
            rng = np.random.default_rng(4); pl = []
            obs = float(np.mean([mse(q[T], D[T]) - mse(pg[T], D[T]) for T in Ts]))
            for _ in range(300):
                lab2 = {}
                for T in Ts:
                    z = D[T]; v = z['sp'].copy(); eb = np.digitize(z['ipB'], BINS)
                    for b in np.unique(eb):
                        i = np.where(eb == b)[0]; v[i] = rng.permutation(v[i])
                    lab2[T] = v
                x = run(D, Ts, 'stated', bk, labels=lab2)
                pl.append(np.mean([mse(x[T], D[T]) - mse(pg[T], D[T]) for T in Ts]))
            pl = np.array(pl)
            print(f'  placebo shuffled SP label, k {bk}: mean {pl.mean():+.4f} sd {pl.std():.4f}, observed vs gsStated {obs:+.4f}, beats {(pl > obs).mean()*100:.1f}%')
            res['placebo'] = dict(mean=float(pl.mean()), sd=float(pl.std()), obs=obs, beats=float((pl > obs).mean()))
            # 2027 effect: fit on all T, score the fake rows the way project_players does
            import pit_stuff_addon as pst  # noqa
            st = dict(B.stuff); st['2026'] = json.load(open(os.path.join(P, 'stuff_2026_loso.json')))
            S = B.S; pids = sorted(set().union(*[set(S[y]) for y in (2024, 2025, 2026)]))
            names = {int(r['mlbId']): r for r in csv.DictReader(open(os.path.join(P, 'projections_pitchers.csv')))}
            lgr = json.load(open(os.path.join(t.ROOT, 'data', 'metadata_rs.json')))['eraPlusConstants']['war']
            out = {}
            for role, gs in (('SP', 1.0), ('RP', 0.0)):
                fake = []
                for pid in pids:
                    hist = [S[2026 - k].get(pid) for k in range(3)]
                    k0 = next(k for k, x in enumerate(hist) if x)
                    fake.append((pid, {'age': hist[k0]['age'] + k0 + 1, 'gs': gs, 'ra9': 0.0, 'fip': 0.0, 'ip': 1.0}, hist))
                Xf = B.design(fake, 2027, 'actual', True, st)
                bf = np.array([h[0]['bf'] if h[0] else 0.0 for _, _, h in fake])
                Xtr = np.vstack([t.add(D[s]['stated'], term(D[s], bk)) for s in Ts])
                lvl, _ = pr.fit_predict(Xtr, np.concatenate([D[s]['y'] for s in Ts]), np.concatenate([D[s]['w'] for s in Ts]), t.add(Xf, (gs / (1 + bf / bk))[:, None]))
                out[role] = dict(zip(pids, lvl + lgr['lgRA9']))
            rows = []
            for pid in pids:
                r = names.get(pid)
                if not r or not r.get('gs_share_2026'):
                    continue
                role = 'SP' if float(r['gs_share_2026']) >= .5 else 'RP'
                rows.append(dict(id=pid, name=r['name'], role=role, ip=float(r['ip_2026']), old=float(r[f'RA9_{role}_2027']), new=float(out[role][pid])))
            res['effect'] = rows
            print(f'  2027 effect, k {bk}')
            for n in ('Joey Estes', 'Jason Alexander'):
                print('   ', [x for x in rows if x['name'] == n])
            S_ = [x for x in rows if x['role'] == 'SP']
            print('    SP rows', len(S_), 'mean shift', round(np.mean([x['new'] - x['old'] for x in S_]), 3), 'IP>=100 mean', round(np.mean([x['new'] - x['old'] for x in S_ if x['ip'] >= 100]), 3), 'IP<30 mean', round(np.mean([x['new'] - x['old'] for x in S_ if x['ip'] < 30]), 3))
            R_ = [x for x in rows if x['role'] == 'RP']
            print('    RP rows', len(R_), 'mean shift', round(np.mean([x['new'] - x['old'] for x in R_]), 3), 'max |shift|', round(max(abs(x['new'] - x['old']) for x in R_), 3))
    tmp = os.path.join(P, '_pit_thin_starter_term.json.tmp')
    with open(tmp, 'w') as f:
        json.dump(res, f, indent=1, default=float)
    os.replace(tmp, os.path.join(P, '_pit_thin_starter_term.json'))


if __name__ == '__main__':
    main()
