#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


"""Charm the service."""

from ops.charm import CharmBase, RelationJoinedEvent
from ops.main import main

from lib.charms.sdcore_nrf.v0.fiveg_nrf import NRFProvides


class DummyFiveGNRFProviderCharm(CharmBase):
    """Charm the service."""

    NRF_URL = "https://nrf.example.com"

    def __init__(self, *args):
        """Init."""
        super().__init__(*args)
        self.nrf_provider = NRFProvides(self, "fiveg-nrf")
        self.framework.observe(
            self.on.fiveg_nrf_relation_joined, self._on_fiveg_nrf_relation_joined
        )

    def _on_fiveg_nrf_relation_joined(self, event: RelationJoinedEvent):
        relation_id = event.relation.id
        self.nrf_provider.set_nrf_information(
            url=self.NRF_URL,
            relation_id=relation_id,
        )

    def _on_nrf_url_changed(
        self,
    ):
        self.nrf_provider.set_nrf_information_in_all_relations(
            url="https://different.nrf.com",
        )


if __name__ == "__main__":
    main(DummyFiveGNRFProviderCharm)
