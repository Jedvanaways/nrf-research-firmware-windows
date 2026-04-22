# Upstream provenance

Everything in this repo that relates to the nRF24LU1+ firmware itself comes
from Bastille Networks' research:

- Upstream: <https://github.com/BastilleResearch/nrf-research-firmware>
- Commit pinned in [`COMMIT`](COMMIT):
  `02b84d1c4e59c0fb98263c83b2e7c7f9863a3b93` (2016-07-26)

## Rebuilding the firmware yourself

On any Linux box with SDCC:

```bash
sudo apt-get install -y sdcc binutils make git
git clone https://github.com/BastilleResearch/nrf-research-firmware.git
cd nrf-research-firmware
git checkout 02b84d1c4e59c0fb98263c83b2e7c7f9863a3b93
make
```

Output lives under `bin/`. The two files this repo ships under
`firmware/` are `bin/dongle.formatted.bin` and `bin/dongle.formatted.ihx`.

Last verified build: SDCC 4.2.0 on Ubuntu 24.04.

## Further reading

- Bastille's MouseJack write-up: <https://www.bastille.net/research/vulnerabilities/mousejack/>
- Details on the nRF24LU1+ bootloader exploit path used by the flasher:
  <https://github.com/BastilleResearch/nrf-research-firmware/blob/master/readme.md>
