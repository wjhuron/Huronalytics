#!/usr/bin/env python3
"""locplus_shape_loader.py — season pitches WITH movement, and the Loc+ module of a branch.

The shape-class Loc+ (branch locplus-shape) reads the sheet fields IndVertBrk and
HorzBrk. FR.load_season carries no movement for 2021-2025, so the release-check
scripts of that branch load seasons through here: locplus_shape_split_fit.load
(Statcast pfx for 2021-2025, the sheets for 2026) with the two fields written in
the sheet's own convention (HorzBrk is positive to a right-hander's arm side and
negative to a left-hander's).
"""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import locplus_shape_split_fit as SS  # noqa: E402


def load_season(y):
    ps = SS.load(y)
    if y != 2026:
        for p in ps:
            p['IndVertBrk'] = p['_ivb']
            h = p['_hb']
            p['HorzBrk'] = None if h is None else (h if p.get('Throws') == 'R' else -h)
    return ps


def branch(path, name='pipeline.locplus_shape'):
    spec = importlib.util.spec_from_file_location(name, os.path.join(path, 'pipeline', 'locplus.py'))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    if not hasattr(m, 'shape_group'):
        sys.exit(f'{path} has no shape classes: not the locplus-shape branch. Stopped.')
    return m
