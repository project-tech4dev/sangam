"""Every tool Sangam Import has, and nothing else.

A file in here is called by the model; a file in `app/ingest/` above is not.
Three modules, by what the tool touches: the catalog, the open web, the
adapter pipeline. Registration is `app/ingest/agent.py`, the same way
`app/agent/build.py` registers Ask Sangam's six.
"""
