
## Live copilot on your phone (proof of concept)

A hosted page that speaks callouts from live GPS instead of a fixed track, so it
cannot drift:

**https://claude.ai/code/artifact/d7d4c546-c107-4a1f-91cd-1fe4568e3293**

Open it in Safari on the phone, allow location, pair your helmet intercom, tap
**Start**, and put the phone away. Once loaded it needs GPS but no signal, so it
keeps working in dead zones — just don't close the tab.

It has the Tail of the Dragon loaded. To build a pack for a different road:

```
cd src/engine
python3 fetch_osm.py "<name>" <south,west,north,east> [--ref "<number>"] -o myroad.json
python3 export_pack.py myroad.json -o pack.json
cd ../.. && python3 - <<'PY'
import json, pathlib
pack = json.load(open("src/engine/pack.json"))
tpl = pathlib.Path("web/recce.template.html").read_text()
pathlib.Path("web/recce.html").write_text(tpl.replace("__PACK__", json.dumps(pack, separators=(",",":"))))
PY
```

Then ask me to republish `web/recce.html` and the same link updates.

**It is a prototype and has never been ridden.** Treat every callout as possibly
wrong, and note that it describes the road rather than telling you to go faster.
