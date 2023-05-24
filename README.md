<div align="center">
  <img src="./icon.svg" alt="ONF Icon" width="200" height="200">
</div>
<br/>
<div align="center">
  <a href="https://charmhub.io/sdcore-nrf"><img src="https://charmhub.io/sdcore-nrf/badge.svg" alt="CharmHub Badge"></a>
  <a href="https://github.com/canonical/sdcore-nrf-operator/actions/workflows/publish-charm.yaml">
    <img src="https://github.com/canonical/sdcore-nrf-operator/actions/workflows/publish-charm.yaml/badge.svg?branch=main" alt=".github/workflows/publish-charm.yaml">
  </a>
  <br/>
  <br/>
  <h1>SD-CORE NRF Operator</h1>
</div>

Charmed Operator for the SD-CORE Network Repository Function (NRF).

# Usage

```bash
juju deploy sdcore-nrf --trust --channel=edge
juju deploy mongodb-k8s --trust --channel=5/edge
juju relate sdcore-nrf:database mongodb-k8s
```

# Image

- **nrf**: `omecproject/5gc-nrf:master-b747b98`
