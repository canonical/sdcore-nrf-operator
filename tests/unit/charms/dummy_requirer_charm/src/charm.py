#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


"""Charm the service."""

import logging

from ops.charm import CharmBase
from ops.main import main

from lib.charms.sdcore_nrf.v0.fiveg_nrf import NRFAvailableEvent, NRFRequires

logger = logging.getLogger(__name__)


class DummyFiveGNRFRequirerCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        """Init."""
        super().__init__(*args)
        self.nrf_requirer = NRFRequires(self, "fiveg-nrf")
        self.framework.observe(self.nrf_requirer.on.nrf_available, self._on_nrf_available)

    def _on_nrf_available(self, event: NRFAvailableEvent):
        logging.info(f"NRF URL: {event.url}")


if __name__ == "__main__":
    main(DummyFiveGNRFRequirerCharm)
