# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library for the `fiveg_nrf` relation.

This library contains the Requires and Provides classes for handling the `fiveg_nrf`
interface.

The purpose of this library is to relate a charm claiming to provide 
NRF information and another charm requiring this information.

## Getting Started
From a charm directory, fetch the library using `charmcraft`:

```shell
charmcraft fetch-lib charms.sdcore_nrf_operator.v0.fiveg_nrf
```

Add the following libraries to the charm's `requirements.txt` file:
- pydantic
- pytest-interface-tester

### Requirer charm
The requirer charm is the one requiring the NRF information.

Example:
```python

from ops.charm import CharmBase
from ops.main import main

from charms.sdcore_nrf_operator.v0.fiveg_nrf import (
    NRFAvailableEvent,
    NRFRequires,
)


class DummyNRFRequirerCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.nrf_requirer = NRFRequires(self, "fiveg-nrf")
        self.framework.observe(
            self.nrf_requirer.on.nrf_available,
            self._on_nrf_available,
        )

    def _on_nrf_available(self, event: NRFAvailableEvent):
        url = event.url
        <Do something with the url>


if __name__ == "__main__":
    main(DummyNRFRequirerCharm)
```

### Provider charm
The provider charm is the one requiring providing the information about the NRF.

Example:
```python

from ops.charm import CharmBase, RelationJoinedEvent
from ops.main import main

from charms.nrf_interface.v0.nrf_interface import (
    NRFProvides,
)


class DummyNRFProviderCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.nrf_provider = NRFProvides(self, "fiveg-nrf")
        self.framework.observe(
            self.on.nrf_relation_joined, self._on_nrf_relation_joined
        )

    def _on_nrf_relation_joined(self, event: RelationJoinedEvent) -> None:
        if not self.unit.is_leader():
            return
        url = "<Here goes your code for fetching the NRF url>"
        try:
            self.nrf_provider.set_nrf_information(
              url=url, relation_id=event.relation.id
            )
        except AddressValueError:
            self.unit.status = BlockedStatus("Invalid MME IPv4 address.")


if __name__ == "__main__":
    main(DummyNRFProviderCharm)
```

"""

# The unique Charmhub library identifier, never change it
LIBID = "cd132a12c2b34243bfd2bae8d08c32d6"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

import logging

from ops.charm import CharmBase, CharmEvents, RelationChangedEvent
from ops.framework import EventBase, EventSource, Handle, Object

from pydantic import BaseModel, AnyHttpUrl, Field, BaseModel, ValidationError, validator

from interface_tester.schema_base import DataBagSchema

from validators import url as check_url_validity
from validators import ValidationFailure


logger = logging.getLogger(__name__)

"""Schemas definition for the provider and requirer sides of the `fiveg_nrf` interface.
It exposes two interfaces.schema_base.DataBagSchema subclasses called:
- ProviderSchema
- RequirerSchema
Examples:
    ProviderSchema:
        unit: <empty>
        app: {"url": "https://nrf-example.com:1234"}
    RequirerSchema:
        unit: <empty>
        app:  <empty>
"""


class MyProviderAppData(BaseModel):
    url: AnyHttpUrl = Field(
        description="Url to reach the NRF.",
        examples=["https://nrf-example.com:1234"]
    )

class ProviderSchema(DataBagSchema):
    """Provider schema for fiveg_nrf."""
    app: MyProviderAppData

class RequirerSchema(DataBagSchema):
    """Requirer schema for fiveg_nrf."""
    

class NRFAvailableEvent(EventBase):
    """Charm event emitted when a NRF is available. It carries the NRF url."""
    
    def __init__(self, handle: Handle, url: str):
        """Init."""
        super().__init__(handle)
        self.url = url # TODO:

    def snapshot(self) -> dict:
        """Returns snapshot."""
        return {"url": self.url}

    def restore(self, snapshot: dict) -> None:
        """Restores snapshot."""
        self.url = snapshot["url"]


class NRFRequirerCharmEvents(CharmEvents):
    """List of events that the NRF requirer charm can leverage."""

    nrf_available = EventSource(NRFAvailableEvent)
    

class NRFRequires(Object):
    """Class to be instantiated by the NRF requirer charm."""
    
    on = NRFRequirerCharmEvents()
    
    def __init__(self, charm: CharmBase, relation_name: str):
        """Init."""
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name
        self.framework.observe(
            charm.on[relation_name].relation_changed,
            self._on_relation_changed
        )
    
    @staticmethod
    def _relation_data_is_valid(remote_app_relation_data: dict) -> bool:
        """Returns whether URL is valid.
        
        Args:
            dict: Remote app relation data.
        Returns:
            bool: True if relation data is valid, False otherwise.
        """
        
        try:
            MyProviderAppData.parse_obj(remote_app_relation_data)
            return True
        except ValueError as e:
            logger.error("Invalid relation data: %s", e)
            return False
        
    @staticmethod
    def _relation_data_is_valid(url: str) -> bool:
        """Returns whether URL is valid.
        
        Args:
            str: URL to be validated.
        Returns:
            bool: True if URL is valid, False otherwise.
        """
        try:
            ProviderSchema(app=MyProviderAppData(url=url))
            return True
        except ValidationError as e:
            logger.error("Invalid url: %s", e)
            return False
        
    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handler triggered on relation changed event.

        Args:
            event: Juju event (RelationChangedEvent)

        Returns:
            None
        """
        relation = event.relation
        if not relation.app:
            logger.warning("No remote application in relation: %s", self.relation_name)
            return
        remote_app_relation_data = relation.data[relation.app]
        if not self._relation_data_is_valid(dict(remote_app_relation_data)): # TODO: pydantic validation migth fail here
            logger.warning("Invalid relation data: %s", remote_app_relation_data)
            return
        self.on.nrf_available.emit(url=remote_app_relation_data["url"])
        
class NRFProvides(Object):
    """Class to be instantiated by the charm providing the NRF data."""

    def __init__(self, charm: CharmBase, relation_name: str):
        """Init."""
        super().__init__(charm, relation_name)
        self.relation_name = relation_name
        self.charm = charm

    @staticmethod
    def _relation_data_is_valid(url: str) -> bool:
        """Returns whether URL is valid.
        
        Args:
            str: URL to be validated.
        Returns:
            bool: True if URL is valid, False otherwise.
        """
        try:
            ProviderSchema(app=MyProviderAppData(url=url))
            return True
        except ValidationError as e:
            logger.error("Invalid url: %s", e)
            return False

    def set_nrf_information(self, url: str) -> None:
        """Sets url in the application relation data.

        Args:
            str: NRF url
            int: Relation ID
        Returns:
            None
        """
        if not self.charm.unit.is_leader():
           raise RuntimeError("Unit must be leader to set application relation data.")
        relations = self.model.relations[self.relation_name]
        if not relations:
            raise RuntimeError(f"Relation {self.relation_name} not created yet.")
        if not self._relation_data_is_valid(url):
            raise ValueError(f"Invalid url: {url}")
        for relation in relations:
            relation.data[self.charm.app].update({"url": url})