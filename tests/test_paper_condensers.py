from types import SimpleNamespace as NS

import pytest

from gridagent.paper_dsr_worker import verify_condensers


def test_condenser_checks():
    names = {"04": "SC04", "16": "SC16", "26": "SC26"}
    objects = {name: NS(loc_name=name, bus1=NS(cterm=NS(loc_name="Bus "+bus)),
                        typ_id=NS(sgn=250), outserv=int(bus != "26")) for bus, name in names.items()}
    app = NS(GetCalcRelevantObjects=lambda pattern, include: [objects[pattern.removesuffix(".ElmSym")]])
    verify_condensers(app, names, "26")
    with pytest.raises(ValueError, match="service state"):
        verify_condensers(app, names, "04")
    objects["SC26"].typ_id.sgn = 100
    with pytest.raises(ValueError, match="nominal"):
        verify_condensers(app, names, "26")
