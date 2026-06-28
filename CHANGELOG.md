# Changelog

## v1.1.0 (Unreleased)

#### New Features

* Add `get_diagnostics()` method to `GeckoIotClient` for structured diagnostic data
* Add `has_configuration` public property (bool) to `GeckoIotClient`
* Add `has_state` public property (bool) to `GeckoIotClient`
* Add `zone_counts` public property (dict[str, int]) to `GeckoIotClient`
* Public diagnostics API removes need for external consumers to access private attributes

#### Release Notes

* Tag as `v1.1.0` and publish to PyPI to make public API available for `ha-gecko-integration`
* Required by `ha-gecko-integration` manifest: `gecko-iot-client==1.1.0`

---

## Unreleased (2025-11-03)

#### New Features

* Add pypi publishing
* Add sonarcloud configuration
#### Fixes

* delete duplicate license
* change target branch to develop
* tests
#### Others

* fix license
* Add doc warning
* Update badge links
* update readme
* deploy docs on eveything branches/pushes (test)
