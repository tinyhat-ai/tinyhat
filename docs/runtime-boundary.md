# Runtime Boundary

The Tinyhat runtime should stay boring. It keeps a Computer reachable and
trusted by the platform. It should not grow every product feature.

The plugin is where agent-facing product behavior belongs.

## Runtime Responsibilities

- Heartbeat
- Attestation
- Runtime command delivery
- Framework installation
- Plugin installation and update
- Safe runtime update plumbing

## Plugin Responsibilities

- Skills that teach the agent what Tinyhat can do.
- Small tools that expose named, safe capabilities.
- Framework adapter metadata.
- Public documentation that lets users inspect what is installed.

If a future feature is mainly "teach the agent how to use Tinyhat", it
belongs in this repo. If it is "keep the Computer alive and trusted", it
belongs in the runtime.
