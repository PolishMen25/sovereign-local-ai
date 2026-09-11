"""Automated arena where local agent profiles compete on sandbox-refereed code tasks.

The arena never judges with a model: only the task's own tests decide a result.
It never trains a model either: accepted solutions are bundled into packets that
stay ``awaiting_owner_approval`` until the owner approves one in the gateway.
"""
