# sdcore-nrf-operator

Charmed Operator for the SD-CORE Network Repository Function (NRF).

## Usage

```bash
juju deploy sdcore-nrf --trust --channel=edge
juju deploy mongodb-k8s --trust --channel=5/edge
juju relate sdcore-nrf:database mongodb-k8s
```

## Image

- **nrf**: omecproject/5gc-nrf:master-b747b98
