"""Funding sources. Each adapter returns the same normalized row contract:

    {source, url, title, usd, currency, competition, deadline?, next_step, ...}

Adapters must degrade to an error dict/`_error` note instead of raising, so one
dead endpoint never kills a multi-source scan.
"""
