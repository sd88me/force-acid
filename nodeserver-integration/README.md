# nodeServer integration

Not part of the `ForceAcid` addon itself - these patch the **nodeServer**
addon (a separate, shared MockbaMod addon), which is what actually renders
the home-page quick-links and the Modules page. This was applied directly
to a live nodeServer install without being tracked anywhere (this folder
didn't exist yet) - recovered from the live device and backed up here
2026-09-13, once the gap was noticed while doing the same integration for
`force-maze`.

## Modules page (`/moduler`) - no patch needed

Automatic: nodeServer's `moduler` endpoint scans every `AddOns/*/NSMODULE.json`
and lists whatever it finds, with start/stop + autolaunch-toggle controls
driven entirely by that file. `addon/NSMODULE.json` already exists in this
repo - nothing further to do here.

## Home page quick-link - two files to add

1. Copy `forceacid.js` to nodeServer's `app/api/endpoints/forceacid.js`.
2. Add this entry to `app/api/ENDPOINTS.js`'s exported array:

```js
    {
        // Force Acid runs its own standalone server (not an in-process
        // nodeServer module -- see force-acid/web/README.md). URL/PARAM stay
        // a plain relative path on purpose (home.js's escape() call mangles
        // absolute "http://host:port" URLs -- see forceacid.js); clicking
        // this link hits nodeServer's own /forceacid route, which
        // forceacid.js immediately 302-redirects out to the real panel.
        NAME: "Force Acid",
        PATH: "./api/endpoints/forceacid.js",
        PARAM: "/forceacid",
        URL: "/forceacid",
        HIDDEN: false,
        HOME: true,
        TARGET: "FORCEACID"
    },
```

3. Restart nodeServer for the new route to be picked up (it does not need
   `acvs`/MPC touched at all - a plain process kill+relaunch of nodeServer's
   own `server.js`, or `run_nodeserver.sh kill` then re-run).

Targets port **8303** (`force-acid`'s own web panel, see `web/README.md`)
- if that ever changes, update `forceacid.js`'s redirect target to match.

See [`force-maze`](https://github.com/sd88me/force-maze)'s
`nodeserver-integration/` for the equivalent patch for that project -
same pattern, different port (8304) and redirect name.
